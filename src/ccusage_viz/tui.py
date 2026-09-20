from __future__ import annotations

import sys
import time
from collections.abc import Callable, Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from shutil import get_terminal_size

from ccusage_viz.acquisition import historical_provider_id, historical_query_intent
from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    format_full_dashboard_command,
    wrap_command,
)
from ccusage_viz.core.time import DateRange, refresh_date_range, today_for_timezone
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.dashboard_layout import (
    PaneLayout as ResolvedPaneLayout,
)
from ccusage_viz.dashboard_layout import (
    PaneRect,
    adjust_weight,
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
from ccusage_viz.diagnostics import format_error
from ccusage_viz.domain import UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.filter_draft import discover_filter_choices, run_filter_editor
from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
    pad_width,
    truncate_width,
)
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalCompletion,
    HistoricalPurpose,
    HistoricalSubmission,
    UsageSnapshot,
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
from ccusage_viz.render.palette import COLOR_SCHEMES, get_color_scheme
from ccusage_viz.render.summary import render_summary, render_summary_placeholder
from ccusage_viz.terminal import FramePainter, Terminal, compose_frame
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.tui_input import InputDecoder, KeyEvent, MouseEvent, read_event, tui_input_mode

_PANE_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor")


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


PaneFuture = Future[HistoricalOutcome] | Future[MonitorOutcome]


@dataclass(slots=True)
class TuiPane:
    component: HistoricalChartComponent | MonitorComponent
    scheduler: FixedIntervalScheduler
    lifecycle: LifecycleOperation[PaneFuture]
    demo_ordinal: int = 0
    render_warning: UsageError | None = None
    last_render: PaneRender | None = None
    body_view: BodyView = "chart"
    previous_values: dict[Hashable, float] = field(default_factory=dict)
    deltas: dict[Hashable, float] = field(default_factory=dict)
    values_initialized: bool = False
    previous_ranks: dict[Hashable, int] = field(default_factory=dict)
    rank_deltas: dict[Hashable, int] = field(default_factory=dict)

    @property
    def interval(self) -> float:
        return _pane_options(self).host.interval


def _pane_options(pane: TuiPane) -> StandaloneLaunch:
    return pane.component.accepted_options or pane.component.candidate


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
    today = today_for_timezone(base.host.timezone)
    interval = interval or DateInterval(today - timedelta(days=7), today)
    chart = TimelineConfig(
        "timeline",
        DateRange(interval.since, interval.until, base.host.timezone),
        presentation=ChartPresentation(theme=base.host.theme, style="linear", legend="hidden"),
        other="hide",
    )
    return StandaloneLaunch(
        base.process,
        StandaloneHostConfig(
            provider=base.host.provider,
            timezone=base.host.timezone,
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
    current = today or today_for_timezone(header.options.host.timezone)
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
        today_for_timezone(header.options.host.timezone),
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


def _dashboard_title_line(title: str, freshness: str, width: int) -> str:
    """Center the title while anchoring freshness at the right edge."""
    freshness = truncate_width(freshness, max(0, min(display_width(freshness), width // 2)))
    freshness_width = display_width(freshness)
    title = truncate_width(title, max(0, width - freshness_width - int(bool(freshness))))
    title_width = display_width(title)
    start = max(0, (width - title_width) // 2)
    if freshness_width:
        start = min(start, max(0, width - freshness_width - title_width - 1))
    line = " " * start + title
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
        detail = render_summary_placeholder(
            header.summary_period,
            today_for_timezone(header.options.host.timezone),
            RenderContext(
                terminal.width,
                1,
                translator,
                color=terminal.color,
                ascii=terminal.ascii,
                color_scheme=header.options.chart.presentation.theme,
            ),
        )
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
        return [_dashboard_title_line(compact_title, freshness, terminal.width)]
    title_line = _dashboard_title_line(title, freshness, terminal.width)
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
    displaced.scheduler.shutdown()
    displaced.lifecycle.shutdown()


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
    options: StandaloneLaunch,
    owner_id: str,
    runtime: QueryRuntime | None = None,
) -> TuiPane:
    registry = build_chart_registry()
    component: HistoricalChartComponent | MonitorComponent
    if isinstance(options.chart, MonitorConfig):
        component = MonitorComponent(
            options,
            owner_id=owner_id,
            runtime=runtime,
            registry=registry,
        )
    else:
        component = HistoricalChartComponent(
            options,
            owner_id=owner_id,
            runtime=runtime,
            registry=registry,
        )
    now = time.monotonic()
    return TuiPane(
        component,
        FixedIntervalScheduler(options.host.interval, now=now),
        LifecycleOperation(owner_id),
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


def _refresh_deltas(pane: TuiPane, values: dict[Hashable, float]) -> None:
    tracker = RefreshDeltas(
        pane.previous_values,
        pane.deltas,
        getattr(pane, "values_initialized", False),
    )
    tracker.accept(values)
    pane.previous_values = tracker.previous
    pane.deltas = tracker.current
    pane.values_initialized = tracker.initialized


def _refresh_ranks(pane: TuiPane, ordered_keys: tuple[Hashable, ...]) -> None:
    tracker = RefreshRanks(pane.previous_ranks, pane.rank_deltas)
    tracker.accept(ordered_keys)
    pane.previous_ranks = tracker.previous
    pane.rank_deltas = tracker.current


def _clear_changes(pane: TuiPane) -> None:
    pane.previous_values.clear()
    pane.deltas.clear()
    pane.values_initialized = False
    pane.previous_ranks.clear()
    pane.rank_deltas.clear()


@dataclass(frozen=True, slots=True)
class PaneRender:
    chart: str
    notices: tuple[str, ...] = ()


def _pane_copy_payload(pane: TuiPane, translator: Translator, terminal: Terminal) -> str:
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
            complete=True,
        )
    return render_snapshot_data(
        active,
        component.snapshot,
        translator,
        terminal,
        view=view,
        complete=True,
    )


def _pane_render(pane: TuiPane, translator: Translator, terminal: Terminal) -> PaneRender:
    active = _pane_options(pane)
    component = pane.component
    if pane.body_view == "command":
        return PaneRender(wrap_command(format_command(active), terminal.width))
    if pane.body_view == "full-command":
        return PaneRender(format_full_command_display(format_full_command(active), terminal.width))
    if pane.body_view in {"data-table", "data-json"}:
        if isinstance(component, MonitorComponent):
            if not isinstance(active.chart, MonitorConfig):
                raise TypeError("monitor pane component has historical configuration")
            buckets = component.buckets(
                max(8, min(32, terminal.width // 4)),
                now=time.monotonic(),
                wall=datetime.now().astimezone(),
            )
            return PaneRender(
                render_monitor_data(
                    buckets,
                    by=active.chart.by,
                    translator=translator,
                    terminal=terminal,
                    view=pane.body_view,
                )
            )
        return PaneRender(
            render_snapshot_data(
                active,
                component.snapshot,
                translator,
                terminal,
                view=pane.body_view,
            )
        )
    error = component.error
    if error is not None:
        return PaneRender(
            format_error(
                error,
                translator,
                color=terminal.color,
                color_scheme=active.chart.presentation.theme,
            )
            if isinstance(error, UsageError)
            else str(error)
        )
    try:
        if isinstance(component, MonitorComponent):
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
                hide_upper_right_axes=True,
                deltas=component.deltas,
                rank_deltas=component.rank_deltas,
                density=active.chart.presentation.density,
                audit=RenderAudit(
                    component.accepted_at,
                    component.last_elapsed,
                    pane.scheduler.interval,
                    "sample",
                    refreshing=pane.lifecycle.submission is not None,
                ),
            )
            candidate = PaneRender(
                component.render(
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


def _local_pane_content(
    chart: str,
    notices: tuple[str, ...],
    *,
    height: int,
) -> str:
    """Keep a bounded notice band inside one pane's content area."""
    notice_rows = min(len(notices), max(0, height - 3))
    chart_height = max(0, height - notice_rows)
    chart_lines = chart.splitlines()[:chart_height]
    chart_lines.extend("" for _ in range(chart_height - len(chart_lines)))
    return "\n".join((*chart_lines, *notices[:notice_rows]))


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


def _new_pane_options(command: str, base: DashboardLaunch) -> StandaloneLaunch:
    from ccusage_viz.configuration import default_pane, standalone_from_pane

    pane = default_pane(command, dashboard=base)
    if command == "monitor":
        pane = replace(pane, chart=replace(pane.chart, by="model", top=3))
    return standalone_from_pane(base, pane)


_PANE_QUICK_ACTIONS = {
    "timeline": (("p/P", "period"), ("g", "granularity"), ("b", "group"), ("+/-", "top")),
    "calendar": (("p/P", "period"),),
    "stack": (("p/P", "period"), ("g", "granularity")),
    "ranking": (("p/P", "period"), ("b", "group"), ("+/-", "top")),
    "monitor": (("w", "window"), ("b", "group"), ("+/-", "top")),
}
_PANE_ADVANCED_ACTIONS = {
    "timeline": (("o", "other"), ("l", "legend"), ("k", "weekdays")),
    "calendar": (),
    "stack": (("c", "cache"), ("l", "legend"), ("k", "weekdays")),
    "ranking": (("o", "other"),),
    "monitor": (("l", "legend"),),
}
_COMMON_PANE_QUICK_ACTIONS = (
    ("d", "density"),
    ("t/T", "theme"),
    ("s", "style"),
)
_COMMON_PANE_ADVANCED_ACTIONS = (("f", "filters"),)
_PANE_CONTENT_ACTIONS = (
    ("v", "view"),
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
    ("s", "style"),
    ("h", "header"),
    ("u", "summary"),
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


def _pane_adjustment_actions(
    command: str, page: str, translator: Translator
) -> tuple[AdjustmentAction, ...]:
    actions = (
        (*_PANE_QUICK_ACTIONS[command], *_COMMON_PANE_QUICK_ACTIONS)
        if page == "quick"
        else (*_PANE_ADVANCED_ACTIONS[command], *_COMMON_PANE_ADVANCED_ACTIONS)
    )
    return _localized_actions(actions, translator)


def _adjustment_controls(command: str, page: str, translator: Translator) -> str:
    return " · ".join(action.text for action in _pane_adjustment_actions(command, page, translator))


def _adjustment_key_supported(command: str, page: str, key: str) -> bool:
    actions = _PANE_QUICK_ACTIONS[command] if page == "quick" else _PANE_ADVANCED_ACTIONS[command]
    supported = {char for spelling, _label in actions for char in spelling if char not in "/"}
    supported.update({"d", "t", "T", "s"} if page == "quick" else ())
    return key in supported


def _query_affecting_adjustment(command: str, key: str) -> bool:
    """Return whether an adjustment needs a matching replacement snapshot."""
    return (
        key in {"p", "P"}
        or (key == "b" and command in {"timeline", "ranking", "monitor"})
        or (command == "monitor" and key == "w")
    )


def _pane_content_actions(body_view: BodyView) -> tuple[tuple[str, str], ...]:
    if body_view_copy_kind(body_view) is None:
        return _PANE_CONTENT_ACTIONS
    return (*_PANE_CONTENT_ACTIONS, ("y", "copy"))


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
) -> tuple[str, ...]:
    shared = adjustment_rows(
        state,
        translator.text(f"status.tui_adjust_{page}"),
        _pane_adjustment_actions(command, page, translator),
        width=width,
        color=False,
        switch_action=translator.text(
            "status.tui_switch_advanced" if page == "quick" else "status.tui_switch_quick"
        ),
        finish_action=translator.text("status.tui_finish_keys"),
    )
    return (
        *shared,
        clip_width(translator.text("status.tui_pane_management_divider"), width),
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


def _pane_adjustment_state(pane: TuiPane, page: str, translator: Translator) -> str:
    chart = _pane_options(pane).chart
    if page == "quick":
        settings = (
            f"{chart.kind} · {chart.presentation.density} · {chart.presentation.theme} · "
            f"{chart.presentation.style} · {pane.body_view}"
        )
    else:
        advanced: list[str] = []
        if isinstance(chart, (TimelineConfig, RankingConfig)):
            advanced.append(f"Other {chart.other}")
        if isinstance(chart, (TimelineConfig, StackConfig)):
            advanced.extend((f"Legend {chart.presentation.legend}", f"Weekdays {chart.weekdays}"))
        if isinstance(chart, StackConfig):
            advanced.insert(0, f"Cache {chart.cache}")
        if isinstance(chart, MonitorConfig):
            advanced.append(f"Legend {chart.presentation.legend}")
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
        return 0 if key == "s" and pane_count else None
    if key == "\t":
        return (focused + 1) % pane_count
    return focused


def _choose_layout_shortcut(
    screen: FramePainter,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
    current: str,
) -> str | None:
    index = _LAYOUT_SHORTCUTS.index(current) if current in _LAYOUT_SHORTCUTS else 0
    while True:
        choices = "\n".join(
            f"{'›' if item == _LAYOUT_SHORTCUTS[index] else ' '} {item}"
            for item in _LAYOUT_SHORTCUTS
        )
        screen.paint(
            compose_frame(
                choices,
                translator.text("label.adjust_layout"),
                translator.text("status.tui_layout_shortcuts_controls"),
                height=height,
            )
        )
        event = read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key in {"j", "\x1b[B"}:
            index = (index + 1) % len(_LAYOUT_SHORTCUTS)
        elif key in {"k", "\x1b[A"}:
            index = (index - 1) % len(_LAYOUT_SHORTCUTS)
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
) -> str | None:
    index = 0
    while True:
        choices = "\n".join(
            f"{'›' if item == _PANE_COMMANDS[index] else ' '} {item.title()}"
            for item in _PANE_COMMANDS
        )
        title = translator.text(f"status.tui_{action}_title")
        controls = translator.text(f"status.tui_{action}_controls")
        if paint_choices is None:
            screen.paint(compose_frame(choices, title, controls, height=height))
        else:
            paint_choices(choices, title, controls)
        event = read_event(decoder, 0.1)
        if not isinstance(event, KeyEvent):
            continue
        key = event.value
        if key in {"j", "\x1b[B"}:
            index = (index + 1) % len(_PANE_COMMANDS)
        elif key in {"k", "\x1b[A"}:
            index = (index - 1) % len(_PANE_COMMANDS)
        elif key in {"\r", "\n"}:
            return _PANE_COMMANDS[index]
        elif key == "\x1b":
            return None


def run_tui(options: DashboardLaunch, translator: Translator) -> int:
    from ccusage_viz.configuration import standalone_from_pane

    runtime = build_query_runtime()
    panes = [
        _new_pane(
            standalone_from_pane(options, pane),
            f"dashboard:pane:{index}",
            runtime,
        )
        for index, pane in enumerate(options.panes)
    ]
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
    browse_controls_hidden = False
    body_view: DashboardBodyView = "chart"
    chooser_overlay: tuple[int, str] | None = None
    copied_status: str | None = None
    pane_copy_status: str | None = None
    manual_refresh_operations: set[OperationToken] = set()
    last_successful_update: datetime | None = None
    last_size: tuple[int, int] | None = None
    screen = FramePainter(sys.stdout)

    def allocate_pane_owner_id() -> str:
        nonlocal next_pane_id
        owner_id = f"dashboard:pane:{next_pane_id}"
        next_pane_id += 1
        return owner_id

    def start_pane_submission(
        pane: TuiPane,
        operation: OperationToken,
    ) -> tuple[PaneFuture, Callable[[], None]]:
        component = pane.component
        if isinstance(component, MonitorComponent):
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
        try:
            return pane.lifecycle.start_ready(
                now=now,
                start=lambda operation: start_pane_submission(pane, operation),
            )
        except BaseException:
            return False

    def pane_records(pane: TuiPane) -> tuple[UsageRecord, ...]:
        component = pane.component
        if isinstance(component, MonitorComponent):
            return component.accepted_records
        return component.snapshot.records if component.snapshot is not None else ()

    def start_new_pane(index: int) -> None:
        refresh(index, trigger=LifecycleTrigger.STARTUP)

    def pane_includes_projects(pane: TuiPane) -> bool:
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
                date_range=DateRange(requested.since, requested.until, options.host.timezone),
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
            for lifecycle in (header.lifecycle, *(pane.lifecycle for pane in panes))
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
                    assert loaded.completion is not None
                    if isinstance(component, MonitorComponent):
                        assert isinstance(loaded, MonitorOutcome)
                        accepted = component.accept(
                            loaded.completion,
                            now=observed_at,
                            wall=datetime.now().astimezone(),
                        )
                        if accepted:
                            pane.demo_ordinal += 1
                    else:
                        assert isinstance(loaded, HistoricalOutcome)
                        accepted = component.accept(loaded.completion)
                        if accepted and component.candidate.chart.kind == "ranking":
                            _refresh_deltas(pane, component.ranking_values())
                            _refresh_ranks(pane, component.ranking_keys())
                    if accepted:
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

    def full_dashboard_command() -> str:
        return format_full_dashboard_command(
            replace(options, host=replace(options.host, theme=dashboard_theme)),
            tuple(PaneConfig(_pane_options(pane).chart) for pane in panes),
            grid=active_grid,
            layout=active_layout,
            column_weights=column_weights,
            row_weights=row_weights,
            header_style=header_style,
            header_summary=header.summary_period,
            dashboard_style=dashboard_style,
        )

    def controls() -> tuple[str, ...]:
        width = get_terminal_size().columns
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
            state = grid_error or _pane_adjustment_state(pane, adjustment_page, translator)
            if pane_copy_status is not None and grid_error is None:
                state = f"{pane_copy_status} · {state}"
            return _adjustment_footer(
                state,
                _pane_options(pane).chart.kind,
                adjustment_page,
                pane.body_view,
                translator,
                width,
            )
        if adjustment_mode == "global":
            state = translator.text(
                "status.tui_current_state",
                runtime=translator.text("status.tui_running"),
                settings=f"{active_layout or active_grid} · {dashboard_theme} · {dashboard_style} · "
                f"{header_style} · {header.summary_period}",
            )
            return _global_adjustment_footer(
                state=grid_error or state,
                translator=translator,
                width=width,
            )
        if browse_controls_hidden:
            return ()
        context = grid_error or translator.text(
            f"status.tui_{body_view.replace('-', '_')}_controls"
        )
        if copied_status is not None:
            context = f"{copied_status} · {context}"
        return (clip_width(context, width),)

    def notices() -> tuple[str, ...]:
        if manual_refresh_operations:
            return (translator.text("status.tui_refreshing"),)
        return ()

    def grid_geometry(
        size_columns: int,
        size_lines: int,
        header_rows: int,
        status_rows: int,
    ) -> ResolvedPaneLayout:
        nonlocal column_weights, row_weights
        grid_height = max(
            3, size_lines - len(controls()) - len(notices()) - header_rows - status_rows
        )
        bands = layout_bands(active_layout or active_grid, len(panes))
        column_weights = reconcile_weights(column_weights, bands.columns)
        row_weights = reconcile_weights(row_weights, bands.rows)
        return resolve_pane_layout(
            layout=active_layout or active_grid,
            pane_count=len(panes),
            width=size_columns,
            height=grid_height,
            divider_style=divider_style,
            column_weights=column_weights,
            row_weights=row_weights,
        )

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
        pane_options = _pane_options(panes[index])
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            pane_options.chart.presentation.theme != "no-color",
            pane_options.host.ascii,
        )

    def paint(*, force: bool = False) -> None:
        nonlocal last_size
        size = get_terminal_size()
        last_size = (size.columns, size.lines)
        header_terminal = Terminal(
            size.columns, 4, dashboard_theme != "no-color", options.host.ascii
        )
        header_lines = _header_lines(
            header, header_style, translator, header_terminal, last_successful_update
        )
        status = None
        if body_view != "chart":
            body = format_full_command_display(full_dashboard_command(), size.columns)
            screen.paint(
                compose_frame(body, status, controls(), notices(), height=size.lines), force=force
            )
            return
        initial_pending = all(
            pane.component.accepted_options is None and pane.component.error is None
            for pane in panes
        )
        if initial_pending:
            completed = sum(pane.lifecycle.submission is None for pane in panes)
            loading = center_text(
                f"{translator.text('label.dashboard')} · {translator.text('status.loading')} {completed}/{len(panes)}",
                size.columns,
            )
            body = "\n".join((*header_lines, loading))
            screen.paint(
                compose_frame(body, status, controls(), notices(), height=size.lines), force=force
            )
            return

        def render_panes(layout: ResolvedPaneLayout) -> list[str]:
            rendered_panes: list[str] = []
            for index, pane in enumerate(panes):
                rect = layout.pane(index)
                cell_width = rect.width
                cell_height = rect.height
                # The active frame-less pane gets a selection ring, so reserve its
                # interior too; its content is never overwritten by the indicator.
                framed = frame_style != "none" or index == focused
                pane_options = _pane_options(pane)
                interior_width = max(1, cell_width - 2 if framed else cell_width)
                interior_height = max(1, cell_height - 2 if framed else cell_height)
                terminal = Terminal(
                    interior_width,
                    interior_height,
                    pane_options.chart.presentation.theme != "no-color",
                    pane_options.host.ascii,
                )
                if chooser_overlay is not None and chooser_overlay[0] == index:
                    rendered_panes.append(chooser_overlay[1])
                    continue
                rendered = _pane_render(pane, translator, terminal)
                local_notices = format_notice_lines(
                    rendered.notices,
                    width=interior_width,
                    color=terminal.color,
                    ascii=terminal.ascii,
                    translator=translator,
                    color_scheme=pane_options.chart.presentation.theme,
                )
                rendered_panes.append(
                    _local_pane_content(
                        rendered.chart,
                        local_notices,
                        height=interior_height,
                    )
                )
            return rendered_panes

        layout = grid_geometry(size.columns, size.lines, len(header_lines), int(status is not None))
        pane_renders = render_panes(layout)
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
        body = "\n".join((*header_lines, grid))
        screen.paint(
            compose_frame(body, status, controls(), notices(), height=size.lines),
            force=force,
        )

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
            paint(force=True)

        try:
            return _choose_pane_type(
                screen,
                translator,
                decoder,
                height=get_terminal_size().lines,
                action=action,
                paint_choices=paint_choices,
            )
        finally:
            chooser_overlay = None

    def create_pane(command: str) -> TuiPane:
        return _new_pane(
            _new_pane_options(command, options),
            allocate_pane_owner_id(),
            runtime,
        )

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
                    if pane.scheduler.due(now=now):
                        refresh(index, trigger=LifecycleTrigger.PERIODIC)
                if changed:
                    paint()
                event = read_event(decoder, 0.1)
                if isinstance(event, MouseEvent):
                    if body_view == "chart" and event.pressed and event.button == 0:
                        size = get_terminal_size()
                        header_rows = len(
                            _header_lines(
                                header,
                                header_style,
                                translator,
                                Terminal(
                                    size.columns,
                                    4,
                                    dashboard_theme != "no-color",
                                    options.host.ascii,
                                ),
                                last_successful_update,
                            )
                        )
                        status = None
                        layout = grid_geometry(
                            size.columns,
                            size.lines,
                            header_rows,
                            int(status is not None),
                        )
                        selected = layout_pane_at(
                            layout,
                            event.x,
                            event.y - header_rows - 1,
                        )
                        if selected is not None:
                            focused = selected
                            adjustment_mode = "pane"
                            adjustment_page = "quick"
                            paint()
                    continue
                key = event.value if isinstance(event, KeyEvent) else None
                if key == "\x03":
                    raise KeyboardInterrupt
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
                            active_grid = parsed
                            active_layout = None
                            column_weights = None
                            row_weights = None
                            grid_draft = None
                            grid_error = None
                    elif key in {"\x7f", "\b"}:
                        grid_draft = grid_draft[:-1]
                    elif key and (key.isalnum() or key in {"x", "X", "-"}):
                        grid_draft += key
                    paint()
                    continue
                if adjustment_mode == "pane":
                    if key is None:
                        continue
                    if key in {"\r", "\n", "\x1b"}:
                        focused = None
                        adjustment_mode = None
                        pane_copy_status = None
                    else:
                        next_focused = _adjustment_target(focused, key, len(panes))
                        if next_focused != focused:
                            focused = next_focused
                            pane_copy_status = None
                        else:
                            assert focused is not None
                            pane = panes[focused]
                            if key == "a":
                                adjustment_page = (
                                    "advanced" if adjustment_page == "quick" else "quick"
                                )
                            elif adjustment_page == "advanced" and key == "f":
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
                                    editor_event = read_event(decoder, 0.1)
                                    return (
                                        editor_event.value
                                        if isinstance(editor_event, KeyEvent)
                                        else None
                                    )

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
                                if edited is not None and edited != base.chart.filters:
                                    _clear_changes(pane)
                                    component.configure(
                                        replace_chart_filters(base, edited),
                                        data_affecting=True,
                                    )
                                    refresh(
                                        focused,
                                        trigger=LifecycleTrigger.CONFIGURATION,
                                        data_affecting=False,
                                    )
                            elif key == "v":
                                pane.body_view = next_body_view(pane.body_view)
                                pane_copy_status = None
                            elif (
                                key in {"y", "Y"}
                                and body_view_copy_kind(pane.body_view) is not None
                            ):
                                copy_kind = body_view_copy_kind(pane.body_view)
                                assert copy_kind is not None
                                copied = copy_command(
                                    _pane_copy_payload(pane, translator, pane_terminal(focused))
                                )
                                pane_copy_status = translator.text(
                                    "status.command_copied"
                                    if copied and copy_kind in {"command", "full-command"}
                                    else "status.data_copied"
                                    if copied
                                    else "status.command_copy_failed"
                                )
                            elif key == "r":
                                choice = choose_pane_type("replace", focused)
                                if choice is not None:
                                    replacement = create_pane(choice)
                                    _replace_pane(
                                        panes,
                                        focused,
                                        replacement,
                                        start=start_new_pane,
                                    )
                            elif key in {"N", "n"}:
                                action = "insert_before" if key == "N" else "insert_after"
                                choice = choose_pane_type(action, focused)
                                if choice is not None:
                                    insert_at = focused if key == "N" else focused + 1
                                    inserted = create_pane(choice)
                                    active_grid = _grid_for_pane_count(active_grid, len(panes) + 1)
                                    _insert_pane(
                                        panes,
                                        insert_at,
                                        inserted,
                                        start=start_new_pane,
                                    )
                                    focused = insert_at
                            elif key in {"{", "}", "J", "K"}:
                                size = get_terminal_size()
                                header_rows = len(
                                    _header_lines(
                                        header,
                                        header_style,
                                        translator,
                                        Terminal(
                                            size.columns,
                                            4,
                                            dashboard_theme != "no-color",
                                            options.host.ascii,
                                        ),
                                        last_successful_update,
                                    )
                                )
                                layout = grid_geometry(size.columns, size.lines, header_rows, 0)
                                slot = layout.topology.slot(focused)
                                if key in {"{", "}"}:
                                    assert column_weights is not None
                                    column_weights = adjust_weight(
                                        column_weights,
                                        slot.column,
                                        1 if key == "}" else -1,
                                    )
                                else:
                                    assert row_weights is not None
                                    row_weights = adjust_weight(
                                        row_weights,
                                        slot.row,
                                        1 if key == "K" else -1,
                                    )
                            elif key == "[" and focused > 0:
                                panes[focused - 1], panes[focused] = (
                                    panes[focused],
                                    panes[focused - 1],
                                )
                                focused -= 1
                            elif key == "]" and focused < len(panes) - 1:
                                panes[focused], panes[focused + 1] = (
                                    panes[focused + 1],
                                    panes[focused],
                                )
                                focused += 1
                            elif key == "x" and len(panes) > 1:
                                removed = panes.pop(focused)
                                removed.scheduler.shutdown()
                                removed.lifecycle.shutdown()
                                active_grid = _grid_for_pane_count(active_grid, len(panes))
                                focused = min(focused, len(panes) - 1)
                            elif _adjustment_key_supported(
                                _pane_options(pane).chart.kind, adjustment_page, key
                            ):
                                component = pane.component
                                base = component.candidate
                                updated = adjust_standalone(base, key)
                                if updated != base:
                                    _clear_changes(pane)
                                    data_affecting = _query_affecting_adjustment(
                                        base.chart.kind, key
                                    )
                                    component.configure(updated, data_affecting=data_affecting)
                                    if updated.host.interval != base.host.interval:
                                        pane.scheduler.rebuild(
                                            updated.host.interval,
                                            now=time.monotonic(),
                                        )
                                    if data_affecting:
                                        refresh(
                                            focused,
                                            trigger=LifecycleTrigger.CONFIGURATION,
                                        )
                                    elif (
                                        isinstance(component, HistoricalChartComponent)
                                        and component.missing_comparison_coverage().intervals
                                    ):
                                        refresh(
                                            focused,
                                            trigger=LifecycleTrigger.CONFIGURATION,
                                            data_affecting=False,
                                        )
                    paint()
                    continue
                if adjustment_mode == "global":
                    if key in {"\r", "\n", "\x1b"}:
                        adjustment_mode = None
                        focused = None
                    elif key in {"t", "T"}:
                        dashboard_theme = _cycle(
                            COLOR_SCHEMES, dashboard_theme, 1 if key == "t" else -1
                        )
                        _set_header_theme(header, dashboard_theme)
                    elif key == "s":
                        dashboard_style = _cycle(DASHBOARD_STYLES, dashboard_style, 1)
                        divider_style, frame_style = _dashboard_structure(dashboard_style)
                    elif key == "h":
                        header_style = _cycle(
                            ("hidden", "compact", "banner", "panel"), header_style, 1
                        )
                        if header_style != "hidden" and header.summary_period != "none":
                            required = required_summary_coverage(
                                today_for_timezone(header.options.host.timezone),
                                header.summary_period,
                            )
                            if any(not header.coverage.covers(item) for item in required.intervals):
                                refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
                    elif key == "u":
                        next_summary = _next_header_summary(header.summary_period)
                        header.summary_period = next_summary
                        header.generation += 1
                        header.lifecycle.detach_active()
                        if header_style != "hidden" and next_summary != "none":
                            required = required_summary_coverage(
                                today_for_timezone(header.options.host.timezone), next_summary
                            )
                            if any(not header.coverage.covers(item) for item in required.intervals):
                                refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
                    elif key == "z":
                        shortcut = _choose_layout_shortcut(
                            screen,
                            translator,
                            decoder,
                            height=get_terminal_size().lines,
                            current=active_layout or active_grid,
                        )
                        if shortcut is not None:
                            resolved = _LAYOUT_SHORTCUT_VALUES[shortcut]
                            if shortcut in {"wide", "narrow", "all"}:
                                active_grid = resolved
                                active_layout = None
                            else:
                                active_layout = resolved
                            column_weights = None
                            row_weights = None
                            grid_error = None
                    elif key == "Z":
                        grid_draft = (
                            _practical_grid(len(panes))
                            if active_layout is not None
                            else active_grid
                        )
                        grid_error = None
                    else:
                        continue
                    paint()
                    continue
                if key in {"h", "H"}:
                    browse_controls_hidden = not browse_controls_hidden
                    paint(force=True)
                    continue
                if key == "r":
                    manual_refresh_operations.clear()
                    for index in range(len(panes)):
                        if refresh(
                            index,
                            trigger=LifecycleTrigger.MANUAL,
                            replace_active=True,
                        ):
                            operation = panes[index].lifecycle.active
                            if operation is not None:
                                manual_refresh_operations.add(operation)
                    if refresh_header(
                        trigger=LifecycleTrigger.MANUAL,
                        replace_active=True,
                    ):
                        operation = header.lifecycle.active
                        if operation is not None:
                            manual_refresh_operations.add(operation)
                    paint(force=True)
                elif key in {"v", "V"}:
                    body_view = next_dashboard_body_view(body_view)
                    copied_status = None
                elif key in {"y", "Y"} and body_view != "chart":
                    copied_status = translator.text(
                        "status.command_copied"
                        if copy_command(full_dashboard_command())
                        else "status.command_copy_failed"
                    )
                elif key == "\t":
                    continue
                elif key == " ":
                    paused = all(item.lifecycle.paused for item in panes)
                    now = time.monotonic()
                    if not paused:
                        header.scheduler.pause()
                        header.lifecycle.pause()
                        for item in panes:
                            item.scheduler.pause()
                            item.lifecycle.pause()
                            if isinstance(item.component, MonitorComponent):
                                item.component.pause()
                    else:
                        wall = datetime.now().astimezone()
                        header.lifecycle.resume()
                        header.scheduler.resume(now=now)
                        refresh_header(trigger=LifecycleTrigger.RESUME)
                        for index, item in enumerate(panes):
                            item.lifecycle.resume()
                            item.scheduler.resume(now=now)
                            if isinstance(item.component, MonitorComponent):
                                item.component.resume(now=now, wall=wall)
                            _clear_changes(item)
                            refresh(index, trigger=LifecycleTrigger.RESUME)
                elif key == "g" and body_view == "chart":
                    focused = None
                    adjustment_mode = "global"
                    adjustment_page = "quick"
                elif key == "s" and body_view == "chart":
                    focused = _adjustment_target(focused, key, len(panes))
                    adjustment_mode = "pane" if focused is not None else None
                    adjustment_page = "quick"
                else:
                    continue
                paint()
    except KeyboardInterrupt:
        return 0
    finally:
        for pane in panes:
            pane.scheduler.shutdown()
            pane.lifecycle.shutdown()
        header.scheduler.shutdown()
        header.lifecycle.shutdown()
        runtime.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        screen.finish()
