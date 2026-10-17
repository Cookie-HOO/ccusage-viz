from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time
from datetime import datetime, timedelta

from ccusage_viz.builtin_summary import build_builtin_pane_summary
from ccusage_viz.configuration import apply_custom_probe_defaults, v2_metric_probe_descriptor
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import CustomProtocolFailure, V2MonitorCapability
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.custom_monitor_defaults import resolve_metric
from ccusage_viz.custom_monitor_models import CustomMonitorCompletion
from ccusage_viz.custom_protocol.responses import (
    CustomProbeResponse,
    CustomSummaryResponse,
    V2MonitorResponse,
    V2ProbeResponse,
    V2SummaryResponse,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.historical_component import HistoricalChartComponent, HistoricalPurpose
from ccusage_viz.lifecycle import LifecycleTrigger, OperationToken
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import MonitorConfig
from ccusage_viz.tui.custom_rendering import _custom_failure_log_detail
from ccusage_viz.tui.datasets.chooser import _dataset_title
from ccusage_viz.tui.header import _replace_header_interval
from ccusage_viz.tui.models import (
    HistoricalOutcome,
    MonitorOutcome,
    MonitorWarmupOutcome,
    TuiChartPane,
    TuiCustomPane,
)
from ccusage_viz.tui.pane_lifecycle import _refresh_deltas, _refresh_ranks
from ccusage_viz.tui.rendering import (
    _update_custom_monitor_attachment_activity,
    _update_monitor_attachment_activity,
)


def collect(session: TuiSession) -> bool:
    from ccusage_viz.tui.queries import (
        record_custom_log,
        record_custom_warnings,
        refresh,
        start_builtin_pane_summary,
        start_custom_pane_summary_submission,
        start_custom_summary,
        start_header,
        start_pane,
    )

    changed = False

    def retire_manual_refresh(operation: OperationToken) -> None:
        nonlocal changed
        if operation not in session.manual_refresh_operations:
            return
        session.manual_refresh_operations.remove(operation)
        if not session.manual_refresh_operations:
            changed = True

    active_operations = {
        lifecycle.active
        for lifecycle in (
            session.header.lifecycle,
            *(summary.lifecycle for summary in session.header.custom_summaries.values()),
            *(
                lifecycle
                for pane in session.panes
                for lifecycle in (
                    (pane.lifecycle, pane.summary.lifecycle)
                    if isinstance(pane, TuiCustomPane) and pane.summary is not None
                    else (pane.lifecycle,)
                    if isinstance(pane, TuiChartPane) and pane.summary_lifecycle is not None
                    else (pane.lifecycle,)
                    if isinstance(pane, TuiChartPane)
                    else ()
                )
            ),
        )
        if lifecycle.active is not None
    }
    if session.manual_refresh_operations - active_operations:
        session.manual_refresh_operations.intersection_update(active_operations)
        changed = True
    completed_header = session.header.lifecycle.take_completed(lambda future: future.done())
    if completed_header is not None:
        operation, future = completed_header
        observed_at = time.monotonic()
        try:
            result = future.result()
            if session.header.lifecycle.accepts(operation, generation=session.header.generation):
                session.header.records = _replace_header_interval(session.header.records, result)
                session.header.coverage = session.header.coverage.merge(result.coverage)
                session.header.snapshot = result
                session.header.accepted_at = datetime.now().astimezone()
                session.last_successful_update = session.header.accepted_at
                session.header.error = None
                session.header.lifecycle.complete(operation, generation=session.header.generation)
                changed = True
        except Exception as exc:
            if session.header.lifecycle.accepts(operation, generation=session.header.generation):
                session.header.lifecycle.complete(operation, generation=session.header.generation)
                session.header.error = str(exc)
                changed = True
        retire_manual_refresh(operation)
        start_header(session, now=observed_at)
    for summary in session.header.custom_summaries.values():
        completed_custom_summary = summary.lifecycle.take_completed(lambda future: future.done())
        if completed_custom_summary is None:
            continue
        operation, future = completed_custom_summary
        observed_at = time.monotonic()
        try:
            outcome = future.result()
            if not summary.lifecycle.accepts(operation, generation=outcome.generation):
                summary.lifecycle.abandon(operation)
            elif outcome.error is not None:
                summary.error = outcome.error
                summary.lifecycle.complete(operation, generation=outcome.generation)
                changed = True
            elif outcome.result is None:
                summary.lifecycle.abandon(operation)
            else:
                response = outcome.result.custom_response
                if not isinstance(response, (CustomSummaryResponse, V2SummaryResponse)):
                    raise TypeError("custom provider result does not contain a summary response")
                summary.response = response
                record_custom_warnings(session, summary.source, response)
                summary.error = None
                summary.accepted_at = datetime.now().astimezone()
                summary.accepted_period = summary.requested_period
                summary.accepted_as_of_date = summary.requested_as_of_date
                summary.lifecycle.complete(operation, generation=outcome.generation)
                session.last_successful_update = summary.accepted_at
                changed = True
        except Exception as exc:
            if summary.lifecycle.accepts(operation, generation=operation.generation):
                summary.error = exc
                summary.lifecycle.complete(operation, generation=operation.generation)
                changed = True
        retire_manual_refresh(operation)
        start_custom_summary(session, summary, now=observed_at)
    for pane in (item for item in session.panes if isinstance(item, TuiCustomPane)):
        summary = pane.summary
        if summary is None:
            continue
        completed_pane_summary = summary.lifecycle.take_completed(lambda future: future.done())
        if completed_pane_summary is None:
            continue
        operation, future = completed_pane_summary
        observed_at = time.monotonic()
        try:
            outcome = future.result()
            if not summary.lifecycle.accepts(operation, generation=outcome.generation):
                summary.lifecycle.abandon(operation)
            elif outcome.error is not None:
                summary.error = outcome.error
                summary.lifecycle.complete(operation, generation=outcome.generation)
                changed = True
            elif outcome.result is None:
                summary.lifecycle.abandon(operation)
            else:
                response = outcome.result.custom_response
                if not isinstance(response, (CustomSummaryResponse, V2SummaryResponse)):
                    raise TypeError("custom provider result does not contain a Pane summary")
                summary.response = response
                record_custom_warnings(session, summary.source, response)
                summary.error = None
                summary.accepted_at = datetime.now().astimezone()
                summary.accepted_period = summary.requested_period
                summary.accepted_as_of_date = summary.requested_as_of_date
                summary.lifecycle.complete(operation, generation=outcome.generation)
                session.last_successful_update = summary.accepted_at
                changed = True
        except Exception as exc:
            if summary.lifecycle.accepts(operation, generation=operation.generation):
                summary.error = exc
                summary.lifecycle.complete(operation, generation=operation.generation)
                changed = True
        retire_manual_refresh(operation)
        if summary.lifecycle.active is None:
            summary.lifecycle.start_ready(
                now=observed_at,
                start=lambda operation, pane=pane: start_custom_pane_summary_submission(
                    session, pane, operation
                ),
            )
    for pane in (item for item in session.panes if isinstance(item, TuiChartPane)):
        lifecycle = pane.summary_lifecycle
        if lifecycle is None or not isinstance(pane.component, HistoricalChartComponent):
            continue
        completed_summary = lifecycle.take_completed(lambda future: future.done())
        if completed_summary is None:
            continue
        operation, future = completed_summary
        observed_at = time.monotonic()
        try:
            outcome = future.result()
            if not lifecycle.accepts(operation, generation=outcome.generation):
                lifecycle.abandon(operation)
            elif outcome.error is not None:
                pane.summary_error = outcome.error
                lifecycle.complete(operation, generation=outcome.generation)
                changed = True
            elif outcome.result is None:
                lifecycle.abandon(operation)
            else:
                pane.summary = build_builtin_pane_summary(
                    outcome.chart,
                    outcome.plan,
                    outcome.result.records,
                    outcome.result.coverage,
                    accepted_at=datetime.now().astimezone(),
                )
                pane.component.set_summary(pane.summary.summary)
                pane.summary_error = None
                lifecycle.complete(operation, generation=outcome.generation)
                session.last_successful_update = pane.summary.accepted_at
                changed = True
        except Exception as exc:
            if lifecycle.accepts(operation, generation=operation.generation):
                pane.summary_error = exc
                lifecycle.complete(operation, generation=operation.generation)
                changed = True
        retire_manual_refresh(operation)
        start_builtin_pane_summary(session, pane, now=observed_at)
    for index, pane in enumerate(session.panes):
        if isinstance(pane, TuiCustomPane):
            completed_custom = pane.lifecycle.take_completed(lambda future: future.done())
            if completed_custom is None:
                continue
            operation, future = completed_custom
            observed_at = time.monotonic()
            try:
                outcome = future.result()
                if not pane.lifecycle.accepts(operation, generation=outcome.generation):
                    pane.lifecycle.abandon(operation)
                elif outcome.error is not None:
                    failure = (
                        outcome.error.values.get("custom_failure")
                        if isinstance(outcome.error, QueryError)
                        else None
                    )
                    retry = False
                    if (
                        isinstance(failure, CustomProtocolFailure)
                        and failure.code == "unsupported_query"
                        and (failure.unsupported is not None)
                        and isinstance(
                            pane.component, (CustomHistoricalComponent, CustomMonitorComponent)
                        )
                        and (pane.component.switch_target_config is not None)
                        and (pane.component.v2_descriptor is not None)
                    ):
                        target = next(
                            (
                                metric
                                for metric in pane.component.v2_descriptor.metrics
                                if metric.id == pane.component.request_config.metric_id
                            ),
                            None,
                        )
                        field = failure.unsupported.get("field")
                        retry = (
                            target is not None
                            and field is not None
                            and pane.component.retry_metric_switch(field, target)
                        )
                    if retry:
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        refresh(
                            session,
                            index,
                            trigger=LifecycleTrigger.CONFIGURATION,
                            data_affecting=False,
                        )
                        changed = True
                        continue
                    if (
                        isinstance(failure, CustomProtocolFailure)
                        and failure.code == "unsupported_query"
                        and (failure.unsupported is not None)
                        and isinstance(
                            pane.component, (CustomHistoricalComponent, CustomMonitorComponent)
                        )
                        and (pane.component.switch_target_config is not None)
                        and (pane.component.v2_descriptor is not None)
                    ):
                        target = next(
                            (
                                metric
                                for metric in pane.component.v2_descriptor.metrics
                                if metric.id == pane.component.request_config.metric_id
                            ),
                            None,
                        )
                        field = failure.unsupported.get("field")
                        if target is not None and field is not None:
                            pane.component.cancel_metric_switch()
                            session.copy_feedback.show(
                                session.translator.text(
                                    "status.custom_metric_switch_no_default",
                                    metric=_dataset_title(target.title, session.translator),
                                    field=field,
                                )
                            )
                            pane.lifecycle.complete(operation, generation=outcome.generation)
                            changed = True
                            continue
                    failed = (
                        pane.component.fail(outcome.error, generation=outcome.generation)
                        if isinstance(pane.component, CustomMonitorComponent)
                        else pane.component.fail(
                            outcome.error,
                            generation=outcome.generation,
                            purpose="primary" if outcome.purpose == "probe" else outcome.purpose,
                        )
                    )
                    if failed:
                        record_custom_log(
                            session,
                            pane,
                            "error",
                            _custom_failure_log_detail(outcome.error, session.translator),
                        )
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        changed = True
                    else:
                        pane.lifecycle.abandon(operation)
                elif outcome.result is None:
                    pane.lifecycle.abandon(operation)
                elif outcome.purpose == "probe":
                    response = outcome.result.custom_response
                    if isinstance(pane.component, CustomMonitorComponent):
                        if not isinstance(response, V2ProbeResponse):
                            raise TypeError("custom monitor probe did not return a V2 response")
                        resolved = resolve_metric(pane.component.candidate, response.descriptor)
                        metric = next(
                            (
                                item
                                for item in response.descriptor.metrics
                                if item.id == resolved.metric_id
                            ),
                            None,
                        )
                        if metric is None or not isinstance(
                            metric.capabilities.charts.get("monitor"), V2MonitorCapability
                        ):
                            raise TypeError(
                                "custom monitor metric is not supported by runtime probe"
                            )
                        from ccusage_viz.custom_monitor_defaults import (
                            apply_custom_monitor_defaults,
                        )

                        resolved, display_window = apply_custom_monitor_defaults(resolved, metric)
                        pane.component.configure(resolved, data_affecting=False)
                        pane.component.set_metric(metric)
                        if display_window is not None:
                            pane.component.configure_display_window(display_window)
                    elif isinstance(response, V2ProbeResponse):
                        resolved = resolve_metric(pane.component.candidate, response.descriptor)
                        descriptor = v2_metric_probe_descriptor(
                            response.descriptor, resolved.metric_id
                        )
                        pane.component.configure(
                            apply_custom_probe_defaults(
                                resolved,
                                descriptor,
                                timezone=session.options.host.timezone or "UTC",
                            ),
                            data_affecting=False,
                        )
                        pane.component.set_capability(
                            descriptor.capabilities.charts[pane.component.candidate.kind]
                        )
                    elif not isinstance(response, CustomProbeResponse):
                        raise TypeError("custom provider result does not contain a probe response")
                    if session.options.host.timezone is None:
                        raise RuntimeError("custom Dataset requests require a timezone")
                    if isinstance(pane.component, CustomHistoricalComponent) and isinstance(
                        response, CustomProbeResponse
                    ):
                        pane.component.configure(
                            apply_custom_probe_defaults(
                                pane.component.candidate,
                                response.descriptor,
                                timezone=session.options.host.timezone,
                            ),
                            data_affecting=False,
                        )
                        pane.component.set_capability(
                            response.descriptor.capabilities.charts[pane.component.candidate.kind]
                        )
                    if isinstance(pane.component, CustomHistoricalComponent):
                        capability = pane.component.capability
                        if (
                            capability is not None
                            and capability.refresh_interval_seconds is not None
                        ):
                            pane.scheduler.rebuild(
                                capability.refresh_interval_seconds, now=observed_at
                            )
                    pane.probe_complete = True
                    try:
                        from ccusage_viz.datasets.service import DatasetService

                        DatasetService().update_runtime_probe(
                            pane.component.candidate.source, response
                        )
                    except OSError:
                        pass
                    record_custom_warnings(session, pane.component.candidate.source, response)
                    pane.lifecycle.complete(operation, generation=outcome.generation)
                    refresh(session, index, trigger=LifecycleTrigger.STARTUP, data_affecting=False)
                    changed = True
                elif isinstance(pane.component, CustomMonitorComponent):
                    response = outcome.result.custom_response
                    if not isinstance(response, V2MonitorResponse):
                        raise TypeError("custom monitor query did not return a V2 observation")
                    if pane.component.accept(
                        CustomMonitorCompletion(
                            outcome.generation, pane.component.request_config, response
                        ),
                        accepted_at=datetime.now().astimezone(),
                    ):
                        record_custom_warnings(session, pane.component.candidate.source, response)
                        record_custom_log(
                            session,
                            pane,
                            "ok",
                            session.translator.text("status.custom_query_succeeded"),
                        )
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        session.last_successful_update = pane.component.accepted_at
                        if pane.attachment is not None:
                            _update_custom_monitor_attachment_activity(
                                pane.component,
                                pane.attachment,
                                now=time.monotonic(),
                                wall=pane.component.accepted_at,  # ty: ignore[invalid-argument-type]
                                translator=session.translator,
                            )
                        changed = True
                    else:
                        pane.lifecycle.abandon(operation)
                elif pane.component.apply_provider_result(
                    outcome.result,
                    purpose=outcome.purpose,
                    comparison_request_config=outcome.comparison_request_config,
                ):
                    record_custom_warnings(
                        session, pane.component.candidate.source, outcome.result.custom_response
                    )
                    record_custom_log(
                        session,
                        pane,
                        "ok",
                        session.translator.text("status.custom_query_succeeded"),
                    )
                    pane.lifecycle.complete(operation, generation=outcome.generation)
                    session.last_successful_update = pane.component.accepted_at
                    changed = True
                    if (
                        outcome.purpose == "primary"
                        and pane.component.start_comparison() is not None
                    ):
                        refresh(
                            session,
                            index,
                            trigger=LifecycleTrigger.CONFIGURATION,
                            data_affecting=False,
                        )
                else:
                    pane.lifecycle.abandon(operation)
            except Exception as exc:
                if pane.lifecycle.accepts(operation, generation=operation.generation):
                    pane.lifecycle.abandon(operation)
                    if pane.component.fail(exc, generation=operation.generation, purpose="primary"):  # ty: ignore[unknown-argument]
                        record_custom_log(
                            session,
                            pane,
                            "error",
                            _custom_failure_log_detail(exc, session.translator),
                        )
                        changed = True
            retire_manual_refresh(operation)
            start_pane(session, index, now=observed_at)
            continue
        if not isinstance(pane, TuiChartPane):
            continue
        completed_pane = pane.lifecycle.take_completed(lambda future: future.done())
        if completed_pane is None:
            continue
        operation, future = completed_pane
        component = pane.component
        observed_at = time.monotonic()
        purpose = HistoricalPurpose.PRIMARY
        try:
            loaded = future.result()
            if isinstance(loaded, HistoricalOutcome):
                purpose = loaded.purpose
            active = pane.lifecycle.accepts(operation, generation=loaded.generation)
            if not active:
                pane.lifecycle.abandon(operation)
                retire_manual_refresh(operation)
                continue
            if loaded.error is not None:
                failed = (
                    component.fail(
                        loaded.error, generation=loaded.generation, purpose=loaded.purpose
                    )
                    if isinstance(component, HistoricalChartComponent)
                    and isinstance(loaded, HistoricalOutcome)
                    else component.fail(loaded.error, generation=loaded.generation)
                )
                if failed:
                    pane.lifecycle.complete(operation, generation=loaded.generation)
                    changed = True
                else:
                    pane.lifecycle.abandon(operation)
            else:
                if isinstance(component, MonitorComponent):
                    if isinstance(loaded, MonitorWarmupOutcome):
                        if not loaded.completions:
                            pane.lifecycle.abandon(operation)
                            retire_manual_refresh(operation)
                            continue
                        chart = component.candidate.chart
                        if not isinstance(chart, MonitorConfig):
                            raise TypeError("monitor pane component has historical configuration")
                        steps = len(loaded.completions)
                        demo_now = observed_at
                        demo_wall = datetime.now().astimezone()
                        demo_seconds = chart.window_seconds / max(1, steps - 1)
                        accepted = all(
                            (
                                component.accept(
                                    completion,
                                    now=demo_now - (steps - ordinal) * demo_seconds,
                                    wall=demo_wall
                                    - timedelta(seconds=(steps - ordinal) * demo_seconds),
                                    detect_gap=False,
                                )
                                for ordinal, completion in enumerate(loaded.completions, start=1)
                            )
                        )
                        if accepted:
                            pane.demo_ordinal = steps
                            pane.demo_warmed_generation = loaded.generation
                            pane.scheduler.rebuild(
                                component.candidate.host.interval, now=observed_at
                            )
                    else:
                        assert isinstance(loaded, MonitorOutcome)
                        assert loaded.completion is not None
                        accepted = component.accept(
                            loaded.completion, now=observed_at, wall=datetime.now().astimezone()
                        )
                        if accepted:
                            pane.demo_ordinal += 1
                else:
                    assert isinstance(loaded, HistoricalOutcome)
                    assert loaded.completion is not None
                    accepted = component.accept(loaded.completion)
                    if accepted and component.candidate.chart.kind == "ranking":
                        _refresh_deltas(pane, component.ranking_values())
                        _refresh_ranks(pane, component.ranking_keys())
                if accepted:
                    if pane.attachment is not None and isinstance(component, MonitorComponent):
                        _update_monitor_attachment_activity(
                            component,
                            pane.attachment,
                            now=observed_at,
                            wall=datetime.now().astimezone(),
                            translator=session.translator,
                        )
                    pane.lifecycle.complete(operation, generation=loaded.generation)
                    session.last_successful_update = component.accepted_at
                    changed = True
                    if (
                        isinstance(component, HistoricalChartComponent)
                        and isinstance(loaded, HistoricalOutcome)
                        and (loaded.purpose is HistoricalPurpose.PRIMARY)
                        and component.missing_comparison_coverage().intervals
                    ):
                        refresh(
                            session,
                            index,
                            trigger=LifecycleTrigger.CONFIGURATION,
                            data_affecting=False,
                        )
                else:
                    pane.lifecycle.abandon(operation)
        except Exception as exc:
            if pane.lifecycle.accepts(operation, generation=operation.generation):
                pane.lifecycle.abandon(operation)
                failed = (
                    component.fail(exc, generation=operation.generation, purpose=purpose)
                    if isinstance(component, HistoricalChartComponent)
                    else component.fail(exc, generation=operation.generation)
                )
                if failed:
                    changed = True
        retire_manual_refresh(operation)
        start_pane(session, index, now=observed_at)
    return changed
