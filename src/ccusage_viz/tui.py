from __future__ import annotations

# ruff: noqa: B023
import sys
import time
from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from shutil import get_terminal_size
from threading import Event
from typing import TypeAlias

from ccusage_viz import __version__
from ccusage_viz.acquisition import historical_provider_id, historical_query_intent
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
    SourceMode,
    clip_overlay_placements,
    compose_overlay_row,
    format_execution_record,
    move_history_selection,
    render_history_table,
)
from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    format_full_dashboard_command,
    wrap_command,
)
from ccusage_viz.core.time import DateRange, local_today, refresh_date_range
from ccusage_viz.coverage import DateCoverage, DateInterval
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
    next_body_view,
    next_dashboard_body_view,
    render_monitor_data,
    render_snapshot_data,
)
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.diagnostics import format_error, transient_query_recovery_lines
from ccusage_viz.domain import UsageRecord
from ccusage_viz.editor_help import editor_help_groups
from ccusage_viz.errors import UsageError, VizError
from ccusage_viz.filter_draft import discover_filter_choices, run_filter_editor
from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
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
    DashboardLaunch,
    MonitorConfig,
    PaneConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
    replace_chart_filters,
)
from ccusage_viz.processing import build_period_summary, required_summary_coverage
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.base import RenderAudit, RenderContext, styled_text
from ccusage_viz.render.filters import active_filter_summary
from ccusage_viz.render.palette import COLOR_SCHEMES, get_color_scheme
from ccusage_viz.render.summary import render_summary
from ccusage_viz.terminal import Frame, FramePainter, Terminal, compose_frame
from ccusage_viz.terminal_ui import (
    AdjustmentAction,
    TransientFeedback,
    adjustment_rows,
    controls_line,
    dimmed,
    feedback_lines,
)
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.text_viewport import (
    next_text_offset,
    render_text_viewport,
    text_viewport_overflows,
)
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    read_event,
    tui_input_mode,
)

_PANE_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor", "animate")


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


@dataclass(slots=True)
class TuiChartPane:
    component: HistoricalChartComponent | MonitorComponent
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[PaneFuture]
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


TuiPane = TuiChartPane | TuiAnimationPane
HelpTreeNode: TypeAlias = tuple[str, tuple["HelpTreeNode", ...]]
HelpTree: TypeAlias = tuple[HelpTreeNode, ...]


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
    scroll_offset: int = 0


@dataclass(slots=True)
class OverlayEditorState:
    """Uncommitted source drafts displayed within one Dashboard animation pane."""

    pane_index: int
    mode: SourceMode
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
    )


def _set_header_theme(header: DashboardHeader, theme: str) -> None:
    header.options = replace(
        header.options,
        chart=replace(
            header.options.chart,
            presentation=replace(header.options.chart.presentation, theme=theme),
        ),
    )


def _next_header_summary(period: str) -> str:
    return _cycle(HEADER_SUMMARIES, period, 1)


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
    summary = _header_summary(header, header.summary_period)
    if header.summary_period == "none":
        detail = ""
    elif summary is None:
        detail = translator.text("status.loading")
    else:
        detail = render_summary(
            summary,
            RenderContext(
                terminal.width,
                1,
                translator,
                color=terminal.color,
                ascii=terminal.ascii,
                color_scheme=header.options.chart.presentation.theme,
            ),
        )
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
        compact_title = f"{title} · {detail}" if detail else title
        return [
            _dashboard_title_line(compact_title, freshness, terminal.width, color=terminal.color)
        ]
    title_line = _dashboard_title_line(title, freshness, terminal.width, color=terminal.color)
    if style == "banner":
        return [title_line] if not detail else [title_line, center_text(detail, terminal.width)]
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
    return [
        styled_rule,
        title_line,
        center_text(detail, terminal.width),
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
    """Release resources owned by a chart or animation pane."""
    if isinstance(pane, TuiAnimationPane):
        pane.overlay.close()
        return
    pane.scheduler.shutdown()
    pane.lifecycle.shutdown()


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
        if not isinstance(pane_config_or_owner, (ChartPaneConfig, AnimationPaneConfig)):
            raise TypeError("dashboard pane configuration is required")
        pane_config = pane_config_or_owner
        if isinstance(pane_config, AnimationPaneConfig):
            return TuiAnimationPane(
                new_animation_session(pane_config.animation, theme=options.host.theme),
                AnimationRenderer(),
                AnimationOverlayRuntime(pane_config.overlay),
            )
        if not isinstance(owner_id, str):
            raise TypeError("dashboard chart pane owner id is required")
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
        attachment=attachment,
        attachment_renderer=attachment_renderer,
    )


def _await_historical(handle: QueryHandle[ProviderResult], started: float) -> UsageSnapshot:
    return snapshot_from_result(handle.result(), time.monotonic() - started)


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


@dataclass(frozen=True, slots=True)
class DashboardOverlayPlacement:
    source_index: int
    placement: OverlayPlacement


def _pane_copy_payload(pane: TuiChartPane, translator: Translator, terminal: Terminal) -> str:
    """Return the focused non-chart pane view's complete clipboard payload."""
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
        buckets = component.buckets(
            max(8, min(32, terminal.width // 4)),
            now=time.monotonic(),
            wall=datetime.now().astimezone(),
        )
        return render_monitor_data(
            buckets,
            by=active.chart.by,
            translator=translator,
            terminal=terminal,
            view=view,
        )
    return render_snapshot_data(
        active,
        component.snapshot,
        translator,
        terminal,
        view=view,
    )


def _pane_render(
    pane: TuiPane,
    translator: Translator,
    terminal: Terminal,
    *,
    defer_animation_overlay: bool = False,
) -> PaneRender:
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
            buckets = component.buckets(
                max(8, min(32, terminal.width // 4)),
                now=time.monotonic(),
                wall=datetime.now().astimezone(),
            )
            return PaneRender(
                render_monitor_data(
                    buckets,
                    by=accepted.chart.by,
                    translator=translator,
                    terminal=terminal,
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
                control_rows=0,
                hide_upper_right_axes=True,
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
            context = RenderContext(
                terminal.width,
                max(
                    1,
                    terminal.height - int(active.chart.presentation.density == "full"),
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
                    active.chart.filters, translator, width=terminal.width
                ),
                density=active.chart.presentation.density,
                pending=display_query_pending,
                audit=RenderAudit(
                    component.accepted_at,
                    component.last_elapsed,
                    pane.scheduler.interval,
                    "sample",
                    refreshing=pane.lifecycle.submission is not None,
                    querying=display_query_pending,
                ),
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
                control_rows=0,
                hide_upper_right_axes=True,
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
    offset: int = 0,
    scrollable: bool = False,
    return_metadata: bool = False,
) -> str | tuple[str, int, int, int]:
    """Keep notices fixed below an optionally scrollable pane body."""
    notice_rows = min(len(notices), max(0, height - 3))
    chart_height = max(0, height - notice_rows)
    viewport = render_text_viewport(chart, offset=offset, visible_rows=chart_height)
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


def _new_pane_options(command: str, base: DashboardLaunch) -> StandaloneLaunch:
    from ccusage_viz.configuration import default_pane, standalone_from_chart_pane

    pane = default_pane(command, dashboard=base)
    if command == "monitor":
        pane = replace(pane, chart=replace(pane.chart, by="model", top=3))
    return standalone_from_chart_pane(base, pane)


_PANE_QUICK_ACTIONS = {
    "timeline": (("p/P", "period"), ("g", "granularity"), ("b", "group"), ("+/-", "top")),
    "calendar": (("p/P", "period"),),
    "stack": (("p/P", "period"), ("g", "granularity")),
    "ranking": (("p/P", "period"), ("b", "group"), ("+/-", "top")),
    "monitor": (("w", "window"), ("b", "group"), ("+/-", "top")),
}
_PANE_ADVANCED_ACTIONS = {
    "timeline": (
        ("o", "other"),
        ("A", "project_aggregation"),
        ("P", "project_label_context"),
        ("l", "legend"),
        ("k", "weekdays"),
    ),
    "calendar": (),
    "stack": (("c", "cache"), ("l", "legend"), ("k", "weekdays")),
    "ranking": (("o", "other"), ("A", "project_aggregation"), ("P", "project_label_context")),
    "monitor": (("A", "project_aggregation"), ("P", "project_label_context"), ("l", "legend")),
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
    ("p", "summary"),
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
        isinstance(chart, (TimelineConfig, RankingConfig, MonitorConfig)) and chart.by == "project"
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
        if (key not in {"A", "P"} or _project_grouping_available(chart))
        and not (
            isinstance(chart, MonitorConfig)
            and chart.presentation.style in {"ranking", "list"}
            and key == "w"
        )
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
        or (key == "b" and command in {"timeline", "ranking", "monitor"})
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
            f"v {translator.text('label.adjust_view')}",
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
        "project_aggregation",
        "project_label_context",
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
    ("Space", "pause"),
    ("p/P", "overlay_position"),
    ("t/T", "animation_theme"),
    ("s/S", "animation_style"),
)
_ANIMATION_PANE_ADVANCED_BINDINGS = (
    ("↑/↓/←/→", "overlay_move"),
    ("0", "overlay_reset"),
    ("e", "overlay_edit"),
    ("i", "overlay_interval"),
    ("l", "overlay_history"),
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
        if isinstance(chart, (TimelineConfig, RankingConfig)):
            advanced.append(f"Other {chart.other}")
            if chart.by == "project":
                advanced.extend(
                    (
                        f"Project aggregation {chart.project_aggregation}",
                        translator.text(
                            "status.project_label_context",
                            context=pane.component.project_label_context,
                        ),
                    )
                )
        if isinstance(chart, (TimelineConfig, StackConfig)):
            advanced.extend((f"Legend {chart.presentation.legend}", f"Weekdays {chart.weekdays}"))
        if isinstance(chart, StackConfig):
            advanced.insert(0, f"Cache {chart.cache}")
        if isinstance(chart, MonitorConfig):
            if chart.by == "project":
                advanced.extend(
                    (
                        f"Project aggregation {chart.project_aggregation}",
                        translator.text(
                            "status.project_label_context",
                            context=pane.component.project_label_context,
                        ),
                    )
                )
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


def _choose_pane_type(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    action: str = "add",
    paint_choices: Callable[[str, str, str], None] | None = None,
    read_input: Callable[[], object] | None = None,
    on_help: Callable[[str], None] | None = None,
) -> str | None:
    index = 0
    while True:
        choices = "\n".join(
            f"{'›' if item == _PANE_COMMANDS[index] else ' '} "
            f"{translator.text(f'label.pane_{item}')}"
            for item in _PANE_COMMANDS
        )
        title = translator.text(f"status.tui_{action}_title")
        controls = translator.text(f"status.tui_{action}_controls")
        if paint_choices is None:
            screen.paint(compose_frame(choices, title, controls, height=height))
        else:
            paint_choices(choices, title, controls)
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


def run_tui(options: DashboardLaunch, translator: Translator) -> int:
    runtime = build_query_runtime()
    panes = [
        _new_pane(
            options,
            pane_config,
            f"dashboard:pane:{index}" if isinstance(pane_config, ChartPaneConfig) else None,
            runtime,
        )
        for index, pane_config in enumerate(options.panes)
    ]
    for index, pane in enumerate(panes):
        pane.pane_id = index
    next_pane_id = len(panes)
    header = _new_header(options, runtime)
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
    overlay_editor: OverlayEditorState | None = None
    overlay_history: OverlayHistoryState | None = None
    help_overlay: HelpOverlayState | None = None
    help_was_active = False
    last_click: tuple[int, float] | None = None
    copy_feedback = TransientFeedback()
    dashboard_paused = False
    manual_refresh_operations: set[OperationToken] = set()

    last_successful_update: datetime | None = None
    last_size: tuple[int, int] | None = None
    screen = FramePainter(sys.stdout)

    def end_adjustment() -> None:
        nonlocal adjustment_mode, adjustment_timer, focused, grid_draft, grid_error, body_view
        adjustment_mode = None
        adjustment_timer = None
        focused = None
        grid_draft = None
        grid_error = None

    def open_help(
        *, context: str = "dashboard", action: str | None = None, selected: str | None = None
    ) -> None:
        nonlocal help_overlay
        help_overlay = HelpOverlayState(
            AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS),
            adjustment_timer.remaining() if adjustment_timer is not None else None,
            context=context,
            action=action,
            selected=selected,
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

    def start_pane(index: int, *, now: float) -> bool:
        pane = panes[index]
        if not isinstance(pane, TuiChartPane):
            return False
        try:
            return pane.lifecycle.start_ready(
                now=now,
                start=lambda operation: start_pane_submission(pane, operation),
            )
        except BaseException:
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
    ) -> bool:
        pane = panes[index]
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
                    date_range=refresh_date_range(current.chart.date_range),
                ),
            )
            component.configure(submitted, data_affecting=True)
        now = time.monotonic()
        try:
            return pane.lifecycle.request(
                trigger,
                generation=component.generation,
                now=now,
                replace_active=replace_active,
                start=lambda operation: start_pane_submission(pane, operation),
            )
        except BaseException:
            return False

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
                *(pane.lifecycle for pane in panes if isinstance(pane, TuiChartPane)),
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
        for index, pane in enumerate(panes):
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
            if isinstance(pane, TuiAnimationPane):
                pane_states.append(
                    DashboardPaneState(
                        pane.pane_id,
                        AnimationPaneConfig(pane.session.spec, pane.overlay.config),
                        pane.body_view,
                        animation_theme=pane.session.theme,
                    )
                )
            else:
                attachment = pane.attachment
                pane_states.append(
                    DashboardPaneState(
                        pane.pane_id,
                        ChartPaneConfig(_pane_display_options(pane).chart),
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
        refresh_indexes: list[tuple[int, bool]] = []
        now = time.monotonic()

        for pane_state in state.panes:
            pane = existing.pop(pane_state.pane_id, None)
            expected_animation = isinstance(pane_state.config, AnimationPaneConfig)
            compatible = (
                pane is not None and isinstance(pane, TuiAnimationPane) == expected_animation
            )
            if compatible and isinstance(pane, TuiChartPane):
                assert isinstance(pane_state.config, ChartPaneConfig)
                compatible = type(_pane_display_options(pane).chart) is type(
                    pane_state.config.chart
                )
            if not compatible:
                if pane is not None:
                    _shutdown_pane(pane)
                pane = _new_pane(
                    options,
                    pane_state.config,
                    f"dashboard:pane:{pane_state.pane_id}" if not expected_animation else None,
                    runtime,
                )
                pane.pane_id = pane_state.pane_id
                if isinstance(pane, TuiChartPane):
                    refresh_indexes.append((len(reconciled), True))
            pane.body_view = pane_state.body_view
            if isinstance(pane, TuiAnimationPane):
                assert isinstance(pane_state.config, AnimationPaneConfig)
                if pane.session.spec != pane_state.config.animation:
                    pane.session.set_style(pane_state.config.animation, now)
                if pane.overlay.config != pane_state.config.overlay:
                    pane.overlay.apply(pane_state.config.overlay, now=now)
                if pane_state.animation_theme is not None:
                    pane.session.set_theme(pane_state.animation_theme, now)
            else:
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
                        refresh_indexes.append((len(reconciled), True))
                    elif (
                        isinstance(component, HistoricalChartComponent)
                        and component.missing_comparison_coverage().intervals
                    ):
                        refresh_indexes.append((len(reconciled), False))
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
        for index, data_affecting in refresh_indexes:
            refresh(index, trigger=LifecycleTrigger.CONFIGURATION, data_affecting=data_affecting)
        if header_style != "hidden" and header_refresh_required:
            refresh_header(trigger=LifecycleTrigger.CONFIGURATION)

    def record_mutation(family: object, mutate: Callable[[], None]) -> bool:
        nonlocal history
        before = capture_dashboard_state()
        mutate()
        after = capture_dashboard_state()
        if after == before:
            return False
        history = history.record(after, family=family, target=family, timestamp=time.monotonic())
        return True

    def full_dashboard_command() -> str:
        return format_full_dashboard_command(
            replace(options, host=replace(options.host, theme=dashboard_theme)),
            tuple(
                ChartPaneConfig(_pane_options(pane).chart)
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
        context = RenderContext(
            width,
            1,
            translator,
            color=dashboard_theme != "no-color",
            ascii=options.host.ascii,
            color_scheme=dashboard_theme,
        )
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
            children: HelpTree,
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
                        child_children,
                        is_last=index == len(children) - 1,
                    )
                )
            return tuple(rows)

        def mode_node(name: str, *, active: bool, enter: str, exit: str) -> HelpTreeNode:
            return (
                f"{active_icon if active else ''}{translator.text(name)}",
                ((enter, ()), (exit, ())),
            )

        def mode_pages() -> HelpTree:
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

        if help_overlay is not None and help_overlay.context != "dashboard":
            if help_overlay.context == "chooser":
                assert help_overlay.action is not None
                assert help_overlay.selected is not None
                context_nodes = (
                    (
                        translator.text("status.tui_help_chooser"),
                        (
                            (translator.text(f"status.tui_{help_overlay.action}_title"), ()),
                            (
                                translator.text(
                                    "status.tui_help_chooser_selected",
                                    pane=translator.text(f"label.pane_{help_overlay.selected}"),
                                ),
                                (),
                            ),
                            (translator.text("status.tui_help_chooser_detail"), ()),
                        ),
                    ),
                )
            elif help_overlay.context == "editor":
                rows = [
                    styled_text(
                        translator.text("status.tui_help_section_controls"),
                        scheme.highlight,
                        context,
                        bold=True,
                    )
                ]
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
            rows = [
                styled_text(
                    translator.text("status.tui_help_section_controls"),
                    scheme.highlight,
                    context,
                    bold=True,
                )
            ]
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
            rows.extend(
                tree_node(
                    "",
                    translator.text("status.tui_help_section_policy"),
                    tuple(policy_children),
                    is_last=True,
                )
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
            if isinstance(focused_pane, TuiChartPane) and focused_pane.body_view != "chart":
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
                    (translator.text("status.tui_help_browse_pause"), ()),
                    (translator.text("status.tui_help_controls"), ()),
                    (translator.text("status.tui_help_interval_dashboard"), ()),
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
                        (translator.text("status.tui_help_animation_pause"), ()),
                        (translator.text("status.tui_help_animation_position"), ()),
                        (translator.text("status.tui_help_animation_theme"), ()),
                        (translator.text("status.tui_help_animation_style"), ()),
                        (translator.text("status.tui_help_animation_move"), ()),
                        (translator.text("status.tui_help_animation_reset"), ()),
                        (
                            translator.text("status.tui_help_animation_edit"),
                            ((translator.text("status.tui_help_editor_detail"), ()),),
                        ),
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
            rows.append(styled_text(translator.text(heading), scheme.highlight, context, bold=True))
            for index, (value, children) in enumerate(nodes):
                rows.extend(tree_node("", value, children, is_last=index == len(nodes) - 1))
        policy_children = [
            (
                translator.text(
                    "status.tui_help_tip_ascii" if options.host.ascii else "status.tui_help_tip"
                ),
                (),
            )
        ]
        if mode == "browse":
            policy_children.append((translator.text("status.tui_help_browse_hint"), ()))
        elif (
            mode == "pane" and focused is not None and isinstance(panes[focused], TuiAnimationPane)
        ):
            policy_children.append((translator.text("status.tui_help_animation_hint"), ()))
        if mode == "pane" and focused is not None:
            focused_pane = panes[focused]
            show_summary_policy = (
                isinstance(focused_pane, TuiChartPane)
                and focused_pane.body_view == "chart"
                and not isinstance(_pane_display_options(focused_pane).chart, MonitorConfig)
            )
        else:
            show_summary_policy = False
        if show_summary_policy:
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
        rows.append("")
        rows.append(
            styled_text(
                translator.text("status.tui_help_section_policy"),
                scheme.highlight,
                context,
                bold=True,
            )
        )
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
            action=translator.text("status.resume" if dashboard_paused else "status.pause"),
        )
        return (clip_width(context, width), global_operations(width))

    def notices() -> tuple[str, ...]:
        paused = (
            (
                controls_line(
                    translator.text("status.dashboard_paused"),
                    width=get_terminal_size().columns,
                    color=dashboard_theme != "no-color",
                ),
            )
            if dashboard_paused
            else ()
        )
        feedback = feedback_lines(
            copy_feedback,
            width=get_terminal_size().columns,
            color=dashboard_theme != "no-color",
            now=time.monotonic(),
        )
        manual = (translator.text("status.tui_refreshing"),) if manual_refresh_operations else ()
        return (*manual, *paused, *feedback)

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
        nonlocal overlay_editor, overlay_history
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
        grid_y = event.y - header_rows - 1
        selected = layout_pane_at(layout, event.x, grid_y)
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
        pane_options = _pane_display_options(pane)
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            pane_options.chart.presentation.theme != "no-color",
            pane_options.host.ascii,
        )

    def paint(*, force: bool = False) -> None:
        nonlocal help_was_active, last_size, dashboard_text_offset, dashboard_text_line_count
        nonlocal dashboard_text_visible_rows
        size = get_terminal_size()
        atomic = help_overlay is not None or help_was_active
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
                pane_content = _local_pane_content(
                    chart,
                    local_notices,
                    height=interior_height,
                    offset=pane.text_offsets.get(pane.body_view, 0),
                    scrollable=pane.body_view != "chart",
                    return_metadata=True,
                )
                assert isinstance(pane_content, tuple)
                content, offset, line_count, visible_rows = pane_content
                if pane.body_view != "chart":
                    pane.text_offsets[pane.body_view] = offset
                    pane.text_line_counts[pane.body_view] = line_count
                    pane.text_visible_rows[pane.body_view] = visible_rows
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

    def choose_pane_type(action: str, pane_index: int) -> str | None:
        nonlocal chooser_overlay

        def paint_choices(choices: str, title: str, chooser_controls: str) -> None:
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
            chooser_frame = compose_frame(
                choices,
                title,
                chooser_controls,
                height=interior_height,
            )
            chooser_overlay = (pane_index, "\n".join(chooser_frame.rows))
            paint()

        try:
            return _choose_pane_type(
                screen,
                translator,
                decoder,
                height=get_terminal_size().lines,
                action=action,
                paint_choices=paint_choices,
                read_input=lambda: raise_if_interrupt(read_adjustment_event(decoder)),
                on_help=lambda selected: show_chooser_help(action, selected),
            )
        finally:
            chooser_overlay = None

    def create_pane(command: str, *, pane_id: int | None = None) -> TuiPane:
        pane_id = allocate_pane_id() if pane_id is None else pane_id
        if command == "animate":
            pane = _new_pane(options, AnimationPaneConfig(default_animation_spec("pane")))
        else:
            pane = _new_pane(
                _new_pane_options(command, options),
                f"dashboard:pane:{pane_id}",
                runtime,
            )
        pane.pane_id = pane_id
        return pane

    try:
        with tui_input_mode() as decoder:
            for index in range(len(panes)):
                refresh(index, trigger=LifecycleTrigger.STARTUP)
            if header_style != "hidden":
                refresh_header(trigger=LifecycleTrigger.STARTUP)
            paint()
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                changed = collect()
                now = time.monotonic()
                if header_style != "hidden" and header.scheduler.due(now=now):
                    refresh_header(trigger=LifecycleTrigger.PERIODIC)
                for index, pane in enumerate(panes):
                    if isinstance(pane, TuiChartPane) and pane.scheduler.due(now=now):
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
                        animation_pane = pane

                        def apply_overlay_draft(
                            pane: TuiAnimationPane = animation_pane,
                            mode: SourceMode = mode,
                            draft: str = draft,
                        ) -> None:
                            pane.overlay.apply_draft(mode, draft)

                        record_mutation(("pane", pane_index, "overlay-source"), apply_overlay_draft)
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
                    focused_index = focused
                    pane = panes[focused_index]
                    if isinstance(pane, TuiAnimationPane):
                        animation_pane = pane
                        animation_now = time.monotonic()
                        handled_animation_key = True
                        if key == " ":
                            pane.session.set_host_paused(
                                not pane.session.host_paused,
                                animation_now,
                                pause_label=translator.text("status.animation_paused"),
                            )
                        elif key == "a":
                            adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                        else:
                            target_page = _animation_adjustment_target_page(adjustment_page, key)
                            if target_page is not None:
                                adjustment_page = target_page
                        if key in {" ", "a"}:
                            paint()
                            continue
                        if adjustment_page == "quick" and key in {"p", "P"}:
                            pane.overlay.cycle_position(1 if key == "p" else -1)
                        elif adjustment_page == "quick" and key in {"t", "T"}:

                            def set_animation_theme(
                                pane: TuiAnimationPane = animation_pane,
                                now: float = animation_now,
                                step: int = 1 if key == "t" else -1,
                            ) -> None:
                                pane.session.set_theme(
                                    _cycle(COLOR_SCHEMES, pane.session.theme, step), now
                                )

                            record_mutation(("pane", focused_index, "theme"), set_animation_theme)
                        elif adjustment_page == "quick" and key in {"s", "S"}:

                            def set_animation_style(
                                pane: TuiAnimationPane = animation_pane,
                                now: float = animation_now,
                                step: int = 1 if key == "s" else -1,
                            ) -> None:
                                cycle_animation_style(
                                    pane.session, target="pane", step=step, now=now
                                )

                            record_mutation(("pane", focused_index, "style"), set_animation_style)
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

                            def cycle_overlay_interval(
                                pane: TuiAnimationPane = animation_pane,
                                now: float = animation_now,
                            ) -> None:
                                pane.overlay.cycle_interval(now=now)

                            record_mutation(
                                ("pane", focused_index, "overlay-interval"), cycle_overlay_interval
                            )
                        elif adjustment_page == "advanced" and key == "l":
                            overlay_history = OverlayHistoryState(focused_index)
                        elif adjustment_page == "advanced" and key == "e":
                            overlay_editor = OverlayEditorState(
                                focused_index,
                                "command" if pane.overlay.config.command is not None else "text",
                                pane.overlay.text_draft,
                                pane.overlay.command_draft,
                            )
                        else:
                            handled_animation_key = False
                        if handled_animation_key:
                            paint()
                            continue
                    if isinstance(pane, TuiChartPane) and pane.body_view != "chart":
                        if key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                            offset = next_text_offset(
                                key,
                                offset=pane.text_offsets.get(pane.body_view, 0),
                                line_count=pane.text_line_counts.get(pane.body_view, 0),
                                visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                            )
                            assert offset is not None
                            pane.text_offsets[pane.body_view] = offset
                        elif key in {"v", "V"}:
                            record_mutation(
                                ("pane", focused, "view"),
                                lambda: setattr(pane, "body_view", next_body_view(pane.body_view)),
                            )
                        elif key in {"y", "Y"} and body_view_copy_kind(pane.body_view) is not None:
                            copy_kind = body_view_copy_kind(pane.body_view)
                            assert copy_kind is not None
                            copied = copy_command(
                                _pane_copy_payload(pane, translator, pane_terminal(focused))
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
                        paint()
                        continue
                    next_focused = _adjustment_target(focused, key, len(panes))
                    if next_focused != focused:
                        focused = next_focused
                        paint()
                        continue
                    if key == "r":
                        try:
                            choice = choose_pane_type("replace", focused)
                        except AdjustmentTimeout:
                            end_adjustment()
                            paint()
                            continue
                        if choice is not None:
                            choice_command = choice

                            def replace_pane(
                                pane_index: int = focused_index,
                                command: str = choice_command,
                            ) -> None:
                                _replace_pane(
                                    panes,
                                    pane_index,
                                    create_pane(command),
                                    start=start_new_pane,
                                )

                            record_mutation(("pane", focused_index, "replace"), replace_pane)
                        paint()
                        continue
                    if key in {"N", "n"}:
                        action = "insert_before" if key == "N" else "insert_after"
                        try:
                            choice = choose_pane_type(action, focused)
                        except AdjustmentTimeout:
                            end_adjustment()
                            paint()
                            continue
                        if choice is not None:
                            insert_at = focused_index if key == "N" else focused_index + 1
                            choice_command = choice

                            def insert(
                                index: int = insert_at,
                                command: str = choice_command,
                            ) -> None:
                                nonlocal active_grid, focused
                                active_grid = _grid_for_pane_count(active_grid, len(panes) + 1)
                                _insert_pane(
                                    panes,
                                    index,
                                    create_pane(command),
                                    start=start_new_pane,
                                )
                                focused = index

                            record_mutation(("pane", focused_index, action), insert)
                        paint()
                        continue
                    if key in {"{", "}", "J", "K"}:
                        adjust_pane_weight(
                            focused,
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
                    elif key == "v":
                        record_mutation(
                            ("pane", focused, "view"),
                            lambda: setattr(pane, "body_view", next_body_view(pane.body_view)),
                        )
                    elif (
                        adjustment_page == "advanced"
                        and key == "P"
                        and _project_grouping_available(_pane_display_options(pane).chart)
                    ):
                        pane.component.cycle_project_label_context()
                    elif (
                        adjustment_page == "advanced"
                        and pane.attachment is not None
                        and isinstance(_pane_display_options(pane).chart, MonitorConfig)
                        and _pane_display_options(pane).chart.presentation.style
                        in {"ranking", "list"}
                        and key in {"t", "T", "s", "S"}
                    ):
                        chart_pane = pane
                        attachment = chart_pane.attachment
                        assert attachment is not None

                        def adjust_attachment(
                            pane: TuiChartPane = chart_pane,
                            attachment: AnimationSessionState = attachment,
                            step: int = 1 if key in {"s", "t"} else -1,
                            adjust_style: bool = key in {"s", "S"},
                        ) -> None:
                            now = time.monotonic()
                            if adjust_style:
                                pane.attachment_enabled = cycle_monitor_attachment(
                                    attachment,
                                    enabled=pane.attachment_enabled,
                                    step=step,
                                    now=now,
                                )
                            else:
                                attachment.set_theme(
                                    _cycle(COLOR_SCHEMES, attachment.theme, step), now
                                )

                        record_mutation(
                            (
                                "pane",
                                focused_index,
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
                                if any(
                                    not header.coverage.covers(item) for item in required.intervals
                                ):
                                    refresh_header(trigger=LifecycleTrigger.CONFIGURATION)

                        record_mutation(("header", "style"), cycle_header)
                    elif key == "p":

                        def cycle_summary() -> None:
                            next_summary = _next_header_summary(header.summary_period)
                            header.summary_period = next_summary
                            header.generation += 1
                            header.lifecycle.detach_active()
                            if header_style != "hidden" and next_summary != "none":
                                required = required_summary_coverage(local_today(), next_summary)
                                if any(
                                    not header.coverage.covers(item) for item in required.intervals
                                ):
                                    refresh_header(trigger=LifecycleTrigger.CONFIGURATION)

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
                            if isinstance(pane, TuiChartPane) and pane.lifecycle.active is not None:
                                manual_refresh_operations.add(pane.lifecycle.active)
                    if refresh_header(
                        trigger=LifecycleTrigger.MANUAL,
                        replace_active=True,
                    ):
                        operation = header.lifecycle.active
                        if operation is not None:
                            manual_refresh_operations.add(operation)
                    paint(force=True)
                elif key in {"v", "V"}:

                    def cycle_dashboard_view() -> None:
                        nonlocal body_view
                        body_view = next_dashboard_body_view(body_view)

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
                elif body_view == "chart" and key == " ":
                    if adjustment_mode == "pane" and focused is not None:
                        pane = panes[focused]
                        if isinstance(pane, TuiAnimationPane):
                            now = time.monotonic()
                            pane.session.set_host_paused(
                                not pane.session.host_paused,
                                now,
                                pause_label=translator.text("status.animation_paused"),
                            )
                            paint()
                            continue
                    chart_panes = [item for item in panes if isinstance(item, TuiChartPane)]
                    animation_panes = [item for item in panes if isinstance(item, TuiAnimationPane)]
                    paused = all(item.lifecycle.paused for item in chart_panes) and all(
                        item.session.host_paused for item in animation_panes
                    )
                    now = time.monotonic()
                    dashboard_paused = not paused
                    if not paused:
                        header.scheduler.pause()
                        header.lifecycle.pause()
                        for item in chart_panes:
                            item.scheduler.pause()
                            item.lifecycle.pause()
                            if isinstance(item.component, MonitorComponent):
                                item.component.pause()
                            if item.attachment is not None:
                                item.attachment.set_host_paused(
                                    True,
                                    now,
                                    pause_label=translator.text("status.animation_paused"),
                                )
                        for item in panes:
                            if isinstance(item, TuiAnimationPane):
                                item.session.set_host_paused(
                                    True,
                                    now,
                                    pause_label=translator.text("status.animation_paused"),
                                )
                    else:
                        wall = datetime.now().astimezone()
                        header.lifecycle.resume()
                        header.scheduler.resume(now=now)
                        refresh_header(trigger=LifecycleTrigger.RESUME)
                        for index, item in enumerate(panes):
                            if not isinstance(item, TuiChartPane):
                                item.session.set_host_paused(False, now)
                                continue
                            item.lifecycle.resume()
                            item.scheduler.resume(now=now)
                            if isinstance(item.component, MonitorComponent):
                                item.component.resume(now=now, wall=wall)
                            if item.attachment is not None:
                                item.attachment.set_host_paused(False, now)
                            _clear_changes(item)
                            refresh(index, trigger=LifecycleTrigger.RESUME)
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
        header.scheduler.shutdown()
        header.lifecycle.shutdown()
        runtime.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        screen.finish()
