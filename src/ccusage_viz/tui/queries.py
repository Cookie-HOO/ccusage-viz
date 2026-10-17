from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
from datetime import datetime
from functools import partial
from threading import Event
from typing import cast

from ccusage_viz.acquisition import (
    builtin_summary_query_intent,
    builtin_summary_query_plan,
    custom_historical_query_intent,
    custom_probe_query_intent,
    custom_summary_query_intent,
    custom_v2_monitor_query_intent,
    custom_v2_probe_query_intent,
    custom_v2_summary_query_intent,
    historical_provider_id,
    historical_query_intent,
)
from ccusage_viz.core.custom_ranking_time import refresh_custom_ranking_range
from ccusage_viz.core.time import DateRange, local_today, refresh_date_range
from ccusage_viz.custom_component import custom_date_summary_supported
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.custom_protocol.requests import CustomSummaryRequest, V2SummaryRequest
from ccusage_viz.domain import UsageRecord
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalPurpose,
    UsageSnapshot,
)
from ccusage_viz.lifecycle import LifecycleTrigger, OperationToken, query_trigger
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import CustomCommandSource, MonitorConfig
from ccusage_viz.processing.summaries import (
    SummaryQueryPlan,
    SummaryScope,
    range_summary_query_plan,
    summary_query_plan,
)
from ccusage_viz.tui.custom_rendering import _custom_failure_log_detail
from ccusage_viz.tui.header import (
    _custom_dashboard_sources,
    _header_refresh_interval,
    _reconcile_custom_dashboard_summaries,
)
from ccusage_viz.tui.models import (
    BuiltinSummaryOutcome,
    CustomDashboardSummary,
    CustomLogRecord,
    CustomOutcome,
    PaneFuture,
    TuiChartPane,
    TuiCustomPane,
)
from ccusage_viz.tui.pane_lifecycle import (
    _await_builtin_summary_submission,
    _await_custom_submission,
    _await_historical,
    _await_historical_submission,
    _await_monitor_submission,
    _await_monitor_warmup,
)


def start_pane_submission(
    session: TuiSession, pane: TuiChartPane, operation: OperationToken
) -> tuple[PaneFuture, Callable[[], None]]:
    component = pane.component
    if isinstance(component, MonitorComponent):
        if (
            component.candidate.host.demo_size
            and pane.demo_warmed_generation != component.generation
        ):
            chart = component.candidate.chart
            if not isinstance(chart, MonitorConfig):
                raise TypeError("monitor pane component has historical configuration")
            cancelled = Event()
            steps = min(24, max(8, chart.window_seconds))
            warmup_future = session.executor.submit(
                _await_monitor_warmup,
                component,
                generation=component.generation,
                trigger=operation.trigger,
                steps=steps,
                cancelled=cancelled,
            )
            return (warmup_future, cancelled.set)
        try:
            submission = component.submit(
                query_trigger(operation.trigger), sample_ordinal=pane.demo_ordinal + 1
            )
        except BaseException as exc:
            component.fail(exc, generation=component.generation)
            raise
        monitor_future = session.executor.submit(_await_monitor_submission, submission)
        return (monitor_future, submission.cancel)
    purpose = (
        HistoricalPurpose.SUPPLEMENTAL
        if operation.trigger is LifecycleTrigger.CONFIGURATION
        and component.snapshot is not None
        and (component.accepted_generation == component.generation)
        and component.missing_comparison_coverage().intervals
        else HistoricalPurpose.PRIMARY
    )
    try:
        submission = component.submit(
            query_trigger(operation.trigger),
            coverage=component.snapshot.coverage
            if purpose is HistoricalPurpose.SUPPLEMENTAL and component.snapshot is not None
            else None,
            purpose=purpose,
        )
    except BaseException as exc:
        component.fail(exc, generation=component.generation, purpose=purpose)
        raise
    historical_future = session.executor.submit(_await_historical_submission, submission)
    return (historical_future, submission.cancel)


def record_custom_log(session: TuiSession, pane: TuiCustomPane, status: str, detail: str) -> None:
    pane.logs.append(CustomLogRecord(datetime.now().astimezone(), status, detail))
    pane.logs[:] = pane.logs[-20:]


def record_custom_warnings(
    session: TuiSession, source: CustomCommandSource, response: object
) -> None:
    for warning in getattr(response, "warnings", ()):
        identity = (source.dataset_id, warning.code)
        if identity in session.displayed_custom_warnings:
            continue
        session.displayed_custom_warnings.add(identity)
        message = (
            warning.message.zh_cn if session.translator.language == "zh" else warning.message.en
        )
        for pane in (item for item in session.panes if isinstance(item, TuiCustomPane)):
            if pane.component.candidate.source.dataset_id == source.dataset_id:
                record_custom_log(session, pane, "warning", message)


def start_custom_submission(
    session: TuiSession, pane: TuiCustomPane, operation: OperationToken
) -> tuple[Future[CustomOutcome], Callable[[], None]]:
    custom_monitor = isinstance(pane.component, CustomMonitorComponent)
    if not pane.probe_complete:
        intent = (
            custom_v2_probe_query_intent
            if custom_monitor or pane.component.candidate.metric_id is not None
            else custom_probe_query_intent
        )(
            pane.component.candidate.source,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=pane.process,
        )
        handle = session.runtime.submit(intent)
        return (
            session.executor.submit(
                _await_custom_submission, handle, operation.generation, "probe"
            ),
            handle.cancel,
        )
    if custom_monitor:
        if session.options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        intent = custom_v2_monitor_query_intent(
            pane.component.request_config,
            timezone=session.options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            end_at=datetime.now().astimezone(),
            process=pane.process,
        )
        handle = session.runtime.submit(intent)
        return (
            session.executor.submit(
                _await_custom_submission, handle, operation.generation, "primary"
            ),
            handle.cancel,
        )
    purpose = "comparison" if pane.component.comparison_is_pending else "primary"
    config = (
        pane.component.comparison_request_config()
        if purpose == "comparison"
        else pane.component.request_config
    )
    if config is None:
        raise RuntimeError("custom comparison request is no longer required")
    if session.options.host.timezone is None:
        raise RuntimeError("custom Dataset requests require a timezone")
    intent = custom_historical_query_intent(
        config,
        timezone=session.options.host.timezone,
        owner_id=operation.owner_id,
        generation=operation.generation,
        trigger=query_trigger(operation.trigger),
        process=pane.process,
        request_id_suffix=":comparison" if purpose == "comparison" else "",
        partition_declared=pane.component.partition_declared_for_request,
    )
    handle = session.runtime.submit(intent)
    return (
        session.executor.submit(
            _await_custom_submission,
            handle,
            operation.generation,
            purpose,
            config if purpose == "comparison" else None,
        ),
        handle.cancel,
    )


def start_builtin_pane_summary_submission(
    session: TuiSession, pane: TuiChartPane, operation: OperationToken
) -> tuple[Future[BuiltinSummaryOutcome], Callable[[], None]]:
    component = pane.component
    if not isinstance(component, HistoricalChartComponent):
        raise TypeError("monitor panes do not have built-in summary lifecycles")
    plan = builtin_summary_query_plan(
        component.candidate, today=local_today(timezone=session.options.host.timezone)
    )
    intent = builtin_summary_query_intent(
        component.candidate,
        session.runtime.definition(historical_provider_id(component.candidate)),
        plan,
        owner_id=operation.owner_id,
        generation=operation.generation,
        trigger=query_trigger(operation.trigger),
    )
    handle = session.runtime.submit(intent)
    return (
        session.executor.submit(
            _await_builtin_summary_submission,
            handle,
            operation.generation,
            plan,
            component.candidate.chart,  # ty: ignore[invalid-argument-type]
        ),
        handle.cancel,
    )


def refresh_builtin_pane_summary(
    session: TuiSession,
    pane: TuiChartPane,
    *,
    trigger: LifecycleTrigger,
    replace_active: bool = False,
    invalidate: bool = False,
) -> bool:
    lifecycle = pane.summary_lifecycle
    if lifecycle is None or not isinstance(pane.component, HistoricalChartComponent):
        return False
    if invalidate:
        pane.summary_generation += 1
        lifecycle.detach_active()
    try:
        return lifecycle.request(
            trigger,
            generation=pane.summary_generation,
            now=time.monotonic(),
            replace_active=replace_active,
            start=lambda operation: start_builtin_pane_summary_submission(session, pane, operation),
        )
    except BaseException as exc:
        pane.summary_error = exc
        return False


def start_builtin_pane_summary(session: TuiSession, pane: TuiChartPane, *, now: float) -> bool:
    lifecycle = pane.summary_lifecycle
    if lifecycle is None:
        return False
    try:
        return lifecycle.start_ready(
            now=now,
            start=lambda operation: start_builtin_pane_summary_submission(session, pane, operation),
        )
    except BaseException as exc:
        pane.summary_error = exc
        return False


def start_custom_pane_summary_submission(
    session: TuiSession, pane: TuiCustomPane, operation: OperationToken
) -> tuple[Future[CustomOutcome], Callable[[], None]]:
    summary = pane.summary
    if summary is None:
        raise RuntimeError("custom Pane has no summary lifecycle")
    config = pane.component.request_config
    if session.options.host.timezone is None:
        raise RuntimeError("custom Dataset requests require a timezone")
    plan = (
        range_summary_query_plan(config.date_range)  # ty: ignore[invalid-argument-type]
        if config.date_range.fixed_bounds
        else summary_query_plan(
            local_today(timezone=session.options.host.timezone),
            cast(SummaryScope, config.granularity),
        )
    )
    summary.select(config.source, config.filters)
    intent = (
        custom_v2_summary_query_intent(
            config,
            plan,
            timezone=session.options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=pane.process,
        )
        if config.metric_id is not None
        else custom_summary_query_intent(
            config.source,
            plan,
            filters=config.filters,
            timezone=session.options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=pane.process,
        )
    )
    request = intent.payload
    if not isinstance(request, (CustomSummaryRequest, V2SummaryRequest)):
        raise TypeError("custom Pane summary intent has an unexpected payload")
    summary.requested_period = request.scope
    summary.requested_as_of_date = request.current.until
    handle = session.runtime.submit(intent)
    return (
        session.executor.submit(_await_custom_submission, handle, operation.generation),
        handle.cancel,
    )


def refresh_custom_pane_summary(
    session: TuiSession,
    pane: TuiCustomPane,
    *,
    trigger: LifecycleTrigger,
    replace_active: bool = False,
    summary_affecting: bool = False,
) -> bool:
    summary = pane.summary
    if summary is None:
        return False
    config = pane.component.request_config
    if not custom_date_summary_supported(config):
        if summary.response is not None or summary.lifecycle.active is not None:
            summary.invalidate()
        return False
    source_changed = summary.source != config.source or summary.filters != config.filters
    if source_changed:
        summary.invalidate()
    try:
        return summary.lifecycle.request(
            trigger,
            generation=summary.generation,
            now=time.monotonic(),
            replace_active=replace_active,
            start=lambda operation: start_custom_pane_summary_submission(session, pane, operation),
        )
    except BaseException as exc:
        summary.error = exc
        return False


def start_pane(session: TuiSession, index: int, *, now: float) -> bool:
    pane = session.panes[index]
    try:
        if isinstance(pane, TuiCustomPane):
            chart_started = pane.lifecycle.start_ready(
                now=now, start=lambda operation: start_custom_submission(session, pane, operation)
            )
            summary_started = (
                refresh_custom_pane_summary(
                    session, pane, trigger=LifecycleTrigger.STARTUP, summary_affecting=True
                )
                if pane.probe_complete
                else False
            )
            return chart_started or summary_started
        if isinstance(pane, TuiChartPane):
            chart_started = pane.lifecycle.start_ready(
                now=now, start=lambda operation: start_pane_submission(session, pane, operation)
            )
            return start_builtin_pane_summary(session, pane, now=now) or chart_started
    except BaseException as exc:
        if isinstance(pane, TuiCustomPane) and pane.component.fail(
            exc, generation=pane.component.generation
        ):
            record_custom_log(
                session, pane, "error", _custom_failure_log_detail(exc, session.translator)
            )
        return False
    return False


def pane_records(session: TuiSession, pane: TuiChartPane) -> tuple[UsageRecord, ...]:
    component = pane.component
    if isinstance(component, MonitorComponent):
        return component.accepted_records
    return component.snapshot.records if component.snapshot is not None else ()


def start_new_pane(session: TuiSession, index: int) -> None:
    refresh(session, index, trigger=LifecycleTrigger.STARTUP)


def pane_includes_projects(session: TuiSession, pane: TuiChartPane) -> bool:
    component = pane.component
    return (
        not isinstance(component, HistoricalChartComponent)
        or component.snapshot is None
        or component.snapshot.includes_project_attribution
    )


def refresh(
    session: TuiSession,
    index: int,
    *,
    trigger: LifecycleTrigger,
    replace_active: bool = False,
    data_affecting: bool = True,
    summary_affecting: bool = False,
) -> bool:
    pane = session.panes[index]
    if isinstance(pane, TuiCustomPane):
        if data_affecting:
            component = pane.component
            component.configure(
                replace(
                    component.candidate,
                    date_range=refresh_custom_ranking_range(
                        component.candidate.date_range,
                        now=datetime.now().astimezone(),
                        timezone=session.options.host.timezone,  # ty: ignore[invalid-argument-type]
                    ),
                ),
                data_affecting=True,
            )
        now = time.monotonic()
        try:
            chart_requested = pane.lifecycle.request(
                trigger,
                generation=pane.component.generation,
                now=now,
                replace_active=replace_active,
                start=lambda operation: start_custom_submission(session, pane, operation),
            )
            should_refresh_summary = summary_affecting or trigger in {
                LifecycleTrigger.PERIODIC,
                LifecycleTrigger.MANUAL,
            }
            summary_requested = (
                refresh_custom_pane_summary(
                    session,
                    pane,
                    trigger=trigger,
                    replace_active=replace_active,
                    summary_affecting=summary_affecting,
                )
                if should_refresh_summary and pane.probe_complete
                else False
            )
            return chart_requested or summary_requested
        except BaseException as exc:
            if pane.component.fail(exc, generation=pane.component.generation):
                record_custom_log(
                    session, pane, "error", _custom_failure_log_detail(exc, session.translator)
                )
            return False
    if not isinstance(pane, TuiChartPane):
        return False
    component = pane.component
    if not isinstance(component, MonitorComponent) and data_affecting:
        current = component.candidate
        if isinstance(current.chart, MonitorConfig):
            raise TypeError("historical pane component has monitor configuration")
        submitted = replace(
            current,
            chart=replace(
                current.chart,
                date_range=refresh_date_range(
                    current.chart.date_range,  # ty: ignore[invalid-argument-type]
                    timezone=session.options.host.timezone,
                ),
            ),
        )
        component.configure(submitted, data_affecting=True)
    now = time.monotonic()
    try:
        chart_requested = pane.lifecycle.request(
            trigger,
            generation=component.generation,
            now=now,
            replace_active=replace_active,
            start=lambda operation: start_pane_submission(session, pane, operation),
        )
        summary_requested = refresh_builtin_pane_summary(
            session, pane, trigger=trigger, replace_active=replace_active, invalidate=data_affecting
        )
        return chart_requested or summary_requested
    except BaseException:
        return False


def start_custom_summary_submission(
    session: TuiSession, summary: CustomDashboardSummary, operation: OperationToken
) -> tuple[Future[CustomOutcome], Callable[[], None]]:
    selections = {item.source.dataset_id: item for item in _custom_dashboard_sources(session.panes)}
    selection = selections.get(summary.source.dataset_id)
    if selection is None:
        raise RuntimeError("custom Dashboard source is no longer visible")
    summary.select(selection.source, ())
    if session.options.host.timezone is None:
        raise RuntimeError("custom Dataset requests require a timezone")
    if selection.summary_mode == "none":
        raise RuntimeError("summary disabled for selected metric")
    plan = (
        range_summary_query_plan(selection.config.date_range)  # ty: ignore[invalid-argument-type]
        if selection.config is not None and selection.config.date_range.fixed_bounds
        else summary_query_plan(
            local_today(timezone=session.options.host.timezone),
            cast(SummaryScope, session.header.summary_period),
        )
    )
    if selection.summary_mode in {"total", "comparisons"} and selection.config is not None:
        if selection.summary_mode == "total":
            plan = SummaryQueryPlan("total", plan.current)  # ty: ignore[invalid-argument-type]
        intent = custom_v2_summary_query_intent(
            selection.config,
            plan,
            timezone=session.options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=session.options.process,
        )
    else:
        intent = custom_summary_query_intent(
            summary.source,
            plan,
            filters=summary.filters,
            timezone=session.options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=session.options.process,
        )
    request = intent.payload
    if isinstance(request, V2SummaryRequest):
        summary.requested_period = request.scope
        summary.requested_as_of_date = request.current.until
    elif not isinstance(request, CustomSummaryRequest):
        raise TypeError("custom Dashboard summary intent has an unexpected payload")
    else:
        summary.requested_period = request.scope
        summary.requested_as_of_date = request.current.until
    handle = session.runtime.submit(intent)
    return (
        session.executor.submit(_await_custom_submission, handle, operation.generation),
        handle.cancel,
    )


def start_custom_summary(
    session: TuiSession, summary: CustomDashboardSummary, *, now: float
) -> bool:
    try:
        return summary.lifecycle.start_ready(
            now=now,
            start=lambda operation: start_custom_summary_submission(session, summary, operation),
        )
    except BaseException as exc:
        summary.error = exc
        return False


def refresh_custom_summary(
    session: TuiSession,
    summary: CustomDashboardSummary,
    *,
    trigger: LifecycleTrigger,
    replace_active: bool = False,
) -> bool:
    if session.header.summary_period == "none":
        return False
    try:
        return summary.lifecycle.request(
            trigger,
            generation=summary.generation,
            now=time.monotonic(),
            replace_active=replace_active,
            start=lambda operation: start_custom_summary_submission(session, summary, operation),
        )
    except BaseException as exc:
        summary.error = exc
        return False


def refresh_custom_summaries(
    session: TuiSession, *, trigger: LifecycleTrigger, replace_active: bool = False
) -> tuple[OperationToken, ...]:
    return tuple(
        summary.lifecycle.active
        for summary in session.header.custom_summaries.values()
        if refresh_custom_summary(session, summary, trigger=trigger, replace_active=replace_active)
        and summary.lifecycle.active is not None
    )


def start_header_submission(
    session: TuiSession, operation: OperationToken
) -> tuple[Future[UsageSnapshot], Callable[[], None]]:
    requested = _header_refresh_interval(
        session.header, aggressive=operation.trigger is LifecycleTrigger.MANUAL
    )
    if requested is None:
        raise AssertionError("admitted header refresh must require data")
    submitted = replace(
        session.header.options,
        chart=replace(
            session.header.options.chart, date_range=DateRange(requested.since, requested.until)
        ),
    )
    intent = historical_query_intent(
        submitted,
        session.header.runtime.definition(historical_provider_id(submitted)),
        owner_id=operation.owner_id,
        generation=operation.generation,
        trigger=query_trigger(operation.trigger),
    )
    started = time.monotonic()
    handle = session.header.runtime.submit(intent)
    session.header.options = submitted
    session.header.error = None
    return (session.executor.submit(_await_historical, handle, started), handle.cancel)


def start_header(session: TuiSession, *, now: float) -> bool:
    if not session.header.token_enabled:
        return False
    try:
        return session.header.lifecycle.start_ready(
            now=now, start=partial(start_header_submission, session)
        )
    except BaseException as exc:
        session.header.error = str(exc)
        return False


def refresh_header(
    session: TuiSession, *, trigger: LifecycleTrigger, replace_active: bool = False
) -> bool:
    if not session.header.token_enabled:
        return False
    if (
        _header_refresh_interval(session.header, aggressive=trigger is LifecycleTrigger.MANUAL)
        is None
    ):
        return False
    now = time.monotonic()
    try:
        return session.header.lifecycle.request(
            trigger,
            generation=session.header.generation,
            now=now,
            replace_active=replace_active,
            start=partial(start_header_submission, session),
        )
    except BaseException as exc:
        session.header.error = str(exc)
        return False


def sync_custom_dashboard_summaries(session: TuiSession) -> None:
    token_enabled = any(isinstance(pane, TuiChartPane) for pane in session.panes)
    if session.header.token_enabled and (not token_enabled):
        session.header.generation += 1
        session.header.lifecycle.detach_active()
    session.header.token_enabled = token_enabled
    added = _reconcile_custom_dashboard_summaries(
        session.header, _custom_dashboard_sources(session.panes), now=time.monotonic()
    )
    if session.header_style != "hidden":
        if token_enabled:
            refresh_header(session, trigger=LifecycleTrigger.CONFIGURATION)
        for summary in added:
            refresh_custom_summary(session, summary, trigger=LifecycleTrigger.CONFIGURATION)
