from __future__ import annotations

# ruff: noqa: B023
import shlex
import sys
import time
from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from shutil import get_terminal_size
from threading import Event
from typing import Literal, cast

from ccusage_viz import __version__
from ccusage_viz.acquisition import (
    builtin_summary_query_intent,
    builtin_summary_query_plan,
    custom_historical_query_intent,
    custom_probe_query_intent,
    custom_summary_query_intent,
    custom_v2_summary_query_intent,
    custom_v2_monitor_query_intent,
    custom_v2_probe_query_intent,
    historical_provider_id,
    historical_query_intent,
)
from ccusage_viz.adjustment_timeout import (
    HELP_IDLE_TIMEOUT_SECONDS,
    AdjustmentIdleTimer,
    AdjustmentTimeout,
)
from ccusage_viz.animate import (
    _editor_line_end,
    _editor_line_start,
    _editor_next_word,
    _editor_previous_word,
    _editor_viewport,
    _format_overlay_interval,
    _overlay_editor_controls,
    cycle_animation_style,
)
from ccusage_viz.animation import (
    AnimationRenderer,
    AnimationSessionState,
    animation_spec,
    animation_style_choices,
    cycle_monitor_attachment,
    default_animation_spec,
    last_activity_label,
    new_animation_session,
)
from ccusage_viz.animation_overlay import (
    AnimationOverlayRuntime,
    OverlayHistoryTableState,
    OverlayPlacement,
    clip_overlay_placements,
    compose_overlay_row,
    format_execution_record,
    move_history_selection,
    render_history_table,
)
from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.builtin_summary import BuiltinPaneSummary, build_builtin_pane_summary
from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    format_full_dashboard_command,
    wrap_command,
)
from ccusage_viz.configuration import (
    apply_custom_probe_defaults,
    default_custom_pane,
    v2_metric_probe_descriptor,
)
from ccusage_viz.core.time import (
    DateRange,
    local_today,
    refresh_date_range,
)
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.custom_component import (
    CustomHistoricalComponent,
    custom_replacement_required,
    custom_summary_replacement_required,
)
from ccusage_viz.custom_filter_draft import run_custom_filter_editor
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomFilter,
    CustomProtocolFailure,
    V2MonitorCapability,
    V2HistoricalChartCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
    resolve_metric,
)
from ccusage_viz.custom_protocol import (
    CustomProbeResponse,
    CustomSummaryRequest,
    CustomSummaryResponse,
    V2MonitorResponse,
    V2ProbeResponse,
    V2SummaryResponse,
    V2SummaryRequest,
)
from ccusage_viz.dashboard_history import DashboardHistory
from ccusage_viz.dashboard_layout import (
    PaneLayout as ResolvedPaneLayout,
)
from ccusage_viz.dashboard_layout import (
    PaneRect,
    adjust_weight,
    fixed_shape,
    layout_bands,
    layout_for_pane_count,
    reconcile_weights,
    resolve_pane_layout,
)
from ccusage_viz.dashboard_layout import (
    pane_at as layout_pane_at,
)
from ccusage_viz.dashboard_layout import (
    parse_grid as parse_numeric_grid,
)
from ccusage_viz.dashboard_layout import (
    parse_layout as parse_dashboard_layout,
)
from ccusage_viz.data_view import (
    BodyView,
    DashboardBodyView,
    body_view_copy_kind,
    cycle_body_view,
    cycle_dashboard_body_view,
    render_current_monitor_data,
    render_custom_data,
    render_snapshot_data,
)
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.diagnostics import format_error, transient_query_recovery_lines
from ccusage_viz.domain import UsageRecord
from ccusage_viz.editor_help import editor_help_groups
from ccusage_viz.errors import QueryError, UsageError, VizError
from ccusage_viz.filter_draft import discover_filter_choices, run_filter_editor
from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
    format_tokens,
    pad_width,
    truncate_width,
    wrap_width,
)
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalCompletion,
    HistoricalPurpose,
    HistoricalSubmission,
    UsageSnapshot,
    historical_replacement_required,
    snapshot_from_result,
)
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import (
    FixedIntervalScheduler,
    LifecycleOperation,
    LifecycleTrigger,
    OperationToken,
    query_trigger,
)
from ccusage_viz.monitor_component import (
    MonitorCompletion,
    MonitorComponent,
    MonitorSubmission,
)
from ccusage_viz.options import (
    DASHBOARD_STYLES,
    HEADER_SUMMARIES,
    AnimationPaneConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardLaunch,
    EmptyPaneConfig,
    Filters,
    HistoricalChartConfig,
    MonitorConfig,
    PaneConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_custom_chart,
    adjust_standalone,
    compatible_styles,
    replace_chart_filters,
)
from ccusage_viz.processing import build_period_summary, required_summary_coverage
from ccusage_viz.processing.custom_historical import CustomChartProjection
from ccusage_viz.processing.summaries import (
    SummaryQueryPlan,
    SummaryScope,
    range_summary_query_plan,
    summary_query_plan,
)
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.base import (
    RenderAudit,
    RenderContext,
    audit_row_visible,
    render_audit,
    styled_text,
)
from ccusage_viz.render.custom import (
    render_custom_failure,
    render_custom_pending,
    render_custom_projection,
)
from ccusage_viz.render.filters import active_filter_summary
from ccusage_viz.render.palette import COLOR_SCHEMES, get_color_scheme
from ccusage_viz.render.summary import render_custom_metrics, render_summary
from ccusage_viz.render.surfaces import (
    EMPTY_SURFACE_CONTROLS,
    HistoricalPresentationSurface,
    SurfaceControls,
    SurfacePresentation,
    dashboard_pane_surface,
    standalone_surface,
)
from ccusage_viz.standalone_help import run_standalone_help
from ccusage_viz.terminal import (
    Frame,
    FramePainter,
    Terminal,
    compose_frame,
    emphasize,
    inspect_terminal,
    set_cursor_visible,
)
from ccusage_viz.terminal_ui import (
    AdjustmentAction,
    TransientFeedback,
    adjustment_rows,
    controls_line,
    dimmed,
    feedback_lines,
    input_mode,
    read_key,
)
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.text_viewport import (
    next_text_offset,
    render_text_viewport,
    text_viewport_overflows,
    wrap_text_rows,
)
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    read_event,
    tui_input_mode,
)

_PANE_COMMANDS = (
    "empty",
    "timeline",
    "stack",
    "calendar",
    "ranking",
    "monitor",
    "animate",
    "datasets",
)

_TOKEN_PANE_COMMANDS = ("timeline", "stack", "calendar", "ranking", "monitor")
_OTHER_PANE_COMMANDS = ("empty", "animate")


def _pane_chooser_rows(translator: Translator, selected: int) -> tuple[list[str], dict[str, int]]:
    current = _PANE_COMMANDS[selected]
    rows: list[str] = []
    positions: dict[str, int] = {}
    for heading, commands in (
        ("status.tui_pane_group_token", _TOKEN_PANE_COMMANDS),
        ("status.tui_pane_group_datasets", ("datasets",)),
        ("status.tui_pane_group_other", _OTHER_PANE_COMMANDS),
    ):
        if rows:
            rows.append("")
        rows.append(translator.text(heading))
        for command in commands:
            positions[command] = len(rows)
            rows.append(
                f"{'›' if command == current else ' '} {translator.text(f'label.pane_{command}')}"
            )
    return rows, positions


@dataclass(frozen=True, slots=True)
class HistoricalOutcome:
    generation: int
    purpose: HistoricalPurpose = HistoricalPurpose.PRIMARY
    completion: HistoricalCompletion | None = None
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class MonitorOutcome:
    generation: int
    completion: MonitorCompletion | None = None
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class MonitorWarmupOutcome:
    generation: int
    completions: tuple[MonitorCompletion, ...] = ()
    error: BaseException | None = None


PaneFuture = Future[HistoricalOutcome] | Future[MonitorOutcome] | Future[MonitorWarmupOutcome]


@dataclass(frozen=True, slots=True)
class BuiltinSummaryOutcome:
    generation: int
    plan: SummaryQueryPlan
    chart: HistoricalChartConfig
    result: ProviderResult | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class TuiEmptyPane:
    pane_id: int = -1


@dataclass(frozen=True, slots=True)
class CustomOutcome:
    generation: int
    result: ProviderResult | None = None
    error: BaseException | None = None
    purpose: Literal["probe", "primary", "comparison"] = "primary"


@dataclass(frozen=True, slots=True)
class CustomLogRecord:
    timestamp: datetime
    status: str
    detail: str


@dataclass(slots=True)
class TuiCustomPane:
    component: CustomHistoricalComponent | CustomMonitorComponent
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[Future[CustomOutcome]]
    process: ProcessConfig
    summary: CustomDashboardSummary | None = None
    probe_complete: bool = False
    pane_id: int = -1
    logs: list[CustomLogRecord] = field(default_factory=list)
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = field(default_factory=dict)
    text_line_counts: dict[BodyView, int] = field(default_factory=dict)
    text_visible_rows: dict[BodyView, int] = field(default_factory=dict)
    error_offset: int = 0
    error_line_count: int = 0
    error_visible_rows: int = 0

    @property
    def interval(self) -> float:
        return self.scheduler.interval


@dataclass(slots=True)
class TuiChartPane:
    component: HistoricalChartComponent | MonitorComponent
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[PaneFuture]
    summary_lifecycle: LifecycleOperation[Future[BuiltinSummaryOutcome]] | None = None
    summary: BuiltinPaneSummary | None = None
    summary_error: BaseException | None = None
    summary_generation: int = 0
    pane_id: int = -1
    demo_ordinal: int = 0
    demo_warmed_generation: int | None = None
    render_warning: UsageError | None = None
    last_render: PaneRender | None = None
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = field(default_factory=dict)
    text_line_counts: dict[BodyView, int] = field(default_factory=dict)
    text_visible_rows: dict[BodyView, int] = field(default_factory=dict)
    previous_values: dict[Hashable, float] = field(default_factory=dict)
    deltas: dict[Hashable, float] = field(default_factory=dict)
    values_initialized: bool = False
    previous_ranks: dict[Hashable, int] = field(default_factory=dict)
    rank_deltas: dict[Hashable, int] = field(default_factory=dict)
    attachment: AnimationSessionState | None = None
    attachment_renderer: AnimationRenderer | None = None
    attachment_enabled: bool = False

    @property
    def interval(self) -> float:
        return _pane_options(self).host.interval


@dataclass(slots=True)
class TuiAnimationPane:
    """A render-only dashboard pane; it owns no provider or lifecycle runtime."""

    session: AnimationSessionState
    renderer: AnimationRenderer
    overlay: AnimationOverlayRuntime
    pane_id: int = -1
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = field(default_factory=dict)
    text_line_counts: dict[BodyView, int] = field(default_factory=dict)
    text_visible_rows: dict[BodyView, int] = field(default_factory=dict)


TuiPane = TuiChartPane | TuiAnimationPane | TuiCustomPane | TuiEmptyPane


@dataclass(frozen=True, slots=True)
class DashboardPaneState:
    """Declarative Pane state suitable for session-only history restoration."""

    pane_id: int
    config: PaneConfig
    body_view: BodyView
    attachment_style: str | None = None
    attachment_theme: str | None = None
    attachment_enabled: bool = False
    animation_theme: str | None = None


@dataclass(frozen=True, slots=True)
class DashboardState:
    """The durable dashboard presentation state, without runtime resources."""

    panes: tuple[DashboardPaneState, ...]
    grid: str
    layout: str | None
    column_weights: tuple[int, ...] | None
    row_weights: tuple[int, ...] | None
    theme: str
    style: str
    header_style: str
    header_summary: str
    body_view: DashboardBodyView


@dataclass(slots=True)
class HelpOverlayState:
    """The active Help context while preserving the underlying modal state."""

    timer: AdjustmentIdleTimer
    adjustment_remaining: float | None
    context: str = "dashboard"
    action: str | None = None
    selected: str | None = None
    dataset_id: str | None = None
    chart_kind: str | None = None
    scroll_offset: int = 0


@dataclass(slots=True)
class OverlayEditorState:
    """Uncommitted source drafts displayed within one Dashboard animation pane."""

    pane_index: int
    mode: str
    text_draft: str
    command_draft: str
    text_cursor: int | None = None
    command_cursor: int | None = None

    def __post_init__(self) -> None:
        self.text_cursor = len(self.text_draft) if self.text_cursor is None else self.text_cursor
        self.command_cursor = (
            len(self.command_draft) if self.command_cursor is None else self.command_cursor
        )

    @property
    def draft(self) -> str:
        return self.command_draft if self.mode == "command" else self.text_draft

    @property
    def cursor(self) -> int:
        cursor = self.command_cursor if self.mode == "command" else self.text_cursor
        assert cursor is not None
        return cursor

    @cursor.setter
    def cursor(self, value: int) -> None:
        if self.mode == "command":
            self.command_cursor = value
        else:
            self.text_cursor = value

    def replace_draft(self, value: str) -> None:
        if self.mode == "command":
            self.command_draft = value
        else:
            self.text_draft = value


@dataclass(slots=True)
class OverlayHistoryState:
    """Command-history table displayed within one Dashboard animation pane."""

    pane_index: int
    table: OverlayHistoryTableState = field(default_factory=OverlayHistoryTableState)


@dataclass(slots=True)
class DashboardDatasetModalState:
    """One nonblocking Dashboard Dataset selection transaction."""

    action: str
    pane_index: int
    initial: CustomChartConfig | None
    statuses: tuple[object, ...]
    service: object
    stage: str = "pane"
    index: int = 0
    offset: int = 0
    draft: CustomPaneDraft = field(default_factory=lambda: CustomPaneDraft())
    error: str | None = None
    future: Future[object] | None = None
    entries: tuple[object, ...] = ()
    selected_dataset_id: str | None = None
    artifact: object | None = None
    official_preview: tuple[object, bytes, object] | None = None
    chart_kinds: tuple[str, ...] = ()
    metrics: tuple[object, ...] = ()
    metric_id: str | None = None
    metric_summary: str = "comparisons"
    metric_periods: tuple[str, ...] = ()
    metric_titles: tuple[str, str] | None = None


def _dataset_title(value, translator: Translator) -> str:
    return value.zh_cn if translator.language == "zh" else value.en


_DOUBLE_CLICK_SECONDS = 0.35


def _pane_options(pane: TuiChartPane) -> StandaloneLaunch:
    component = pane.component
    return component.accepted_options or component.candidate


def _pane_display_options(pane: TuiChartPane) -> StandaloneLaunch:
    component = pane.component
    if isinstance(component, HistoricalChartComponent) and getattr(component, "is_pending", False):
        return component.candidate
    if (
        isinstance(component, MonitorComponent)
        and component.candidate != component.accepted_options
    ):
        return component.candidate
    return _pane_options(pane)


def _chart_pane_config(pane: TuiChartPane) -> ChartPaneConfig:
    chart = _pane_options(pane).chart
    assert not isinstance(chart, CustomChartConfig)
    return ChartPaneConfig(chart)


def _custom_pane_options(dashboard: DashboardLaunch, pane: TuiCustomPane) -> StandaloneLaunch:
    from ccusage_viz.configuration import standalone_from_chart_pane

    chart = pane.component.accepted_config or pane.component.candidate
    return standalone_from_chart_pane(dashboard, CustomChartPaneConfig(chart))


@dataclass(slots=True)
class CustomDashboardSummary:
    """Per-dataset accepted state for one Header-owned source summary."""

    source: CustomCommandSource
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[Future[CustomOutcome]]
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    response: CustomSummaryResponse | V2SummaryResponse | None = None
    error: BaseException | None = None
    generation: int = 0
    accepted_at: datetime | None = None
    accepted_period: str | None = None
    accepted_as_of_date: date | None = None
    requested_period: str | None = None
    requested_as_of_date: date | None = None
    metric_id: str | None = None
    summary_mode: str = "comparisons"

    def select(
        self, source: CustomCommandSource, filters: tuple[tuple[str, tuple[str, ...]], ...]
    ) -> None:
        """Adopt the first visible Pane source only at a Header refresh boundary."""
        self.source = source
        self.filters = filters

    def invalidate(self) -> None:
        """Discard facts that no longer describe the selected summary query."""
        self.generation += 1
        self.lifecycle.detach_active()
        self.response = None
        self.error = None
        self.accepted_at = None
        self.accepted_period = None
        self.accepted_as_of_date = None
        self.requested_period = None
        self.requested_as_of_date = None


@dataclass(frozen=True, slots=True)
class CustomDashboardSource:
    """A Dataset source selected once per Header summary."""

    source: CustomCommandSource
    config: CustomChartConfig | None = field(default=None, compare=False)
    summary_mode: str = "comparisons"


@dataclass(slots=True)
class DashboardHeader:
    options: StandaloneLaunch
    runtime: QueryRuntime
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[Future[UsageSnapshot]]
    snapshot: UsageSnapshot | None = None
    error: str | None = None
    generation: int = 0
    records: tuple[UsageRecord, ...] = ()
    coverage: DateCoverage = field(default_factory=DateCoverage)
    accepted_at: datetime | None = None
    summary_period: str = "day"
    token_enabled: bool = True
    custom_summaries: dict[str, CustomDashboardSummary] = field(default_factory=dict)


def _header_options(
    base: DashboardLaunch, interval: DateInterval | None = None
) -> StandaloneLaunch:
    """Build the dashboard's deliberately unfiltered, all-agent daily query."""
    today = local_today()
    interval = interval or DateInterval(today - timedelta(days=7), today)
    chart = TimelineConfig(
        "timeline",
        DateRange(interval.since, interval.until),
        presentation=ChartPresentation(theme=base.host.theme, style="linear", legend="hidden"),
        other="hide",
    )
    return StandaloneLaunch(
        base.process,
        StandaloneHostConfig(
            provider=base.host.provider,
            ascii=base.host.ascii,
            demo_size=base.host.demo_size,
            interval=base.host.header_interval,
        ),
        chart,
    )


def _new_header(options: DashboardLaunch, runtime: QueryRuntime) -> DashboardHeader:
    return DashboardHeader(
        _header_options(options),
        runtime,
        FixedIntervalScheduler(options.host.header_interval, now=time.monotonic()),
        LifecycleOperation("dashboard:header"),
        summary_period=options.host.header_summary,
        token_enabled=any(isinstance(pane, ChartPaneConfig) for pane in options.panes),
    )


def _custom_dashboard_sources(panes: list[TuiPane]) -> tuple[CustomDashboardSource, ...]:
    """Choose the first visible Pane context for each distinct dataset ID."""
    sources: dict[str, CustomDashboardSource] = {}
    for pane in panes:
        if not isinstance(pane, TuiCustomPane):
            continue
        config = pane.component.candidate
        summary_mode = config.metric_summary
        if summary_mode == "none":
            continue
        sources.setdefault(
            config.source.dataset_id,
            CustomDashboardSource(config.source, config, summary_mode),
        )
    return tuple(sources.values())


def _reconcile_custom_dashboard_summaries(
    header: DashboardHeader,
    sources: tuple[CustomDashboardSource, ...],
    *,
    now: float,
) -> tuple[CustomDashboardSummary, ...]:
    """Add/remove Header ownership without replacing same-ID accepted sources."""
    added: list[CustomDashboardSummary] = []
    wanted = {item.source.dataset_id: item for item in sources}
    for dataset_id in tuple(header.custom_summaries):
        if dataset_id not in wanted:
            summary = header.custom_summaries.pop(dataset_id)
            summary.scheduler.shutdown()
            summary.lifecycle.shutdown()
    for dataset_id, selection in wanted.items():
        summary = header.custom_summaries.get(dataset_id)
        if summary is not None:
            if summary.source != selection.source:
                summary.invalidate()
                summary.select(selection.source, ())
                added.append(summary)
            summary.metric_id = selection.config.metric_id if selection.config is not None else None
            summary.summary_mode = selection.summary_mode
            continue
        summary = CustomDashboardSummary(
            selection.source,
            FixedIntervalScheduler(header.scheduler.interval, now=now),
            LifecycleOperation(f"dashboard:header:custom:{dataset_id}"),
        )
        summary.metric_id = selection.config.metric_id
        summary.summary_mode = selection.summary_mode
        header.custom_summaries[dataset_id] = summary
        added.append(summary)
    return tuple(added)


def _invalidate_custom_dashboard_summaries(header: DashboardHeader) -> None:
    for summary in header.custom_summaries.values():
        summary.generation += 1
        summary.lifecycle.detach_active()


def _set_header_theme(header: DashboardHeader, theme: str) -> None:
    header.options = replace(
        header.options,
        chart=replace(
            header.options.chart,
            presentation=replace(header.options.chart.presentation, theme=theme),
        ),
    )


def _cycle_header_summary(period: str, *, step: int = 1) -> str:
    """Cycle Dashboard header summary scopes in either direction."""
    return _cycle(HEADER_SUMMARIES, period, step)


def _next_header_summary(period: str) -> str:
    """Return the next Dashboard header summary scope."""
    return _cycle_header_summary(period)


def _header_refresh_interval(
    header: DashboardHeader, *, aggressive: bool = False, today=None
) -> DateInterval | None:
    period = header.summary_period
    if period == "none":
        return None
    current = today or local_today()
    required = required_summary_coverage(current, period)
    uncovered = tuple(
        missing for interval in required.intervals for missing in header.coverage.missing(interval)
    )
    if uncovered or aggressive:
        intervals = uncovered or required.intervals
        return DateInterval(
            min(item.since for item in intervals), max(item.until for item in intervals)
        )
    return DateInterval(current, current)


def _header_summary(header: DashboardHeader, period: str):
    if period == "none":
        return None
    summary = build_period_summary(
        header.records,
        local_today(),
        period,
        header.coverage,
    )
    return summary


def _replace_header_interval(
    records: tuple[UsageRecord, ...], snapshot: UsageSnapshot
) -> tuple[UsageRecord, ...]:
    intervals = snapshot.coverage.intervals
    retained = tuple(
        record
        for record in records
        if record.day is None
        or not any(item.since <= record.day <= item.until for item in intervals)
    )
    return (*retained, *snapshot.records)


def _dashboard_title_line(title: str, freshness: str, width: int, *, color: bool = True) -> str:
    """Center the title with version left and freshness anchored right."""
    version = f"v{__version__}"
    version_width = display_width(version)
    freshness = truncate_width(freshness, max(0, min(display_width(freshness), width // 2)))
    freshness_width = display_width(freshness)
    title = truncate_width(title, max(0, width - version_width - freshness_width - 2))
    title_width = display_width(title)
    start = max(version_width + 1, (width - title_width) // 2)
    if freshness_width:
        start = min(start, max(version_width + 1, width - freshness_width - title_width - 1))
    version = dimmed(version, color=color)
    line = version + " " * max(1, start - version_width) + title
    gap = max(int(bool(freshness)), width - display_width(line) - freshness_width)
    return pad_width(clip_width(line + " " * gap + freshness, width), width)


def _header_lines(
    header: DashboardHeader,
    style: str,
    translator: Translator,
    terminal: Terminal,
    last_successful_update: datetime | None = None,
) -> list[str]:
    if style == "hidden":
        return []
    context = RenderContext(
        terminal.width,
        1,
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=header.options.chart.presentation.theme,
    )
    summary = _header_summary(header, header.summary_period) if header.token_enabled else None
    details: list[str] = []
    if header.summary_period != "none":
        if header.token_enabled:
            details.append(
                translator.text("status.loading")
                if summary is None
                else render_summary(summary, context)
            )
        for dataset_id in sorted(header.custom_summaries):
            custom = header.custom_summaries[dataset_id]
            if custom.response is not None:
                rendered = render_custom_metrics(
                    (custom.response.summary.metric,),
                    context,
                    period="range" if custom.summary_mode == "total" else custom.accepted_period,
                    as_of_date=custom.accepted_as_of_date,
                )
                if rendered:
                    details.append(rendered)
            elif custom.error is None:
                details.append(translator.text("status.loading"))
    detail_lines = tuple(line for detail in details for line in detail.splitlines() if line)
    scheme = get_color_scheme(header.options.chart.presentation.theme)
    title = styled_text(
        translator.text("label.dashboard"),
        scheme.highlight,
        RenderContext(
            terminal.width,
            1,
            translator,
            color=terminal.color,
            ascii=terminal.ascii,
            color_scheme=header.options.chart.presentation.theme,
        ),
        bold=True,
    )
    freshness = (
        translator.text("status.updated", time=last_successful_update.strftime("%H:%M:%S"))
        if last_successful_update is not None
        else ""
    )
    if style == "compact":
        return [
            _dashboard_title_line(title, freshness, terminal.width, color=terminal.color),
            *(center_text(line, terminal.width) for line in detail_lines),
        ]
    title_line = _dashboard_title_line(title, freshness, terminal.width, color=terminal.color)
    if style == "banner":
        return [title_line, *(center_text(line, terminal.width) for line in detail_lines)]
    rule = "=" if terminal.ascii else "═"
    styled_rule = styled_text(
        rule * terminal.width,
        scheme.other,
        RenderContext(
            terminal.width,
            1,
            translator,
            color=terminal.color,
            ascii=terminal.ascii,
            color_scheme=header.options.chart.presentation.theme,
        ),
    )
    panel_details = detail_lines or ("",)
    return [
        styled_rule,
        title_line,
        *(center_text(line, terminal.width) for line in panel_details),
        styled_rule,
    ]


def _grid_shape(grid: str, count: int) -> tuple[int, int]:
    """Return logical bands for compatibility with rectangular-grid callers."""
    layout = resolve_pane_layout(
        layout=grid,
        pane_count=count,
        width=max(8, count * 8),
        height=max(6, count * 6),
        divider_style="none",
    )
    return layout.topology.rows, layout.topology.columns


def _grid_for_pane_count(grid: str, pane_count: int) -> str:
    return layout_for_pane_count(grid, pane_count)


def _practical_grid(pane_count: int) -> str:
    """Return the smallest two-column grid suitable for numeric layout editing."""
    if pane_count == 1:
        return "1x1"
    columns = 2
    rows = (pane_count + columns - 1) // columns
    return f"{rows}x{columns}"


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


def parse_grid(value: str, pane_count: int) -> str | None:
    """Normalize a runtime numeric grid only when it can display every pane."""
    return parse_numeric_grid(value, pane_count)


@dataclass(frozen=True, slots=True)
class PaneLayout:
    """The exact cell geometry shared by rendering and pointer hit testing."""

    widths: tuple[int, ...]
    heights: tuple[int, ...]
    gutter: int

    @property
    def width(self) -> int:
        return sum(self.widths) + self.gutter * (len(self.widths) - 1)

    @property
    def height(self) -> int:
        return sum(self.heights) + self.gutter * (len(self.heights) - 1)


def _dashboard_structure(style: str) -> tuple[str, str]:
    return {
        "minimal": ("none", "none"),
        "split": ("line", "none"),
        "framed": ("none", "subtle"),
        "accent": ("none", "accent"),
    }[style]


def resolve_panel_layout(
    *, width: int, height: int, rows: int, columns: int, divider_style: str
) -> PaneLayout:
    """Allocate every grid row and column, including uneven remainders."""
    gutter = 0 if divider_style == "none" else 1
    available_width = max(columns * 4, width - gutter * (columns - 1))
    available_height = max(rows * 3, height - gutter * (rows - 1))
    width_base, width_remainder = divmod(available_width, columns)
    height_base, height_remainder = divmod(available_height, rows)
    return PaneLayout(
        tuple(width_base + int(index < width_remainder) for index in range(columns)),
        tuple(height_base + int(index < height_remainder) for index in range(rows)),
        gutter,
    )


def pane_rects(
    *,
    pane_count: int,
    width: int,
    height: int,
    rows: int,
    columns: int,
    divider_style: str = "line",
    top: int = 2,
    left: int = 1,
) -> tuple[PaneRect, ...]:
    layout = resolve_panel_layout(
        width=width,
        height=height,
        rows=rows,
        columns=columns,
        divider_style=divider_style,
    )
    rects: list[PaneRect] = []
    for row, cell_height in enumerate(layout.heights):
        cell_left = left
        for column, cell_width in enumerate(layout.widths):
            index = row * columns + column
            if index < pane_count:
                rects.append(PaneRect(index, cell_left, top, cell_width, cell_height))
            cell_left += cell_width + layout.gutter
        top += cell_height + layout.gutter
    return tuple(rects)


def pane_at(rects: tuple[PaneRect, ...], x: int, y: int) -> int | None:
    for rect in rects:
        if rect.left <= x < rect.left + rect.width and rect.top <= y < rect.top + rect.height:
            return rect.index
    return None


def _fit_line(line: str, width: int) -> str:
    return pad_width(clip_width(line, width), width)


def _frame(
    lines: list[str],
    width: int,
    height: int,
    *,
    selected: bool,
    ascii: bool,
    frame_style: str,
    shell_context: RenderContext | None = None,
) -> list[str]:
    """Frame a pane only when configured or explicitly selected for adjustment."""
    width, height = max(4, width), max(3, height)
    if frame_style == "none" and not selected:
        body = [_fit_line(line, width) for line in lines[:height]]
        body.extend(" " * width for _ in range(height - len(body)))
        return body
    effective_style = "subtle" if frame_style == "none" else frame_style
    if ascii or effective_style == "mono":
        glyphs = ("+", "+", "-", "|", "+", "+")
    elif effective_style == "accent":
        glyphs = ("╔", "╗", "═", "║", "╚", "╝")
    else:
        glyphs = ("┌", "┐", "─", "│", "└", "┘")
    left, right, horizontal, vertical, bottom_left, bottom_right = glyphs
    if selected and effective_style == "auto":
        left, right, horizontal, vertical, bottom_left, bottom_right = "╔", "╗", "═", "║", "╚", "╝"
    if shell_context is not None:
        color = (
            get_color_scheme(shell_context.color_scheme).highlight
            if selected
            else get_color_scheme(shell_context.color_scheme).other
        )
        left, right, horizontal, vertical, bottom_left, bottom_right = (
            styled_text(glyph, color, shell_context, bold=selected)
            for glyph in (left, right, horizontal, vertical, bottom_left, bottom_right)
        )
    body = [_fit_line(line, width - 2) for line in lines[: height - 2]]
    body.extend(" " * (width - 2) for _ in range(height - 2 - len(body)))
    return [
        left + horizontal * (width - 2) + right,
        *(vertical + item + vertical for item in body),
        bottom_left + horizontal * (width - 2) + bottom_right,
    ]


def compose_panes(
    charts: list[str],
    width: int,
    height: int,
    rows: int,
    columns: int,
    *,
    focused: int = -1,
    ascii: bool = False,
    divider_style: str = "line",
    frame_style: str = "auto",
    shell_context: RenderContext | None = None,
) -> str:
    """Compose charts with either framed cells or explicit row/column separators."""
    layout = resolve_panel_layout(
        width=width,
        height=height,
        rows=rows,
        columns=columns,
        divider_style=divider_style,
    )

    def cell(index: int, cell_width: int, cell_height: int) -> list[str]:
        chart = charts[index].splitlines() if index < len(charts) else []
        return _frame(
            chart,
            cell_width,
            cell_height,
            selected=index == focused,
            ascii=ascii,
            frame_style=frame_style,
            shell_context=shell_context,
        )

    separator = (
        ":" if ascii and divider_style == "dashed" else "┊" if divider_style == "dashed" else "│"
    )
    horizontal = (
        "." if ascii and divider_style == "dashed" else "┄" if divider_style == "dashed" else "─"
    )
    if shell_context is not None:
        border = get_color_scheme(shell_context.color_scheme).other
        separator = styled_text(separator, border, shell_context)
        horizontal = styled_text(horizontal, border, shell_context)
    output: list[str] = []
    for row, cell_height in enumerate(layout.heights):
        row_cells = [
            cell(row * columns + column, cell_width, cell_height)
            for column, cell_width in enumerate(layout.widths)
        ]
        joiner = separator if layout.gutter else ""
        output.extend(joiner.join(parts) for parts in zip(*row_cells, strict=True))
        if layout.gutter and row + 1 < rows:
            output.append(horizontal * layout.width)
    return "\n".join(output)


def _compose_dashboard_overlays(
    grid: str,
    layout: ResolvedPaneLayout,
    overlays: tuple[DashboardOverlayPlacement, ...],
    *,
    focused: int,
) -> str:
    """Paint pane-relative overlays above the complete Dashboard grid."""
    rows = grid.splitlines()
    ordered = sorted(
        overlays,
        key=lambda item: (item.source_index == focused, item.source_index),
    )
    for item in ordered:
        for placement in clip_overlay_placements(
            (item.placement,), width=layout.width, height=layout.height
        ):
            rows[placement.row] = compose_overlay_row(
                rows[placement.row], placement, width=layout.width
            )
    return "\n".join(rows)


def _compose_resolved_panes(
    charts: list[str],
    layout: ResolvedPaneLayout,
    *,
    focused: int = -1,
    ascii: bool = False,
    divider_style: str = "line",
    frame_style: str = "auto",
    shell_context: RenderContext | None = None,
) -> str:
    """Compose exactly the rectangles produced by the shared layout resolver."""
    rendered = {
        rect.index: _frame(
            charts[rect.index].splitlines() if rect.index < len(charts) else [],
            rect.width,
            rect.height,
            selected=rect.index == focused,
            ascii=ascii,
            frame_style=frame_style,
            shell_context=shell_context,
        )
        for rect in layout.panes
    }
    vertical = (
        ":" if ascii and divider_style == "dashed" else "┊" if divider_style == "dashed" else "│"
    )
    horizontal = (
        "." if ascii and divider_style == "dashed" else "┄" if divider_style == "dashed" else "─"
    )
    intersection = "+" if ascii else "┼"
    if shell_context is not None:
        border = get_color_scheme(shell_context.color_scheme).other
        vertical, horizontal, intersection = (
            styled_text(glyph, border, shell_context)
            for glyph in (vertical, horizontal, intersection)
        )

    column_gutters: set[int] = set()
    cursor = 0
    for size in layout.column_sizes[:-1]:
        cursor += size
        column_gutters.update(range(cursor, cursor + layout.gutter))
        cursor += layout.gutter
    row_gutters: set[int] = set()
    cursor = 0
    for size in layout.row_sizes[:-1]:
        cursor += size
        row_gutters.update(range(cursor, cursor + layout.gutter))
        cursor += layout.gutter

    output: list[str] = []
    for y in range(layout.height):
        segments: list[str] = []
        x = 0
        while x < layout.width:
            rect = next(
                (
                    item
                    for item in layout.panes
                    if item.left <= x < item.left + item.width
                    and item.top <= y < item.top + item.height
                ),
                None,
            )
            if rect is not None:
                segments.append(rendered[rect.index][y - rect.top])
                x = rect.left + rect.width
                continue
            if x in column_gutters and y in row_gutters:
                segments.append(intersection)
            elif y in row_gutters:
                segments.append(horizontal)
            elif x in column_gutters:
                segments.append(vertical)
            else:
                segments.append(" ")
            x += 1
        output.append("".join(segments))
    return "\n".join(output)


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
        if not isinstance(owner_id, str):
            raise TypeError("dashboard chart pane owner id is required")
        if isinstance(pane_config, CustomChartPaneConfig):
            started_at = time.monotonic()
            component = (
                CustomMonitorComponent(pane_config.chart)
                if pane_config.chart.kind == "monitor"
                else CustomHistoricalComponent(pane_config.chart)
            )
            return TuiCustomPane(
                component,
                FixedIntervalScheduler(
                    options.host.sampling_interval
                    if pane_config.chart.kind == "monitor"
                    else options.host.refresh_interval,
                    now=started_at,
                ),
                LifecycleOperation(owner_id),
                options.process,
                None
                if pane_config.chart.kind == "monitor" or pane_config.chart.metric_id is not None
                else CustomDashboardSummary(
                    pane_config.chart.source,
                    FixedIntervalScheduler(options.host.refresh_interval, now=started_at),
                    LifecycleOperation(f"{owner_id}:summary"),
                    filters=pane_config.chart.filters,
                ),
            )
        from ccusage_viz.configuration import standalone_from_chart_pane

        return _new_pane(
            standalone_from_chart_pane(options, pane_config), owner_id, runtime=runtime
        )
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
) -> CustomOutcome:
    try:
        return CustomOutcome(generation, result=handle.result(), purpose=purpose)
    except BaseException as exc:
        return CustomOutcome(generation, error=exc, purpose=purpose)


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


@dataclass(frozen=True, slots=True)
class PaneRender:
    chart: str
    notices: tuple[str, ...] = ()
    overlay_placements: tuple[OverlayPlacement, ...] = ()
    error_body: bool = False


@dataclass(frozen=True, slots=True)
class DashboardOverlayPlacement:
    source_index: int
    placement: OverlayPlacement


def _pane_copy_payload(
    pane: TuiChartPane | TuiCustomPane,
    translator: Translator,
    terminal: Terminal,
    *,
    dashboard: DashboardLaunch | None = None,
) -> str:
    """Return the focused non-chart pane view's complete clipboard payload."""
    if isinstance(pane, TuiCustomPane):
        if dashboard is None:
            raise ValueError("custom pane copy requires dashboard options")
        active = _custom_pane_options(dashboard, pane)
        view = body_view_copy_kind(pane.body_view)
        if view is None:
            raise ValueError("chart panes do not have a copy payload")
        if view == "command":
            return format_command(active)
        if view == "full-command":
            return format_full_command(active)
        if pane.component.model is None:
            return translator.text("status.loading")
        return render_custom_data(
            pane.component.model,
            language=translator.language,
            translator=translator,
            view=view,
        )
    active = _pane_options(pane)
    view = body_view_copy_kind(pane.body_view)
    if view is None:
        raise ValueError("chart panes do not have a copy payload")
    if view == "command":
        return format_command(active)
    if view == "full-command":
        return format_full_command(active)
    component = pane.component
    if isinstance(component, MonitorComponent):
        if not isinstance(active.chart, MonitorConfig):
            raise TypeError("monitor pane component has historical configuration")
        return render_current_monitor_data(
            component,
            active.chart,
            translator=translator,
            terminal=terminal,
            now=time.monotonic(),
            wall=datetime.now().astimezone(),
            view=view,
        )
    return render_snapshot_data(
        active,
        component.snapshot,
        translator,
        terminal,
        view=view,
    )


def _custom_render_context(
    config: CustomChartConfig,
    translator: Translator,
    terminal: Terminal,
    *,
    accepted_at: datetime | None,
    interval: float | None,
    pending: bool,
    surface: HistoricalPresentationSurface,
    controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
    reserved_summary_rows: int = 0,
) -> RenderContext:
    """Adapt Custom semantics to the selected kind-specific product surface."""
    is_ungrouped_timeline = config.kind == "timeline" and config.group_by is None
    presentation = SurfacePresentation(
        config.kind,
        config.presentation.theme,
        config.presentation.style,
        config.presentation.legend,
        config.presentation.density,
        config.weekdays,
        config.date_range.period if config.date_range.relative_until else None,
        translator.text("label.total") if is_ungrouped_timeline else None,
        None,
        accepted_at,
        None,
        interval,
        refreshing=pending,
        querying=False,
        pending=pending,
    )
    return surface.context(
        terminal,
        translator,
        presentation,
        controls=controls,
        reserved_summary_rows=reserved_summary_rows,
    )


def _custom_failure_log_detail(error: BaseException, translator: Translator) -> str:
    if isinstance(error, QueryError):
        failure = error.values.get("custom_failure")
        if isinstance(failure, CustomProtocolFailure):
            message = failure.message.zh_cn if translator.language == "zh" else failure.message.en
            detail = f"{failure.code}: {message}"
            if failure.unsupported is not None:
                field = failure.unsupported.get("field")
                value = failure.unsupported.get("value")
                if isinstance(field, str) and isinstance(value, str):
                    detail = f"{detail} ({field}={value})"
            return detail
    return translator.text("status.custom_log_error")


def _render_custom_failure(
    component: CustomHistoricalComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    accepted_at: datetime | None,
    interval: float | None,
    surface: HistoricalPresentationSurface,
) -> PaneRender:
    context = _custom_render_context(
        component.candidate,
        translator,
        terminal,
        accepted_at=accepted_at,
        interval=interval,
        pending=False,
        surface=surface,
    )
    return PaneRender(
        "\n\n".join(
            (
                render_custom_failure(component.candidate, context, component.presentation),
                format_error(component.error, translator, color=False),
            )
        ),
        error_body=True,
    )


def _render_custom_monitor(
    component: CustomMonitorComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    interval: float,
) -> PaneRender:
    config = component.accepted_config or component.candidate
    response = component.accepted_response
    title = (
        config.metric_titles[1] if translator.language == "zh" else config.metric_titles[0]
    ) if config.metric_titles is not None else config.metric_id or config.source.dataset_id
    heading = center_text(f"{title} · source window", terminal.width)
    if response is None:
        body = (
            format_error(component.error, translator, color=False)
            if component.error
            else translator.text("status.loading")
        )
        return PaneRender(f"{heading}\n{body}", error_body=component.error is not None)
    observation = response.observation
    rows = [heading, f"Total  {format_tokens(round(float(observation.total)))}"]
    for group in sorted(observation.groups, key=lambda item: (-item.value, item.id)):
        label = group.label.zh_cn if translator.language == "zh" else group.label.en
        rows.append(f"{label}  {format_tokens(round(float(group.value)))}")
    return PaneRender("\n".join(rows))


def _render_custom_projection(
    projection: CustomChartProjection,
    config: CustomChartConfig,
    translator: Translator,
    terminal: Terminal,
    *,
    accepted_at: datetime | None,
    interval: float | None,
    pending: bool,
    surface: HistoricalPresentationSurface,
    summary: CustomDashboardSummary | None = None,
    controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
) -> PaneRender:
    context = _custom_render_context(
        config,
        translator,
        terminal,
        accepted_at=accepted_at,
        interval=interval,
        pending=pending,
        surface=surface,
        controls=controls,
    )
    summary_render = ""
    if summary is not None and summary.response is not None:
        summary_render = render_custom_metrics(
            (summary.response.summary.metric,),
            context,
            period=summary.accepted_period,
            as_of_date=summary.accepted_as_of_date,
        )
        min_chart_rows = 9 + int(
            config.kind in {"timeline", "stack"} and config.presentation.legend == "below-title"
        )
        summary_rows = max(0, context.height - min_chart_rows)
        if len(summary_render.splitlines()) > summary_rows:
            compact_context = replace(context, density="compact")
            summary_render = render_custom_metrics(
                (summary.response.summary.metric,),
                compact_context,
                period=summary.accepted_period,
                as_of_date=summary.accepted_as_of_date,
            )
        summary_render = "\n".join(summary_render.splitlines()[:summary_rows])
        if summary_render:
            context = _custom_render_context(
                config,
                translator,
                terminal,
                accepted_at=accepted_at,
                interval=interval,
                pending=pending,
                surface=surface,
                controls=controls,
                reserved_summary_rows=len(summary_render.splitlines()),
            )
    rendered = render_custom_projection(
        replace(projection, config=config, presentation=projection.presentation), context
    )
    if summary_render:
        rendered = "\n".join((summary_render, rendered))
    audit = render_audit(context)
    if audit:
        rendered = "\n".join((rendered, audit))
    return PaneRender(rendered)


def _pane_render(
    pane: TuiPane,
    translator: Translator,
    terminal: Terminal,
    *,
    dashboard: DashboardLaunch | None = None,
    defer_animation_overlay: bool = False,
) -> PaneRender:
    if isinstance(pane, TuiEmptyPane):
        return PaneRender(
            "\n".join(
                (
                    translator.text("status.empty_pane"),
                    translator.text("status.empty_pane_hint"),
                )
            )
        )
    if isinstance(pane, TuiCustomPane):
        component = pane.component
        if (
            pane.body_view in {"command", "full-command", "data-table", "data-json"}
            and dashboard is None
        ):
            raise ValueError("custom pane text views require dashboard options")
        options = _custom_pane_options(dashboard, pane) if dashboard is not None else None
        if isinstance(component, CustomMonitorComponent):
            if pane.body_view == "command":
                assert options is not None
                return PaneRender(wrap_command(format_command(options), terminal.width))
            if pane.body_view == "full-command":
                assert options is not None
                return PaneRender(
                    format_full_command_display(format_full_command(options), terminal.width)
                )
            return _render_custom_monitor(component, translator, terminal, interval=pane.interval)
        if component.error is not None and component.model is None:
            return _render_custom_failure(
                component,
                translator,
                terminal,
                accepted_at=component.accepted_at,
                interval=pane.interval,
                surface=dashboard_pane_surface(component.candidate.kind),
            )
        if pane.body_view == "command":
            assert options is not None
            return PaneRender(wrap_command(format_command(options), terminal.width))
        if pane.body_view == "full-command":
            assert options is not None
            return PaneRender(
                format_full_command_display(format_full_command(options), terminal.width)
            )
        if pane.body_view in {"data-table", "data-json"}:
            if component.model is None:
                return PaneRender(translator.text("status.loading"))
            return PaneRender(
                render_custom_data(
                    component.model,
                    language=translator.language,
                    translator=translator,
                    view=pane.body_view,
                )
            )
        if component.model is None:
            return PaneRender(translator.text("status.loading"))
        if component.is_pending:
            context = _custom_render_context(
                component.candidate,
                translator,
                terminal,
                accepted_at=component.accepted_at,
                interval=pane.interval,
                pending=True,
                surface=dashboard_pane_surface(component.candidate.kind),
            )
            rendered = render_custom_pending(component.candidate, context, component.presentation)
            audit = render_audit(context)
            return PaneRender("\n".join(line for line in (rendered, audit) if line))
        rendered = _render_custom_projection(
            component.model,
            component.accepted_config or component.candidate,
            translator,
            terminal,
            accepted_at=component.accepted_at,
            interval=pane.interval,
            pending=component.is_pending or pane.lifecycle.submission is not None,
            surface=dashboard_pane_surface((component.accepted_config or component.candidate).kind),
            summary=pane.summary,
        )
        if component.error is not None:
            return PaneRender(
                rendered.chart, (format_error(component.error, translator, color=False),)
            )
        return rendered
    if isinstance(pane, TuiAnimationPane):
        if pane.body_view != "chart":
            return PaneRender("")
        now = time.monotonic()
        pane.overlay.poll(now=now, translator=translator)
        result = pane.renderer.render(
            pane.session,
            width=terminal.width,
            height=terminal.height,
            color=terminal.color,
            ascii=terminal.ascii,
            now=now,
            translator=translator,
        )
        rows = list(result.rows)
        if defer_animation_overlay:
            return PaneRender(
                "\n".join(rows),
                overlay_placements=pane.overlay.unbounded_placements(
                    width=terminal.width, height=len(rows)
                ),
            )
        for placement in pane.overlay.placements(width=terminal.width, height=len(rows)):
            if 0 <= placement.row < len(rows):
                rows[placement.row] = compose_overlay_row(
                    rows[placement.row], placement, width=terminal.width
                )
        return PaneRender("\n".join(rows))
    active = _pane_display_options(pane)
    component = pane.component
    if pane.body_view == "command":
        return PaneRender(wrap_command(format_command(active), terminal.width))
    if pane.body_view == "full-command":
        return PaneRender(format_full_command_display(format_full_command(active), terminal.width))
    if pane.body_view in {"data-table", "data-json"}:
        accepted = _pane_options(pane)
        if isinstance(component, MonitorComponent):
            if not isinstance(accepted.chart, MonitorConfig):
                raise TypeError("monitor pane component has historical configuration")
            return PaneRender(
                render_current_monitor_data(
                    component,
                    accepted.chart,
                    translator=translator,
                    terminal=terminal,
                    now=time.monotonic(),
                    wall=datetime.now().astimezone(),
                    view=pane.body_view,
                )
            )
        return PaneRender(
            render_snapshot_data(
                accepted,
                component.snapshot,
                translator,
                terminal,
                view=pane.body_view,
            )
        )
    error = component.error
    if error is not None:
        message = (
            format_error(
                error,
                translator,
                color=terminal.color,
                color_scheme=active.chart.presentation.theme,
            )
            if isinstance(error, VizError)
            else str(error)
        )
        recovery = transient_query_recovery_lines(
            error, translator, initial=component.accepted_options is None
        )
        if (
            recovery is not None
            and isinstance(component, HistoricalChartComponent)
            and component.snapshot is not None
        ):
            rendered = render_historical_component(
                component,
                translator,
                terminal,
                controls=SurfaceControls(),
                surface=dashboard_pane_surface(cast("HistoricalChartConfig", active.chart).kind),
                ranking_deltas=pane.deltas if active.chart.kind == "ranking" else None,
                ranking_rank_deltas=pane.rank_deltas if active.chart.kind == "ranking" else None,
                normalize_titles=True,
                interval=pane.scheduler.interval,
                refreshing=pane.lifecycle.submission is not None,
            )
            pane.last_render = PaneRender(rendered.chart, (*rendered.notices, *recovery))
            return pane.last_render
        if recovery is not None and isinstance(component, HistoricalChartComponent):
            return PaneRender("\n".join(recovery))
        if recovery is not None and pane.last_render is not None:
            return PaneRender(pane.last_render.chart, (*pane.last_render.notices, *recovery))
        return PaneRender(message, recovery or ())
    try:
        if isinstance(component, MonitorComponent):
            if component.accepted_options is None and pane.lifecycle.submission is not None:
                return PaneRender(translator.text("status.loading"))
            display = component.display() if hasattr(component, "display") else component
            display_query_pending = getattr(display, "display_query_pending", False)
            title_chart = (
                active.chart
                if not display_query_pending or component.accepted_options is None
                else component.accepted_options.chart
            )
            if not isinstance(title_chart, MonitorConfig):
                raise TypeError("monitor pane component has historical configuration")
            audit = RenderAudit(
                component.accepted_at,
                component.last_elapsed,
                pane.scheduler.interval,
                "sample",
                refreshing=pane.lifecycle.submission is not None,
                querying=display_query_pending,
            )
            context = RenderContext(
                terminal.width,
                max(
                    1,
                    terminal.height
                    - int(audit_row_visible(active.chart.presentation.density, audit)),
                ),
                translator,
                color=terminal.color,
                ascii=terminal.ascii,
                color_scheme=active.chart.presentation.theme,
                style=active.chart.presentation.style,
                legend_position=active.chart.presentation.legend,
                title_content=translator.text(f"label.{title_chart.by or 'total'}"),
                hide_upper_right_axes=True,
                deltas=component.deltas,
                rank_deltas=component.rank_deltas,
                filter_summary=active_filter_summary(
                    active.chart.filters
                    if isinstance(active.chart.filters, Filters)
                    else Filters(),
                    translator,
                    width=terminal.width,
                ),
                density=active.chart.presentation.density,
                pending=display_query_pending,
                audit=audit,
            )
            candidate = PaneRender(
                display.render(
                    context,
                    now=time.monotonic(),
                    count=max(8, min(32, terminal.width // 4)),
                    wall=datetime.now().astimezone(),
                )
            )
        elif component.snapshot is None:
            label = translator.text(f"label.{active.chart.kind}")
            candidate = PaneRender(f"{label} · {translator.text('status.loading')}")
        else:
            rendered = render_historical_component(
                component,
                translator,
                terminal,
                controls=SurfaceControls(),
                surface=dashboard_pane_surface(cast("HistoricalChartConfig", active.chart).kind),
                ranking_deltas=pane.deltas if active.chart.kind == "ranking" else None,
                ranking_rank_deltas=pane.rank_deltas if active.chart.kind == "ranking" else None,
                normalize_titles=True,
                interval=pane.scheduler.interval,
                refreshing=pane.lifecycle.submission is not None,
            )
            candidate = PaneRender(rendered.chart, rendered.notices)
    except UsageError as exc:
        pane.render_warning = exc
        warning = format_error(
            exc, translator, color=terminal.color, color_scheme=active.chart.presentation.theme
        )
        if pane.last_render is None:
            return PaneRender(warning)
        return PaneRender(pane.last_render.chart, (*pane.last_render.notices, warning))
    pane.last_render = candidate
    pane.render_warning = None
    return candidate


def _update_monitor_attachment_activity(
    component: MonitorComponent,
    attachment: AnimationSessionState,
    *,
    now: float,
    wall: datetime,
    translator: Translator,
) -> None:
    """Apply an accepted monitor interval and retain its last active wall time."""

    delta = component.accepted_total_token_delta
    active = (delta or 0) > 0
    attachment.set_playback_requested(active, now)
    if active:
        attachment.activity_label = last_activity_label(translator, wall)


def _append_monitor_attachment(
    pane: TuiChartPane,
    body: str,
    *,
    terminal: Terminal,
    reserved_rows: int,
    now: float,
    translator: Translator,
) -> str:
    """Append a pane-local rain attachment below viable ranking/list monitors."""
    if not isinstance(pane.component, MonitorComponent):
        return body
    attachment = pane.attachment
    renderer = pane.attachment_renderer
    config = _pane_display_options(pane)
    if (
        not pane.attachment_enabled
        or attachment is None
        or renderer is None
        or not isinstance(config.chart, MonitorConfig)
        or config.chart.presentation.style not in {"ranking", "list"}
        or (
            getattr(pane.component, "accepted_total_token_delta", None) is None
            and attachment.activity_label is None
        )
    ):
        if attachment is not None:
            attachment.set_visible(False, now)
        return body
    residual_height = terminal.height - len(body.rstrip("\r\n").splitlines()) - reserved_rows
    if residual_height < 1:
        attachment.set_visible(False, now)
        return body
    attachment.set_visible(True, now)
    result = renderer.render(
        attachment,
        width=terminal.width,
        height=residual_height,
        color=terminal.color,
        ascii=terminal.ascii,
        now=now,
        translator=translator,
    )
    if not result.viable:
        attachment.set_visible(False, now)
        return body
    return "\n".join((*((body,) if body else ()), *result.rows))


def _local_pane_content(
    chart: str,
    notices: tuple[str, ...],
    *,
    height: int,
    width: int = 80,
    offset: int = 0,
    scrollable: bool = False,
    return_metadata: bool = False,
) -> str | tuple[str, int, int, int]:
    """Keep notices fixed below an optionally scrollable pane body."""
    notice_rows = min(len(notices), max(0, height - 3))
    chart_height = max(0, height - notice_rows)
    rows = wrap_text_rows(chart, width=width) if scrollable else chart
    viewport = render_text_viewport(rows, offset=offset, visible_rows=chart_height)
    chart_lines = (viewport.body if scrollable else chart).splitlines()[:chart_height]
    chart_lines.extend("" for _ in range(chart_height - len(chart_lines)))
    content = "\n".join((*chart_lines, *notices[:notice_rows]))
    if not return_metadata:
        return content
    return (
        content,
        viewport.offset if scrollable else 0,
        viewport.line_count,
        viewport.visible_rows,
    )


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


def _cycle_custom_grouping(
    config: CustomChartConfig, groupings: tuple[str, ...], *, step: int = 1
) -> CustomChartConfig:
    """Advance custom grouping and preserve a style valid for the result."""

    values = (None, *groupings)
    current = config.group_by if config.group_by in values else values[0]
    group_by = values[(values.index(current) + step) % len(values)]
    presentation = config.presentation
    styles = compatible_styles(config.kind, group_by)
    if presentation.style not in styles:
        presentation = replace(presentation, style=styles[0])
    return replace(
        config,
        group_by=group_by,
        top=(config.top or 3) if group_by else None,
        presentation=presentation,
    )


def _new_pane_options(command: str, base: DashboardLaunch) -> StandaloneLaunch:
    from ccusage_viz.configuration import default_pane, standalone_from_chart_pane

    pane = default_pane(command, dashboard=base)
    if command == "monitor":
        pane = replace(pane, chart=replace(pane.chart, by="model", top=3))
    return standalone_from_chart_pane(base, pane)


_PANE_QUICK_ACTIONS = {
    "timeline": (("p/P", "period"), ("g/G", "granularity"), ("b/B", "group"), ("+/-", "top")),
    "calendar": (("p/P", "period"),),
    "stack": (("p/P", "period"), ("g/G", "granularity"), ("b/B", "group"), ("+/-", "top")),
    "ranking": (("p/P", "period"), ("b/B", "group"), ("+/-", "top")),
    "monitor": (("w", "window"), ("b/B", "group"), ("+/-", "top")),
}
_PANE_ADVANCED_ACTIONS = {
    "timeline": (("o", "other"), ("l", "legend"), ("k", "weekdays")),
    "calendar": (),
    "stack": (("o", "other"), ("c", "cache"), ("l", "legend"), ("k", "weekdays")),
    "ranking": (("o", "other"),),
    "monitor": (("l", "legend"),),
}
_COMMON_PANE_QUICK_ACTIONS = (
    ("d", "density"),
    ("t/T", "theme"),
    ("s/S", "style"),
)
_COMMON_PANE_ADVANCED_ACTIONS = (("f", "filters"),)
_PANE_CONTENT_ACTIONS = (
    ("v", "view"),
    ("r", "replace"),
    ("N", "insert_before"),
    ("n", "insert_after"),
    ("x", "delete"),
)


def _custom_capability_for_component(
    component: CustomHistoricalComponent,
) -> CustomChartCapability | None:
    """Return capabilities only when they describe the active custom source."""

    response = component.accepted_response
    if (
        response is None
        or component.accepted_config is None
        or component.accepted_config.source != component.candidate.source
    ):
        return None
    return response.capabilities.charts.get(component.candidate.kind)


def _custom_capability(pane: TuiCustomPane) -> CustomChartCapability | None:
    """Return the active Dashboard custom pane capability."""

    return _custom_capability_for_component(pane.component)


def _custom_supported_filters(
    capabilities: CustomCapabilities, capability: CustomChartCapability
) -> tuple[CustomFilter, ...]:
    allowed = set(capability.filters)
    return tuple(item for item in capabilities.filters if item.id in allowed)


def _custom_pane_adjustment_bindings(pane: TuiCustomPane, page: str) -> tuple[tuple[str, str], ...]:
    """Return the active custom actions for one Dashboard adjustment page."""

    capability = _custom_capability(pane)
    chart = pane.component.candidate
    if page == "quick":
        actions: list[tuple[str, str]] = [("p/P", "period")]
        if capability is not None:
            if len(capability.granularities) > 1:
                actions.append(("g/G", "granularity"))
            if chart.kind != "calendar" and capability.group_by:
                actions.append(("b/B", "group"))
            if capability.filters:
                actions.append(("f", "filters"))
        if chart.group_by is not None:
            actions.append(("+/-", "top"))
        return (*actions, *_COMMON_PANE_QUICK_ACTIONS)

    actions = []
    if chart.group_by is not None:
        actions.append(("o", "other"))
    if chart.kind in {"timeline", "stack"}:
        actions.extend((("l", "legend"), ("k", "weekdays")))
    actions.append(("L", "custom_logs"))
    return tuple(actions)


def _custom_pane_adjustment_actions(
    pane: TuiCustomPane, page: str, translator: Translator
) -> tuple[AdjustmentAction, ...]:
    return _localized_actions(_custom_pane_adjustment_bindings(pane, page), translator)


def _custom_pane_adjustment_keys(pane: TuiCustomPane, page: str) -> frozenset[str]:
    return frozenset(
        character
        for binding, _label in _custom_pane_adjustment_bindings(pane, page)
        for character in binding
        if character not in {"/", " "}
    )


def _custom_pane_adjustment_state(pane: TuiCustomPane, page: str, translator: Translator) -> str:
    chart = pane.component.candidate
    if page == "quick":
        settings = (
            f"{chart.kind} · {chart.presentation.density} · {chart.presentation.theme} · "
            f"{chart.presentation.style} · chart"
        )
    else:
        settings = []
        if chart.group_by is not None:
            settings.append(f"Other {chart.other}")
        if chart.kind in {"timeline", "stack"}:
            settings.extend((f"Legend {chart.presentation.legend}", f"Weekdays {chart.weekdays}"))
        settings.extend((chart.source.dataset_id, " ".join(chart.source.command_argv)))
        settings = " · ".join(settings)
    return translator.text(
        "status.tui_current_state",
        runtime=translator.text("status.tui_running"),
        settings=settings,
    )


def _custom_adjustment_footer(
    pane: TuiCustomPane,
    page: str,
    translator: Translator,
    width: int,
    *,
    color: bool,
) -> tuple[str, ...]:
    shared = adjustment_rows(
        _custom_pane_adjustment_state(pane, page, translator),
        translator.text(f"status.tui_adjust_{page}"),
        _custom_pane_adjustment_actions(pane, page, translator),
        width=width,
        color=False,
        switch_action=translator.text(
            "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
        ),
        finish_action=translator.text("adjustment.finish"),
    )
    return (
        *shared,
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _pane_content_actions("chart"),
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


_ANIMATION_PANE_CONTENT_ACTIONS = (
    ("r", "replace"),
    ("N", "insert_before"),
    ("n", "insert_after"),
    ("x", "delete"),
)
_PANE_POSITION_ACTIONS = (
    ("[", "previous"),
    ("]", "next"),
    ("Tab", "next_pane"),
    ("{ / }", "width"),
    ("J / K", "height"),
)
_GLOBAL_ACTIONS = (
    ("t/T", "theme"),
    ("s/S", "style"),
    ("H", "header"),
    ("p/P", "summary"),
    ("z", "layout"),
    ("Z", "grid"),
)
_LAYOUT_SHORTCUTS = (
    "wide",
    "narrow",
    "all",
    "auto",
    "spotlight-wide",
    "spotlight-wide2",
)
_LAYOUT_SHORTCUT_VALUES = {
    "wide": "2x2",
    "narrow": "3x1",
    "all": "5x2",
    "auto": "auto",
    "spotlight-wide": "spotlight-wide",
    "spotlight-wide2": "spotlight-wide2",
}


def _localized_actions(
    actions: tuple[tuple[str, str], ...], translator: Translator
) -> tuple[AdjustmentAction, ...]:
    return tuple(
        AdjustmentAction(key, translator.text(f"label.adjust_{label}"), priority)
        for priority, (key, label) in enumerate(actions)
    )


def _project_grouping_available(chart: object | None) -> bool:
    return (
        isinstance(chart, (TimelineConfig, StackConfig, RankingConfig, MonitorConfig))
        and chart.by == "project"
    )


def _pane_adjustment_bindings(
    command: str,
    page: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Return the state-aware, locale-independent bindings for a Pane page."""

    actions = (
        (*_PANE_QUICK_ACTIONS[command], *_COMMON_PANE_QUICK_ACTIONS)
        if page == "quick"
        else (*_PANE_ADVANCED_ACTIONS[command], *_COMMON_PANE_ADVANCED_ACTIONS)
    )
    visible = tuple(
        (key, label)
        for key, label in actions
        if not (
            isinstance(chart, MonitorConfig)
            and chart.presentation.style in {"ranking", "list"}
            and key == "w"
        )
        and not (isinstance(chart, StackConfig) and chart.by != "composition" and key == "c")
    )
    if (
        isinstance(chart, MonitorConfig)
        and chart.presentation.style == "cumulative-bars"
        and page == "quick"
    ):
        visible = (("w", "window"), ("g", "granularity"), *visible[1:])
    if attachment_available and page == "advanced":
        visible = (*visible, ("t/T", "animation_theme"), ("s/S", "animation_style"))
    return visible


def _pane_adjustment_actions(
    command: str,
    page: str,
    translator: Translator,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> tuple[AdjustmentAction, ...]:
    return _localized_actions(
        _pane_adjustment_bindings(
            command,
            page,
            chart=chart,
            attachment_available=attachment_available,
        ),
        translator,
    )


def _adjustment_controls(
    command: str, page: str, translator: Translator, *, chart: object | None = None
) -> str:
    return " · ".join(
        action.text for action in _pane_adjustment_actions(command, page, translator, chart=chart)
    )


def _adjustment_page_keys(
    command: str,
    page: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> frozenset[str]:
    """Return every individual key exposed by the current adjustment page."""

    return frozenset(
        character
        for binding, _label in _pane_adjustment_bindings(
            command,
            page,
            chart=chart,
            attachment_available=attachment_available,
        )
        for character in binding
        if character not in {"/", " "}
    )


def _adjustment_target_page(
    command: str,
    current_page: str,
    key: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> str | None:
    """Resolve an unambiguous Dashboard Pane adjustment shortcut target page."""

    other_page = "advanced" if current_page == "quick" else "quick"
    if key in _adjustment_page_keys(
        command,
        current_page,
        chart=chart,
        attachment_available=attachment_available,
    ):
        return current_page
    if key in _adjustment_page_keys(
        command,
        other_page,
        chart=chart,
        attachment_available=attachment_available,
    ):
        return other_page
    return None


def _adjustment_key_supported(
    command: str,
    page: str,
    key: str,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> bool:
    return key in _adjustment_page_keys(
        command,
        page,
        chart=chart,
        attachment_available=attachment_available,
    )


def _query_affecting_adjustment(command: str, key: str) -> bool:
    """Compatibility helper for key-only callers.

    Runtime paths compare complete configurations through
    :func:`historical_replacement_required` instead.
    """
    return (
        key in {"p", "P"}
        or (key in {"b", "B"} and command in {"timeline", "stack", "ranking", "monitor"})
        or (command == "monitor" and key == "w")
    )


def _text_view_footer(
    body_view: BodyView,
    translator: Translator,
    width: int,
    *,
    line_count: int,
    visible_rows: int,
) -> tuple[str, ...]:
    """Render the always-visible, read-only footer for a text body view."""
    scroll = (
        f"↑/↓ {translator.text('status.text_scroll')} · "
        f"Home {translator.text('status.text_top')} · "
        f"e {translator.text('status.text_end')} · "
        if text_viewport_overflows(line_count=line_count, visible_rows=visible_rows)
        else ""
    )
    return (
        clip_width(
            f"{scroll}y {translator.text('label.adjust_copy')} · "
            f"v/V {translator.text('label.adjust_view')}",
            width,
        ),
    )


def _pane_content_actions(body_view: BodyView) -> tuple[tuple[str, str], ...]:
    if body_view_copy_kind(body_view) is None:
        return _PANE_CONTENT_ACTIONS
    return (*_PANE_CONTENT_ACTIONS, ("y", "copy"))


def _pane_help_settings_actions(
    command: str,
    translator: Translator,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
) -> tuple[tuple[str, AdjustmentAction], ...]:
    """Return every current settings binding with its effective adjustment page."""
    return tuple(
        (page, action)
        for page in ("quick", "advanced")
        for action in _pane_adjustment_actions(
            command,
            page,
            translator,
            chart=chart,
            attachment_available=attachment_available,
        )
    )


def _pane_help_action_text(page: str, action: AdjustmentAction, translator: Translator) -> str:
    detail_labels = (
        "period",
        "granularity",
        "group",
        "top",
        "density",
        "theme",
        "style",
        "other",
        "legend",
        "weekdays",
        "cache",
        "filters",
        "window",
        "animation_theme",
        "animation_style",
    )
    detail_labels_by_action = {
        translator.text(f"label.adjust_{label}"): label for label in detail_labels
    }
    detail_label = detail_labels_by_action.get(action.label)
    detail = (
        translator.text(f"status.tui_help_parameter_{detail_label}")
        if detail_label is not None
        else action.label
    )
    return translator.text(f"status.tui_help_parameter_{page}", action=action.text, detail=detail)


_ANIMATION_PANE_QUICK_BINDINGS = (
    ("p/P", "overlay_position"),
    ("t/T", "animation_theme"),
    ("s/S", "animation_style"),
)
_ANIMATION_PANE_ADVANCED_BINDINGS = (
    ("↑/↓/←/→", "overlay_move"),
    ("0", "overlay_reset"),
    ("e", "overlay_edit"),
    ("i", "overlay_interval"),
    ("L", "overlay_history"),
)


def _animation_pane_adjustment_keys(page: str) -> frozenset[str]:
    """Return individual non-global animation Pane adjustment keys."""

    bindings = (
        _ANIMATION_PANE_QUICK_BINDINGS if page == "quick" else _ANIMATION_PANE_ADVANCED_BINDINGS
    )
    key_map = {"↑": "\x1b[A", "↓": "\x1b[B", "→": "\x1b[C", "←": "\x1b[D"}
    return frozenset(
        key_map.get(character, character)
        for binding, _label in bindings
        if binding != "Space"
        for character in binding
        if character not in {"/", " "}
    )


def _animation_adjustment_target_page(current_page: str, key: str) -> str | None:
    """Resolve an unambiguous Dashboard Animation Pane adjustment shortcut."""

    other_page = "advanced" if current_page == "quick" else "quick"
    if key in _animation_pane_adjustment_keys(current_page):
        return current_page
    if key in _animation_pane_adjustment_keys(other_page):
        return other_page
    return None


def _animation_pane_adjustment_actions(
    page: str, translator: Translator
) -> tuple[AdjustmentAction, ...]:
    bindings = (
        _ANIMATION_PANE_QUICK_BINDINGS if page == "quick" else _ANIMATION_PANE_ADVANCED_BINDINGS
    )
    return tuple(
        AdjustmentAction(binding, translator.text(f"adjustment.{label}"), priority)
        for priority, (binding, label) in enumerate(bindings)
    )


def _empty_pane_adjustment_footer(
    translator: Translator,
    width: int,
    *,
    color: bool = False,
) -> tuple[str, ...]:
    """Render Dashboard-only management controls for an unconfigured pane."""

    return (
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _ANIMATION_PANE_CONTENT_ACTIONS,
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


def _animation_adjustment_footer(
    pane: TuiAnimationPane,
    page: str,
    translator: Translator,
    width: int,
    *,
    color: bool = False,
) -> tuple[str, ...]:
    actions = _animation_pane_adjustment_actions(page, translator)
    shared = adjustment_rows(
        translator.text(
            "status.animation_adjust_quick"
            if page == "quick"
            else (
                "status.animation_adjust_advanced_command"
                if pane.overlay.config.command is not None
                else "status.animation_adjust_advanced"
            ),
            style=pane.session.spec.display_name,
            style_index=animation_style_choices("pane").index(pane.session.spec.style) + 1,
            style_count=len(animation_style_choices("pane")),
            theme=pane.session.theme,
            theme_index=COLOR_SCHEMES.index(pane.session.theme) + 1,
            theme_count=len(COLOR_SCHEMES),
            position=pane.overlay.presentation.position,
            offset_x=pane.overlay.presentation.offset_x,
            offset_y=pane.overlay.presentation.offset_y,
            interval=_format_overlay_interval(pane.overlay.config.interval),
        ),
        translator.text(f"adjustment.page_{page}"),
        actions,
        width=width,
        color=False,
        switch_action=translator.text(
            "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
        ),
        finish_action=translator.text("adjustment.finish"),
    )
    return (
        *shared,
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _ANIMATION_PANE_CONTENT_ACTIONS,
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


def _pane_management_divider(translator: Translator, width: int, *, color: bool) -> str:
    """Render the Dashboard Pane section boundary above scoped actions."""

    divider = translator.text("status.tui_pane_management_divider")
    return clip_width(f"\x1b[1m{divider}\x1b[0m" if color else divider, width)


def _management_row(
    label: str,
    actions: tuple[tuple[str, str], ...],
    translator: Translator,
    width: int,
) -> str:
    localized = _localized_actions(actions, translator)
    separator = " · "

    def compose(visible: tuple[AdjustmentAction, ...]) -> str:
        omitted = len(localized) - len(visible)
        parts = [action.text for action in visible]
        if omitted:
            parts.append(f"…(+{omitted})")
        return f"{label}: {separator.join(parts)}"

    visible = localized
    while visible and display_width(compose(visible)) > width:
        visible = visible[:-1]
    return clip_width(compose(visible), width)


def _adjustment_footer(
    state: str,
    command: str,
    page: str,
    body_view: BodyView,
    translator: Translator,
    width: int,
    *,
    chart: object | None = None,
    attachment_available: bool = False,
    color: bool = False,
) -> tuple[str, ...]:
    shared = adjustment_rows(
        state,
        translator.text(f"status.tui_adjust_{page}"),
        _pane_adjustment_actions(
            command,
            page,
            translator,
            chart=chart,
            attachment_available=attachment_available,
        ),
        width=width,
        color=False,
        switch_action=translator.text(
            "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
        ),
        finish_action=translator.text("adjustment.finish"),
    )
    return (
        *shared,
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _pane_content_actions(body_view),
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )


def _pane_adjustment_state(pane: TuiChartPane, page: str, translator: Translator) -> str:
    chart = _pane_display_options(pane).chart
    if page == "quick":
        settings = (
            f"{chart.kind} · {chart.presentation.density} · {chart.presentation.theme} · "
            f"{chart.presentation.style} · {pane.body_view}"
        )
    else:
        advanced: list[str] = []
        if isinstance(chart, (TimelineConfig, StackConfig, RankingConfig)):
            advanced.append(f"Other {chart.other}")
        if isinstance(chart, (TimelineConfig, StackConfig)):
            advanced.extend((f"Legend {chart.presentation.legend}", f"Weekdays {chart.weekdays}"))
        if isinstance(chart, StackConfig) and chart.by == "composition":
            advanced.insert(0, f"Cache {chart.cache}")
        if isinstance(chart, MonitorConfig):
            advanced.append(f"Legend {chart.presentation.legend}")
            if chart.presentation.style in {"ranking", "list"} and pane.attachment is not None:
                advanced.append(
                    translator.text(
                        "status.monitor_attachment_settings",
                        style=(
                            pane.attachment.spec.display_name
                            if pane.attachment_enabled
                            else translator.text("label.animation_none")
                        ),
                        theme=pane.attachment.theme,
                    ).lstrip(" ·")
                )
        settings = " · ".join(advanced)
    if not settings:
        return translator.text("status.tui_running")
    return translator.text(
        "status.tui_current_state",
        runtime=translator.text("status.tui_running"),
        settings=settings,
    )


def _global_adjustment_footer(
    *,
    state: str,
    translator: Translator,
    width: int,
) -> tuple[str, str]:
    actions = _localized_actions(_GLOBAL_ACTIONS, translator)
    label = translator.text("status.tui_adjust_quick")
    prefix = f"{label}：" if any(ord(char) > 127 for char in label) else f"{label}: "
    action_row = " · ".join(
        (*(_action.text for _action in actions), translator.text("status.tui_finish_keys"))
    )
    return clip_width(state, width), clip_width(prefix + action_row, width)


def _adjustment_target(focused: int | None, key: str, pane_count: int) -> int | None:
    if key == "\x1b":
        return None
    if focused is None:
        return 0 if key == "m" and pane_count else None
    if key == "\t":
        return (focused + 1) % pane_count
    return focused


def _layout_shortcut_capacity(shortcut: str) -> int | None:
    value = _LAYOUT_SHORTCUT_VALUES[shortcut]
    if "x" not in value:
        return None
    rows, columns = fixed_shape(value)
    return rows * columns


def _layout_shortcut_available(shortcut: str, pane_count: int) -> bool:
    return parse_dashboard_layout(_LAYOUT_SHORTCUT_VALUES[shortcut], pane_count) is not None


def _next_available_layout_shortcut(index: int, available: tuple[int, ...], direction: int) -> int:
    position = available.index(index)
    return available[(position + direction) % len(available)]


def _choose_layout_shortcut(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    current: str,
    pane_count: int,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    available = tuple(
        index
        for index, shortcut in enumerate(_LAYOUT_SHORTCUTS)
        if _layout_shortcut_available(shortcut, pane_count)
    )
    if not available:
        return None
    current_index = next(
        (
            item_index
            for item_index, shortcut in enumerate(_LAYOUT_SHORTCUTS)
            if current in {shortcut, _LAYOUT_SHORTCUT_VALUES[shortcut]}
        ),
        None,
    )
    index = current_index if current_index in available else available[0]
    while True:
        choices = "\n".join(
            (
                f"{'›' if item_index == index else ' '} {shortcut}"
                if item_index in available
                else f"  {shortcut} · {translator.text('status.tui_layout_unavailable', capacity=_layout_shortcut_capacity(shortcut), count=pane_count)}"
            )
            for item_index, shortcut in enumerate(_LAYOUT_SHORTCUTS)
        )
        screen.paint(
            compose_frame(
                choices,
                translator.text("label.adjust_layout"),
                translator.text("status.tui_layout_shortcuts_controls"),
                height=height,
            )
        )
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key in {"j", "\x1b[B"}:
            index = _next_available_layout_shortcut(index, available, 1)
        elif key in {"k", "\x1b[A"}:
            index = _next_available_layout_shortcut(index, available, -1)
        elif key in {"\r", "\n"}:
            return _LAYOUT_SHORTCUTS[index]
        elif key == "\x1b":
            return None


_CUSTOM_PANE_KINDS = ("timeline", "stack", "calendar", "ranking")


@dataclass(slots=True)
class CustomPaneDraft:
    kind: str = "timeline"
    dataset_id: str = ""
    command: str = ""
    field: int = 0


def _choose_custom_pane_config(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    dashboard: DashboardLaunch,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
    initial: CustomChartConfig | None = None,
) -> CustomChartPaneConfig | None:
    if initial is not None and initial.source.source_kind == "installed":
        return _choose_installed_pane_config(
            screen,
            translator,
            decoder,
            height=height,
            dashboard=dashboard,
            initial=initial,
            paint_choices=paint_choices,
            read_input=read_input,
        )
    draft = CustomPaneDraft(
        kind=initial.kind if initial is not None else "timeline",
        dataset_id=initial.source.dataset_id if initial is not None else "",
        command=shlex.join(initial.source.command_argv) if initial is not None else "",
    )
    error: str | None = None
    while True:
        fields = (
            translator.text("label.custom_kind"),
            translator.text("label.custom_dataset"),
            translator.text("label.custom_command"),
        )
        values = (draft.kind, draft.dataset_id, draft.command)
        choices = "\n".join(
            f"{'›' if index == draft.field else ' '} {field}: {value or '—'}"
            for index, (field, value) in enumerate(zip(fields, values, strict=True))
        )
        controls = translator.text("status.custom_pane_controls")
        notices = () if error is None else (error,)
        if paint_choices is None:
            screen.paint(
                compose_frame(
                    choices,
                    translator.text("status.custom_pane_title"),
                    controls,
                    notices,
                    height=height,
                )
            )
        else:
            paint_choices(choices, translator.text("status.custom_pane_title"), controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if isinstance(event, PasteEvent):
            if draft.field == 1:
                draft.dataset_id += event.value
            elif draft.field == 2:
                draft.command += event.value
            continue
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            return None
        if key in {"\t", "\x1b[B"}:
            draft.field = (draft.field + 1) % len(fields)
            continue
        if key == "\x1b[A":
            draft.field = (draft.field - 1) % len(fields)
            continue
        if draft.field == 0 and key in {"j", "\x1b[C"}:
            draft.kind = _CUSTOM_PANE_KINDS[(_CUSTOM_PANE_KINDS.index(draft.kind) + 1) % 4]
            continue
        if draft.field == 0 and key in {"k", "\x1b[D"}:
            draft.kind = _CUSTOM_PANE_KINDS[(_CUSTOM_PANE_KINDS.index(draft.kind) - 1) % 4]
            continue
        if key == "\x19":
            value = (draft.kind, draft.dataset_id, draft.command)[draft.field]
            error = translator.text(
                "status.command_copied" if copy_command(value) else "status.command_copy_failed"
            )
            continue
        if key == "\x15":
            if draft.field == 0:
                error = translator.text("status.custom_pane_kind_required")
            elif draft.field == 1:
                draft.dataset_id = ""
                error = translator.text("status.custom_pane_field_cleared")
            else:
                draft.command = ""
                error = translator.text("status.custom_pane_field_cleared")
            continue
        if key in {"\r", "\n"}:
            try:
                argv = tuple(shlex.split(draft.command))
                source = CustomCommandSource(draft.dataset_id.strip(), argv)
                return default_custom_pane(draft.kind, source=source, dashboard=dashboard)
            except ValueError as exc:
                error = str(exc)
            continue
        if draft.field in {1, 2}:
            value = draft.dataset_id if draft.field == 1 else draft.command
            if key in {"\x7f", "\b"}:
                value = value[:-1]
            elif len(key) == 1 and key.isprintable():
                value += key
            else:
                continue
            if draft.field == 1:
                draft.dataset_id = value
            else:
                draft.command = value


def _choose_installed_pane_config(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    dashboard: DashboardLaunch,
    initial: CustomChartConfig,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> CustomChartPaneConfig | None:
    """Edit an installed Dataset pane without exposing its resolved command."""

    from ccusage_viz.datasets.service import DatasetService

    kind = initial.kind
    dataset_id = initial.source.dataset_id
    field = 0
    error: str | None = None
    while True:
        fields = (translator.text("label.custom_kind"), translator.text("label.custom_dataset"))
        values = (kind, dataset_id)
        choices = "\n".join(
            f"{'›' if index == field else ' '} {label}: {value or '—'}"
            for index, (label, value) in enumerate(zip(fields, values, strict=True))
        )
        controls = translator.text("status.custom_pane_controls")
        notices = () if error is None else (error,)
        if paint_choices is None:
            screen.paint(
                compose_frame(
                    choices,
                    translator.text("status.custom_pane_title"),
                    controls,
                    notices,
                    height=height,
                )
            )
        else:
            paint_choices(choices, translator.text("status.custom_pane_title"), controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if isinstance(event, PasteEvent) and field == 1:
            dataset_id += event.value
            continue
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            return None
        if key in {"\t", "\x1b[B"}:
            field = (field + 1) % len(fields)
            continue
        if key == "\x1b[A":
            field = (field - 1) % len(fields)
            continue
        if field == 0 and key in {"j", "\x1b[C"}:
            kind = _CUSTOM_PANE_KINDS[
                (_CUSTOM_PANE_KINDS.index(kind) + 1) % len(_CUSTOM_PANE_KINDS)
            ]
            continue
        if field == 0 and key in {"k", "\x1b[D"}:
            kind = _CUSTOM_PANE_KINDS[
                (_CUSTOM_PANE_KINDS.index(kind) - 1) % len(_CUSTOM_PANE_KINDS)
            ]
            continue
        if key == "\x19":
            value = (kind, dataset_id)[field]
            error = translator.text(
                "status.command_copied" if copy_command(value) else "status.command_copy_failed"
            )
            continue
        if key == "\x15":
            if field == 0:
                error = translator.text("status.custom_pane_kind_required")
            else:
                dataset_id = ""
                error = translator.text("status.custom_pane_field_cleared")
            continue
        if key in {"\r", "\n"}:
            try:
                source = DatasetService().installed_command_source(dataset_id.strip())
                return default_custom_pane(kind, source=source, dashboard=dashboard)
            except (UsageError, ValueError) as exc:
                error = format_error(exc, translator) if isinstance(exc, UsageError) else str(exc)
            continue
        if field != 1:
            continue
        if key in {"\x7f", "\b"}:
            dataset_id = dataset_id[:-1]
        elif len(key) == 1 and key.isprintable():
            dataset_id += key


_DATASET_VIEW_KINDS = ("timeline", "calendar", "stack", "ranking")


def _chooser_viewport(
    rows: list[str], *, index: int, offset: int, height: int, reserved_rows: int = 2
) -> tuple[str, int]:
    """Keep the selected chooser row visible in the available frame body."""

    visible_rows = max(1, height - reserved_rows)
    maximum_offset = max(0, len(rows) - visible_rows)
    offset = min(max(0, offset), maximum_offset)
    if index < offset:
        offset = index
    elif index >= offset + visible_rows:
        offset = index - visible_rows + 1
    return "\n".join(rows[offset : offset + visible_rows]), offset


def _official_catalog_rows(
    entries: tuple[object, ...], translator: Translator, *, index: int, width: int
) -> list[str]:
    """Render official catalog entries in a compact two-line table layout."""

    name_width = max(12, width * 25 // 100)
    id_width = max(10, width * 18 // 100)
    summary_width = max(12, width - name_width - id_width - 5)
    rows = [
        clip_width(
            f"  {pad_width(translator.text('status.dataset_column_name'), name_width)} "
            f"{pad_width(translator.text('label.custom_dataset'), id_width)} "
            f"{pad_width(translator.text('status.dataset_column_summary'), summary_width)}",
            width,
        ),
        "─" * width,
    ]
    for item_index, entry in enumerate(entries):
        name = entry.title.zh_cn if translator.language == "zh" else entry.title.en
        summary = entry.summary.zh_cn if translator.language == "zh" else entry.summary.en
        summary_lines = list(wrap_width(summary, summary_width))
        if len(summary_lines) > 2:
            summary_lines = [
                summary_lines[0],
                truncate_width(summary_lines[1], summary_width - 3) + "...",
            ]
        elif len(summary_lines) < 2:
            summary_lines.append("")
        rows.extend(
            (
                clip_width(
                    f"{'›' if item_index == index else ' '} "
                    f"{pad_width(truncate_width(name, name_width), name_width)} "
                    f"{pad_width(truncate_width(entry.id, id_width), id_width)} {summary_lines[0]}",
                    width,
                ),
                clip_width(f"  {'':{name_width}} {'':{id_width}} {summary_lines[1]}", width),
            )
        )
    return rows


def _official_catalog_viewport(
    entries: tuple[object, ...],
    translator: Translator,
    *,
    index: int,
    offset: int,
    width: int,
    height: int,
) -> tuple[str, int]:
    rows = _official_catalog_rows(entries, translator, index=index, width=width)
    header = rows[:2]
    items = rows[2:]
    body, offset = _chooser_viewport(
        items, index=index * 2, offset=offset, height=max(1, height - len(header))
    )
    return "\n".join([*header, *body.splitlines()]), offset


def _official_preview_rows(
    preview: tuple[object, bytes, object], translator: Translator
) -> tuple[str, ...]:
    _artifact, _archive, manifest = preview
    descriptor = manifest.descriptor
    if descriptor is None:
        return (
            manifest.metric.title.zh_cn
            if translator.language == "zh"
            else manifest.metric.title.en,
        )
    title = (
        descriptor.dataset.title.zh_cn
        if translator.language == "zh"
        else descriptor.dataset.title.en
    )
    description = (
        descriptor.dataset.description.zh_cn
        if translator.language == "zh"
        else descriptor.dataset.description.en
    )
    charts = " · ".join(
        translator.text(f"label.pane_{kind}") for kind in descriptor.capabilities.charts
    )
    required = tuple(item.name for item in descriptor.environment if item.required)
    optional = tuple(item.name for item in descriptor.environment if not item.required)
    return (
        title,
        description,
        f"{translator.text('status.dataset_column_version')}: {descriptor.version}",
        f"{translator.text('status.dataset_details_supports')}: {charts}",
        translator.text("status.dataset_details_environment"),
        *(
            f"{translator.text('status.dataset_environment_required')}: {' · '.join(required)}"
            if required
            else (),
        ),
        *(
            f"{translator.text('status.dataset_environment_optional')}: {' · '.join(optional)}"
            if optional
            else (),
        ),
    )


def _choose_dataset_view(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    kinds: tuple[str, ...] = _DATASET_VIEW_KINDS,
    height: int,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    index = 0
    offset = 0
    while True:
        rows = [
            f"{'›' if item_index == index else ' '} {translator.text(f'label.pane_{kind}')}"
            for item_index, kind in enumerate(kinds)
        ]
        title = translator.text("status.dataset_chooser_title")
        controls = translator.text("status.dataset_chooser_controls")
        choices, offset = _chooser_viewport(rows, index=index, offset=offset, height=height)
        if paint_choices is None:
            screen.paint(compose_frame(choices, title, controls, height=height))
        else:
            paint_choices(choices, title, controls, ())
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        if event.value == "\x1b":
            return None
        if event.value in {"j", "\x1b[B"}:
            index = (index + 1) % len(kinds)
        elif event.value in {"k", "\x1b[A"}:
            index = (index - 1) % len(kinds)
        elif event.value in {"\r", "\n"}:
            return kinds[index]


def _browse_dataset_catalog(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    service: object,
    height: int,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    """Fetch and present verified official datasets without blocking the dashboard."""

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-catalog")
    future = executor.submit(cast(Callable[[], tuple[object, ...]], service.official_entries))
    entries: tuple[object, ...] | None = None
    error: str | None = None
    try:
        while entries is None and error is None:
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_controls")
            notices = (translator.text("status.dataset_catalog_loading"),)
            if paint_choices is None:
                screen.paint(compose_frame("", title, controls, notices, height=height))
            else:
                paint_choices("", title, controls, notices)
            if future.done():
                try:
                    entries = future.result()
                except UsageError as exc:
                    error = format_error(exc, translator)
                except Exception:
                    error = translator.text("status.dataset_catalog_unavailable")
                continue
            event = read_input() if read_input is not None else read_event(decoder, 0.1)
            if isinstance(event, KeyEvent) and event.value == "\x1b":
                future.cancel()
                return None
            if not future.done():
                continue
            try:
                entries = future.result()
            except UsageError as exc:
                error = format_error(exc, translator)
            except Exception:
                error = translator.text("status.dataset_catalog_unavailable")
        if error is not None:
            while True:
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
                if paint_choices is None:
                    screen.paint(compose_frame("", title, controls, (error,), height=height))
                else:
                    paint_choices("", title, controls, (error,))
                event = read_input() if read_input is not None else read_event(decoder, 0.1)
                if isinstance(event, KeyEvent) and event.value == "\x1b":
                    return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    assert entries is not None
    index = 0
    offset = 0
    confirming = False
    notice: str | None = None
    host_os, host_arch = service.platform
    platform_name = f"{host_os}/{host_arch}"
    while True:
        choices, offset = (
            _official_catalog_viewport(
                entries,
                translator,
                index=index,
                offset=offset,
                width=get_terminal_size().columns,
                height=height,
            )
            if entries
            else (translator.text("status.datasets_official_empty"), 0)
        )
        selected = entries[index] if entries else None
        available = selected is not None and any(
            artifact.os == host_os and artifact.arch == host_arch for artifact in selected.artifacts
        )
        title = translator.text("status.dataset_browse_title")
        controls = translator.text(
            "status.dataset_browse_confirm_controls"
            if confirming
            else "status.dataset_browse_controls"
        )
        notices = () if notice is None else (notice,)
        if confirming and selected is not None:
            artifact = next(
                artifact
                for artifact in selected.artifacts
                if artifact.os == host_os and artifact.arch == host_arch
            )
            detail = "\n".join(
                (
                    choices,
                    "",
                    selected.summary.zh_cn if translator.language == "zh" else selected.summary.en,
                    f"{artifact.repository} · {artifact.release_tag} · {platform_name}",
                    translator.text(
                        "status.dataset_browse_confirm",
                        dataset_id=selected.id,
                        repository=artifact.repository,
                    ),
                )
            )
        else:
            detail = choices
        if paint_choices is None:
            screen.paint(compose_frame(detail, title, controls, notices, height=height))
        else:
            paint_choices(detail, title, controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            if confirming:
                confirming = False
                notice = None
                continue
            return None
        if key == "h":
            notice = translator.text("status.dataset_catalog_help_hint")
            continue
        if not entries:
            continue
        if not confirming and key in {"j", "\x1b[B"}:
            index = (index + 1) % len(entries)
            notice = None
            continue
        if not confirming and key in {"k", "\x1b[A"}:
            index = (index - 1) % len(entries)
            notice = None
            continue
        if key not in {"\r", "\n"}:
            continue
        if not available:
            notice = translator.text(
                "status.dataset_catalog_unavailable_platform", platform=platform_name
            )
            continue
        if not confirming:
            confirming = True
            notice = None
            continue
        notice = translator.text("status.dataset_browse_installing", dataset_id=selected.id)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-install")
        install = executor.submit(service.install_official, selected.id)
        try:
            while not install.done():
                if paint_choices is None:
                    screen.paint(compose_frame(detail, title, controls, (notice,), height=height))
                else:
                    paint_choices(detail, title, controls, (notice,))
                event = read_input() if read_input is not None else read_event(decoder, 0.1)
                if isinstance(event, KeyEvent) and event.value == "\x1b":
                    # A started installation is transactional and cannot be safely cancelled.
                    continue
            install.result()
        except UsageError as exc:
            confirming = False
            notice = format_error(exc, translator)
            continue
        except Exception:
            confirming = False
            notice = translator.text("error.dataset_download_failed")
            continue
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return selected.id


def _install_github_dataset(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    service: object,
    height: int,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> str | None:
    """Install a verified GitHub dataset from one repository input."""

    repository = ""
    artifact: object | None = None
    error: str | None = None
    resolving: Future[object] | None = None
    installing: Future[object] | None = None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-github")
    try:
        while True:
            if resolving is not None and resolving.done():
                try:
                    artifact = resolving.result()
                    error = None
                except UsageError as exc:
                    error = format_error(exc, translator)
                except Exception:
                    error = translator.text("error.dataset_download_failed")
                resolving = None
            if installing is not None and installing.done():
                try:
                    status = installing.result()
                    installed = status.installed
                    if installed is None:
                        raise UsageError("error.dataset_corrupt")
                    return installed.dataset_id
                except UsageError as exc:
                    error = format_error(exc, translator)
                except Exception:
                    error = translator.text("error.dataset_download_failed")
                artifact = None
                installing = None

            title = translator.text("status.dataset_github_title")
            if resolving is not None:
                body = repository or "—"
                controls = translator.text("status.dataset_github_loading_controls")
                notices = (translator.text("status.dataset_github_resolving"),)
            elif installing is not None:
                body = repository
                controls = translator.text("status.dataset_github_loading_controls")
                notices = (translator.text("status.dataset_github_installing"),)
            elif artifact is not None:
                body = "\n".join(
                    (
                        repository,
                        "",
                        f"{artifact.release_tag} · {artifact.asset_name}",
                        artifact.sha256,
                        translator.text(
                            "status.dataset_github_confirm", repository=artifact.repository
                        ),
                    )
                )
                controls = translator.text("status.dataset_github_confirm_controls")
                notices = () if error is None else (error,)
            else:
                body = repository or "—"
                controls = translator.text("status.dataset_github_controls")
                notices = () if error is None else (error,)
            if paint_choices is None:
                screen.paint(compose_frame(body, title, controls, notices, height=height))
            else:
                paint_choices(body, title, controls, notices)

            event = read_input() if read_input is not None else read_event(decoder, 0.1)
            if (
                isinstance(event, PasteEvent)
                and artifact is None
                and resolving is None
                and installing is None
            ):
                repository += event.value
                error = None
                continue
            if not isinstance(event, KeyEvent):
                continue
            key = event.value
            if key == "\x1b":
                if resolving is not None or installing is not None:
                    continue
                if artifact is not None:
                    artifact = None
                    error = None
                    continue
                return None
            if resolving is not None or installing is not None:
                continue
            if artifact is not None:
                if key in {"\r", "\n"}:
                    installing = executor.submit(service.install_resolved_github_artifact, artifact)
                continue
            if key in {"\r", "\n"}:
                if repository.strip():
                    resolving = executor.submit(service.resolve_github_repository, repository)
                    error = None
                continue
            if key in {"\x7f", "\b"}:
                repository = repository[:-1]
                error = None
            elif len(key) == 1 and key.isprintable():
                repository += key
                error = None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _choose_dataset_pane_config(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    dashboard: DashboardLaunch,
    initial: CustomChartConfig | None = None,
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
) -> CustomChartPaneConfig | None:
    """Select a ready Dataset, then Metric and chart kind for V2 sources."""

    from ccusage_viz.datasets.service import DatasetService

    service = DatasetService()
    try:
        statuses = service.ready_registered_sources()
    except UsageError as exc:
        statuses = ()
        error: str | None = format_error(exc, translator)
    else:
        error = None
    index = 0
    offset = 0
    while True:
        entries = list(statuses)
        if not entries:
            return None
        index %= len(entries)
        choices: list[str] = []
        for item_index, status in enumerate(entries):
            selected = "›" if item_index == index else " "
            descriptor = status.registration.probe.descriptor
            choices.append(
                f"{selected} {_dataset_title(descriptor.dataset.title, translator)} "
                f"{descriptor.version} · {translator.text('status.dataset_ready')}"
            )
        title = translator.text("status.dataset_chooser_title")
        controls = translator.text("status.dataset_chooser_controls")
        notices = () if error is None else (error,)
        body, offset = _chooser_viewport(
            choices,
            index=index,
            offset=offset,
            height=height,
            reserved_rows=2 + len(notices),
        )
        if paint_choices is None:
            screen.paint(compose_frame(body, title, controls, notices, height=height))
        else:
            paint_choices(body, title, controls, notices)
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "\x1b":
            return None
        if key in {"j", "\x1b[B"}:
            index = (index + 1) % len(entries)
            continue
        if key in {"k", "\x1b[A"}:
            index = (index - 1) % len(entries)
            continue
        if key not in {"\r", "\n"}:
            continue
        status = entries[index]
        descriptor = status.registration.probe.descriptor
        metric_id: str | None = None
        metric_summary = "comparisons"
        metric_periods: tuple[str, ...] = ()
        metric_titles: tuple[str, str] | None = None
        if isinstance(descriptor, V2ProbeDescriptor):
            metric_index = next(
                (
                    index
                    for index, metric in enumerate(descriptor.metrics)
                    if metric.id == descriptor.default_metric_id
                ),
                0,
            )
            metric_offset = 0
            while True:
                metric = descriptor.metrics[metric_index]
                metric_choices = [
                    f"{'›' if position == metric_index else ' '} {_dataset_title(item.title, translator)}"
                    for position, item in enumerate(descriptor.metrics)
                ]
                body, metric_offset = _chooser_viewport(
                    metric_choices,
                    index=metric_index,
                    offset=metric_offset,
                    height=height,
                    reserved_rows=2,
                )
                if paint_choices is None:
                    screen.paint(
                        compose_frame(
                            body,
                            translator.text("status.dataset_chooser_title"),
                            translator.text("status.dataset_chooser_controls"),
                            (),
                            height=height,
                        )
                    )
                else:
                    paint_choices(
                        body,
                        translator.text("status.dataset_chooser_title"),
                        translator.text("status.dataset_chooser_controls"),
                        (),
                    )
                event = read_input() if read_input is not None else read_event(decoder, 0.1)
                if not isinstance(event, KeyEvent):
                    continue
                if event.value == "\x1b":
                    break
                if event.value in {"j", "\x1b[B"}:
                    metric_index = (metric_index + 1) % len(descriptor.metrics)
                    continue
                if event.value in {"k", "\x1b[A"}:
                    metric_index = (metric_index - 1) % len(descriptor.metrics)
                    continue
                if event.value in {"\r", "\n"}:
                    metric_id = metric.id
                    metric_summary = metric.summary
                    metric_titles = (metric.title.en, metric.title.zh_cn)
                    ranking = metric.capabilities.charts.get("ranking")
                    metric_periods = (
                        ranking.periods
                        if isinstance(ranking, V2HistoricalChartCapability)
                        else ()
                    )
                    break
            if metric_id is None:
                continue
            kinds = tuple(metric.capabilities.charts)
        else:
            kinds = tuple(descriptor.capabilities.charts)
        if not kinds:
            continue
        view = _choose_dataset_view(
            screen,
            translator,
            decoder,
            height=height,
            kinds=kinds,
            paint_choices=paint_choices,
            read_input=read_input,
        )
        if view is None:
            continue
        try:
            source = service.registered_command_source(status.registration.dataset_id)
        except UsageError as exc:
            error = format_error(exc, translator)
            continue
        return default_custom_pane(
            view,
            source=source,
            dashboard=dashboard,
            metric_id=metric_id,
            metric_summary=metric_summary,
            metric_periods=metric_periods,
            metric_titles=metric_titles,
        )


def _choose_pane_type(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    action: str = "add",
    paint_choices: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    read_input: Callable[[], object] | None = None,
    on_help: Callable[[str], None] | None = None,
) -> str | None:
    index = 0
    offset = 0
    while True:
        rows, positions = _pane_chooser_rows(translator, index)
        title = translator.text(f"status.tui_{action}_title")
        controls = translator.text(f"status.tui_{action}_controls")
        choices, offset = _chooser_viewport(
            rows,
            index=positions[_PANE_COMMANDS[index]],
            offset=offset,
            height=height,
        )
        if paint_choices is None:
            screen.paint(compose_frame(choices, title, controls, height=height))
        else:
            paint_choices(choices, title, controls, ())
        event = read_input() if read_input is not None else read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key == "h" and on_help is not None:
            on_help(_PANE_COMMANDS[index])
        elif key in {"j", "\x1b[B"}:
            index = (index + 1) % len(_PANE_COMMANDS)
        elif key in {"k", "\x1b[A"}:
            index = (index - 1) % len(_PANE_COMMANDS)
        elif key in {"\r", "\n"}:
            return _PANE_COMMANDS[index]
        elif key == "\x1b":
            return None


def _custom_standalone_actions(
    component: CustomHistoricalComponent,
    translator: Translator,
) -> tuple[AdjustmentAction, ...]:
    """Return the live custom adjustments available to a standalone chart."""

    capability = _custom_capability_for_component(component)
    actions: list[tuple[str, str]] = [("p/P", "period")]
    chart = component.candidate
    if capability is not None:
        if len(capability.granularities) > 1:
            actions.append(("g/G", "granularity"))
        if chart.kind != "calendar" and capability.group_by:
            actions.append(("b/B", "group"))
        if capability.filters:
            actions.append(("f", "filters"))
    if chart.group_by is not None:
        actions.extend((("+/-", "top"), ("o", "other")))
    if chart.kind in {"timeline", "stack"}:
        actions.extend((("k", "weekdays"), ("l", "legend")))
    actions.extend(
        (
            ("d", "density"),
            ("t/T", "theme"),
            ("s/S", "style"),
            ("L", "custom_logs"),
        )
    )
    return _localized_actions(tuple(actions), translator)


def _custom_standalone_render(
    component: CustomHistoricalComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    interval: float | None = None,
    pending: bool,
    summary: CustomDashboardSummary | None = None,
) -> PaneRender:
    if component.error is not None and component.model is None:
        return _render_custom_failure(
            component,
            translator,
            terminal,
            accepted_at=component.accepted_at,
            interval=interval,
            surface=standalone_surface(component.candidate.kind),
        )
    if component.model is None:
        return PaneRender(translator.text("status.loading"))
    if component.is_pending:
        context = _custom_render_context(
            component.candidate,
            translator,
            terminal,
            accepted_at=component.accepted_at,
            interval=interval,
            pending=True,
            surface=standalone_surface(component.candidate.kind),
        )
        rendered = render_custom_pending(component.candidate, context)
        audit = render_audit(context)
        return PaneRender("\n".join(line for line in (rendered, audit) if line))
    rendered = _render_custom_projection(
        component.model,
        component.accepted_config or component.candidate,
        translator,
        terminal,
        accepted_at=component.accepted_at,
        interval=interval,
        pending=pending,
        surface=standalone_surface((component.accepted_config or component.candidate).kind),
        summary=summary,
    )
    return (
        PaneRender(
            rendered.chart,
            (*rendered.notices, format_error(component.error, translator, color=False)),
        )
        if component.error is not None
        else rendered
    )


def _run_custom_standalone_adjustment(
    component: CustomHistoricalComponent,
    translator: Translator,
    screen: FramePainter,
    *,
    ascii: bool,
) -> tuple[CustomChartConfig, bool] | None:
    """Adjust a custom chart without entering Dashboard pane adjustment mode."""

    current = component.candidate
    initial = current
    page = "quick"
    timer = AdjustmentIdleTimer()
    last_size = None

    def paint() -> None:
        nonlocal last_size
        size = get_terminal_size()
        last_size = size
        terminal = Terminal(
            size.columns,
            size.lines,
            current.presentation.theme != "no-color",
            ascii,
        )
        try:
            terminal = inspect_terminal(
                current.kind,
                no_color=current.presentation.theme == "no-color",
                ascii=ascii,
                size=size,
            )
            preview = CustomHistoricalComponent(current)
            if component.accepted_response is not None:
                preview.accept_response(component.accepted_response)
            rendered = _custom_standalone_render(
                preview, translator, terminal, interval=None, pending=False
            )
            body, notices = rendered.chart, rendered.notices
        except (UsageError, ValueError) as exc:
            body = format_error(exc, translator, color=terminal.color)
            notices = ()
        controls = adjustment_rows(
            " · ".join(action.text for action in _custom_standalone_actions(component, translator)),
            translator.text(f"adjustment.page_{page}"),
            _custom_standalone_actions(component, translator),
            width=terminal.width,
            color=terminal.color,
            switch_action=translator.text(
                "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
            ),
            finish_action=translator.text("adjustment.finish"),
        )
        screen.paint(
            compose_frame(
                body,
                translator.text("label.adjust_chart"),
                controls,
                format_notice_lines(
                    notices,
                    width=terminal.width,
                    color=terminal.color,
                    ascii=terminal.ascii,
                    translator=translator,
                    color_scheme=current.presentation.theme,
                ),
                height=terminal.height,
            )
        )

    try:
        with input_mode():
            paint()
            while True:
                key = read_key(min(0.1, timer.remaining()))
                if key is None:
                    timer.check()
                    continue
                timer.record_input()
                if get_terminal_size() != last_size:
                    paint()
                if key == "\x03":
                    raise KeyboardInterrupt
                if key == "L":
                    return current, custom_replacement_required(initial, current)
                if key in {"\x1b"}:
                    return None
                if key in {"\r", "\n"}:
                    return current, custom_replacement_required(initial, current)
                if key == "a":
                    page = "advanced" if page == "quick" else "quick"
                    paint()
                    continue
                capability = _custom_capability_for_component(component)
                updated = current
                if key in {"p", "P", "d", "t", "T", "s", "S", "k", "l", "o", "+", "=", "-", "_"}:
                    updated = adjust_custom_chart(current, key)
                elif (
                    key in {"g", "G"}
                    and capability is not None
                    and len(capability.granularities) > 1
                ):
                    values = capability.granularities
                    value = current.granularity if current.granularity in values else values[0]
                    updated = replace(
                        current, granularity=_cycle(values, value, 1 if key == "g" else -1)
                    )
                elif (
                    key in {"b", "B"}
                    and current.kind != "calendar"
                    and capability is not None
                    and capability.group_by
                ):
                    updated = _cycle_custom_grouping(
                        current,
                        capability.group_by,
                        step=1 if key == "b" else -1,
                    )
                if updated != current:
                    current = updated
                    paint()
    except AdjustmentTimeout:
        return current, custom_replacement_required(initial, current)
    except KeyboardInterrupt:
        return None


def run_custom_standalone(options: StandaloneLaunch, translator: Translator) -> int:
    """Run one custom chart with the native standalone shell and lifecycle."""

    if not isinstance(options.chart, CustomChartConfig):
        raise TypeError("custom standalone runner requires a custom chart configuration")
    started_at = time.monotonic()
    component = CustomHistoricalComponent(options.chart)
    scheduler = FixedIntervalScheduler(options.host.interval, now=started_at)
    lifecycle: LifecycleOperation[Future[CustomOutcome]] = LifecycleOperation("standalone:custom")
    summary = CustomDashboardSummary(
        options.chart.source,
        FixedIntervalScheduler(options.host.interval, now=started_at),
        LifecycleOperation("standalone:custom:summary"),
        filters=options.chart.filters,
    )
    runtime = build_query_runtime()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-custom")
    screen = FramePainter(sys.stdout)
    current = options.chart
    controls_hidden = False
    body_view: BodyView = "chart"
    text_offsets: dict[BodyView, int] = {}
    text_line_counts: dict[BodyView, int] = {}
    text_visible_rows: dict[BodyView, int] = {}
    error_offset = 0
    error_line_count = 0
    error_visible_rows = 0
    logs: list[CustomLogRecord] = []
    copy_feedback = TransientFeedback()
    last_size: tuple[int, int] | None = None

    def record(status: str, detail: str) -> None:
        logs.append(CustomLogRecord(datetime.now().astimezone(), status, detail))
        logs[:] = logs[-20:]

    def record_warnings(response: object) -> None:
        for warning in getattr(response, "warnings", ()):
            record(
                "warning",
                warning.message.zh_cn if translator.language == "zh" else warning.message.en,
            )

    probe_complete = False

    def start(operation: OperationToken) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        if not probe_complete:
            intent = (
                custom_v2_probe_query_intent
                if component.candidate.metric_id is not None
                else custom_probe_query_intent
            )(
                component.candidate.source,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=options.process,
            )
            handle = runtime.submit(intent)
            return (
                executor.submit(_await_custom_submission, handle, operation.generation, "probe"),
                handle.cancel,
            )
        purpose = "comparison" if component.comparison_is_pending else "primary"
        config = (
            component.candidate if purpose == "primary" else component.comparison_request_config()
        )
        if config is None:
            raise RuntimeError("custom comparison request is no longer required")
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        intent = custom_historical_query_intent(
            config,
            timezone=options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=options.process,
            request_id_suffix=":comparison" if purpose == "comparison" else "",
        )
        handle = runtime.submit(intent)
        return (
            executor.submit(_await_custom_submission, handle, operation.generation, purpose),
            handle.cancel,
        )

    def start_summary(
        operation: OperationToken,
    ) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        config = component.candidate
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        plan = (
            range_summary_query_plan(config.date_range)
            if config.date_range.fixed_bounds
            else summary_query_plan(
                local_today(timezone=options.host.timezone), cast(SummaryScope, config.granularity)
            )
        )
        summary.select(config.source, config.filters)
        intent = custom_summary_query_intent(
            config.source,
            plan,
            filters=config.filters,
            timezone=options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=options.process,
        )
        request = intent.payload
        if not isinstance(request, CustomSummaryRequest):
            raise TypeError("custom standalone summary intent has an unexpected payload")
        summary.requested_period = request.scope
        summary.requested_as_of_date = request.current.until
        handle = runtime.submit(intent)
        return executor.submit(
            _await_custom_submission, handle, operation.generation
        ), handle.cancel

    def request_summary(trigger: LifecycleTrigger, *, replace_active: bool = False) -> bool:
        if not probe_complete:
            return False
        source_changed = (
            summary.source != component.candidate.source
            or summary.filters != component.candidate.filters
        )
        if source_changed:
            summary.invalidate()
        try:
            return summary.lifecycle.request(
                trigger,
                generation=summary.generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=start_summary,
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def complete_summary(operation: OperationToken, outcome: CustomOutcome) -> None:
        if not summary.lifecycle.accepts(operation, generation=outcome.generation):
            summary.lifecycle.abandon(operation)
            return
        if outcome.error is not None or outcome.result is None:
            summary.error = outcome.error or RuntimeError("custom command returned no summary")
            summary.lifecycle.complete(operation, generation=outcome.generation)
            return
        response = outcome.result.custom_response
        if not isinstance(response, (CustomSummaryResponse, V2SummaryResponse)):
            raise TypeError("custom provider result does not contain a summary response")
        summary.response = response
        summary.error = None
        summary.accepted_at = datetime.now().astimezone()
        summary.accepted_period = summary.requested_period
        summary.accepted_as_of_date = summary.requested_as_of_date
        summary.lifecycle.complete(operation, generation=outcome.generation)
        record_warnings(response)

    def request(
        trigger: LifecycleTrigger, *, replace_active: bool = False, roll_range: bool = True
    ) -> bool:
        nonlocal current
        if roll_range:
            refreshed = replace(
                component.candidate,
                date_range=refresh_date_range(
                    component.candidate.date_range, timezone=options.host.timezone
                ),
            )
            component.configure(refreshed, data_affecting=refreshed != component.candidate)
            current = component.candidate
        try:
            requested = lifecycle.request(
                trigger,
                generation=component.generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=start,
            )
            if requested:
                request_summary(trigger, replace_active=replace_active)
            return requested
        except BaseException as exc:
            if component.fail(exc, generation=component.generation):
                record("error", str(exc))
            return False

    def controls() -> str:
        if body_view == "chart" and controls_hidden:
            return ""
        return translator.text(
            {
                "chart": "status.keys",
                "command": "status.command_keys",
                "full-command": "status.custom_full_command_keys",
                "data-table": "status.data_table_keys",
                "data-json": "status.data_json_keys",
            }[body_view],
            scroll=translator.text("status.text_scroll_keys")
            if body_view != "chart"
            and text_viewport_overflows(
                line_count=text_line_counts.get(body_view, 0),
                visible_rows=text_visible_rows.get(body_view, 0),
            )
            else "",
        )

    def paint(*, force: bool = False) -> None:
        nonlocal last_size, error_offset, error_line_count, error_visible_rows
        size = get_terminal_size()
        last_size = (size.columns, size.lines)
        terminal = Terminal(
            size.columns,
            size.lines,
            current.presentation.theme != "no-color",
            options.host.ascii,
        )
        try:
            terminal = inspect_terminal(
                current.kind,
                no_color=current.presentation.theme == "no-color",
                ascii=options.host.ascii,
                size=size,
            )
            provisional = _custom_standalone_render(
                component,
                translator,
                terminal,
                interval=options.host.interval,
                pending=lifecycle.submission is not None,
                summary=summary,
            )
            notices = provisional.notices
        except UsageError as exc:
            provisional = PaneRender(format_error(exc, translator, color=False))
            notices = ()
        footer = controls()
        feedback = feedback_lines(copy_feedback, width=size.columns, color=terminal.color)
        notice_rows = (
            *format_notice_lines(
                notices,
                width=size.columns,
                color=terminal.color,
                ascii=options.host.ascii,
                translator=translator,
                color_scheme=current.presentation.theme,
            ),
            *feedback,
        )
        control_rows = (
            controls_line(footer, width=size.columns, color=terminal.color) if footer else ()
        )
        body_height = max(1, terminal.height - 1 - len(notice_rows) - int(bool(control_rows)))
        if body_view == "chart":
            try:
                rendered = _custom_standalone_render(
                    component,
                    translator,
                    Terminal(terminal.width, body_height, terminal.color, terminal.ascii),
                    interval=options.host.interval,
                    pending=lifecycle.submission is not None,
                    summary=summary,
                )
                body, notices = rendered.chart, rendered.notices
            except UsageError:
                body, notices = provisional.chart, provisional.notices
        else:
            body = (
                wrap_command(format_command(replace(options, chart=current)), size.columns)
                if body_view == "command"
                else format_full_command_display(
                    format_full_command(replace(options, chart=current)), size.columns
                )
                if body_view == "full-command"
                else render_custom_data(
                    component.model,
                    language=translator.language,
                    translator=translator,
                    view=body_view,
                )
                if component.model is not None
                else translator.text("status.loading")
            )
        error_body = body_view == "chart" and provisional.error_body
        if error_body:
            body_rows = wrap_text_rows(body, width=size.columns)
            error_visible_rows = body_height
            error_line_count = len(body_rows)
            error_offset = min(error_offset, max(0, error_line_count - error_visible_rows))
            body = render_text_viewport(
                body_rows, offset=error_offset, visible_rows=error_visible_rows
            ).body
        elif body_view != "chart":
            viewport = render_text_viewport(
                body,
                offset=text_offsets.get(body_view, 0),
                visible_rows=body_height,
            )
            text_offsets[body_view] = viewport.offset
            text_line_counts[body_view] = viewport.line_count
            text_visible_rows[body_view] = viewport.visible_rows
            body = viewport.body
        screen.paint(
            compose_frame(
                body,
                translator.text("status.refresh_every", seconds=f"{options.host.interval:g}"),
                control_rows,
                notice_rows,
                height=size.lines,
            ),
            force=force,
        )

    try:
        request(LifecycleTrigger.STARTUP, roll_range=False)
        if not options.host.watch:
            operation = lifecycle.operation
            future = lifecycle.submission
            if operation is None or future is None:
                paint()
                return 1
            try:
                while True:
                    outcome = future.result()
                    if outcome.error is not None or outcome.result is None:
                        error = outcome.error or RuntimeError("custom command returned no result")
                        component.fail(error, generation=outcome.generation)
                        record("error", str(error))
                        paint()
                        return 1
                    if not lifecycle.accepts(operation, generation=outcome.generation):
                        paint()
                        return 1
                    if outcome.purpose == "probe":
                        response = outcome.result.custom_response
                        if options.host.timezone is None:
                            raise RuntimeError("custom Dataset requests require a timezone")
                        if isinstance(response, V2ProbeResponse):
                            resolved = resolve_metric(component.candidate, response.descriptor)
                            component.configure(
                                apply_custom_probe_defaults(
                                    resolved,
                                    v2_metric_probe_descriptor(
                                        response.descriptor, resolved.metric_id
                                    ),
                                    timezone=options.host.timezone,
                                ),
                                data_affecting=False,
                            )
                        elif isinstance(response, CustomProbeResponse):
                            component.configure(
                                apply_custom_probe_defaults(
                                    component.candidate,
                                    response.descriptor,
                                    timezone=options.host.timezone,
                                ),
                                data_affecting=False,
                            )
                        else:
                            raise TypeError("custom provider result does not contain a probe response")
                        current = component.candidate
                        probe_complete = True
                        lifecycle.complete(operation, generation=outcome.generation)
                        record_warnings(response)
                        request(LifecycleTrigger.STARTUP, roll_range=False)
                        operation = lifecycle.operation
                        future = lifecycle.submission
                        if operation is None or future is None:
                            raise RuntimeError("custom probe did not schedule a chart request")
                        continue
                    if not component.apply_provider_result(outcome.result, purpose=outcome.purpose):
                        paint()
                        return 1
                    lifecycle.complete(operation, generation=outcome.generation)
                    break
                record_warnings(outcome.result.custom_response)
                current = component.candidate
                comparison = component.start_comparison()
                if comparison is not None:
                    try:
                        if options.host.timezone is None:
                            raise RuntimeError("custom Dataset requests require a timezone")
                        intent = custom_historical_query_intent(
                            comparison,
                            timezone=options.host.timezone,
                            owner_id=operation.owner_id,
                            generation=operation.generation,
                            trigger=query_trigger(LifecycleTrigger.CONFIGURATION),
                            process=options.process,
                            request_id_suffix=":comparison",
                        )
                        comparison_outcome = _await_custom_submission(
                            runtime.submit(intent), operation.generation, "comparison"
                        )
                        if (
                            comparison_outcome.error is not None
                            or comparison_outcome.result is None
                        ):
                            component.fail(
                                comparison_outcome.error
                                or RuntimeError("custom comparison command returned no result"),
                                generation=operation.generation,
                                purpose="comparison",
                            )
                        else:
                            component.apply_provider_result(
                                comparison_outcome.result, purpose="comparison"
                            )
                    except BaseException as exc:
                        component.fail(exc, generation=operation.generation, purpose="comparison")
                summary_operation = summary.lifecycle.operation
                summary_future = summary.lifecycle.submission
                if summary_operation is not None and summary_future is not None:
                    try:
                        complete_summary(summary_operation, summary_future.result())
                    except BaseException as exc:
                        summary.error = exc
                record("ok", getattr(outcome.result, "diagnostics", "") or "ok")
                paint()
                return 0
            finally:
                lifecycle.abandon(operation)
        with input_mode():
            paint()
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                now = time.monotonic()
                if copy_feedback.message is not None and now >= copy_feedback.expires_at:
                    copy_feedback.current(now=now)
                    paint()
                if scheduler.due(now=now):
                    request(LifecycleTrigger.PERIODIC)
                    paint()
                completed_summary = summary.lifecycle.take_completed(lambda future: future.done())
                if completed_summary is not None:
                    summary_operation, summary_future = completed_summary
                    try:
                        complete_summary(summary_operation, summary_future.result())
                    except BaseException as exc:
                        summary.error = exc
                        if summary.lifecycle.accepts(
                            summary_operation, generation=summary_operation.generation
                        ):
                            summary.lifecycle.complete(
                                summary_operation, generation=summary_operation.generation
                            )
                    paint()
                    summary.lifecycle.start_ready(now=time.monotonic(), start=start_summary)
                completed = lifecycle.take_completed(lambda future: future.done())
                if completed is not None:
                    operation, future = completed
                    active = lifecycle.accepts(operation, generation=operation.generation)
                    try:
                        outcome = future.result()
                        purpose = outcome.purpose
                        if active and outcome.error is None and outcome.result is not None:
                            if purpose == "probe":
                                response = outcome.result.custom_response
                                if options.host.timezone is None:
                                    raise RuntimeError("custom Dataset requests require a timezone")
                                if isinstance(response, V2ProbeResponse):
                                    resolved = resolve_metric(component.candidate, response.descriptor)
                                    component.configure(
                                        apply_custom_probe_defaults(
                                            resolved,
                                            v2_metric_probe_descriptor(
                                                response.descriptor, resolved.metric_id
                                            ),
                                            timezone=options.host.timezone,
                                        ),
                                        data_affecting=False,
                                    )
                                elif isinstance(response, CustomProbeResponse):
                                    component.configure(
                                        apply_custom_probe_defaults(
                                            component.candidate,
                                            response.descriptor,
                                            timezone=options.host.timezone,
                                        ),
                                        data_affecting=False,
                                    )
                                else:
                                    raise TypeError("custom provider result does not contain a probe response")
                                current = component.candidate
                                probe_complete = True
                                lifecycle.complete(operation, generation=operation.generation)
                                record_warnings(response)
                                request(LifecycleTrigger.STARTUP, roll_range=False)
                            else:
                                accepted = component.apply_provider_result(
                                    outcome.result, purpose=purpose
                                )
                                if accepted:
                                    lifecycle.complete(operation, generation=operation.generation)
                                    record_warnings(outcome.result.custom_response)
                                    current = component.candidate
                                    record("ok", getattr(outcome.result, "diagnostics", "") or "ok")
                                    if (
                                        purpose == "primary"
                                        and component.start_comparison() is not None
                                    ):
                                        request(LifecycleTrigger.CONFIGURATION, roll_range=False)
                                else:
                                    lifecycle.abandon(operation)
                        elif active:
                            error = outcome.error or RuntimeError(
                                "custom command returned no result"
                            )
                            component.fail(
                                error,
                                generation=outcome.generation,
                                purpose="primary" if purpose == "probe" else purpose,
                            )
                            record("error", str(error))
                            lifecycle.abandon(operation)
                        else:
                            lifecycle.abandon(operation)
                    except BaseException as exc:
                        if active:
                            component.fail(exc, generation=operation.generation)
                            record("error", str(exc))
                        lifecycle.abandon(operation)
                    paint()
                    lifecycle.start_ready(now=time.monotonic(), start=start)
                key = read_key(0.05)
                if key == "\x03":
                    raise KeyboardInterrupt
                error_body = (
                    body_view == "chart" and component.error is not None and component.model is None
                )
                if error_body and key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                    updated_offset = next_text_offset(
                        key,
                        offset=error_offset,
                        line_count=error_line_count,
                        visible_rows=error_visible_rows,
                    )
                    assert updated_offset is not None
                    error_offset = updated_offset
                    paint(force=True)
                elif body_view != "chart" and key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                    offset = next_text_offset(
                        key,
                        offset=text_offsets.get(body_view, 0),
                        line_count=text_line_counts.get(body_view, 0),
                        visible_rows=text_visible_rows.get(body_view, 0),
                    )
                    assert offset is not None
                    text_offsets[body_view] = offset
                    paint(force=True)
                elif body_view == "chart" and key == "r":
                    request(LifecycleTrigger.MANUAL, replace_active=True)
                    paint(force=True)
                elif body_view == "chart" and key == "c":
                    controls_hidden = not controls_hidden
                    paint(force=True)
                elif body_view == "chart" and key == "h":
                    run_standalone_help(
                        screen,
                        translator,
                        color=current.presentation.theme != "no-color",
                        read_key=read_key,
                    )
                    paint(force=True)
                elif key in {"v", "V"}:
                    body_view = cycle_body_view(body_view, step=1 if key == "v" else -1)
                    paint(force=True)
                elif key in {"y", "Y"} and body_view != "chart":
                    value = (
                        format_command(replace(options, chart=current))
                        if body_view == "command"
                        else format_full_command(replace(options, chart=current))
                        if body_view == "full-command"
                        else render_custom_data(
                            component.model,
                            language=translator.language,
                            translator=translator,
                            view=body_view,
                        )
                        if component.model is not None
                        else translator.text("status.loading")
                    )
                    copied = copy_command(value)
                    copy_feedback.show(
                        translator.text(
                            "status.command_copied"
                            if copied and body_view in {"command", "full-command"}
                            else "status.data_copied"
                            if copied
                            else "status.command_copy_failed"
                        )
                    )
                    paint()
                elif key in {"m", "M"} and body_view == "chart":
                    picked = _run_custom_standalone_adjustment(
                        component, translator, screen, ascii=options.host.ascii
                    )
                    if picked is not None:
                        updated, data_affecting = picked
                        if updated != component.candidate:
                            component.configure(updated, data_affecting=data_affecting)
                            current = component.candidate
                            if data_affecting:
                                request(LifecycleTrigger.CONFIGURATION, roll_range=False)
                    paint(force=True)
                elif key == "L" and body_view == "chart":
                    lines = tuple(
                        f"{item.timestamp:%H:%M:%S} {item.status}: {item.detail}" for item in logs
                    ) or (translator.text("status.custom_logs_empty"),)
                    while True:
                        screen.paint(
                            compose_frame(
                                "\n".join(lines),
                                translator.text("status.custom_logs_title"),
                                translator.text("status.custom_logs_controls"),
                                height=get_terminal_size().lines,
                            )
                        )
                        if read_key(0.1) in {"\x1b", "\r", "\n"}:
                            break
                    paint(force=True)
    except KeyboardInterrupt:
        return 0
    finally:
        scheduler.shutdown()
        lifecycle.shutdown()
        summary.scheduler.shutdown()
        summary.lifecycle.shutdown()
        runtime.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        screen.finish()


def run_tui(options: DashboardLaunch, translator: Translator) -> int:
    runtime = build_query_runtime()
    panes = [
        _new_pane(
            options,
            pane_config,
            f"dashboard:pane:{index}"
            if isinstance(pane_config, (ChartPaneConfig, CustomChartPaneConfig))
            else None,
            runtime,
        )
        for index, pane_config in enumerate(options.panes)
    ]
    for index, pane in enumerate(panes):
        pane.pane_id = index
    next_pane_id = len(panes)
    header = _new_header(options, runtime)
    _reconcile_custom_dashboard_summaries(
        header, _custom_dashboard_sources(panes), now=time.monotonic()
    )
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ccusage-viz-tui")
    focused: int | None = None
    active_grid = options.host.grid
    active_layout = options.host.layout
    column_weights = options.host.column_weights
    row_weights = options.host.row_weights
    header_style = options.host.header_style
    dashboard_style = options.host.style
    dashboard_theme = options.host.theme
    divider_style, frame_style = _dashboard_structure(dashboard_style)
    grid_draft: str | None = None
    grid_error: str | None = None
    adjustment_mode: str | None = None
    adjustment_page = "quick"
    adjustment_timer: AdjustmentIdleTimer | None = None
    browse_controls_hidden = False
    body_view: DashboardBodyView = "chart"
    dashboard_text_offset = 0
    dashboard_text_line_count = 0
    dashboard_text_visible_rows = 0
    chooser_overlay: tuple[int, str] | None = None
    dataset_modal: DashboardDatasetModalState | None = None
    overlay_editor: OverlayEditorState | None = None
    overlay_history: OverlayHistoryState | None = None
    custom_logs_pane: int | None = None
    help_overlay: HelpOverlayState | None = None
    help_was_active = False
    last_click: tuple[int, float] | None = None
    copy_feedback = TransientFeedback()
    manual_refresh_operations: set[OperationToken] = set()
    displayed_custom_warnings: set[tuple[str, str]] = set()

    last_successful_update: datetime | None = None
    last_size: tuple[int, int] | None = None
    screen = FramePainter(sys.stdout)

    def set_screen_cursor_visible(visible: bool) -> None:
        stream = getattr(screen, "stream", None)
        if stream is not None:
            set_cursor_visible(stream, visible)

    def end_adjustment() -> None:
        nonlocal adjustment_mode, adjustment_timer, focused, grid_draft, grid_error, body_view
        adjustment_mode = None
        adjustment_timer = None
        focused = None
        grid_draft = None
        grid_error = None

    def open_help(
        *,
        context: str = "dashboard",
        action: str | None = None,
        selected: str | None = None,
        dataset_id: str | None = None,
        chart_kind: str | None = None,
    ) -> None:
        nonlocal help_overlay
        help_overlay = HelpOverlayState(
            AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS),
            adjustment_timer.remaining() if adjustment_timer is not None else None,
            context=context,
            action=action,
            selected=selected,
            dataset_id=dataset_id,
            chart_kind=chart_kind,
        )
        paint()

    def close_help() -> None:
        nonlocal adjustment_timer, help_overlay
        assert help_overlay is not None
        remaining = help_overlay.adjustment_remaining
        help_overlay = None
        if adjustment_mode is not None and remaining is not None:
            adjustment_timer = AdjustmentIdleTimer.from_remaining(remaining)

    def read_adjustment_event(decoder: InputDecoder) -> object:
        timeout = 0.1
        if help_overlay is not None:
            timeout = min(timeout, help_overlay.timer.remaining())
        deadline = animation_deadline()
        if deadline is not None:
            timeout = min(timeout, max(0.0, deadline - time.monotonic()))
        remaining = copy_feedback.remaining(now=time.monotonic())
        if remaining is not None:
            timeout = min(timeout, remaining)
        if help_overlay is not None:
            event = read_event(decoder, timeout)
            if isinstance(event, (KeyEvent, MouseEvent)) and not (
                isinstance(event, KeyEvent) and event.value == "\x03"
            ):
                help_overlay.timer.record_input()
            elif event is None:
                help_overlay.timer.check()
            return event
        if adjustment_timer is None:
            return read_event(decoder, timeout)
        event = read_event(decoder, min(timeout, adjustment_timer.remaining()))
        if isinstance(event, (KeyEvent, MouseEvent)):
            adjustment_timer.record_input()
        elif event is None:
            adjustment_timer.check()
        return event

    def raise_if_interrupt(event: object) -> object:
        """Route decoded Ctrl-C through the TUI's controlled cleanup path."""

        if isinstance(event, KeyEvent) and event.value == "\x03":
            raise KeyboardInterrupt
        return event

    def allocate_pane_id() -> int:
        nonlocal next_pane_id
        pane_id = next_pane_id
        next_pane_id += 1
        return pane_id

    def start_pane_submission(
        pane: TuiChartPane,
        operation: OperationToken,
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
                warmup_future = executor.submit(
                    _await_monitor_warmup,
                    component,
                    generation=component.generation,
                    trigger=operation.trigger,
                    steps=steps,
                    cancelled=cancelled,
                )
                return warmup_future, cancelled.set
            try:
                submission = component.submit(
                    query_trigger(operation.trigger),
                    sample_ordinal=pane.demo_ordinal + 1,
                )
            except BaseException as exc:
                component.fail(exc, generation=component.generation)
                raise
            monitor_future = executor.submit(_await_monitor_submission, submission)
            return monitor_future, submission.cancel
        purpose = (
            HistoricalPurpose.SUPPLEMENTAL
            if operation.trigger is LifecycleTrigger.CONFIGURATION
            and component.snapshot is not None
            and component.accepted_generation == component.generation
            and component.missing_comparison_coverage().intervals
            else HistoricalPurpose.PRIMARY
        )
        try:
            submission = component.submit(
                query_trigger(operation.trigger),
                coverage=(
                    component.snapshot.coverage
                    if purpose is HistoricalPurpose.SUPPLEMENTAL and component.snapshot is not None
                    else None
                ),
                purpose=purpose,
            )
        except BaseException as exc:
            component.fail(
                exc,
                generation=component.generation,
                purpose=purpose,
            )
            raise
        historical_future = executor.submit(_await_historical_submission, submission)
        return historical_future, submission.cancel

    def record_custom_log(pane: TuiCustomPane, status: str, detail: str) -> None:
        pane.logs.append(CustomLogRecord(datetime.now().astimezone(), status, detail))
        pane.logs[:] = pane.logs[-20:]

    def record_custom_warnings(source: CustomCommandSource, response: object) -> None:
        for warning in getattr(response, "warnings", ()):
            identity = (source.dataset_id, warning.code)
            if identity in displayed_custom_warnings:
                continue
            displayed_custom_warnings.add(identity)
            message = warning.message.zh_cn if translator.language == "zh" else warning.message.en
            for pane in (item for item in panes if isinstance(item, TuiCustomPane)):
                if pane.component.candidate.source.dataset_id == source.dataset_id:
                    record_custom_log(pane, "warning", message)

    def start_custom_submission(
        pane: TuiCustomPane, operation: OperationToken
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
            handle = runtime.submit(intent)
            return (
                executor.submit(_await_custom_submission, handle, operation.generation, "probe"),
                handle.cancel,
            )
        if custom_monitor:
            if options.host.timezone is None:
                raise RuntimeError("custom Dataset requests require a timezone")
            intent = custom_v2_monitor_query_intent(
                pane.component.candidate,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                end_at=datetime.now().astimezone(),
                process=pane.process,
            )
            handle = runtime.submit(intent)
            return (
                executor.submit(_await_custom_submission, handle, operation.generation, "primary"),
                handle.cancel,
            )
        purpose = "comparison" if pane.component.comparison_is_pending else "primary"
        config = (
            pane.component.comparison_request_config()
            if purpose == "comparison"
            else pane.component.candidate
        )
        if config is None:
            raise RuntimeError("custom comparison request is no longer required")
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        intent = custom_historical_query_intent(
            config,
            timezone=options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=pane.process,
            request_id_suffix=":comparison" if purpose == "comparison" else "",
        )
        handle = runtime.submit(intent)
        return (
            executor.submit(_await_custom_submission, handle, operation.generation, purpose),
            handle.cancel,
        )

    def start_builtin_pane_summary_submission(
        pane: TuiChartPane, operation: OperationToken
    ) -> tuple[Future[BuiltinSummaryOutcome], Callable[[], None]]:
        component = pane.component
        if not isinstance(component, HistoricalChartComponent):
            raise TypeError("monitor panes do not have built-in summary lifecycles")
        plan = builtin_summary_query_plan(
            component.candidate, today=local_today(timezone=options.host.timezone)
        )
        intent = builtin_summary_query_intent(
            component.candidate,
            runtime.definition(historical_provider_id(component.candidate)),
            plan,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
        )
        handle = runtime.submit(intent)
        return (
            executor.submit(
                _await_builtin_summary_submission,
                handle,
                operation.generation,
                plan,
                component.candidate.chart,
            ),
            handle.cancel,
        )

    def refresh_builtin_pane_summary(
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
                start=lambda operation: start_builtin_pane_summary_submission(pane, operation),
            )
        except BaseException as exc:
            pane.summary_error = exc
            return False

    def start_builtin_pane_summary(pane: TuiChartPane, *, now: float) -> bool:
        lifecycle = pane.summary_lifecycle
        if lifecycle is None:
            return False
        try:
            return lifecycle.start_ready(
                now=now,
                start=lambda operation: start_builtin_pane_summary_submission(pane, operation),
            )
        except BaseException as exc:
            pane.summary_error = exc
            return False

    def start_custom_pane_summary_submission(
        pane: TuiCustomPane, operation: OperationToken
    ) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        summary = pane.summary
        if summary is None:
            raise RuntimeError("custom Pane has no summary lifecycle")
        config = pane.component.candidate
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        plan = (
            range_summary_query_plan(config.date_range)
            if config.date_range.fixed_bounds
            else summary_query_plan(
                local_today(timezone=options.host.timezone),
                cast(SummaryScope, config.granularity),
            )
        )
        summary.select(config.source, config.filters)
        intent = custom_summary_query_intent(
            config.source,
            plan,
            filters=config.filters,
            timezone=options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=pane.process,
        )
        request = intent.payload
        if not isinstance(request, CustomSummaryRequest):
            raise TypeError("custom Pane summary intent has an unexpected payload")
        summary.requested_period = request.scope
        summary.requested_as_of_date = request.current.until
        handle = runtime.submit(intent)
        return (
            executor.submit(_await_custom_submission, handle, operation.generation),
            handle.cancel,
        )

    def refresh_custom_pane_summary(
        pane: TuiCustomPane,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
        summary_affecting: bool = False,
    ) -> bool:
        summary = pane.summary
        if summary is None:
            return False
        config = pane.component.candidate
        source_changed = summary.source != config.source or summary.filters != config.filters
        if source_changed:
            summary.invalidate()
        try:
            return summary.lifecycle.request(
                trigger,
                generation=summary.generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=lambda operation: start_custom_pane_summary_submission(pane, operation),
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def start_pane(index: int, *, now: float) -> bool:
        pane = panes[index]
        try:
            if isinstance(pane, TuiCustomPane):
                chart_started = pane.lifecycle.start_ready(
                    now=now,
                    start=lambda operation: start_custom_submission(pane, operation),
                )
                summary_started = (
                    refresh_custom_pane_summary(
                        pane, trigger=LifecycleTrigger.STARTUP, summary_affecting=True
                    )
                    if pane.probe_complete
                    else False
                )
                return chart_started or summary_started
            if isinstance(pane, TuiChartPane):
                chart_started = pane.lifecycle.start_ready(
                    now=now,
                    start=lambda operation: start_pane_submission(pane, operation),
                )
                return start_builtin_pane_summary(pane, now=now) or chart_started
        except BaseException as exc:
            if isinstance(pane, TuiCustomPane) and pane.component.fail(
                exc, generation=pane.component.generation
            ):
                record_custom_log(pane, "error", _custom_failure_log_detail(exc, translator))
            return False
        return False

    def pane_records(pane: TuiChartPane) -> tuple[UsageRecord, ...]:
        component = pane.component
        if isinstance(component, MonitorComponent):
            return component.accepted_records
        return component.snapshot.records if component.snapshot is not None else ()

    def start_new_pane(index: int) -> None:
        refresh(index, trigger=LifecycleTrigger.STARTUP)

    def pane_includes_projects(pane: TuiChartPane) -> bool:
        component = pane.component
        return (
            not isinstance(component, HistoricalChartComponent)
            or component.snapshot is None
            or component.snapshot.includes_project_attribution
        )

    def refresh(
        index: int,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
        data_affecting: bool = True,
        summary_affecting: bool = False,
    ) -> bool:
        pane = panes[index]
        if isinstance(pane, TuiCustomPane):
            if data_affecting:
                component = pane.component
                component.configure(
                    replace(
                        component.candidate,
                        date_range=refresh_date_range(
                            component.candidate.date_range, timezone=options.host.timezone
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
                    start=lambda operation: start_custom_submission(pane, operation),
                )
                should_refresh_summary = summary_affecting or trigger in {
                    LifecycleTrigger.PERIODIC,
                    LifecycleTrigger.MANUAL,
                }
                summary_requested = (
                    refresh_custom_pane_summary(
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
                    record_custom_log(pane, "error", _custom_failure_log_detail(exc, translator))
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
                        current.chart.date_range, timezone=options.host.timezone
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
                start=lambda operation: start_pane_submission(pane, operation),
            )
            summary_requested = refresh_builtin_pane_summary(
                pane,
                trigger=trigger,
                replace_active=replace_active,
                invalidate=data_affecting,
            )
            return chart_requested or summary_requested
        except BaseException:
            return False

    def start_custom_summary_submission(
        summary: CustomDashboardSummary, operation: OperationToken
    ) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        selections = {item.source.dataset_id: item for item in _custom_dashboard_sources(panes)}
        selection = selections.get(summary.source.dataset_id)
        if selection is None:
            raise RuntimeError("custom Dashboard source is no longer visible")
        summary.select(selection.source, ())
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        if selection.summary_mode == "none":
            raise RuntimeError("summary disabled for selected metric")
        plan = (
            range_summary_query_plan(selection.config.date_range)
            if selection.config is not None and selection.config.date_range.fixed_bounds
            else summary_query_plan(
                local_today(timezone=options.host.timezone),
                cast(SummaryScope, header.summary_period),
            )
        )
        if selection.summary_mode in {"total", "comparisons"} and selection.config is not None:
            if selection.summary_mode == "total":
                plan = SummaryQueryPlan("total", plan.current)
            intent = custom_v2_summary_query_intent(
                selection.config,
                plan,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=options.process,
            )
        else:
            intent = custom_summary_query_intent(
                summary.source,
                plan,
                filters=summary.filters,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=options.process,
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
        handle = runtime.submit(intent)
        return (
            executor.submit(_await_custom_submission, handle, operation.generation),
            handle.cancel,
        )

    def start_custom_summary(summary: CustomDashboardSummary, *, now: float) -> bool:
        try:
            return summary.lifecycle.start_ready(
                now=now,
                start=lambda operation: start_custom_summary_submission(summary, operation),
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def refresh_custom_summary(
        summary: CustomDashboardSummary,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
    ) -> bool:
        if header.summary_period == "none":
            return False
        try:
            return summary.lifecycle.request(
                trigger,
                generation=summary.generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=lambda operation: start_custom_summary_submission(summary, operation),
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def refresh_custom_summaries(
        *, trigger: LifecycleTrigger, replace_active: bool = False
    ) -> tuple[OperationToken, ...]:
        return tuple(
            summary.lifecycle.active
            for summary in header.custom_summaries.values()
            if refresh_custom_summary(summary, trigger=trigger, replace_active=replace_active)
            and summary.lifecycle.active is not None
        )

    def start_header_submission(
        operation: OperationToken,
    ) -> tuple[Future[UsageSnapshot], Callable[[], None]]:
        requested = _header_refresh_interval(
            header,
            aggressive=operation.trigger is LifecycleTrigger.MANUAL,
        )
        if requested is None:
            raise AssertionError("admitted header refresh must require data")
        submitted = replace(
            header.options,
            chart=replace(
                header.options.chart,
                date_range=DateRange(requested.since, requested.until),
            ),
        )
        intent = historical_query_intent(
            submitted,
            header.runtime.definition(historical_provider_id(submitted)),
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
        )
        started = time.monotonic()
        handle = header.runtime.submit(intent)
        header.options = submitted
        header.error = None
        return executor.submit(_await_historical, handle, started), handle.cancel

    def start_header(*, now: float) -> bool:
        if not header.token_enabled:
            return False
        try:
            return header.lifecycle.start_ready(now=now, start=start_header_submission)
        except BaseException as exc:
            header.error = str(exc)
            return False

    def refresh_header(
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
    ) -> bool:
        if not header.token_enabled:
            return False
        if (
            _header_refresh_interval(
                header,
                aggressive=trigger is LifecycleTrigger.MANUAL,
            )
            is None
        ):
            return False
        now = time.monotonic()
        try:
            return header.lifecycle.request(
                trigger,
                generation=header.generation,
                now=now,
                replace_active=replace_active,
                start=start_header_submission,
            )
        except BaseException as exc:
            header.error = str(exc)
            return False

    def collect() -> bool:
        nonlocal last_successful_update
        changed = False

        def retire_manual_refresh(operation: OperationToken) -> None:
            nonlocal changed
            if operation not in manual_refresh_operations:
                return
            manual_refresh_operations.remove(operation)
            if not manual_refresh_operations:
                changed = True

        active_operations = {
            lifecycle.active
            for lifecycle in (
                header.lifecycle,
                *(summary.lifecycle for summary in header.custom_summaries.values()),
                *(
                    lifecycle
                    for pane in panes
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
        if manual_refresh_operations - active_operations:
            manual_refresh_operations.intersection_update(active_operations)
            changed = True

        completed_header = header.lifecycle.take_completed(lambda future: future.done())
        if completed_header is not None:
            operation, future = completed_header
            observed_at = time.monotonic()
            try:
                result = future.result()
                if header.lifecycle.accepts(operation, generation=header.generation):
                    header.records = _replace_header_interval(header.records, result)
                    header.coverage = header.coverage.merge(result.coverage)
                    header.snapshot = result
                    header.accepted_at = datetime.now().astimezone()
                    last_successful_update = header.accepted_at
                    header.error = None
                    header.lifecycle.complete(operation, generation=header.generation)
                    changed = True
            except Exception as exc:
                if header.lifecycle.accepts(operation, generation=header.generation):
                    header.lifecycle.complete(operation, generation=header.generation)
                    header.error = str(exc)
                    changed = True
            retire_manual_refresh(operation)
            start_header(now=observed_at)
        for summary in header.custom_summaries.values():
            completed_custom_summary = summary.lifecycle.take_completed(
                lambda future: future.done()
            )
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
                        raise TypeError(
                            "custom provider result does not contain a summary response"
                        )
                    summary.response = response
                    record_custom_warnings(summary.source, response)
                    summary.error = None
                    summary.accepted_at = datetime.now().astimezone()
                    summary.accepted_period = summary.requested_period
                    summary.accepted_as_of_date = summary.requested_as_of_date
                    summary.lifecycle.complete(operation, generation=outcome.generation)
                    last_successful_update = summary.accepted_at
                    changed = True
            except Exception as exc:
                if summary.lifecycle.accepts(operation, generation=operation.generation):
                    summary.error = exc
                    summary.lifecycle.complete(operation, generation=operation.generation)
                    changed = True
            retire_manual_refresh(operation)
            start_custom_summary(summary, now=observed_at)
        for pane in (item for item in panes if isinstance(item, TuiCustomPane)):
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
                    record_custom_warnings(summary.source, response)
                    summary.error = None
                    summary.accepted_at = datetime.now().astimezone()
                    summary.accepted_period = summary.requested_period
                    summary.accepted_as_of_date = summary.requested_as_of_date
                    summary.lifecycle.complete(operation, generation=outcome.generation)
                    last_successful_update = summary.accepted_at
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
                        pane, operation
                    ),
                )
        for pane in (item for item in panes if isinstance(item, TuiChartPane)):
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
                    last_successful_update = pane.summary.accepted_at
                    changed = True
            except Exception as exc:
                if lifecycle.accepts(operation, generation=operation.generation):
                    pane.summary_error = exc
                    lifecycle.complete(operation, generation=operation.generation)
                    changed = True
            retire_manual_refresh(operation)
            start_builtin_pane_summary(pane, now=observed_at)
        for index, pane in enumerate(panes):
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
                        failed = (
                            pane.component.fail(outcome.error, generation=outcome.generation)
                            if isinstance(pane.component, CustomMonitorComponent)
                            else pane.component.fail(
                                outcome.error,
                                generation=outcome.generation,
                                purpose="primary"
                                if outcome.purpose == "probe"
                                else outcome.purpose,
                            )
                        )
                        if failed:
                            record_custom_log(
                                pane, "error", _custom_failure_log_detail(outcome.error, translator)
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
                            pane.component.configure(
                                resolve_metric(pane.component.candidate, response.descriptor),
                                data_affecting=False,
                            )
                            metric = next(
                                (
                                    item
                                    for item in response.descriptor.metrics
                                    if item.id == pane.component.candidate.metric_id
                                ),
                                None,
                            )
                            if metric is None or not isinstance(
                                metric.capabilities.charts.get("monitor"), V2MonitorCapability
                            ):
                                raise TypeError(
                                    "custom monitor metric is not supported by runtime probe"
                                )
                        elif isinstance(response, V2ProbeResponse):
                            resolved = resolve_metric(
                                pane.component.candidate, response.descriptor
                            )
                            pane.component.configure(
                                apply_custom_probe_defaults(
                                    resolved,
                                    v2_metric_probe_descriptor(
                                        response.descriptor, resolved.metric_id
                                    ),
                                    timezone=options.host.timezone or "UTC",
                                ),
                                data_affecting=False,
                            )
                        elif not isinstance(response, CustomProbeResponse):
                            raise TypeError(
                                "custom provider result does not contain a probe response"
                            )
                        if options.host.timezone is None:
                            raise RuntimeError("custom Dataset requests require a timezone")
                        if isinstance(pane.component, CustomHistoricalComponent) and isinstance(
                            response, CustomProbeResponse
                        ):
                            pane.component.configure(
                                apply_custom_probe_defaults(
                                    pane.component.candidate,
                                    response.descriptor,
                                    timezone=options.host.timezone,
                                ),
                                data_affecting=False,
                            )
                        pane.probe_complete = True
                        record_custom_warnings(pane.component.candidate.source, response)
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        refresh(
                            index,
                            trigger=LifecycleTrigger.STARTUP,
                            data_affecting=False,
                        )
                        changed = True
                    elif isinstance(pane.component, CustomMonitorComponent):
                        response = outcome.result.custom_response
                        if not isinstance(response, V2MonitorResponse):
                            raise TypeError("custom monitor query did not return a V2 observation")
                        if pane.component.accept(
                            CustomMonitorCompletion(
                                outcome.generation, pane.component.candidate, response
                            ),
                            accepted_at=datetime.now().astimezone(),
                        ):
                            record_custom_warnings(pane.component.candidate.source, response)
                            record_custom_log(
                                pane, "ok", translator.text("status.custom_query_succeeded")
                            )
                            pane.lifecycle.complete(operation, generation=outcome.generation)
                            last_successful_update = pane.component.accepted_at
                            changed = True
                        else:
                            pane.lifecycle.abandon(operation)
                    elif pane.component.apply_provider_result(
                        outcome.result, purpose=outcome.purpose
                    ):
                        record_custom_warnings(
                            pane.component.candidate.source, outcome.result.custom_response
                        )
                        record_custom_log(
                            pane,
                            "ok",
                            translator.text("status.custom_query_succeeded"),
                        )
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        last_successful_update = pane.component.accepted_at
                        changed = True
                        if (
                            outcome.purpose == "primary"
                            and pane.component.start_comparison() is not None
                        ):
                            refresh(
                                index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                            )
                    else:
                        pane.lifecycle.abandon(operation)
                except Exception as exc:
                    if pane.lifecycle.accepts(operation, generation=operation.generation):
                        pane.lifecycle.abandon(operation)
                        if pane.component.fail(
                            exc, generation=operation.generation, purpose="primary"
                        ):
                            record_custom_log(
                                pane, "error", _custom_failure_log_detail(exc, translator)
                            )
                            changed = True
                retire_manual_refresh(operation)
                start_pane(index, now=observed_at)
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
                            loaded.error,
                            generation=loaded.generation,
                            purpose=loaded.purpose,
                        )
                        if isinstance(
                            component,
                            HistoricalChartComponent,
                        )
                        and isinstance(loaded, HistoricalOutcome)
                        else component.fail(
                            loaded.error,
                            generation=loaded.generation,
                        )
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
                                raise TypeError(
                                    "monitor pane component has historical configuration"
                                )
                            steps = len(loaded.completions)
                            demo_now = observed_at
                            demo_wall = datetime.now().astimezone()
                            demo_seconds = chart.window_seconds / max(1, steps - 1)
                            accepted = all(
                                component.accept(
                                    completion,
                                    now=demo_now - (steps - ordinal) * demo_seconds,
                                    wall=demo_wall
                                    - timedelta(seconds=(steps - ordinal) * demo_seconds),
                                    detect_gap=False,
                                )
                                for ordinal, completion in enumerate(loaded.completions, start=1)
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
                                loaded.completion,
                                now=observed_at,
                                wall=datetime.now().astimezone(),
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
                                translator=translator,
                            )
                        pane.lifecycle.complete(operation, generation=loaded.generation)
                        last_successful_update = component.accepted_at
                        changed = True
                        if (
                            isinstance(component, HistoricalChartComponent)
                            and isinstance(loaded, HistoricalOutcome)
                            and loaded.purpose is HistoricalPurpose.PRIMARY
                            and component.missing_comparison_coverage().intervals
                        ):
                            refresh(
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
                        component.fail(
                            exc,
                            generation=operation.generation,
                            purpose=purpose,
                        )
                        if isinstance(component, HistoricalChartComponent)
                        else component.fail(exc, generation=operation.generation)
                    )
                    if failed:
                        changed = True
            retire_manual_refresh(operation)
            start_pane(index, now=observed_at)
        return changed

    def animation_deadline() -> float | None:
        deadlines = (
            deadline
            for pane in panes
            for deadline in (
                (pane.session.next_deadline, pane.overlay.next_due)
                if isinstance(pane, TuiAnimationPane) and pane.body_view == "chart"
                else (pane.attachment.next_deadline,)
                if isinstance(pane, TuiChartPane)
                and pane.body_view == "chart"
                and pane.attachment is not None
                else ()
            )
            if deadline is not None
        )
        return min(deadlines, default=None)

    def capture_dashboard_state() -> DashboardState:
        pane_states: list[DashboardPaneState] = []
        for pane in panes:
            if isinstance(pane, TuiEmptyPane):
                pane_states.append(DashboardPaneState(pane.pane_id, EmptyPaneConfig(), "chart"))
            elif isinstance(pane, TuiCustomPane):
                pane_states.append(
                    DashboardPaneState(
                        pane.pane_id,
                        CustomChartPaneConfig(pane.component.candidate),
                        pane.body_view,
                    )
                )
            elif isinstance(pane, TuiAnimationPane):
                pane_states.append(
                    DashboardPaneState(
                        pane.pane_id,
                        AnimationPaneConfig(pane.session.spec, pane.overlay.config),
                        pane.body_view,
                        animation_theme=pane.session.theme,
                    )
                )
            else:
                assert isinstance(pane, TuiChartPane)
                attachment = pane.attachment
                chart = _pane_display_options(pane).chart
                assert not isinstance(chart, CustomChartConfig)
                pane_states.append(
                    DashboardPaneState(
                        pane.pane_id,
                        ChartPaneConfig(chart),
                        pane.body_view,
                        attachment.spec.style if attachment is not None else None,
                        attachment.theme if attachment is not None else None,
                        pane.attachment_enabled,
                    )
                )
        return DashboardState(
            tuple(pane_states),
            active_grid,
            active_layout,
            column_weights,
            row_weights,
            dashboard_theme,
            dashboard_style,
            header_style,
            header.summary_period,
            body_view,
        )

    history = DashboardHistory(capture_dashboard_state())

    def apply_dashboard_state(state: DashboardState) -> None:
        """Reconcile declarative history without discarding unaffected live Panes."""
        nonlocal panes, active_grid, active_layout, column_weights, row_weights
        nonlocal dashboard_theme, dashboard_style, divider_style, frame_style, header_style
        nonlocal body_view, focused, adjustment_mode, adjustment_page, adjustment_timer
        from ccusage_viz.configuration import standalone_from_chart_pane

        existing = {pane.pane_id: pane for pane in panes}
        reconciled: list[TuiPane] = []
        refresh_indexes: list[tuple[int, bool, bool]] = []
        now = time.monotonic()

        for pane_state in state.panes:
            pane = existing.pop(pane_state.pane_id, None)
            config = pane_state.config
            compatible = (
                (isinstance(config, EmptyPaneConfig) and isinstance(pane, TuiEmptyPane))
                or (isinstance(config, AnimationPaneConfig) and isinstance(pane, TuiAnimationPane))
                or (isinstance(config, CustomChartPaneConfig) and isinstance(pane, TuiCustomPane))
                or (
                    isinstance(config, ChartPaneConfig)
                    and isinstance(pane, TuiChartPane)
                    and type(_pane_display_options(pane).chart) is type(config.chart)
                )
            )
            if not compatible:
                if pane is not None:
                    _shutdown_pane(pane)
                pane = _new_pane(
                    options,
                    config,
                    f"dashboard:pane:{pane_state.pane_id}"
                    if isinstance(config, (ChartPaneConfig, CustomChartPaneConfig))
                    else None,
                    runtime,
                )
                pane.pane_id = pane_state.pane_id
                if isinstance(pane, TuiCustomPane):
                    refresh_indexes.append((len(reconciled), True, True))
                elif isinstance(pane, TuiChartPane):
                    refresh_indexes.append((len(reconciled), True, False))
            if isinstance(pane, (TuiChartPane, TuiAnimationPane, TuiCustomPane)):
                pane.body_view = pane_state.body_view
            if isinstance(pane, TuiAnimationPane):
                assert isinstance(pane_state.config, AnimationPaneConfig)
                if pane.session.spec != pane_state.config.animation:
                    pane.session.set_style(pane_state.config.animation, now)
                if pane.overlay.config != pane_state.config.overlay:
                    pane.overlay.apply(pane_state.config.overlay, now=now)
                if pane_state.animation_theme is not None:
                    pane.session.set_theme(pane_state.animation_theme, now)
            elif isinstance(pane, TuiCustomPane):
                assert isinstance(pane_state.config, CustomChartPaneConfig)
                if pane.component.candidate != pane_state.config.chart:
                    current = pane.component.candidate
                    data_affecting = custom_replacement_required(current, pane_state.config.chart)
                    summary_affecting = custom_summary_replacement_required(
                        current, pane_state.config.chart
                    )
                    pane.component.configure(pane_state.config.chart, data_affecting=data_affecting)
                    if current.source != pane_state.config.chart.source:
                        pane.probe_complete = False
                    if data_affecting or summary_affecting:
                        refresh_indexes.append((len(reconciled), data_affecting, summary_affecting))
            elif isinstance(pane, TuiChartPane):
                assert isinstance(pane_state.config, ChartPaneConfig)
                component = pane.component
                candidate = standalone_from_chart_pane(options, pane_state.config)
                current = component.candidate
                if candidate != current:
                    data_affecting = (
                        historical_replacement_required(current, candidate)
                        if isinstance(component, HistoricalChartComponent)
                        else (
                            isinstance(current.chart, MonitorConfig)
                            and isinstance(candidate.chart, MonitorConfig)
                            and (
                                current.chart.by != candidate.chart.by
                                or current.chart.filters != candidate.chart.filters
                            )
                        )
                    )
                    _clear_changes(pane)
                    component.configure(candidate, data_affecting=data_affecting)
                    if candidate.host.interval != current.host.interval:
                        pane.scheduler.rebuild(candidate.host.interval, now=now)
                    if data_affecting:
                        refresh_indexes.append((len(reconciled), True, False))
                    elif (
                        isinstance(component, HistoricalChartComponent)
                        and component.missing_comparison_coverage().intervals
                    ):
                        refresh_indexes.append((len(reconciled), False, False))
                if pane.attachment is not None:
                    if pane_state.attachment_style is not None:
                        pane.attachment.set_style(
                            animation_spec(pane_state.attachment_style, target="monitor"), now
                        )
                    if pane_state.attachment_theme is not None:
                        pane.attachment.set_theme(pane_state.attachment_theme, now)
                    pane.attachment_enabled = pane_state.attachment_enabled
            reconciled.append(pane)

        for pane in existing.values():
            _shutdown_pane(pane)
        panes = reconciled
        active_grid = state.grid
        active_layout = state.layout
        column_weights = state.column_weights
        row_weights = state.row_weights
        theme_changed = dashboard_theme != state.theme
        dashboard_theme = state.theme
        dashboard_style = state.style
        divider_style, frame_style = _dashboard_structure(dashboard_style)
        header_style = state.header_style
        header_refresh_required = (
            header.summary_period != state.header_summary
            and _header_summary(header, state.header_summary) is None
        )
        header.summary_period = state.header_summary
        if theme_changed:
            _set_header_theme(header, dashboard_theme)
        body_view = state.body_view
        if focused is not None and focused >= len(panes):
            end_adjustment()
        for index, data_affecting, summary_affecting in refresh_indexes:
            refresh(
                index,
                trigger=LifecycleTrigger.CONFIGURATION,
                data_affecting=data_affecting,
                summary_affecting=summary_affecting,
            )
        if header_style != "hidden" and header_refresh_required:
            refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
        sync_custom_dashboard_summaries()

    def sync_custom_dashboard_summaries() -> None:
        token_enabled = any(isinstance(pane, TuiChartPane) for pane in panes)
        if header.token_enabled and not token_enabled:
            header.generation += 1
            header.lifecycle.detach_active()
        header.token_enabled = token_enabled
        added = _reconcile_custom_dashboard_summaries(
            header, _custom_dashboard_sources(panes), now=time.monotonic()
        )
        if header_style != "hidden":
            if token_enabled:
                refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
            for summary in added:
                refresh_custom_summary(summary, trigger=LifecycleTrigger.CONFIGURATION)

    def record_mutation(family: object, mutate: Callable[[], None]) -> bool:
        nonlocal history
        before = capture_dashboard_state()
        mutate()
        after = capture_dashboard_state()
        if after == before:
            return False
        sync_custom_dashboard_summaries()
        history = history.record(after, family=family, target=family, timestamp=time.monotonic())
        return True

    def full_dashboard_command() -> str:
        return format_full_dashboard_command(
            replace(options, host=replace(options.host, theme=dashboard_theme)),
            tuple(
                EmptyPaneConfig()
                if isinstance(pane, TuiEmptyPane)
                else CustomChartPaneConfig(pane.component.candidate)
                if isinstance(pane, TuiCustomPane)
                else _chart_pane_config(pane)
                if isinstance(pane, TuiChartPane)
                else AnimationPaneConfig(pane.session.spec, pane.overlay.config)
                for pane in panes
            ),
            grid=active_grid,
            layout=active_layout,
            column_weights=column_weights,
            row_weights=row_weights,
            header_style=header_style,
            header_summary=header.summary_period,
            dashboard_style=dashboard_style,
        )

    def global_operations(width: int) -> str:
        return controls_line(
            translator.text("status.tui_global_operations"),
            width=width,
            color=dashboard_theme != "no-color",
        )

    def help_lines(width: int) -> tuple[str, ...]:
        mode = (
            "pane"
            if adjustment_mode == "pane"
            else "global"
            if adjustment_mode == "global"
            else "browse"
        )
        page = "quick" if adjustment_page == "quick" else "advanced"
        scheme = get_color_scheme(dashboard_theme)
        branch, last, pipe = ("|- ", "\\- ", "|  ") if options.host.ascii else ("├─ ", "└─ ", "│  ")
        active_icon = "* " if options.host.ascii else "● "
        selected_page_icon = "[x] " if options.host.ascii else "● "
        unselected_page_icon = "[ ] " if options.host.ascii else "○ "

        def tree_rows(prefix: str, continuation: str, value: str) -> tuple[str, ...]:
            available = max(1, width - display_width(prefix))
            wrapped = wrap_width(value, available)
            return tuple(
                f"{prefix if row_index == 0 else continuation}{row}"
                for row_index, row in enumerate(wrapped)
            )

        def tree_node(
            prefix: str,
            value: str,
            children: tuple[tuple[str, object], ...],
            *,
            is_last: bool,
        ) -> tuple[str, ...]:
            connector = last if is_last else branch
            child_prefix = prefix + ("   " if is_last else pipe)
            rows = list(tree_rows(prefix + connector, child_prefix + "   ", value))
            for index, (child_value, child_children) in enumerate(children):
                rows.extend(
                    tree_node(
                        child_prefix,
                        child_value,
                        cast(tuple[tuple[str, object], ...], child_children),
                        is_last=index == len(children) - 1,
                    )
                )
            return tuple(rows)

        def mode_node(
            name: str, *, active: bool, enter: str, exit: str
        ) -> tuple[str, tuple[object, ...]]:
            return (
                f"{active_icon if active else ''}{translator.text(name)}",
                ((enter, ()), (exit, ())),
            )

        def mode_pages() -> tuple[tuple[str, tuple[object, ...]], ...]:
            active_page = translator.text(f"status.tui_help_page_{page}")
            other_page = translator.text(
                f"status.tui_help_page_{'advanced' if page == 'quick' else 'quick'}"
            )
            return (
                (
                    translator.text(
                        "status.tui_help_mode_pages",
                        active=selected_page_icon.rstrip(),
                        page=active_page,
                        other=unselected_page_icon.rstrip(),
                        other_page=other_page,
                    ),
                    (),
                ),
                (translator.text("status.tui_help_mode_pages_detail"), ()),
            )

        def help_heading(value: str) -> str:
            return emphasize(
                value,
                color=scheme.highlight,
                enabled=dashboard_theme != "no-color",
            )

        if help_overlay is not None and help_overlay.context != "dashboard":
            if help_overlay.context == "chooser":
                assert help_overlay.action is not None
                assert help_overlay.selected is not None
                sections = (
                    (
                        "status.tui_help_section_selecting",
                        (
                            translator.text(f"status.tui_{help_overlay.action}_title"),
                            translator.text("status.tui_help_chooser_detail"),
                        ),
                    ),
                    (
                        "status.tui_help_section_options",
                        tuple(
                            translator.text(
                                "status.tui_help_labeled_option",
                                option=(
                                    f"{'*' if options.host.ascii else '●'} "
                                    f"{translator.text(f'label.pane_{item}')}"
                                    if item == help_overlay.selected
                                    else translator.text(f"label.pane_{item}")
                                ),
                                detail=translator.text(f"status.tui_help_chooser_option_{item}"),
                            )
                            for item in _PANE_COMMANDS
                        ),
                    ),
                )
                rows: list[str] = []
                for heading, values in sections:
                    if rows:
                        rows.append("")
                    rows.append(help_heading(translator.text(heading)))
                    for index, value in enumerate(values):
                        rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
                return tuple(clip_width(line, width) for line in rows)
            elif help_overlay.context == "dataset-chooser":
                assert dataset_modal is not None
                modal = dataset_modal
                if modal.stage == "source" and modal.statuses:
                    status = modal.statuses[modal.index]
                    descriptor = status.registration.probe.descriptor
                    sections = (
                        (
                            "status.tui_help_section_selecting",
                            (translator.text("status.tui_help_dataset_chooser"),),
                        ),
                        (
                            "status.tui_help_section_options",
                            (translator.text("status.tui_help_dataset_chooser_manage"),),
                        ),
                        (
                            "status.tui_help_section_selected",
                            (
                                translator.text(
                                    "status.tui_help_dataset_chooser_selected",
                                    name=_dataset_title(descriptor.dataset.title, translator),
                                    version=descriptor.version,
                                ),
                                (
                                    descriptor.dataset.description.zh_cn
                                    if translator.language == "zh"
                                    else descriptor.dataset.description.en
                                ),
                            ),
                        ),
                    )
                else:
                    assert modal.chart_kinds
                    chart_kind = modal.chart_kinds[modal.index]
                    sections = (
                        (
                            "status.tui_help_section_selecting",
                            (translator.text("status.tui_help_dataset_chart_chooser"),),
                        ),
                        (
                            "status.tui_help_section_options",
                            tuple(
                                translator.text(
                                    "status.tui_help_labeled_option",
                                    option=(
                                        f"{'*' if options.host.ascii else '●'} "
                                        f"{translator.text(f'label.pane_{item}')}"
                                        if item == chart_kind
                                        else translator.text(f"label.pane_{item}")
                                    ),
                                    detail=translator.text(
                                        f"status.tui_help_chooser_option_{item}"
                                    ),
                                )
                                for item in modal.chart_kinds
                            ),
                        ),
                    )
                rows = []
                for heading, values in sections:
                    if rows:
                        rows.append("")
                    rows.append(help_heading(translator.text(heading)))
                    for index, value in enumerate(values):
                        rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
                rows.append("")
                rows.append(help_heading(translator.text("status.tui_help_section_policy")))
                policy = (
                    translator.text("status.tui_help_dataset_policy"),
                    translator.text("status.tui_help_idle_close"),
                )
                for index, value in enumerate(policy):
                    rows.extend(tree_node("", value, (), is_last=index == len(policy) - 1))
                return tuple(clip_width(line, width) for line in rows)
            elif help_overlay.context == "catalog-browser":
                sections = (
                    (
                        "status.tui_help_section_selecting",
                        (translator.text("status.tui_help_catalog_browser"),),
                    ),
                    (
                        "status.tui_help_section_options",
                        (translator.text("status.tui_help_catalog_columns"),),
                    ),
                    (
                        "status.tui_help_section_selected",
                        (translator.text("status.tui_help_catalog_selected"),),
                    ),
                )
                rows = []
                for heading, values in sections:
                    if rows:
                        rows.append("")
                    rows.append(help_heading(translator.text(heading)))
                    for index, value in enumerate(values):
                        rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
                rows.append("")
                rows.append(help_heading(translator.text("status.tui_help_section_policy")))
                rows.extend(
                    tree_node("", translator.text("status.tui_help_idle_close"), (), is_last=True)
                )
                return tuple(clip_width(line, width) for line in rows)
            elif help_overlay.context == "editor":
                rows = [help_heading(translator.text("status.tui_help_section_controls"))]
                groups = editor_help_groups(dashboard=True)
                for index, group in enumerate(groups):
                    rows.extend(
                        tree_node(
                            "",
                            translator.text(group.heading_key),
                            tuple((translator.text(item_key), ()) for item_key in group.item_keys),
                            is_last=index == len(groups) - 1,
                        )
                    )
                return tuple(clip_width(line, width) for line in rows)
            else:
                context_nodes = (
                    (
                        translator.text("status.tui_help_history_overlay"),
                        ((translator.text("status.tui_help_history_overlay_detail"), ()),),
                    ),
                )
            rows = [help_heading(translator.text("status.tui_help_section_controls"))]
            for value, children in context_nodes:
                rows.extend(tree_node("", value, children, is_last=False))
            policy_children = [
                (
                    translator.text(
                        "status.tui_help_tip_ascii" if options.host.ascii else "status.tui_help_tip"
                    ),
                    (),
                )
            ]
            if help_overlay.context in {"editor", "history"}:
                policy_children.append((translator.text("status.tui_help_animation_hint"), ()))
            policy_children.append((translator.text("status.tui_help_idle_close"), ()))
            rows.append("")
            rows.append(help_heading(translator.text("status.tui_help_section_policy")))
            for index, (value, children) in enumerate(policy_children):
                rows.extend(
                    tree_node("", value, children, is_last=index == len(policy_children) - 1)
                )
            return tuple(clip_width(line, width) for line in rows)

        text_navigation: tuple[tuple[str, tuple[object, ...]], ...] = ()
        if mode == "browse" and body_view != "chart":
            text_children: list[tuple[str, tuple[object, ...]]] = []
            if text_viewport_overflows(
                line_count=dashboard_text_line_count,
                visible_rows=dashboard_text_visible_rows,
            ):
                text_children.append((translator.text("status.tui_help_text_scroll"), ()))
            text_children.append((translator.text("status.tui_help_text_copy"), ()))
            text_navigation = (
                (translator.text("status.tui_help_text_navigation"), tuple(text_children)),
            )
        elif mode == "pane" and focused is not None:
            focused_pane = panes[focused]
            if (
                isinstance(focused_pane, (TuiChartPane, TuiCustomPane))
                and focused_pane.body_view != "chart"
            ):
                text_children = [(translator.text("status.tui_help_content_view"), ())]
                if text_viewport_overflows(
                    line_count=focused_pane.text_line_counts.get(focused_pane.body_view, 0),
                    visible_rows=focused_pane.text_visible_rows.get(focused_pane.body_view, 0),
                ):
                    text_children.append((translator.text("status.tui_help_text_scroll"), ()))
                if body_view_copy_kind(focused_pane.body_view) is not None:
                    text_children.append((translator.text("status.tui_help_text_copy"), ()))
                text_navigation = (
                    (translator.text("status.tui_help_text_navigation"), tuple(text_children)),
                )

        common_children = [
            (translator.text("status.tui_help_history"), ()),
            (translator.text("status.tui_help_help"), ()),
        ]
        structure_children = [
            (translator.text("status.tui_help_content_view"), ()),
            (translator.text("status.tui_help_content_replace"), ()),
            (translator.text("status.tui_help_content_insert"), ()),
            (translator.text("status.tui_help_structure_move"), ()),
            (translator.text("status.tui_help_structure_select"), ()),
            (translator.text("status.tui_help_structure_width"), ()),
            (translator.text("status.tui_help_structure_height"), ()),
        ]
        if mode == "browse":
            browse_children = [
                (translator.text("status.tui_help_browse_view"), ()),
                (translator.text("status.tui_help_browse_pane"), ()),
                (translator.text("status.tui_help_browse_dashboard"), ()),
            ]
            if body_view == "chart":
                browse_children[:0] = [
                    (translator.text("status.tui_help_browse_refresh"), ()),
                    (translator.text("status.tui_help_controls"), ()),
                    (
                        translator.text("status.tui_help_intervals_dashboard"),
                        (
                            (translator.text("status.tui_help_interval_historical"), ()),
                            (translator.text("status.tui_help_interval_monitor_dashboard"), ()),
                            (translator.text("status.tui_help_interval_header"), ()),
                        ),
                    ),
                ]
            control_nodes = (
                (translator.text("status.tui_help_browse"), tuple(browse_children)),
                (translator.text("status.tui_help_common"), tuple(common_children)),
                *text_navigation,
            )
        elif mode == "pane":
            assert focused is not None
            focused_pane = panes[focused]
            if len(panes) > 1:
                structure_children.insert(
                    3, (translator.text("status.tui_help_content_delete"), ())
                )
            parameter_children: list[tuple[str, tuple[object, ...]]] = []
            if isinstance(focused_pane, TuiChartPane) and focused_pane.body_view == "chart":
                chart = _pane_display_options(focused_pane).chart
                parameter_children.extend(
                    (_pane_help_action_text(page_name, action, translator), ())
                    for page_name, action in _pane_help_settings_actions(
                        chart.kind,
                        translator,
                        chart=chart,
                        attachment_available=(
                            isinstance(chart, MonitorConfig)
                            and chart.presentation.style in {"ranking", "list"}
                            and focused_pane.attachment is not None
                        ),
                    )
                )
                if isinstance(chart, MonitorConfig):
                    parameter_children.append(
                        (translator.text("status.tui_help_interval_monitor"), ())
                    )
            elif isinstance(focused_pane, TuiAnimationPane):
                parameter_children.extend(
                    (
                        (translator.text("status.tui_help_animation_position"), ()),
                        (translator.text("status.tui_help_animation_theme"), ()),
                        (translator.text("status.tui_help_animation_style"), ()),
                        (translator.text("status.tui_help_animation_move"), ()),
                        (translator.text("status.tui_help_animation_reset"), ()),
                        (translator.text("status.tui_help_animation_edit"), ()),
                        (translator.text("status.tui_help_animation_interval"), ()),
                        (
                            translator.text("status.tui_help_animation_history"),
                            ((translator.text("status.tui_help_history_overlay_detail"), ()),),
                        ),
                        (translator.text("status.tui_help_animation_schedule"), ()),
                    )
                )
                structure_children.pop(0)
            control_nodes = (
                (translator.text("status.tui_help_mode"), mode_pages()),
                (translator.text("status.tui_help_pane_settings"), tuple(parameter_children)),
                (translator.text("status.tui_help_pane_structure"), tuple(structure_children)),
                (translator.text("status.tui_help_common"), tuple(common_children)),
                *text_navigation,
            )
        else:
            control_nodes = (
                (translator.text("status.tui_help_mode"), ()),
                (
                    translator.text("status.tui_help_dashboard_settings"),
                    (
                        (translator.text("status.tui_help_dashboard_theme"), ()),
                        (translator.text("status.tui_help_dashboard_style"), ()),
                        (translator.text("status.tui_help_dashboard_header"), ()),
                        (translator.text("status.tui_help_dashboard_summary"), ()),
                        (
                            translator.text("status.tui_help_dashboard_layout"),
                            ((translator.text("status.tui_help_layout_chooser"), ()),),
                        ),
                        (
                            translator.text("status.tui_help_dashboard_grid"),
                            ((translator.text("status.tui_help_grid_editor"), ()),),
                        ),
                    ),
                ),
                (translator.text("status.tui_help_common"), tuple(common_children)),
            )
        mode_nodes = (
            mode_node(
                "status.tui_help_browse_label",
                active=mode == "browse",
                enter=translator.text("status.tui_help_browse_enter"),
                exit=translator.text("status.tui_help_browse_exit"),
            ),
            mode_node(
                "status.tui_help_pane_label",
                active=mode == "pane",
                enter=translator.text("status.tui_help_pane_enter"),
                exit=translator.text("status.tui_help_pane_exit"),
            ),
            mode_node(
                "status.tui_help_global_label",
                active=mode == "global",
                enter=translator.text("status.tui_help_global_enter"),
                exit=translator.text("status.tui_help_global_exit"),
            ),
        )
        sections = (
            ("status.tui_help_section_modes", mode_nodes),
            ("status.tui_help_section_controls", control_nodes),
        )
        rows: list[str] = []
        for heading, nodes in sections:
            if rows:
                rows.append("")
            rows.append(help_heading(translator.text(heading)))
            for index, (value, children) in enumerate(nodes):
                rows.extend(
                    tree_node(
                        "",
                        value,
                        cast(tuple[tuple[str, object], ...], children),
                        is_last=index == len(nodes) - 1,
                    )
                )
        policy_children = [
            (
                translator.text(
                    "status.tui_help_tip_ascii" if options.host.ascii else "status.tui_help_tip"
                ),
                (),
            )
        ]
        if mode == "browse":
            policy_children.extend(
                (
                    (translator.text("status.tui_help_browse_hint"), ()),
                    (translator.text("status.tui_help_schedule_coalesce"), ()),
                )
            )
        elif (
            mode == "pane" and focused is not None and isinstance(panes[focused], TuiAnimationPane)
        ):
            policy_children.append((translator.text("status.tui_help_animation_hint"), ()))
        focused_pane = panes[focused] if focused is not None else None
        if (
            mode == "pane"
            and isinstance(focused_pane, TuiChartPane)
            and focused_pane.body_view == "chart"
            and not isinstance(_pane_display_options(focused_pane).chart, MonitorConfig)
        ):
            policy_children.extend(
                (
                    (
                        translator.text("status.tui_help_summary_scope"),
                        (
                            (translator.text("status.tui_help_summary_scope_fixed"), ()),
                            (translator.text("status.tui_help_summary_scope_filters"), ()),
                        ),
                    ),
                    (
                        translator.text("status.tui_help_summary_comparisons"),
                        (
                            (translator.text("status.tui_help_summary_comparisons_day"), ()),
                            (
                                translator.text(
                                    "status.tui_help_summary_comparisons_month_quarter"
                                ),
                                (),
                            ),
                            (translator.text("status.tui_help_summary_comparisons_year"), ()),
                        ),
                    ),
                )
            )
        policy_children.append((translator.text("status.tui_help_idle_close"), ()))
        rows.append("")
        rows.append(help_heading(translator.text("status.tui_help_section_policy")))
        for index, (value, children) in enumerate(policy_children):
            rows.extend(tree_node("", value, children, is_last=index == len(policy_children) - 1))
        return tuple(clip_width(line, width) for line in rows)

    def help_panel(size_columns: int, size_lines: int) -> tuple[str, ...]:
        content_width = max(1, min(size_columns - 4, 100))
        lines = help_lines(content_width)
        context = RenderContext(
            content_width,
            1,
            translator,
            color=dashboard_theme != "no-color",
            ascii=options.host.ascii,
            color_scheme=dashboard_theme,
        )
        scheme = get_color_scheme(dashboard_theme)
        editor_help = help_overlay is not None and help_overlay.context == "editor"
        title = clip_width(
            styled_text(
                translator.text(
                    "status.tui_help_editor_title" if editor_help else "status.tui_help_title"
                ),
                scheme.highlight,
                context,
                bold=True,
            ),
            content_width,
        )
        footer = clip_width(
            styled_text(
                translator.text(
                    "status.tui_help_editor_close" if editor_help else "status.tui_help_close"
                ),
                scheme.other,
                context,
                dim=True,
            ),
            content_width,
        )
        panel_width = max(
            1,
            min(
                size_columns, max(*(display_width(line) for line in (*lines, title, footer)), 1) + 4
            ),
        )
        body_rows = max(1, size_lines - 5)
        max_offset = max(0, len(lines) - body_rows)
        offset = min(help_overlay.scroll_offset if help_overlay is not None else 0, max_offset)
        visible = lines[offset : offset + body_rows]
        border = "-" * max(0, panel_width - 2)
        inner_width = max(0, panel_width - 4)
        rows = ["+" + border + "+", "| " + pad_width(title, inner_width) + " |"]
        rows.extend("| " + pad_width(line, inner_width) + " |" for line in visible)
        rows.append("|" + "-" * max(0, panel_width - 2) + "|")
        rows.append("| " + pad_width(footer, inner_width) + " |")
        rows.append("+" + border + "+")
        return tuple(rows)

    def help_panel_bounds(size_columns: int, size_lines: int) -> tuple[int, int, int, int]:
        panel = help_panel(size_columns, size_lines)
        width = max((display_width(line) for line in panel), default=1)
        height = len(panel)
        return (
            (size_columns - width) // 2 + 1,
            max(1, (size_lines - height) // 2 + 1),
            width,
            height,
        )

    def help_frame(size_columns: int, size_lines: int) -> Frame:
        panel = help_panel(size_columns, size_lines)
        x, y, panel_width, _ = help_panel_bounds(size_columns, size_lines)
        rows = ["" for _ in range(size_lines)]
        for offset, row in enumerate(panel):
            row_index = y - 1 + offset
            if 0 <= row_index < len(rows):
                rows[row_index] = " " * max(0, x - 1) + pad_width(row, panel_width)
        return Frame(tuple(rows))

    def process_help_event(event: object) -> None:
        assert help_overlay is not None
        if isinstance(event, KeyEvent) and event.value in {"h", "\x08", "\x1b", "\r", "\n"}:
            close_help()
        elif isinstance(event, KeyEvent) and event.value in {"\x1b[A", "\x1b[B"}:
            delta = -1 if event.value == "\x1b[A" else 1
            max_offset = max(
                0,
                len(help_lines(get_terminal_size().columns)) - get_terminal_size().lines + 5,
            )
            help_overlay.scroll_offset = min(max(0, help_overlay.scroll_offset + delta), max_offset)
        elif isinstance(event, MouseEvent) and event.pressed:
            size = get_terminal_size()
            x, y, width, height = help_panel_bounds(size.columns, size.lines)
            if not (x <= event.x < x + width and y <= event.y < y + height):
                close_help()
        paint()

    def controls() -> tuple[str, ...]:
        width = get_terminal_size().columns
        if help_overlay is not None:
            return ()
        if grid_draft is not None:
            rows = [
                clip_width(translator.text("status.tui_layout_prompt", value=grid_draft), width)
            ]
            if grid_error is not None:
                rows.append(clip_width(grid_error, width))
            rows.append(clip_width(translator.text("status.tui_layout_controls"), width))
            return tuple(rows)
        if adjustment_mode == "pane" and focused is not None:
            pane = panes[focused]
            if isinstance(pane, TuiAnimationPane):
                return (
                    *_animation_adjustment_footer(
                        pane,
                        adjustment_page,
                        translator,
                        width,
                        color=dashboard_theme != "no-color",
                    ),
                    global_operations(width),
                )
            if isinstance(pane, TuiEmptyPane):
                return (
                    *_empty_pane_adjustment_footer(
                        translator,
                        width,
                        color=dashboard_theme != "no-color",
                    ),
                    global_operations(width),
                )
            if isinstance(pane, TuiCustomPane):
                if pane.body_view != "chart":
                    return (
                        *_text_view_footer(
                            pane.body_view,
                            translator,
                            width,
                            line_count=pane.text_line_counts.get(pane.body_view, 0),
                            visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                        ),
                        global_operations(width),
                    )
                return (
                    *_custom_adjustment_footer(
                        pane,
                        adjustment_page,
                        translator,
                        width,
                        color=dashboard_theme != "no-color",
                    ),
                    global_operations(width),
                )
            if pane.body_view != "chart":
                return (
                    *_text_view_footer(
                        pane.body_view,
                        translator,
                        width,
                        line_count=pane.text_line_counts.get(pane.body_view, 0),
                        visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                    ),
                    global_operations(width),
                )
            state = grid_error or _pane_adjustment_state(pane, adjustment_page, translator)
            return (
                *_adjustment_footer(
                    state,
                    _pane_display_options(pane).chart.kind,
                    adjustment_page,
                    pane.body_view,
                    translator,
                    width,
                    chart=_pane_display_options(pane).chart,
                    attachment_available=(
                        adjustment_page == "advanced"
                        and isinstance(_pane_display_options(pane).chart, MonitorConfig)
                        and _pane_display_options(pane).chart.presentation.style
                        in {"ranking", "list"}
                        and pane.attachment is not None
                    ),
                    color=dashboard_theme != "no-color",
                ),
                global_operations(width),
            )
        if adjustment_mode == "global":
            state = translator.text(
                "status.tui_current_state",
                runtime=translator.text("status.tui_running"),
                settings=f"{active_layout or active_grid} · {dashboard_theme} · {dashboard_style} · "
                f"{header_style} · {header.summary_period}",
            )
            return (
                *_global_adjustment_footer(
                    state=grid_error or state,
                    translator=translator,
                    width=width,
                ),
                global_operations(width),
            )
        if body_view != "chart":
            return (
                *_text_view_footer(
                    body_view,
                    translator,
                    width,
                    line_count=dashboard_text_line_count,
                    visible_rows=dashboard_text_visible_rows,
                ),
                global_operations(width),
            )
        if browse_controls_hidden:
            return ()
        context = grid_error or translator.text(
            f"status.tui_{body_view.replace('-', '_')}_controls",
            action=translator.text("status.hide_controls"),
        )
        return (clip_width(context, width), global_operations(width))

    def notices() -> tuple[str, ...]:
        feedback = feedback_lines(
            copy_feedback,
            width=get_terminal_size().columns,
            color=dashboard_theme != "no-color",
            now=time.monotonic(),
        )
        manual = (translator.text("status.tui_refreshing"),) if manual_refresh_operations else ()
        return (*manual, *feedback)

    def grid_geometry(
        size_columns: int,
        size_lines: int,
        header_rows: int,
        status_rows: int,
    ) -> ResolvedPaneLayout:
        grid_height = max(
            3, size_lines - len(controls()) - len(notices()) - header_rows - status_rows
        )
        bands = layout_bands(active_layout or active_grid, len(panes))
        resolved_column_weights = reconcile_weights(column_weights, bands.columns)
        resolved_row_weights = reconcile_weights(row_weights, bands.rows)
        return resolve_pane_layout(
            layout=active_layout or active_grid,
            pane_count=len(panes),
            width=size_columns,
            height=grid_height,
            divider_style=divider_style,
            column_weights=resolved_column_weights,
            row_weights=resolved_row_weights,
        )

    def adjust_pane_weight(pane_index: int, *, axis: str, delta: int) -> bool:
        """Adjust one Dashboard layout band and retain it in undo history."""

        nonlocal column_weights, row_weights
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        slot = layout.topology.slot(pane_index)
        if axis == "column":

            def adjust_column() -> None:
                nonlocal column_weights
                column_weights = adjust_weight(
                    reconcile_weights(column_weights, layout.topology.columns), slot.column, delta
                )

            return record_mutation(("layout", "column-weight", slot.column), adjust_column)

        def adjust_row() -> None:
            nonlocal row_weights
            row_weights = adjust_weight(
                reconcile_weights(row_weights, layout.topology.rows), slot.row, delta
            )

        return record_mutation(("layout", "row-weight", slot.row), adjust_row)

    def handle_pane_mouse(event: MouseEvent) -> bool:
        """Handle pane focus clicks before pane-local modal input consumes them."""

        nonlocal adjustment_mode, adjustment_page, adjustment_timer, focused, last_click
        nonlocal overlay_editor, overlay_history, custom_logs_pane
        if (
            body_view != "chart"
            or not event.pressed
            or event.button != 0
            or event.modifiers & 0b1100000
        ):
            return False
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        grid_x = event.x - 1
        grid_y = event.y - header_rows - 1
        selected = layout_pane_at(layout, grid_x, grid_y)
        now = time.monotonic()
        double_click = (
            selected is not None
            and last_click is not None
            and last_click[0] == selected
            and now - last_click[1] <= _DOUBLE_CLICK_SECONDS
        )
        last_click = (selected, now) if selected is not None else None
        if adjustment_mode == "pane":
            if selected != focused and double_click and selected is not None:
                overlay_editor = None
                overlay_history = None
                custom_logs_pane = None
                focused = selected
                adjustment_page = "quick"
                adjustment_timer = AdjustmentIdleTimer()
            # Keep the first press inert: terminating adjustment here would
            # prevent a normal second press from completing the double-click.
            return True
        if adjustment_mode in {None, "global"} and double_click and selected is not None:
            focused = selected
            adjustment_mode = "pane"
            adjustment_page = "quick"
            adjustment_timer = AdjustmentIdleTimer()
        return True

    def pane_terminal(index: int) -> Terminal:
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        rect = layout.pane(index)
        framed = frame_style != "none" or index == focused
        pane = panes[index]
        if isinstance(pane, TuiAnimationPane):
            return Terminal(
                max(1, rect.width - 2 if framed else rect.width),
                max(1, rect.height - 2 if framed else rect.height),
                pane.session.theme != "no-color",
                options.host.ascii,
            )
        if isinstance(pane, TuiCustomPane):
            return Terminal(
                max(1, rect.width - 2 if framed else rect.width),
                max(1, rect.height - 2 if framed else rect.height),
                pane.component.candidate.presentation.theme != "no-color",
                options.host.ascii,
            )
        if isinstance(pane, TuiEmptyPane):
            return Terminal(
                max(1, rect.width - 2 if framed else rect.width),
                max(1, rect.height - 2 if framed else rect.height),
                dashboard_theme != "no-color",
                options.host.ascii,
            )
        pane_options = _pane_display_options(pane)
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            pane_options.chart.presentation.theme != "no-color",
            pane_options.host.ascii,
        )

    def paint(*, force: bool = False) -> None:
        nonlocal help_was_active, last_size, dashboard_text_offset, dashboard_text_line_count
        nonlocal dashboard_text_visible_rows, chooser_overlay
        if dataset_modal is None:
            chooser_overlay = None
        else:
            _paint_dataset_modal()
        size = get_terminal_size()
        atomic = (
            help_overlay is not None
            or help_was_active
            or any(isinstance(pane, TuiAnimationPane) for pane in panes)
        )
        if help_overlay is not None:
            last_size = (size.columns, size.lines)
            screen.paint(help_frame(size.columns, size.lines), force=force, atomic=atomic)
            help_was_active = True
            return
        last_size = (size.columns, size.lines)
        header_terminal = Terminal(
            size.columns, 4, dashboard_theme != "no-color", options.host.ascii
        )
        header_lines = _header_lines(
            header, header_style, translator, header_terminal, last_successful_update
        )
        status = None
        if body_view != "chart":
            control_rows = controls()
            notice_rows = notices()
            viewport = render_text_viewport(
                format_full_command_display(full_dashboard_command(), size.columns),
                offset=dashboard_text_offset,
                visible_rows=size.lines - len(control_rows) - len(notice_rows),
            )
            dashboard_text_offset = viewport.offset
            dashboard_text_line_count = viewport.line_count
            dashboard_text_visible_rows = viewport.visible_rows
            screen.paint(
                compose_frame(
                    viewport.body,
                    status,
                    control_rows,
                    notice_rows,
                    height=size.lines,
                ),
                force=force,
                atomic=atomic,
            )
            help_was_active = False
            return

        def render_panes(
            layout: ResolvedPaneLayout,
        ) -> tuple[list[str], tuple[DashboardOverlayPlacement, ...]]:
            rendered_panes: list[str] = []
            overlays: list[DashboardOverlayPlacement] = []
            for index, pane in enumerate(panes):
                rect = layout.pane(index)
                cell_width = rect.width
                cell_height = rect.height
                # The active frame-less pane gets a selection ring, so reserve its
                # interior too; its content is never overwritten by the indicator.
                framed = frame_style != "none" or index == focused
                interior_width = max(1, cell_width - 2 if framed else cell_width)
                interior_height = max(1, cell_height - 2 if framed else cell_height)
                if isinstance(pane, TuiAnimationPane):
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        pane.session.theme != "no-color",
                        options.host.ascii,
                    )
                    color_scheme = pane.session.theme
                elif isinstance(pane, TuiCustomPane):
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        pane.component.candidate.presentation.theme != "no-color",
                        options.host.ascii,
                    )
                    color_scheme = pane.component.candidate.presentation.theme
                elif isinstance(pane, TuiEmptyPane):
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        dashboard_theme != "no-color",
                        options.host.ascii,
                    )
                    color_scheme = dashboard_theme
                else:
                    pane_options = _pane_display_options(pane)
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        pane_options.chart.presentation.theme != "no-color",
                        pane_options.host.ascii,
                    )
                    color_scheme = pane_options.chart.presentation.theme
                if chooser_overlay is not None and chooser_overlay[0] == index:
                    rendered_panes.append(chooser_overlay[1])
                    continue
                if overlay_editor is not None and overlay_editor.pane_index == index:
                    editor_controls = _overlay_editor_controls(
                        translator, width=interior_width, color=terminal.color, dashboard=True
                    )
                    rendered_panes.append(
                        "\n".join(
                            compose_frame(
                                _editor_viewport(
                                    overlay_editor.draft,
                                    overlay_editor.cursor,
                                    interior_width,
                                    cursor_visible=int(time.monotonic() * 2) % 2 == 0,
                                )[0],
                                copy_feedback.message
                                or translator.text(
                                    "status.overlay_editor_mode_title",
                                    mode=translator.text(
                                        f"status.overlay_editor_mode_{overlay_editor.mode}"
                                    ),
                                ),
                                editor_controls,
                                height=interior_height,
                            ).rows
                        )
                    )
                    continue
                if custom_logs_pane == index:
                    assert isinstance(pane, TuiCustomPane)
                    rows = tuple(
                        f"{translator.text(f'status.custom_log_{record.status}')} "
                        f"{record.timestamp:%H:%M:%S}: {record.detail}"
                        for record in pane.logs
                    ) or (translator.text("status.custom_logs_empty"),)
                    rendered_panes.append(
                        "\n".join(
                            compose_frame(
                                "\n".join(rows),
                                translator.text("status.custom_logs_title"),
                                (translator.text("status.custom_logs_controls"),),
                                height=interior_height,
                            ).rows
                        )
                    )
                    continue
                if overlay_history is not None and overlay_history.pane_index == index:
                    assert isinstance(pane, TuiAnimationPane)
                    history_table = render_history_table(
                        tuple(pane.overlay.history),
                        overlay_history.table,
                        available_width=interior_width,
                        available_height=interior_height - 1,
                        empty=translator.text("status.overlay_history_empty"),
                    )
                    history_controls = controls_line(
                        translator.text("status.overlay_history_dashboard_controls"),
                        width=interior_width,
                        color=terminal.color,
                    )
                    rendered_panes.append(
                        "\n".join(
                            compose_frame(
                                history_table.body,
                                None,
                                (history_controls,),
                                height=interior_height,
                            ).rows
                        )
                    )
                    continue
                if isinstance(pane, TuiAnimationPane):
                    try:
                        rendered = _pane_render(
                            pane, translator, terminal, defer_animation_overlay=True
                        )
                    except TypeError as error:
                        if "defer_animation_overlay" not in str(error):
                            raise
                        rendered = _pane_render(pane, translator, terminal)
                elif isinstance(pane, TuiCustomPane):
                    rendered = _pane_render(pane, translator, terminal, dashboard=options)
                else:
                    rendered = _pane_render(pane, translator, terminal)
                if isinstance(pane, TuiAnimationPane):
                    origin_x = rect.left + (1 if framed else 0)
                    origin_y = rect.top + (1 if framed else 0)
                    overlays.extend(
                        DashboardOverlayPlacement(
                            index,
                            OverlayPlacement(
                                origin_y + placement.row,
                                origin_x + placement.column,
                                placement.text,
                            ),
                        )
                        for placement in pane.overlay.unbounded_placements(
                            width=terminal.width, height=terminal.height
                        )
                    )
                local_notices = format_notice_lines(
                    rendered.notices,
                    width=interior_width,
                    color=terminal.color,
                    ascii=terminal.ascii,
                    translator=translator,
                    color_scheme=color_scheme,
                )
                chart = (
                    _append_monitor_attachment(
                        pane,
                        rendered.chart,
                        terminal=terminal,
                        reserved_rows=len(local_notices),
                        now=time.monotonic(),
                        translator=translator,
                    )
                    if isinstance(pane, TuiChartPane) and pane.body_view == "chart"
                    else rendered.chart
                )
                text_pane = (
                    pane
                    if isinstance(pane, (TuiChartPane, TuiAnimationPane, TuiCustomPane))
                    else None
                )
                error_body = isinstance(text_pane, TuiCustomPane) and rendered.error_body
                scrollable = text_pane is not None and (
                    text_pane.body_view != "chart" or error_body
                )
                pane_content = _local_pane_content(
                    chart,
                    local_notices,
                    width=interior_width,
                    height=interior_height,
                    offset=(
                        text_pane.error_offset
                        if error_body
                        else text_pane.text_offsets.get(text_pane.body_view, 0)
                    )
                    if text_pane is not None
                    else 0,
                    scrollable=scrollable,
                    return_metadata=True,
                )
                assert isinstance(pane_content, tuple)
                content, offset, line_count, visible_rows = pane_content
                if text_pane is not None and scrollable:
                    if error_body:
                        text_pane.error_offset = offset
                        text_pane.error_line_count = line_count
                        text_pane.error_visible_rows = visible_rows
                    else:
                        text_pane.text_offsets[text_pane.body_view] = offset
                        text_pane.text_line_counts[text_pane.body_view] = line_count
                        text_pane.text_visible_rows[text_pane.body_view] = visible_rows
                rendered_panes.append(content)
            return rendered_panes, tuple(overlays)

        layout = grid_geometry(size.columns, size.lines, len(header_lines), int(status is not None))
        pane_renders, dashboard_overlays = render_panes(layout)
        grid = _compose_resolved_panes(
            pane_renders,
            layout,
            focused=focused if focused is not None else -1,
            ascii=options.host.ascii,
            divider_style=divider_style,
            frame_style=frame_style,
            shell_context=RenderContext(
                size.columns,
                layout.height,
                translator,
                color=dashboard_theme != "no-color",
                ascii=options.host.ascii,
                color_scheme=dashboard_theme,
            ),
        )
        grid = _compose_dashboard_overlays(
            grid,
            layout,
            dashboard_overlays,
            focused=focused if focused is not None else -1,
        )
        body = "\n".join((*header_lines, grid))
        screen.paint(
            compose_frame(body, status, controls(), notices(), height=size.lines),
            force=force,
            atomic=atomic,
        )
        help_was_active = False

    def show_chooser_help(action: str, selected: str) -> None:
        open_help(context="chooser", action=action, selected=selected)
        while help_overlay is not None:
            try:
                event = raise_if_interrupt(read_adjustment_event(decoder))
            except AdjustmentTimeout:
                close_help()
                return
            process_help_event(event)

    def choose_pane_type_blocking(
        action: str, pane_index: int, *, initial: CustomChartConfig | None = None
    ) -> CustomChartPaneConfig | str | None:
        nonlocal chooser_overlay

        def chooser_height() -> int:
            size = get_terminal_size()
            header_rows = len(
                _header_lines(
                    header,
                    header_style,
                    translator,
                    Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                    last_successful_update,
                )
            )
            layout = grid_geometry(size.columns, size.lines, header_rows, 0)
            cell_height = layout.pane(pane_index).height
            framed = frame_style != "none" or pane_index == focused
            return max(1, cell_height - 2 if framed else cell_height)

        def paint_choices(
            choices: str,
            title: str,
            chooser_controls: str,
            chooser_notices: tuple[str, ...],
        ) -> None:
            nonlocal chooser_overlay
            size = get_terminal_size()
            header_rows = len(
                _header_lines(
                    header,
                    header_style,
                    translator,
                    Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                    last_successful_update,
                )
            )
            layout = grid_geometry(size.columns, size.lines, header_rows, 0)
            cell_height = layout.pane(pane_index).height
            framed = frame_style != "none" or pane_index == focused
            interior_height = max(1, cell_height - 2 if framed else cell_height)
            formatted_notices = format_notice_lines(
                chooser_notices,
                width=size.columns,
                color=dashboard_theme != "no-color",
                ascii=options.host.ascii,
                translator=translator,
                color_scheme=dashboard_theme,
            )
            chooser_frame = compose_frame(
                choices,
                title,
                chooser_controls,
                formatted_notices,
                height=interior_height,
            )
            chooser_overlay = (pane_index, "\n".join(chooser_frame.rows))
            paint()

        try:
            choice = _choose_pane_type(
                screen,
                translator,
                decoder,
                height=chooser_height(),
                action=action,
                paint_choices=paint_choices,
                read_input=lambda: raise_if_interrupt(read_adjustment_event(decoder)),
                on_help=lambda selected: show_chooser_help(action, selected),
            )
            if choice != "datasets":
                return choice
            return _choose_dataset_pane_config(
                screen,
                translator,
                decoder,
                height=chooser_height(),
                dashboard=options,
                initial=initial,
                paint_choices=paint_choices,
                read_input=lambda: raise_if_interrupt(read_adjustment_event(decoder)),
            )
        finally:
            chooser_overlay = None

    def open_dataset_modal(
        action: str, pane_index: int, *, initial: CustomChartConfig | None = None
    ) -> None:
        """Start a Dataset chooser without taking ownership of the event loop."""

        nonlocal dataset_modal
        from ccusage_viz.datasets.service import DatasetService

        service = DatasetService()
        try:
            statuses = tuple(service.ready_registered_sources())
            error = None
        except UsageError as exc:
            statuses = ()
            error = format_error(exc, translator)
        draft = CustomPaneDraft(
            kind=initial.kind if initial is not None else "timeline",
            dataset_id=initial.source.dataset_id if initial is not None else "",
            command=shlex.join(initial.source.command_argv) if initial is not None else "",
        )
        dataset_modal = DashboardDatasetModalState(
            action, pane_index, initial, statuses, service, draft=draft, error=error
        )

    def _dataset_modal_height(pane_index: int) -> int:
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        cell_height = layout.pane(pane_index).height
        framed = frame_style != "none" or pane_index == focused
        return max(1, cell_height - 2 if framed else cell_height)

    def _paint_dataset_modal() -> None:
        """Render the active Dataset state in its target pane."""

        nonlocal chooser_overlay
        assert dataset_modal is not None
        modal = dataset_modal
        height = _dataset_modal_height(modal.pane_index)
        notices = () if modal.error is None else (modal.error,)
        if modal.stage == "pane":
            rows = [
                f"{'›' if item == _PANE_COMMANDS[modal.index] else ' '} "
                f"{translator.text(f'label.pane_{item}')}"
                for item in _PANE_COMMANDS
            ]
            body, modal.offset = _chooser_viewport(
                rows, index=modal.index, offset=modal.offset, height=height
            )
            title = translator.text(f"status.tui_{modal.action}_title")
            controls = translator.text(f"status.tui_{modal.action}_controls")
        elif modal.stage == "source":
            entries = modal.statuses
            modal.index %= len(entries)
            rows = []
            for item_index, status in enumerate(entries):
                selected = "›" if item_index == modal.index else " "
                descriptor = status.registration.probe.descriptor
                rows.append(
                    f"{selected} {_dataset_title(descriptor.dataset.title, translator)} "
                    f"{descriptor.version} · {translator.text('status.dataset_ready')}"
                )
            body, modal.offset = _chooser_viewport(
                rows,
                index=modal.index,
                offset=modal.offset,
                height=height,
                reserved_rows=2 + len(notices),
            )
            title = translator.text("status.dataset_chooser_title")
            controls = translator.text("status.dataset_chooser_controls")
        elif modal.stage == "browse":
            if modal.future is not None:
                body = ""
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
                notices = (translator.text("status.dataset_catalog_loading"),)
            elif not modal.entries:
                body = ""
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
                notices = (translator.text("status.datasets_official_empty"),)
            else:
                body, modal.offset = _official_catalog_viewport(
                    modal.entries,
                    translator,
                    index=modal.index,
                    offset=modal.offset,
                    width=get_terminal_size().columns,
                    height=height,
                )
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
        elif modal.stage == "browse_loading":
            body = ""
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_loading_controls")
            notices = (translator.text("status.dataset_browse_loading"),)
        elif modal.stage == "github":
            body = modal.draft.command or "—"
            title = translator.text("status.dataset_github_title")
            if modal.future is not None:
                controls = translator.text("status.dataset_github_loading_controls")
                notices = (translator.text("status.dataset_github_resolving"),)
            elif modal.artifact is not None:
                body = "\n".join(
                    (
                        modal.draft.command,
                        "",
                        f"{modal.artifact.release_tag} · {modal.artifact.asset_name}",
                        modal.artifact.sha256,
                        translator.text(
                            "status.dataset_github_confirm",
                            repository=modal.artifact.repository,
                        ),
                    )
                )
                controls = translator.text("status.dataset_github_confirm_controls")
            else:
                controls = translator.text("status.dataset_github_controls")
        elif modal.stage == "github_installing":
            body = modal.draft.command
            title = translator.text("status.dataset_github_title")
            controls = translator.text("status.dataset_github_loading_controls")
            notices = (translator.text("status.dataset_github_installing"),)
        elif modal.stage == "browse_confirm":
            assert modal.official_preview is not None
            body = "\n".join(_official_preview_rows(modal.official_preview, translator))
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_confirm_controls")
        elif modal.stage == "installing":
            body = modal.selected_dataset_id or ""
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_confirm_controls")
            notices = (
                translator.text(
                    "status.dataset_browse_installing", dataset_id=modal.selected_dataset_id
                ),
            )
        elif modal.stage == "installed":
            rows = [
                f"{'›' if item_index == modal.index else ' '} {translator.text(f'label.pane_{kind}')}"
                for item_index, kind in enumerate(modal.chart_kinds)
            ]
            body, modal.offset = _chooser_viewport(
                rows, index=modal.index, offset=modal.offset, height=height
            )
            title = translator.text("status.dataset_chooser_title")
            controls = translator.text("status.dataset_chooser_controls")
        elif modal.stage == "metric":
            rows = [
                f"{'›' if item_index == modal.index else ' '} {_dataset_title(metric.title, translator)}"
                for item_index, metric in enumerate(modal.metrics)
            ]
            body, modal.offset = _chooser_viewport(
                rows, index=modal.index, offset=modal.offset, height=height
            )
            title = translator.text("status.dataset_chooser_title")
            controls = translator.text("status.dataset_chooser_controls")
        else:
            fields = (
                translator.text("label.custom_kind"),
                translator.text("label.custom_dataset"),
                translator.text("label.custom_command"),
            )
            values = (modal.draft.kind, modal.draft.dataset_id, modal.draft.command)
            body = "\n".join(
                f"{'›' if index == modal.draft.field else ' '} {label}: {value or '—'}"
                for index, (label, value) in enumerate(zip(fields, values, strict=True))
            )
            title = translator.text("status.custom_pane_title")
            controls = translator.text("status.custom_pane_controls")
        size = get_terminal_size()
        formatted_notices = format_notice_lines(
            notices,
            width=size.columns,
            color=dashboard_theme != "no-color",
            ascii=options.host.ascii,
            translator=translator,
            color_scheme=dashboard_theme,
        )
        chooser_overlay = (
            modal.pane_index,
            "\n".join(compose_frame(body, title, controls, formatted_notices, height=height).rows),
        )

    def finish_dataset_modal(choice: CustomChartPaneConfig | str | None) -> None:
        """Apply one completed modal choice through the normal history transaction."""

        nonlocal active_grid, focused, dataset_modal, chooser_overlay
        assert dataset_modal is not None
        modal = dataset_modal
        dataset_modal = None
        chooser_overlay = None
        if choice is None:
            return
        if modal.action == "replace":
            record_mutation(
                ("pane", modal.pane_index, "replace"),
                lambda choice=choice, index=modal.pane_index: _replace_pane(
                    panes, index, create_pane(choice), start=start_new_pane
                ),
            )
            return
        insert_at = modal.pane_index if modal.action == "insert_before" else modal.pane_index + 1

        def insert(
            choice: CustomChartPaneConfig | str = choice, insert_at: int = insert_at
        ) -> None:
            nonlocal active_grid, focused
            active_grid = _grid_for_pane_count(active_grid, len(panes) + 1)
            _insert_pane(panes, insert_at, create_pane(choice), start=start_new_pane)
            focused = insert_at

        record_mutation(("pane", modal.pane_index, modal.action), insert)

    def collect_dataset_modal() -> bool:
        """Consume a completed Dataset catalog request without blocking the Dashboard."""

        assert dataset_modal is not None
        modal = dataset_modal
        if modal.future is None or not modal.future.done():
            return False
        if modal.stage == "browse":
            try:
                modal.entries = tuple(modal.future.result())
                modal.error = None
            except UsageError as exc:
                modal.error = format_error(exc, translator)
            except Exception:
                modal.error = translator.text("status.dataset_catalog_unavailable")
            modal.future = None
            return True
        if modal.stage == "installing":
            try:
                modal.future.result()
                modal.statuses = tuple(modal.service.status())
                modal.draft.dataset_id = modal.selected_dataset_id or ""
                modal.stage, modal.index, modal.offset = "installed", 0, 0
                modal.error = None
            except UsageError as exc:
                modal.stage = "browse_confirm"
                modal.error = format_error(exc, translator)
            except Exception:
                modal.stage = "browse_confirm"
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        if modal.stage == "browse_loading":
            try:
                modal.official_preview = cast(tuple[object, bytes, object], modal.future.result())
                modal.stage = "browse_confirm"
                modal.error = None
            except UsageError as exc:
                modal.stage = "browse"
                modal.error = format_error(exc, translator)
            except Exception:
                modal.stage = "browse"
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        if modal.stage == "github":
            try:
                modal.artifact = modal.future.result()
                modal.error = None
            except UsageError as exc:
                modal.error = format_error(exc, translator)
            except Exception:
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        if modal.stage == "github_installing":
            try:
                status = modal.future.result()
                installed = status.installed
                if installed is None:
                    raise UsageError("error.dataset_corrupt")
                modal.draft.dataset_id = installed.dataset_id
                modal.statuses = tuple(modal.service.status())
                modal.stage, modal.index, modal.offset = "installed", 0, 0
                modal.error = None
            except UsageError as exc:
                modal.stage = "github"
                modal.error = format_error(exc, translator)
            except Exception:
                modal.stage = "github"
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        return False

    def handle_dataset_modal(event: object) -> None:
        """Apply one event to the active Dataset modal without blocking Dashboard work."""

        nonlocal dataset_modal
        assert dataset_modal is not None
        modal = dataset_modal
        if not isinstance(event, (KeyEvent, PasteEvent)):
            return
        if isinstance(event, PasteEvent):
            if modal.stage == "local" and modal.draft.field in {1, 2}:
                if modal.draft.field == 1:
                    modal.draft.dataset_id += event.value
                else:
                    modal.draft.command += event.value
            return
        key = event.value
        if key == "\x03":
            raise KeyboardInterrupt
        if modal.stage == "pane":
            if key == "h":
                open_help(
                    context="chooser",
                    action=modal.action,
                    selected=_PANE_COMMANDS[modal.index],
                )
                return
            if key == "\x1b":
                finish_dataset_modal(None)
            elif key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(_PANE_COMMANDS)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(_PANE_COMMANDS)
            elif key in {"\r", "\n"}:
                choice = _PANE_COMMANDS[modal.index]
                if choice == "datasets":
                    modal.stage, modal.index, modal.offset = "source", 0, 0
                else:
                    finish_dataset_modal(choice)
            return
        if modal.stage == "source":
            entries = modal.statuses
            if key == "h" and entries:
                open_help(
                    context="dataset-chooser",
                    dataset_id=entries[modal.index].registration.dataset_id,
                )
                return
            if key == "\x1b":
                modal.stage, modal.index, modal.offset = "pane", 0, 0
            elif key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(entries)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(entries)
            elif key in {"\r", "\n"}:
                status = entries[modal.index]
                modal.draft.dataset_id = status.registration.dataset_id
                descriptor = status.registration.probe.descriptor
                if isinstance(descriptor, V2ProbeDescriptor):
                    modal.metrics = descriptor.metrics
                    modal.index = next(
                        (
                            position
                            for position, metric in enumerate(descriptor.metrics)
                            if metric.id == descriptor.default_metric_id
                        ),
                        0,
                    )
                    modal.offset = 0
                    modal.stage = "metric"
                else:
                    modal.chart_kinds = tuple(descriptor.capabilities.charts)
                if modal.chart_kinds:
                    modal.stage, modal.index, modal.offset = "installed", 0, 0
            return
        if modal.stage == "metric":
            if key == "\x1b":
                modal.stage, modal.index, modal.offset = "source", 0, 0
            elif key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(modal.metrics)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(modal.metrics)
            elif key in {"\r", "\n"}:
                metric = modal.metrics[modal.index]
                modal.metric_id = metric.id
                modal.metric_summary = metric.summary
                modal.metric_titles = (metric.title.en, metric.title.zh_cn)
                ranking = metric.capabilities.charts.get("ranking")
                modal.metric_periods = (
                    ranking.periods
                    if isinstance(ranking, V2HistoricalChartCapability)
                    else ()
                )
                modal.chart_kinds = tuple(metric.capabilities.charts)
                if modal.chart_kinds:
                    modal.stage, modal.index, modal.offset = "installed", 0, 0
            return
        if modal.stage == "github":
            if key == "\x1b":
                if modal.future is not None:
                    return
                if modal.artifact is not None:
                    modal.artifact = None
                    modal.error = None
                else:
                    modal.stage, modal.index, modal.offset = "source", 0, 0
            elif modal.future is not None:
                return
            elif modal.artifact is not None:
                if key in {"\r", "\n"}:
                    modal.stage = "github_installing"
                    modal.future = executor.submit(
                        cast(
                            Callable[[object], object],
                            modal.service.install_resolved_github_artifact,
                        ),
                        modal.artifact,
                    )
            elif key in {"\r", "\n"}:
                if modal.draft.command.strip():
                    modal.future = executor.submit(
                        cast(Callable[[str], object], modal.service.resolve_github_repository),
                        modal.draft.command,
                    )
                    modal.error = None
            elif key in {"\x7f", "\b"}:
                modal.draft.command = modal.draft.command[:-1]
                modal.error = None
            elif len(key) == 1 and key.isprintable():
                modal.draft.command += key
                modal.error = None
            return
        if modal.stage == "github_installing":
            return
        if modal.stage == "browse":
            if key == "h" and modal.future is None and modal.entries:
                open_help(context="catalog-browser")
            elif key == "\x1b":
                if modal.future is not None:
                    modal.future.cancel()
                modal.future = None
                modal.stage, modal.index, modal.offset = "source", 0, 0
            elif modal.future is None and modal.entries:
                if key in {"j", "\x1b[B"}:
                    modal.index = (modal.index + 1) % len(modal.entries)
                elif key in {"k", "\x1b[A"}:
                    modal.index = (modal.index - 1) % len(modal.entries)
                elif key in {"\r", "\n"}:
                    selected = modal.entries[modal.index]
                    host_os, host_arch = cast(tuple[str, str], modal.service.platform)
                    if not any(
                        artifact.os == host_os and artifact.arch == host_arch
                        for artifact in selected.artifacts
                    ):
                        modal.error = translator.text(
                            "status.dataset_catalog_unavailable_platform",
                            platform=f"{host_os}/{host_arch}",
                        )
                    else:
                        modal.selected_dataset_id = selected.id
                        modal.stage = "browse_loading"
                        modal.future = executor.submit(
                            cast(Callable[[str], object], modal.service.prepare_official_install),
                            selected.id,
                        )
            return
        if modal.stage == "browse_loading":
            return
        if modal.stage == "browse_confirm":
            if key == "\x1b":
                modal.stage = "browse"
                modal.error = None
            elif key in {"\r", "\n"}:
                assert modal.selected_dataset_id is not None
                assert modal.official_preview is not None
                modal.stage = "installing"
                modal.future = executor.submit(
                    cast(Callable[[object, bytes], object], modal.service.install_artifact),
                    modal.official_preview[0],
                    modal.official_preview[1],
                )
            return
        if modal.stage == "installing":
            return
        if modal.stage == "installed":
            if key == "h":
                open_help(
                    context="dataset-chooser",
                    dataset_id=modal.draft.dataset_id,
                    chart_kind=modal.chart_kinds[modal.index],
                )
                return
            if key == "\x1b":
                modal.stage, modal.index, modal.offset = "source", 0, 0
            elif key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(modal.chart_kinds)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(modal.chart_kinds)
            elif key in {"\r", "\n"}:
                try:
                    source = modal.service.registered_command_source(modal.draft.dataset_id)
                except UsageError as exc:
                    modal.error = format_error(exc, translator)
                else:
                    finish_dataset_modal(
                        default_custom_pane(
                            modal.chart_kinds[modal.index],
                            source=source,
                            dashboard=options,
                            metric_id=modal.metric_id,
                            metric_summary=modal.metric_summary,
                            metric_periods=modal.metric_periods,
                            metric_titles=modal.metric_titles,
                        )
                    )
            return
        if key == "\x1b":
            modal.stage, modal.index, modal.offset = "source", 0, 0
        elif key in {"\t", "\x1b[B"}:
            modal.draft.field = (modal.draft.field + 1) % 3
        elif key == "\x1b[A":
            modal.draft.field = (modal.draft.field - 1) % 3
        elif modal.draft.field == 0 and key in {"j", "\x1b[C"}:
            kinds = _CUSTOM_PANE_KINDS
            modal.draft.kind = kinds[(kinds.index(modal.draft.kind) + 1) % len(kinds)]
        elif modal.draft.field == 0 and key in {"k", "\x1b[D"}:
            kinds = _CUSTOM_PANE_KINDS
            modal.draft.kind = kinds[(kinds.index(modal.draft.kind) - 1) % len(kinds)]
        elif key == "\x19":
            value = (modal.draft.kind, modal.draft.dataset_id, modal.draft.command)[
                modal.draft.field
            ]
            modal.error = translator.text(
                "status.command_copied" if copy_command(value) else "status.command_copy_failed"
            )
        elif key == "\x15":
            if modal.draft.field == 0:
                modal.error = translator.text("status.custom_pane_kind_required")
            elif modal.draft.field == 1:
                modal.draft.dataset_id = ""
                modal.error = translator.text("status.custom_pane_field_cleared")
            else:
                modal.draft.command = ""
                modal.error = translator.text("status.custom_pane_field_cleared")
        elif key in {"\r", "\n"}:
            try:
                source = CustomCommandSource(
                    modal.draft.dataset_id.strip(), tuple(shlex.split(modal.draft.command))
                )
                finish_dataset_modal(
                    default_custom_pane(modal.draft.kind, source=source, dashboard=options)
                )
            except ValueError as exc:
                modal.error = str(exc)
        elif modal.draft.field in {1, 2}:
            value = modal.draft.dataset_id if modal.draft.field == 1 else modal.draft.command
            if key in {"\x7f", "\b"}:
                value = value[:-1]
            elif len(key) == 1 and key.isprintable():
                value += key
            else:
                return
            if modal.draft.field == 1:
                modal.draft.dataset_id = value
            else:
                modal.draft.command = value

    def create_pane(command: PaneConfig | str, *, pane_id: int | None = None) -> TuiPane:
        pane_id = allocate_pane_id() if pane_id is None else pane_id
        if isinstance(command, CustomChartPaneConfig):
            pane = _new_pane(options, command, f"dashboard:pane:{pane_id}", runtime)
        elif command == "empty":
            pane = _new_pane(options, EmptyPaneConfig())
        elif command == "animate":
            pane = _new_pane(options, AnimationPaneConfig(default_animation_spec("pane")))
        else:
            assert isinstance(command, str)
            pane = _new_pane(
                _new_pane_options(command, options),
                f"dashboard:pane:{pane_id}",
                runtime,
            )
        pane.pane_id = pane_id
        return pane

    try:
        set_screen_cursor_visible(False)
        with tui_input_mode() as decoder:
            for index in range(len(panes)):
                refresh(index, trigger=LifecycleTrigger.STARTUP)
            if header_style != "hidden":
                refresh_header(trigger=LifecycleTrigger.STARTUP)
                refresh_custom_summaries(trigger=LifecycleTrigger.STARTUP)
            paint()
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                changed = collect()
                if dataset_modal is not None:
                    changed = collect_dataset_modal() or changed
                now = time.monotonic()
                if header_style != "hidden" and header.scheduler.due(now=now):
                    refresh_header(trigger=LifecycleTrigger.PERIODIC)
                    refresh_custom_summaries(trigger=LifecycleTrigger.PERIODIC)
                for index, pane in enumerate(panes):
                    if isinstance(pane, (TuiChartPane, TuiCustomPane)) and pane.scheduler.due(
                        now=now
                    ):
                        refresh(index, trigger=LifecycleTrigger.PERIODIC)
                deadline = animation_deadline()
                feedback_expired = (
                    copy_feedback.message is not None and now >= copy_feedback.expires_at
                )
                cursor_tick = overlay_editor is not None and int(now * 2) != int((now - 0.1) * 2)
                if (
                    changed
                    or feedback_expired
                    or cursor_tick
                    or (deadline is not None and now >= deadline)
                ):
                    paint()
                try:
                    event = raise_if_interrupt(read_adjustment_event(decoder))
                except AdjustmentTimeout:
                    if help_overlay is not None:
                        help_overlay = None
                    end_adjustment()
                    paint()
                    continue
                if help_overlay is not None:
                    process_help_event(event)
                    continue
                if dataset_modal is not None:
                    handle_dataset_modal(event)
                    paint()
                    continue
                if isinstance(event, MouseEvent):
                    if handle_pane_mouse(event):
                        paint()
                    continue
                # A text/command draft owns every printable key, including u/U/h.
                if overlay_editor is not None:
                    if not isinstance(event, (KeyEvent, PasteEvent)):
                        continue
                    pane = panes[overlay_editor.pane_index]
                    assert isinstance(pane, TuiAnimationPane)
                    animation_pane = pane
                    if isinstance(event, PasteEvent):
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[:cursor]
                            + event.value
                            + overlay_editor.draft[cursor:]
                        )
                        overlay_editor.cursor = cursor + len(event.value)
                        paint()
                        continue
                    key = event.value
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "\x1b":
                        overlay_editor = None
                    elif key == "\t":
                        overlay_editor.mode = "command" if overlay_editor.mode == "text" else "text"
                    elif key == "\r":
                        mode = overlay_editor.mode
                        draft = overlay_editor.draft
                        pane_index = overlay_editor.pane_index
                        record_mutation(
                            ("pane", pane_index, "overlay-source"),
                            lambda pane=animation_pane: pane.overlay.apply_draft(mode, draft),
                        )
                        overlay_editor = None
                    elif key in {"\n", "\x0b"}:
                        adjust_pane_weight(
                            overlay_editor.pane_index,
                            axis="row",
                            delta=1 if key == "\x0b" else -1,
                        )
                    elif key == "\x08":
                        open_help(context="editor")
                    elif key == "\x15":
                        overlay_editor.replace_draft("")
                        overlay_editor.cursor = 0
                        copy_feedback.show(translator.text("status.overlay_editor_cleared"))
                    elif key == "\x19":
                        copy_feedback.show(
                            translator.text(
                                "status.command_copied"
                                if copy_command(overlay_editor.draft)
                                else "status.command_copy_failed"
                            )
                        )
                    elif key == "\x12":
                        overlay_editor.replace_draft(
                            pane.overlay.config.text or ""
                            if overlay_editor.mode == "text"
                            else pane.overlay.config.command or ""
                        )
                        overlay_editor.cursor = len(overlay_editor.draft)
                    elif key == "\x7f" and overlay_editor.cursor:
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[: cursor - 1] + overlay_editor.draft[cursor:]
                        )
                        overlay_editor.cursor = cursor - 1
                    elif key in {"\x1b[3~", "\x04"}:
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[:cursor] + overlay_editor.draft[cursor + 1 :]
                        )
                    elif key == "\x1b[D":
                        overlay_editor.cursor = max(0, overlay_editor.cursor - 1)
                    elif key == "\x1b[C":
                        overlay_editor.cursor = min(
                            len(overlay_editor.draft), overlay_editor.cursor + 1
                        )
                    elif key in {"\x1b[H", "\x01"}:
                        overlay_editor.cursor = _editor_line_start(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif key == "\x02":
                        overlay_editor.cursor = _editor_previous_word(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif key == "\x17":
                        overlay_editor.cursor = _editor_next_word(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif key in {"\x1b[F", "\x05"}:
                        overlay_editor.cursor = _editor_line_end(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif len(key) == 1 and key.isprintable():
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[:cursor] + key + overlay_editor.draft[cursor:]
                        )
                        overlay_editor.cursor = cursor + 1
                    paint()
                    continue
                if custom_logs_pane is not None:
                    if not isinstance(event, KeyEvent):
                        continue
                    key = event.value
                    pane = panes[custom_logs_pane]
                    assert isinstance(pane, TuiCustomPane)
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "\x1b":
                        custom_logs_pane = None
                    elif key in {"y", "Y"}:
                        copy_feedback.show(
                            translator.text(
                                "status.data_copied"
                                if copy_command(
                                    "\n".join(
                                        f"{record.timestamp.isoformat()} {record.status}: {record.detail}"
                                        for record in pane.logs
                                    )
                                )
                                else "status.command_copy_failed"
                            )
                        )
                    paint()
                    continue
                if overlay_history is not None:
                    if not isinstance(event, KeyEvent):
                        continue
                    key = event.value
                    pane = panes[overlay_history.pane_index]
                    assert isinstance(pane, TuiAnimationPane)
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "h":
                        open_help(context="history")
                        continue
                    if key == "\x1b":
                        overlay_history = None
                    else:
                        records = tuple(pane.overlay.history)
                        if key in {"y", "\r", "\n"} and overlay_history.table.selected is not None:
                            copy_feedback.show(
                                translator.text(
                                    "status.command_copied"
                                    if copy_command(
                                        format_execution_record(overlay_history.table.selected)
                                    )
                                    else "status.command_copy_failed"
                                )
                            )
                        elif key == "\x1b[A":
                            move_history_selection(overlay_history.table, records, -1)
                        elif key == "\x1b[B":
                            move_history_selection(overlay_history.table, records, 1)
                        elif key in {"{", "}", "J", "K"}:
                            adjust_pane_weight(
                                overlay_history.pane_index,
                                axis="column" if key in {"{", "}"} else "row",
                                delta=1 if key in {"}", "K"} else -1,
                            )
                    paint()
                    continue
                if isinstance(event, MouseEvent):
                    continue
                key = event.value if isinstance(event, KeyEvent) else None
                if key == "\x03":
                    raise KeyboardInterrupt
                # A draft owns every ordinary key: root shortcuts must not leak in.
                if grid_draft is not None:
                    if key == "\x1b":
                        grid_draft = None
                        grid_error = None
                    elif key in {"\r", "\n"}:
                        parsed = parse_grid(grid_draft, len(panes))
                        if parsed is None:
                            grid_error = translator.text(
                                "error.tui_grid_runtime", value=grid_draft, count=len(panes)
                            )
                        else:
                            changed_grid = parsed != active_grid or active_layout is not None
                            if changed_grid:

                                def apply_grid() -> None:
                                    nonlocal active_grid, active_layout, column_weights, row_weights
                                    active_grid = parsed
                                    active_layout = None
                                    column_weights = None
                                    row_weights = None

                                record_mutation(("layout", "topology"), apply_grid)
                            grid_draft = None
                            grid_error = None
                    elif key in {"\x7f", "\b"}:
                        grid_draft = grid_draft[:-1]
                    elif key and (key.isalnum() or key in {"x", "X", "-"}):
                        grid_draft += key
                    paint()
                    continue
                if key in {"u", "U"}:
                    restored = history.undo() if key == "u" else history.redo()
                    if restored is history:
                        copy_feedback.show(
                            translator.text(
                                "status.tui_history_empty_undo"
                                if key == "u"
                                else "status.tui_history_empty_redo"
                            )
                        )
                    else:
                        history = restored
                        apply_dashboard_state(history.current)
                    paint()
                    continue
                if key == "h":
                    open_help()
                    continue
                if adjustment_mode == "pane":
                    if key is None:
                        continue
                    if key in {"\r", "\n", "\x1b"}:
                        end_adjustment()
                        paint()
                        continue
                    assert focused is not None
                    pane = panes[focused]
                    focused_index = focused
                    if isinstance(pane, TuiAnimationPane):
                        if key == "a":
                            adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                        else:
                            target_page = _animation_adjustment_target_page(adjustment_page, key)
                            if target_page is not None:
                                adjustment_page = target_page
                        if key == "a":
                            paint()
                            continue
                        animation_pane = pane
                        if adjustment_page == "quick" and key in {"p", "P"}:
                            animation_pane.overlay.cycle_position(1 if key == "p" else -1)
                        elif adjustment_page == "quick" and key in {"t", "T"}:
                            record_mutation(
                                ("pane", focused, "theme"),
                                lambda pane=animation_pane, now=now: pane.session.set_theme(
                                    _cycle(
                                        COLOR_SCHEMES, pane.session.theme, 1 if key == "t" else -1
                                    ),
                                    now,
                                ),
                            )
                        elif adjustment_page == "quick" and key in {"s", "S"}:
                            record_mutation(
                                ("pane", focused, "style"),
                                lambda pane=animation_pane, now=now: cycle_animation_style(
                                    pane.session,
                                    target="pane",
                                    step=1 if key == "s" else -1,
                                    now=now,
                                ),
                            )
                        elif adjustment_page == "advanced" and key == "\x1b[A":
                            pane.overlay.adjust_offset(dy=-1)
                        elif adjustment_page == "advanced" and key == "\x1b[B":
                            pane.overlay.adjust_offset(dy=1)
                        elif adjustment_page == "advanced" and key == "\x1b[C":
                            pane.overlay.adjust_offset(dx=1)
                        elif adjustment_page == "advanced" and key == "\x1b[D":
                            pane.overlay.adjust_offset(dx=-1)
                        elif adjustment_page == "advanced" and key == "0":
                            pane.overlay.reset_offset()
                        elif adjustment_page == "advanced" and key == "i":
                            record_mutation(
                                ("pane", focused, "overlay-interval"),
                                lambda pane=animation_pane, now=now: pane.overlay.cycle_interval(
                                    now=now
                                )
                                and None,
                            )
                        elif adjustment_page == "advanced" and key == "L":
                            overlay_history = OverlayHistoryState(focused)
                        elif adjustment_page == "advanced" and key == "e":
                            overlay_editor = OverlayEditorState(
                                focused,
                                "command"
                                if animation_pane.overlay.config.command is not None
                                else "text",
                                animation_pane.overlay.text_draft,
                                animation_pane.overlay.command_draft,
                            )
                        else:
                            now = None
                        if now is not None:
                            paint()
                            continue
                    if isinstance(pane, TuiCustomPane) and key in {"v", "V"}:
                        record_mutation(
                            ("pane", focused_index, "view"),
                            lambda pane=pane: setattr(
                                pane,
                                "body_view",
                                cycle_body_view(pane.body_view, step=1 if key == "v" else -1),
                            ),
                        )
                        paint()
                        continue
                    if isinstance(pane, TuiCustomPane) and (
                        key in {"a", "f"}
                        or key in _custom_pane_adjustment_keys(pane, adjustment_page)
                        or key
                        in _custom_pane_adjustment_keys(
                            pane,
                            "advanced" if adjustment_page == "quick" else "quick",
                        )
                    ):
                        if key == "a":
                            adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                            paint()
                            continue
                        target_page = (
                            adjustment_page
                            if key in _custom_pane_adjustment_keys(pane, adjustment_page)
                            else "advanced"
                            if adjustment_page == "quick"
                            else "quick"
                        )
                        adjustment_page = target_page
                        component = pane.component
                        base = component.candidate
                        capability = _custom_capability(pane)

                        def apply_custom_query(
                            config: CustomChartConfig,
                            *,
                            mutation: str,
                            pane: TuiCustomPane = pane,
                            pane_index: int = focused_index,
                        ) -> None:
                            pane.component.configure(config, data_affecting=True)
                            refresh(
                                pane_index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                                summary_affecting=mutation in {"granularity", "filters", "source"},
                            )

                        if key == "L":
                            custom_logs_pane = focused_index
                        elif key in {"p", "P"}:
                            updated = adjust_custom_chart(base, key)
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-period"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="period"
                                    ),
                                )
                        elif (
                            key in {"g", "G"}
                            and capability is not None
                            and capability.granularities
                        ):
                            values = capability.granularities
                            current = base.granularity if base.granularity in values else values[0]
                            direction = 1 if key == "g" else -1
                            updated = replace(base, granularity=_cycle(values, current, direction))
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-granularity"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="granularity"
                                    ),
                                )
                        elif (
                            key in {"b", "B"}
                            and base.kind != "calendar"
                            and capability is not None
                            and capability.group_by
                        ):
                            updated = _cycle_custom_grouping(
                                base, capability.group_by, step=1 if key == "b" else -1
                            )
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-group"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="group"
                                    ),
                                )
                        elif (
                            key == "f"
                            and capability is not None
                            and capability.filters
                            and component.accepted_response is not None
                        ):
                            response = component.accepted_response
                            filters = _custom_supported_filters(response.capabilities, capability)
                            size = get_terminal_size()

                            def paint_custom_filter_editor(body: str, editor_controls: str) -> None:
                                screen.paint(
                                    compose_frame(
                                        body,
                                        translator.text("label.adjust_filters"),
                                        editor_controls,
                                        height=size.lines,
                                    )
                                )

                            def read_custom_filter_key() -> str | None:
                                editor_event = raise_if_interrupt(read_adjustment_event(decoder))
                                return (
                                    editor_event.value
                                    if isinstance(editor_event, KeyEvent)
                                    else None
                                )

                            try:
                                edited = run_custom_filter_editor(
                                    base.filters,
                                    filters,
                                    translator,
                                    width=size.columns,
                                    paint=paint_custom_filter_editor,
                                    read_key=read_custom_filter_key,
                                )
                            except AdjustmentTimeout:
                                end_adjustment()
                                paint()
                                continue
                            if edited is not None and edited != base.filters:
                                updated = replace(base, filters=edited)
                                record_mutation(
                                    ("pane", focused_index, "custom-filters"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="filters"
                                    ),
                                )
                        elif key == "f":
                            copy_feedback.show(translator.text("status.custom_filter_unavailable"))
                        elif key in {"d", "t", "T", "s", "S", "k", "l", "o", "+", "=", "-", "_"}:
                            updated = adjust_custom_chart(base, key)
                            if updated != base:

                                def apply_custom_presentation(
                                    pane: TuiCustomPane = pane,
                                    config: CustomChartConfig = updated,
                                ) -> None:
                                    pane.component.configure(config, data_affecting=False)

                                record_mutation(
                                    ("pane", focused_index, "custom-presentation"),
                                    apply_custom_presentation,
                                )
                        paint()
                        continue
                    error_body = (
                        isinstance(pane, TuiCustomPane)
                        and pane.body_view == "chart"
                        and pane.component.error is not None
                        and (
                            isinstance(pane.component, CustomMonitorComponent)
                            or pane.component.model is None
                        )
                    )
                    if isinstance(pane, (TuiChartPane, TuiCustomPane)) and (
                        pane.body_view != "chart" or error_body
                    ):
                        handled_body_key = False
                        if key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                            offset = next_text_offset(
                                key,
                                offset=(
                                    pane.error_offset
                                    if error_body
                                    else pane.text_offsets.get(pane.body_view, 0)
                                ),
                                line_count=(
                                    pane.error_line_count
                                    if error_body
                                    else pane.text_line_counts.get(pane.body_view, 0)
                                ),
                                visible_rows=(
                                    pane.error_visible_rows
                                    if error_body
                                    else pane.text_visible_rows.get(pane.body_view, 0)
                                ),
                            )
                            assert offset is not None
                            if error_body:
                                pane.error_offset = offset
                            else:
                                pane.text_offsets[pane.body_view] = offset
                            handled_body_key = True
                        elif key in {"v", "V"}:
                            text_pane = pane
                            record_mutation(
                                ("pane", focused, "view"),
                                lambda pane=text_pane: setattr(
                                    pane,
                                    "body_view",
                                    cycle_body_view(pane.body_view, step=1 if key == "v" else -1),
                                ),
                            )
                            handled_body_key = True
                        elif key in {"y", "Y"} and body_view_copy_kind(pane.body_view) is not None:
                            copy_kind = body_view_copy_kind(pane.body_view)
                            assert copy_kind is not None
                            copied = copy_command(
                                _pane_copy_payload(
                                    pane,
                                    translator,
                                    pane_terminal(focused),
                                    dashboard=options,
                                )
                            )
                            copy_feedback.show(
                                translator.text(
                                    "status.command_copied"
                                    if copied and copy_kind in {"command", "full-command"}
                                    else "status.data_copied"
                                    if copied
                                    else "status.command_copy_failed"
                                )
                            )
                            handled_body_key = True
                        if handled_body_key or not error_body:
                            paint()
                            continue
                        # An error-only custom pane remains a Dashboard pane: keys it
                        # does not own must reach the existing management routes below.
                    next_focused = _adjustment_target(focused, key, len(panes))
                    if next_focused != focused:
                        focused = next_focused
                        paint()
                        continue
                    if key == "r":
                        open_dataset_modal(
                            "replace",
                            focused_index,
                            initial=pane.component.candidate
                            if isinstance(pane, TuiCustomPane)
                            else None,
                        )
                        paint()
                        continue
                    if key in {"N", "n"}:
                        open_dataset_modal(
                            "insert_before" if key == "N" else "insert_after", focused_index
                        )
                        paint()
                        continue
                    if key in {"{", "}", "J", "K"}:
                        adjust_pane_weight(
                            focused_index,
                            axis="column" if key in {"{", "}"} else "row",
                            delta=1 if key in {"}", "K"} else -1,
                        )
                        paint()
                        continue
                    if key == "[" and focused_index > 0:

                        def move_previous(index: int = focused_index) -> None:
                            nonlocal focused
                            panes[index - 1], panes[index] = panes[index], panes[index - 1]
                            focused = index - 1

                        record_mutation(("pane", focused_index, "previous"), move_previous)
                        paint()
                        continue
                    if key == "]" and focused_index < len(panes) - 1:

                        def move_next(index: int = focused_index) -> None:
                            nonlocal focused
                            panes[index], panes[index + 1] = panes[index + 1], panes[index]
                            focused = index + 1

                        record_mutation(("pane", focused_index, "next"), move_next)
                        paint()
                        continue
                    if key == "x" and len(panes) > 1:

                        def delete(index: int = focused_index) -> None:
                            nonlocal active_grid, focused
                            removed = panes.pop(index)
                            _shutdown_pane(removed)
                            active_grid = _grid_for_pane_count(active_grid, len(panes))
                            focused = min(index, len(panes) - 1)

                        record_mutation(("pane", focused_index, "delete"), delete)
                        paint()
                        continue
                    if not isinstance(pane, TuiChartPane):
                        paint()
                        continue
                    chart_pane = pane
                    if key == "a":
                        adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                    else:
                        chart = _pane_display_options(pane).chart
                        target_page = _adjustment_target_page(
                            chart.kind,
                            adjustment_page,
                            key,
                            chart=chart,
                            attachment_available=(
                                isinstance(chart, MonitorConfig)
                                and chart.presentation.style in {"ranking", "list"}
                                and pane.attachment is not None
                            ),
                        )
                        if target_page is not None:
                            adjustment_page = target_page
                    if adjustment_page == "advanced" and key == "f":
                        component = pane.component
                        base = component.candidate
                        size = get_terminal_size()
                        editor_width = size.columns
                        editor_height = size.lines

                        def paint_filter_editor(
                            body: str,
                            editor_controls: str,
                            *,
                            height: int = editor_height,
                        ) -> None:
                            screen.paint(
                                compose_frame(
                                    body,
                                    translator.text("status.tui_adjust_history"),
                                    editor_controls,
                                    height=height,
                                )
                            )

                        def read_filter_key() -> str | None:
                            editor_event = raise_if_interrupt(read_adjustment_event(decoder))
                            return (
                                editor_event.value if isinstance(editor_event, KeyEvent) else None
                            )

                        try:
                            edited = run_filter_editor(
                                base.chart.filters,
                                discover_filter_choices(
                                    pane_records(pane),
                                    base.chart.filters,
                                    include_projects=pane_includes_projects(pane),
                                ),
                                translator,
                                width=editor_width,
                                paint=paint_filter_editor,
                                read_key=read_filter_key,
                            )
                        except AdjustmentTimeout:
                            end_adjustment()
                            paint()
                            continue
                        if edited is not None and edited != base.chart.filters:

                            def apply_filters(
                                pane: TuiChartPane = pane,
                                component: HistoricalChartComponent | MonitorComponent = component,
                                base: StandaloneLaunch = base,
                                edited=edited,
                                pane_index: int = focused,
                            ) -> None:
                                _clear_changes(pane)
                                component.configure(
                                    replace_chart_filters(base, edited),
                                    data_affecting=True,
                                )
                                refresh(
                                    pane_index,
                                    trigger=LifecycleTrigger.CONFIGURATION,
                                    data_affecting=False,
                                )

                            record_mutation(("pane", focused, "filters"), apply_filters)
                    elif key in {"v", "V"}:
                        record_mutation(
                            ("pane", focused, "view"),
                            lambda pane=chart_pane: setattr(
                                pane,
                                "body_view",
                                cycle_body_view(pane.body_view, step=1 if key == "v" else -1),
                            ),
                        )
                    elif (
                        adjustment_page == "advanced"
                        and chart_pane.attachment is not None
                        and isinstance(_pane_display_options(chart_pane).chart, MonitorConfig)
                        and _pane_display_options(chart_pane).chart.presentation.style
                        in {"ranking", "list"}
                        and key in {"t", "T", "s", "S"}
                    ):
                        attachment = chart_pane.attachment
                        assert attachment is not None

                        def adjust_attachment(
                            pane: TuiChartPane = chart_pane,
                            attachment: AnimationSessionState = attachment,
                        ) -> None:
                            now = time.monotonic()
                            if key in {"s", "S"}:
                                pane.attachment_enabled = cycle_monitor_attachment(
                                    attachment,
                                    enabled=pane.attachment_enabled,
                                    step=1 if key == "s" else -1,
                                    now=now,
                                )
                            else:
                                attachment.set_theme(
                                    _cycle(
                                        COLOR_SCHEMES,
                                        attachment.theme,
                                        1 if key == "t" else -1,
                                    ),
                                    now,
                                )

                        record_mutation(
                            (
                                "pane",
                                focused,
                                "attachment-style" if key in {"s", "S"} else "attachment-theme",
                            ),
                            adjust_attachment,
                        )
                    elif _adjustment_key_supported(
                        _pane_display_options(pane).chart.kind,
                        adjustment_page,
                        key,
                        chart=_pane_display_options(pane).chart,
                    ):
                        component = pane.component
                        base = component.candidate
                        updated = adjust_standalone(base, key)
                        if updated != base:
                            data_affecting = (
                                historical_replacement_required(base, updated)
                                if isinstance(component, HistoricalChartComponent)
                                else (
                                    isinstance(base.chart, MonitorConfig)
                                    and isinstance(updated.chart, MonitorConfig)
                                    and (
                                        base.chart.by != updated.chart.by
                                        or base.chart.filters != updated.chart.filters
                                    )
                                )
                            )

                            def apply_adjustment(
                                pane: TuiChartPane = pane,
                                component: HistoricalChartComponent | MonitorComponent = component,
                                base: StandaloneLaunch = base,
                                updated: StandaloneLaunch = updated,
                                data_affecting: bool = data_affecting,
                                pane_index: int = focused,
                            ) -> None:
                                _clear_changes(pane)
                                component.configure(updated, data_affecting=data_affecting)
                                if updated.host.interval != base.host.interval:
                                    pane.scheduler.rebuild(
                                        updated.host.interval,
                                        now=time.monotonic(),
                                    )
                                if data_affecting:
                                    refresh(
                                        pane_index,
                                        trigger=LifecycleTrigger.CONFIGURATION,
                                    )
                                elif (
                                    isinstance(component, HistoricalChartComponent)
                                    and component.missing_comparison_coverage().intervals
                                ):
                                    refresh(
                                        pane_index,
                                        trigger=LifecycleTrigger.CONFIGURATION,
                                        data_affecting=False,
                                    )

                            record_mutation(
                                ("pane", focused, "configuration", key), apply_adjustment
                            )
                    paint()
                    continue
                if adjustment_mode == "global":
                    if key in {"\r", "\n", "\x1b"}:
                        end_adjustment()
                    elif key in {"t", "T"}:

                        def cycle_theme() -> None:
                            nonlocal dashboard_theme
                            dashboard_theme = _cycle(
                                COLOR_SCHEMES, dashboard_theme, 1 if key == "t" else -1
                            )
                            _set_header_theme(header, dashboard_theme)

                        record_mutation(("dashboard", "theme"), cycle_theme)
                    elif key in {"s", "S"}:

                        def cycle_style() -> None:
                            nonlocal dashboard_style, divider_style, frame_style
                            dashboard_style = _cycle(
                                DASHBOARD_STYLES, dashboard_style, 1 if key == "s" else -1
                            )
                            divider_style, frame_style = _dashboard_structure(dashboard_style)

                        record_mutation(("dashboard", "style"), cycle_style)
                    elif key == "H":

                        def cycle_header() -> None:
                            nonlocal header_style
                            header_style = _cycle(
                                ("hidden", "compact", "banner", "panel"), header_style, 1
                            )
                            if header_style != "hidden" and header.summary_period != "none":
                                required = required_summary_coverage(
                                    local_today(), header.summary_period
                                )
                                if header.token_enabled and any(
                                    not header.coverage.covers(item) for item in required.intervals
                                ):
                                    refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
                                refresh_custom_summaries(trigger=LifecycleTrigger.CONFIGURATION)

                        record_mutation(("header", "style"), cycle_header)
                    elif key in {"p", "P"}:

                        def cycle_summary() -> None:
                            next_summary = _cycle_header_summary(
                                header.summary_period, step=1 if key == "p" else -1
                            )
                            header.summary_period = next_summary
                            header.generation += 1
                            header.lifecycle.detach_active()
                            _invalidate_custom_dashboard_summaries(header)
                            if header_style != "hidden" and next_summary != "none":
                                required = required_summary_coverage(local_today(), next_summary)
                                if header.token_enabled and any(
                                    not header.coverage.covers(item) for item in required.intervals
                                ):
                                    refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
                                refresh_custom_summaries(trigger=LifecycleTrigger.CONFIGURATION)

                        record_mutation(("header", "summary"), cycle_summary)
                    elif key == "z":
                        try:
                            shortcut = _choose_layout_shortcut(
                                screen,
                                translator,
                                decoder,
                                height=get_terminal_size().lines,
                                current=active_layout or active_grid,
                                pane_count=len(panes),
                                read_input=lambda: raise_if_interrupt(
                                    read_adjustment_event(decoder)
                                ),
                            )
                        except AdjustmentTimeout:
                            end_adjustment()
                            paint()
                            continue
                        if shortcut is not None:
                            resolved = _LAYOUT_SHORTCUT_VALUES[shortcut]

                            def choose_layout() -> None:
                                nonlocal \
                                    active_grid, \
                                    active_layout, \
                                    column_weights, \
                                    row_weights, \
                                    grid_error
                                if shortcut in {"wide", "narrow", "all"}:
                                    active_grid = resolved
                                    active_layout = None
                                else:
                                    active_layout = resolved
                                column_weights = None
                                row_weights = None
                                grid_error = None

                            record_mutation(("layout", "topology"), choose_layout)
                    elif key == "Z":
                        grid_draft = ""
                        grid_error = None
                    else:
                        continue
                    paint()
                    continue
                if body_view != "chart" and key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                    offset = next_text_offset(
                        key,
                        offset=dashboard_text_offset,
                        line_count=dashboard_text_line_count,
                        visible_rows=dashboard_text_visible_rows,
                    )
                    assert offset is not None
                    dashboard_text_offset = offset
                    paint(force=True)
                    continue
                if body_view == "chart" and key == "c":
                    browse_controls_hidden = not browse_controls_hidden
                    paint(force=True)
                    continue
                if body_view == "chart" and key == "r":
                    manual_refresh_operations.clear()
                    for index in range(len(panes)):
                        if refresh(
                            index,
                            trigger=LifecycleTrigger.MANUAL,
                            replace_active=True,
                        ):
                            pane = panes[index]
                            if (
                                isinstance(pane, (TuiChartPane, TuiCustomPane))
                                and pane.lifecycle.active is not None
                            ):
                                manual_refresh_operations.add(pane.lifecycle.active)
                    if refresh_header(
                        trigger=LifecycleTrigger.MANUAL,
                        replace_active=True,
                    ):
                        operation = header.lifecycle.active
                        if operation is not None:
                            manual_refresh_operations.add(operation)
                    manual_refresh_operations.update(
                        refresh_custom_summaries(
                            trigger=LifecycleTrigger.MANUAL,
                            replace_active=True,
                        )
                    )
                    paint(force=True)
                elif key in {"v", "V"}:

                    def cycle_dashboard_view() -> None:
                        nonlocal body_view
                        body_view = cycle_dashboard_body_view(
                            body_view, step=1 if key == "v" else -1
                        )

                    record_mutation(("dashboard", "view"), cycle_dashboard_view)
                elif key in {"y", "Y"} and body_view != "chart":
                    copy_feedback.show(
                        translator.text(
                            "status.command_copied"
                            if copy_command(full_dashboard_command())
                            else "status.command_copy_failed"
                        )
                    )
                elif key == "\t":
                    continue
                elif key == "d" and body_view == "chart":
                    focused = None
                    adjustment_mode = "global"
                    adjustment_page = "quick"
                    adjustment_timer = AdjustmentIdleTimer()
                elif key == "m" and body_view == "chart":
                    focused = _adjustment_target(focused, key, len(panes))
                    adjustment_mode = "pane" if focused is not None else None
                    adjustment_page = "quick"
                    adjustment_timer = AdjustmentIdleTimer() if focused is not None else None
                else:
                    continue
                paint()
    except KeyboardInterrupt:
        return 0
    finally:
        for pane in panes:
            _shutdown_pane(pane)
        for summary in tuple(header.custom_summaries.values()):
            summary.scheduler.shutdown()
            summary.lifecycle.shutdown()
        header.scheduler.shutdown()
        header.lifecycle.shutdown()
        runtime.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        screen.finish()
        set_screen_cursor_visible(True)
