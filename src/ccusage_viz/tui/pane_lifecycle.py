from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from dataclasses import replace
from datetime import datetime
from threading import Event
from typing import Literal
from zoneinfo import ZoneInfo

from ccusage_viz.animation import (
    AnimationRenderer,
    animation_spec,
    default_animation_spec,
    new_animation_session,
)
from ccusage_viz.animation_overlay import AnimationOverlayRuntime
from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalSubmission,
    UsageSnapshot,
    snapshot_from_result,
)
from ccusage_viz.lifecycle import (
    FixedIntervalScheduler,
    LifecycleOperation,
    LifecycleTrigger,
    query_trigger,
)
from ccusage_viz.monitor_component import MonitorCompletion, MonitorComponent, MonitorSubmission
from ccusage_viz.options import (
    AnimationPaneConfig,
    ChartPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    HistoricalChartConfig,
    MonitorConfig,
    PaneConfig,
    StandaloneLaunch,
)
from ccusage_viz.processing.summaries import SummaryQueryPlan
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.tui.models import (
    BuiltinSummaryOutcome,
    CustomDashboardSummary,
    CustomOutcome,
    HistoricalOutcome,
    MonitorOutcome,
    MonitorWarmupOutcome,
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    TuiEmptyPane,
    TuiPane,
)


def _shutdown_pane(pane: TuiPane) -> None:
    """Release resources owned by a query-backed or animation pane."""
    if isinstance(pane, TuiEmptyPane):
        return
    if isinstance(pane, TuiAnimationPane):
        pane.overlay.close()
        return
    pane.scheduler.shutdown()
    pane.lifecycle.shutdown()
    if isinstance(pane, TuiChartPane) and pane.summary_lifecycle is not None:
        pane.summary_lifecycle.shutdown()
    if isinstance(pane, TuiCustomPane) and pane.summary is not None:
        pane.summary.scheduler.shutdown()
        pane.summary.lifecycle.shutdown()


def _replace_pane(
    panes: list[TuiPane],
    index: int,
    replacement: TuiPane,
    *,
    start: Callable[[int], None],
) -> None:
    displaced = panes[index]
    panes[index] = replacement
    start(index)
    _shutdown_pane(displaced)


def _insert_pane(
    panes: list[TuiPane],
    index: int,
    inserted: TuiPane,
    *,
    start: Callable[[int], None],
) -> None:
    panes.insert(index, inserted)
    start(index)


def _new_pane(
    options: StandaloneLaunch | DashboardLaunch,
    pane_config_or_owner: PaneConfig | str,
    owner_id: str | QueryRuntime | None = None,
    runtime: QueryRuntime | None = None,
) -> TuiPane:
    """Construct a query-backed chart pane or an isolated animation pane."""
    if isinstance(options, DashboardLaunch):
        if not isinstance(
            pane_config_or_owner,
            (AnimationPaneConfig, ChartPaneConfig, CustomChartPaneConfig, EmptyPaneConfig),
        ):
            raise TypeError("dashboard pane configuration is required")
        pane_config = pane_config_or_owner
        if isinstance(pane_config, EmptyPaneConfig):
            return TuiEmptyPane()
        if isinstance(pane_config, AnimationPaneConfig):
            return TuiAnimationPane(
                new_animation_session(pane_config.animation, theme=options.host.theme),
                AnimationRenderer(),
                AnimationOverlayRuntime(pane_config.overlay),
            )
        # The public helper remains usable for a single Dashboard pane outside
        # the Dashboard construction loop; regular Dashboard callers pass a
        # stable pane-specific owner ID.
        if owner_id is None:
            owner_id = "dashboard:pane"
        if not isinstance(owner_id, str):
            raise TypeError("dashboard chart pane owner id must be a string")
        if isinstance(pane_config, CustomChartPaneConfig):
            started_at = time.monotonic()
            component = (
                CustomMonitorComponent(pane_config.chart)
                if pane_config.chart.kind == "monitor"
                else CustomHistoricalComponent(pane_config.chart)
            )
            attachment = None
            attachment_renderer = None
            if isinstance(component, CustomMonitorComponent):
                if options.host.timezone is None:
                    raise RuntimeError("custom Dataset requests require a timezone")
                component.configure_display_timezone(ZoneInfo(options.host.timezone))
                component.start_monitoring(datetime.now(ZoneInfo(options.host.timezone)))
                attachment = new_animation_session(
                    default_animation_spec("monitor"), theme="classic"
                )
                attachment.set_playback_requested(False, started_at)
                attachment.set_idle_animation_requested(True, started_at)
                attachment.set_visible(False, started_at)
                attachment_renderer = AnimationRenderer()
            interval = (
                options.host.sampling_interval
                if pane_config.chart.kind == "monitor"
                else options.host.refresh_interval
            )
            if (
                isinstance(component, CustomHistoricalComponent)
                and component.capability is not None
            ):
                interval = component.capability.refresh_interval_seconds or interval
            pane = TuiCustomPane(
                component,
                FixedIntervalScheduler(interval, now=started_at),
                LifecycleOperation(owner_id),
                options.process,
                None
                if pane_config.chart.kind == "monitor"
                else CustomDashboardSummary(
                    pane_config.chart.source,
                    FixedIntervalScheduler(options.host.refresh_interval, now=started_at),
                    LifecycleOperation(f"{owner_id}:summary"),
                    filters=pane_config.chart.filters,
                    metric_id=pane_config.chart.metric_id,
                    summary_mode=pane_config.chart.metric_summary,
                ),
                attachment=attachment,
                attachment_renderer=attachment_renderer,
                ranking_item_spacing=pane_config.ranking_item_spacing,
            )
            if attachment is not None:
                if pane_config.attachment_style is not None:
                    attachment.set_style(
                        animation_spec(pane_config.attachment_style, target="monitor"), started_at
                    )
                if pane_config.attachment_theme is not None:
                    attachment.set_theme(pane_config.attachment_theme, started_at)
                pane.attachment_enabled = pane_config.attachment_style is not None
            return pane
        from ccusage_viz.configuration import standalone_from_chart_pane

        pane = _new_pane(
            standalone_from_chart_pane(options, pane_config), owner_id, runtime=runtime
        )
        assert isinstance(pane, TuiChartPane)
        attachment = pane.attachment
        if attachment is not None:
            now = time.monotonic()
            if pane_config.attachment_style is not None:
                attachment.set_style(
                    animation_spec(pane_config.attachment_style, target="monitor"), now
                )
            if pane_config.attachment_theme is not None:
                attachment.set_theme(pane_config.attachment_theme, now)
            pane.attachment_enabled = pane_config.attachment_style is not None
        return pane
    if not isinstance(pane_config_or_owner, str):
        raise TypeError("chart pane owner id is required")
    if isinstance(owner_id, QueryRuntime):
        runtime = owner_id
    elif owner_id is not None:
        raise TypeError("chart pane runtime is required")
    chart_owner_id = pane_config_or_owner
    registry = build_chart_registry()
    component: HistoricalChartComponent | MonitorComponent
    if isinstance(options.chart, MonitorConfig):
        component = MonitorComponent(
            options,
            owner_id=chart_owner_id,
            runtime=runtime,
            registry=registry,
        )
    else:
        component = HistoricalChartComponent(
            options,
            owner_id=chart_owner_id,
            runtime=runtime,
            registry=registry,
            include_summary=False,
        )
    now = time.monotonic()
    attachment = None
    attachment_renderer = None
    if isinstance(component, MonitorComponent):
        attachment = new_animation_session(default_animation_spec("monitor"), theme="classic")
        attachment.set_playback_requested(False, now)
        attachment.set_idle_animation_requested(True, now)
        attachment.set_visible(False, now)
        attachment_renderer = AnimationRenderer()
    return TuiChartPane(
        component,
        FixedIntervalScheduler(options.host.interval, now=now),
        LifecycleOperation(chart_owner_id),
        (
            LifecycleOperation(f"{chart_owner_id}:summary")
            if isinstance(component, HistoricalChartComponent)
            else None
        ),
        attachment=attachment,
        attachment_renderer=attachment_renderer,
    )


def _await_custom_submission(
    handle: QueryHandle[ProviderResult],
    generation: int,
    purpose: Literal["probe", "primary", "comparison"] = "primary",
    comparison_request_config: CustomChartConfig | None = None,
) -> CustomOutcome:
    try:
        return CustomOutcome(
            generation,
            result=handle.result(),
            purpose=purpose,
            comparison_request_config=comparison_request_config,
        )
    except BaseException as exc:
        return CustomOutcome(
            generation,
            error=exc,
            purpose=purpose,
            comparison_request_config=comparison_request_config,
        )


def _await_historical(handle: QueryHandle[ProviderResult], started: float) -> UsageSnapshot:
    return snapshot_from_result(handle.result(), time.monotonic() - started)


def _await_builtin_summary_submission(
    handle: QueryHandle[ProviderResult],
    generation: int,
    plan: SummaryQueryPlan,
    chart: HistoricalChartConfig,
) -> BuiltinSummaryOutcome:
    try:
        return BuiltinSummaryOutcome(generation, plan, chart, result=handle.result())
    except BaseException as exc:
        return BuiltinSummaryOutcome(generation, plan, chart, error=exc)


def _await_historical_submission(submission: HistoricalSubmission) -> HistoricalOutcome:
    try:
        return HistoricalOutcome(
            submission.generation,
            submission.purpose,
            completion=submission.result(),
        )
    except BaseException as exc:
        return HistoricalOutcome(
            submission.generation,
            submission.purpose,
            error=exc,
        )


def _await_monitor_submission(submission: MonitorSubmission) -> MonitorOutcome:
    try:
        return MonitorOutcome(submission.generation, completion=submission.result())
    except BaseException as exc:
        return MonitorOutcome(submission.generation, error=exc)


def _await_monitor_warmup(
    component: MonitorComponent,
    *,
    generation: int,
    trigger: LifecycleTrigger,
    steps: int,
    cancelled: Event,
) -> MonitorWarmupOutcome:
    """Collect the deterministic cumulative demo history off the TUI thread."""
    completions: list[MonitorCompletion] = []
    try:
        for ordinal in range(1, steps + 1):
            if cancelled.is_set() or component.generation != generation:
                return MonitorWarmupOutcome(generation)
            submission = component.submit(query_trigger(trigger), sample_ordinal=ordinal)
            completion = submission.result()
            if cancelled.is_set() or component.generation != generation:
                return MonitorWarmupOutcome(generation)
            completions.append(completion)
        return MonitorWarmupOutcome(generation, tuple(completions))
    except BaseException as exc:
        return MonitorWarmupOutcome(generation, tuple(completions), exc)


def _refresh_deltas(pane: TuiChartPane, values: dict[Hashable, float]) -> None:
    tracker = RefreshDeltas(
        pane.previous_values,
        pane.deltas,
        getattr(pane, "values_initialized", False),
    )
    tracker.accept(values)
    pane.previous_values = tracker.previous
    pane.deltas = tracker.current
    pane.values_initialized = tracker.initialized


def _refresh_ranks(pane: TuiChartPane, ordered_keys: tuple[Hashable, ...]) -> None:
    tracker = RefreshRanks(pane.previous_ranks, pane.rank_deltas)
    tracker.accept(ordered_keys)
    pane.previous_ranks = tracker.previous
    pane.rank_deltas = tracker.current


def _clear_changes(pane: TuiChartPane) -> None:
    pane.previous_values.clear()
    pane.deltas.clear()
    pane.values_initialized = False
    pane.previous_ranks.clear()
    pane.rank_deltas.clear()


def _new_pane_options(command: str, base: DashboardLaunch) -> StandaloneLaunch:
    from ccusage_viz.configuration import default_pane, standalone_from_chart_pane

    pane = default_pane(command, dashboard=base)
    if command == "monitor":
        pane = replace(pane, chart=replace(pane.chart, by="model", top=3))
    return standalone_from_chart_pane(base, pane)
