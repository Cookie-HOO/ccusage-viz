from __future__ import annotations

import sys
import time
from collections.abc import Hashable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from shutil import get_terminal_size

from ccusage_viz.acquisition import historical_provider_id, historical_query_intent
from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.command_copy import (
    copy_command,
    format_dashboard_pane_command,
    format_full_command_display,
    format_full_dashboard_command,
)
from ccusage_viz.core.time import DateRange, refresh_date_range, today_for_timezone
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.data_view import DashboardBodyView, next_dashboard_body_view
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.diagnostics import format_error
from ccusage_viz.domain import UsageRecord
from ccusage_viz.errors import UsageError
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
    HistoricalSubmission,
    UsageSnapshot,
    snapshot_from_result,
)
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import Translator
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
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
)
from ccusage_viz.processing import build_period_summary, required_summary_coverage
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult, QueryTrigger
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import COLOR_SCHEMES, get_color_scheme
from ccusage_viz.render.summary import render_summary, render_summary_placeholder
from ccusage_viz.terminal import InteractiveScreen, Terminal
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.tui_input import InputDecoder, KeyEvent, MouseEvent, read_event, tui_input_mode

_PANE_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor")


@dataclass(frozen=True, slots=True)
class HistoricalOutcome:
    generation: int
    completion: HistoricalCompletion | None = None
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class MonitorOutcome:
    generation: int
    completion: MonitorCompletion | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class TuiPane:
    component: HistoricalChartComponent | MonitorComponent
    future: Future[HistoricalOutcome | MonitorOutcome] | None = None
    query_handle: QueryHandle[ProviderResult] | None = None
    refreshed_at: float = 0.0
    demo_ordinal: int = 0
    render_warning: UsageError | None = None
    last_render: PaneRender | None = None
    copied: bool = False
    pending_trigger: QueryTrigger | None = None
    previous_values: dict[Hashable, float] = field(default_factory=dict)
    deltas: dict[Hashable, float] = field(default_factory=dict)
    values_initialized: bool = False
    previous_ranks: dict[Hashable, int] = field(default_factory=dict)
    rank_deltas: dict[Hashable, int] = field(default_factory=dict)
    owner_id: str = "dashboard:pane"

    @property
    def interval(self) -> float:
        return _pane_options(self).host.interval


def _pane_options(pane: TuiPane) -> StandaloneLaunch:
    return pane.component.accepted_options or pane.component.candidate


@dataclass(slots=True)
class DashboardHeader:
    options: StandaloneLaunch
    runtime: QueryRuntime
    snapshot: UsageSnapshot | None = None
    future: Future[UsageSnapshot] | None = None
    query_handle: QueryHandle[ProviderResult] | None = None
    refreshed_at: float = 0.0
    error: str | None = None
    generation: int = 0
    submitted_generation: int | None = None
    submitted_options: StandaloneLaunch | None = None
    pending_trigger: QueryTrigger | None = None
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
    return replace(summary, all_agents=True) if summary is not None else None


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
            all_agents=True,
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
    if grid == "auto":
        columns = 1 if count == 1 else 2
        return (count + columns - 1) // columns, columns
    rows, columns = (int(part) for part in grid.lower().split("x", 1))
    return rows, columns


def parse_grid(value: str, pane_count: int) -> str | None:
    """Normalize a session layout only when it can display every pane."""
    if value.casefold() == "auto":
        return "auto"
    try:
        rows, columns = (int(part) for part in value.lower().split("x", 1))
    except ValueError:
        return None
    if rows < 1 or columns < 1 or rows * columns < pane_count:
        return None
    return f"{rows}x{columns}"


@dataclass(frozen=True, slots=True)
class PaneRect:
    index: int
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class PanelLayout:
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
) -> PanelLayout:
    """Allocate every grid row and column, including uneven remainders."""
    gutter = 0 if divider_style == "none" else 1
    available_width = max(columns * 4, width - gutter * (columns - 1))
    available_height = max(rows * 3, height - gutter * (rows - 1))
    width_base, width_remainder = divmod(available_width, columns)
    height_base, height_remainder = divmod(available_height, rows)
    return PanelLayout(
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


def compose_panels(
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
    return TuiPane(component=component, owner_id=owner_id)


def _await_historical(
    handle: QueryHandle[ProviderResult], started: float
) -> UsageSnapshot:
    return snapshot_from_result(handle.result(), time.monotonic() - started)


def _await_historical_submission(submission: HistoricalSubmission) -> HistoricalOutcome:
    try:
        return HistoricalOutcome(submission.generation, completion=submission.result())
    except BaseException as exc:
        return HistoricalOutcome(submission.generation, error=exc)


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


def _pane_render(pane: TuiPane, translator: Translator, terminal: Terminal) -> PaneRender:
    active = _pane_options(pane)
    component = pane.component
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
                terminal.height,
                translator,
                color=terminal.color,
                ascii=terminal.ascii,
                color_scheme=active.chart.presentation.theme,
                style=active.chart.presentation.style,
                legend_position=active.chart.presentation.legend,
                hide_upper_right_axes=True,
                deltas=component.deltas,
                rank_deltas=component.rank_deltas,
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


def _unique_notices(panes: list[PaneRender]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(notice for pane in panes for notice in pane.notices))


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


def _new_pane_options(command: str, base: DashboardLaunch) -> StandaloneLaunch:
    from ccusage_viz.configuration import default_pane, standalone_from_pane

    pane = default_pane(command, dashboard=base)
    if command == "monitor":
        pane = replace(pane, chart=replace(pane.chart, by="model", top=3))
    return standalone_from_pane(base, pane)


_QUICK_KEYS = {
    "timeline": frozenset("pPgbB+-=tTsS"),
    "calendar": frozenset("pPtTsS"),
    "stack": frozenset("pPgtTsS"),
    "ranking": frozenset("pPbB+-=tTsS"),
    "monitor": frozenset("wWbB+-=tTsS"),
}
_ADVANCED_KEYS = {
    "timeline": frozenset("olkuOLKU"),
    "calendar": frozenset("uU"),
    "stack": frozenset("clkuCLKU"),
    "ranking": frozenset("ouOU"),
    "monitor": frozenset("lL"),
}


def _adjustment_controls(command: str, page: str, translator: Translator) -> str:
    key = (
        "status.tui_adjust_monitor_pane_quick_controls"
        if command == "monitor" and page == "quick"
        else f"status.tui_adjust_{command}_{page}_controls"
    )
    return translator.text(key)


def _adjustment_key_supported(command: str, page: str, key: str) -> bool:
    keys = _QUICK_KEYS if page == "quick" else _ADVANCED_KEYS
    return key in keys[command]


def _query_affecting_adjustment(command: str, key: str) -> bool:
    """Return whether an adjustment needs a matching replacement snapshot."""
    return key in {"p", "P"} or (
        key in {"b", "B"} and command in {"timeline", "ranking", "monitor"}
    ) or (command == "monitor" and key in {"w", "W", "i", "I"})


def _adjustment_footer(
    command: str, page: str, translator: Translator, width: int
) -> tuple[tuple[str, str, str], tuple[int, int]]:
    """Compose the three adjustment rows and final-row Finish hit target."""
    heading = translator.text(f"status.tui_adjust_{page}")
    settings = f"{heading} · {_adjustment_controls(command, page, translator)}"
    management = translator.text("status.tui_adjust_management")
    finish = f"[{translator.text('status.tui_finish')}]"
    finish_width = display_width(finish)
    if finish_width >= width:
        final = pad_width(clip_width(finish, width), width)
        target = (1, max(1, display_width(final)))
    else:
        gap = width - finish_width
        final = " " * gap + finish
        target = (gap + 1, width)
    return (
        pad_width(clip_width(settings, width), width),
        pad_width(clip_width(management, width), width),
        final,
    ), target


def _finish_clicked(
    event: MouseEvent, *, adjusting: bool, width: int, height: int, hit_target: tuple[int, int]
) -> bool:
    return (
        adjusting
        and event.pressed
        and event.button == 0
        and event.y == height
        and hit_target[0] <= event.x <= min(width, hit_target[1])
    )


def _adjustment_target(focused: int | None, key: str, pane_count: int) -> int | None:
    if key == "\x1b":
        return None
    if focused is None:
        return 0 if key == "s" and pane_count else None
    if key == "\t":
        return (focused + 1) % pane_count
    return focused


def _dashboard_adjustment_status(
    *, adjusting: bool, focused: int | None, pane_count: int, translator: Translator
) -> str | None:
    if not adjusting or focused is None:
        return None
    key = (
        "status.tui_dashboard_adjust_multiple" if pane_count > 1 else "status.tui_dashboard_adjust"
    )
    return translator.text(key)


def _choose_pane_type(
    screen: InteractiveScreen,
    translator: Translator,
    decoder: InputDecoder,
    *,
    height: int,
) -> str | None:
    index = 0
    while True:
        choices = "\n".join(
            f"{'›' if item == _PANE_COMMANDS[index] else ' '} {item.title()}"
            for item in _PANE_COMMANDS
        )
        screen.paint(
            choices,
            translator.text("status.tui_add_title"),
            translator.text("status.tui_add_controls"),
            height=height,
        )
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
    copied_status: str | None = None
    scheduling_paused = False
    last_successful_update: datetime | None = None
    last_size: tuple[int, int] | None = None
    footer_notice_rows = 0
    screen = InteractiveScreen(sys.stdout)

    def allocate_pane_owner_id() -> str:
        nonlocal next_pane_id
        owner_id = f"dashboard:pane:{next_pane_id}"
        next_pane_id += 1
        return owner_id

    def refresh(
        index: int,
        *,
        trigger: QueryTrigger,
        queue_if_running: bool = False,
    ) -> None:
        pane = panes[index]
        if pane.future is not None and not pane.future.done():
            if queue_if_running:
                pane.pending_trigger = trigger
                if pane.query_handle is not None:
                    pane.query_handle.cancel()
            return
        component = pane.component
        if isinstance(component, MonitorComponent):
            submission = component.submit(
                trigger,
                sample_ordinal=pane.demo_ordinal + 1,
            )
            pane.query_handle = submission.handle
            pane.future = executor.submit(_await_monitor_submission, submission)
            return
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
        submission = component.submit(trigger)
        pane.query_handle = submission.handle
        pane.future = executor.submit(_await_historical_submission, submission)

    def refresh_header(
        *,
        trigger: QueryTrigger,
        queue_if_running: bool = False,
        aggressive: bool = False,
    ) -> None:
        requested = _header_refresh_interval(header, aggressive=aggressive)
        if requested is None:
            return
        if header.future is not None and not header.future.done():
            if queue_if_running:
                header.pending_trigger = trigger
                if header.query_handle is not None:
                    header.query_handle.cancel()
            return
        header.error = None
        header.submitted_generation = header.generation
        submitted = replace(
            header.options,
            chart=replace(
                header.options.chart,
                date_range=DateRange(requested.since, requested.until, options.host.timezone),
            ),
        )
        header.submitted_options = submitted
        header.refreshed_at = time.monotonic()
        intent = historical_query_intent(
            submitted,
            header.runtime.definition(historical_provider_id(submitted)),
            owner_id="dashboard:header",
            generation=header.generation,
            trigger=trigger,
        )
        started = time.monotonic()
        header.query_handle = header.runtime.submit(intent)
        header.future = executor.submit(_await_historical, header.query_handle, started)

    def collect() -> bool:
        nonlocal last_successful_update
        changed = False
        future = header.future
        if future is not None and future.done():
            submitted_generation = header.submitted_generation
            submitted_options = header.submitted_options
            header.future = None
            header.query_handle = None
            header.submitted_generation = None
            header.submitted_options = None
            try:
                result = future.result()
                if submitted_generation == header.generation and submitted_options is not None:
                    header.records = _replace_header_interval(header.records, result)
                    header.coverage = header.coverage.merge(result.coverage)
                    header.snapshot = result
                    header.accepted_at = datetime.now().astimezone()
                    last_successful_update = header.accepted_at
                    changed = True
            except Exception as exc:
                if submitted_generation == header.generation:
                    header.error = str(exc)
                    changed = True
            if header.pending_trigger is not None:
                trigger = header.pending_trigger
                header.pending_trigger = None
                refresh_header(trigger=trigger)
        for index, pane in enumerate(panes):
            future = pane.future
            if future is None or not future.done():
                continue
            component = pane.component
            pane.future = None
            pane.query_handle = None
            observed_at = time.monotonic()
            outcome_generation: int | None = None
            try:
                loaded = future.result()
                outcome_generation = loaded.generation
                if loaded.error is not None:
                    if component.fail(loaded.error, generation=loaded.generation):
                        pane.refreshed_at = observed_at
                        changed = True
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
                        pane.refreshed_at = observed_at
                        last_successful_update = component.accepted_at
                        changed = True
            except Exception as exc:
                if outcome_generation is not None and component.fail(
                    exc, generation=outcome_generation
                ):
                    pane.refreshed_at = observed_at
                    changed = True
            if pane.pending_trigger is not None:
                trigger = pane.pending_trigger
                pane.pending_trigger = None
                refresh(index, trigger=trigger)
        return changed

    def full_dashboard_command() -> str:
        return format_full_dashboard_command(
            replace(options, host=replace(options.host, theme=dashboard_theme)),
            tuple(PaneConfig(_pane_options(pane).chart) for pane in panes),
            grid=active_grid,
            header_style=header_style,
            header_summary=header.summary_period,
            dashboard_style=dashboard_style,
        )

    def controls() -> tuple[str, ...]:
        width = get_terminal_size().columns
        if adjustment_mode == "pane" and focused is not None:
            return _adjustment_footer(
                _pane_options(panes[focused]).chart.kind,
                adjustment_page,
                translator,
                width
            )[0]
        if adjustment_mode == "global":
            keys = translator.text(f"status.tui_global_{adjustment_page}_controls")
            finish = f"[{translator.text('status.tui_finish')}]"
            return (
                clip_width(
                    f"{translator.text(f'status.tui_adjust_{adjustment_page}')} · {keys}", width
                ),
                clip_width(translator.text("status.tui_global_management"), width),
                pad_width(finish, width),
            )
        if browse_controls_hidden and grid_draft is None:
            return ()
        if grid_draft is not None:
            context = translator.text("status.tui_layout_prompt", value=grid_draft)
        else:
            context = grid_error or translator.text(
                f"status.tui_{body_view.replace('-', '_')}_controls"
            )
            if copied_status is not None:
                context = f"{context} · {copied_status}"
        return (clip_width(context, width),)

    def grid_geometry(
        size_columns: int,
        size_lines: int,
        header_rows: int,
        status_rows: int,
        notice_rows: int = 0,
    ) -> tuple[int, int, PanelLayout]:
        rows, columns = _grid_shape(active_grid, len(panes))
        grid_height = max(3, size_lines - len(controls()) - header_rows - status_rows - notice_rows)
        return (
            rows,
            columns,
            resolve_panel_layout(
                width=size_columns,
                height=grid_height,
                rows=rows,
                columns=columns,
                divider_style=divider_style,
            ),
        )

    def paint(*, force: bool = False) -> None:
        nonlocal footer_notice_rows, last_size
        size = get_terminal_size()
        last_size = (size.columns, size.lines)
        header_terminal = Terminal(
            size.columns, 4, dashboard_theme != "no-color", options.host.ascii
        )
        header_lines = _header_lines(
            header, header_style, translator, header_terminal, last_successful_update
        )
        status = _dashboard_adjustment_status(
            adjusting=adjustment_mode == "pane",
            focused=focused,
            pane_count=len(panes),
            translator=translator,
        )
        if body_view != "chart":
            footer_notice_rows = 0
            body = format_full_command_display(full_dashboard_command(), size.columns)
            screen.paint(body, status, controls(), height=size.lines, force=force)
            return
        initial_pending = all(
            pane.refreshed_at == 0.0 and pane.component.error is None for pane in panes
        )
        if initial_pending:
            completed = sum(pane.future is None for pane in panes)
            loading = center_text(
                f"{translator.text('label.dashboard')} · {translator.text('status.loading')} {completed}/{len(panes)}",
                size.columns,
            )
            body = "\n".join((*header_lines, loading))
            screen.paint(body, status, controls(), height=size.lines, force=force)
            return

        def render_panes(layout: PanelLayout, columns: int) -> list[PaneRender]:
            rendered_panes = []
            for index, pane in enumerate(panes):
                cell_width = layout.widths[index % columns]
                cell_height = layout.heights[index // columns]
                # The active frame-less pane gets a selection ring, so reserve its
                # interior too; its content is never overwritten by the indicator.
                framed = frame_style != "none" or index == focused
                pane_options = _pane_options(pane)
                terminal = Terminal(
                    max(1, cell_width - 2 if framed else cell_width),
                    max(1, cell_height - 2 if framed else cell_height),
                    pane_options.chart.presentation.theme != "no-color",
                    pane_options.host.ascii,
                )
                rendered_panes.append(_pane_render(pane, translator, terminal))
            return rendered_panes

        rows, columns, layout = grid_geometry(
            size.columns, size.lines, len(header_lines), int(status is not None)
        )
        pane_renders = render_panes(layout, columns)
        notices = _unique_notices(pane_renders)
        notice_lines = format_notice_lines(
            notices,
            width=size.columns,
            color=dashboard_theme != "no-color",
            ascii=options.host.ascii,
            translator=translator,
            color_scheme=dashboard_theme,
        )
        if notice_lines:
            rows, columns, layout = grid_geometry(
                size.columns,
                size.lines,
                len(header_lines),
                int(status is not None),
                len(notice_lines),
            )
            pane_renders = render_panes(layout, columns)
            notices = _unique_notices(pane_renders)
            notice_lines = format_notice_lines(
                notices,
                width=size.columns,
                color=dashboard_theme != "no-color",
                ascii=options.host.ascii,
                translator=translator,
                color_scheme=dashboard_theme,
            )
        footer_notice_rows = len(notice_lines)
        grid = compose_panels(
            [pane.chart for pane in pane_renders],
            size.columns,
            layout.height,
            rows,
            columns,
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
            body,
            status,
            controls(),
            notice_lines,
            height=size.lines,
            force=force,
        )

    try:
        with tui_input_mode() as decoder:
            for index in range(len(panes)):
                refresh(index, trigger=QueryTrigger.STARTUP)
            if header_style != "hidden":
                refresh_header(trigger=QueryTrigger.STARTUP)
            paint()
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                changed = collect()
                now = time.monotonic()
                if (
                    not scheduling_paused
                    and header_style != "hidden"
                    and header.future is None
                    and now - header.refreshed_at >= options.host.header_interval
                ):
                    refresh_header(trigger=QueryTrigger.TICK)
                for index, pane in enumerate(panes):
                    if (
                        not scheduling_paused
                        and pane.future is None
                        and now - pane.refreshed_at >= pane.interval
                    ):
                        refresh(index, trigger=QueryTrigger.TICK)
                if changed:
                    paint()
                event = read_event(decoder, 0.1)
                if isinstance(event, MouseEvent):
                    if body_view == "chart" and event.pressed and event.button == 0:
                        size = get_terminal_size()
                        if adjustment_mode == "pane" and focused is not None:
                            _, finish_target = _adjustment_footer(
                                _pane_options(panes[focused]).chart.kind,
                                adjustment_page,
                                translator,
                                size.columns,
                            )
                            if _finish_clicked(
                                event,
                                adjusting=True,
                                width=size.columns,
                                height=size.lines,
                                hit_target=finish_target,
                            ):
                                focused = None
                                adjustment_mode = None
                                paint()
                                continue
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
                        status = _dashboard_adjustment_status(
                            adjusting=adjustment_mode == "pane",
                            focused=focused,
                            pane_count=len(panes),
                            translator=translator,
                        )
                        rows, columns, layout = grid_geometry(
                            size.columns,
                            size.lines,
                            header_rows,
                            int(status is not None),
                            footer_notice_rows,
                        )
                        selected = pane_at(
                            pane_rects(
                                pane_count=len(panes),
                                width=size.columns,
                                height=layout.height,
                                rows=rows,
                                columns=columns,
                                divider_style=divider_style,
                                top=header_rows + 1,
                            ),
                            event.x,
                            event.y,
                        )
                        if selected is not None:
                            focused = selected
                            adjustment_mode = "pane"
                            adjustment_page = "quick"
                            panes[selected].copied = False
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
                            grid_draft = None
                            grid_error = None
                    elif key in {"\x7f", "\b"}:
                        grid_draft = grid_draft[:-1]
                    elif key and (key.isalnum() or key in {"x", "X"}):
                        grid_draft += key
                    paint()
                    continue
                if adjustment_mode == "pane":
                    next_focused = _adjustment_target(focused, key or "", len(panes))
                    if next_focused is None:
                        focused = None
                        adjustment_mode = None
                    elif next_focused != focused:
                        focused = next_focused
                    else:
                        assert focused is not None
                        pane = panes[focused]
                        if key in {"a", "A"}:
                            adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                        elif key == "[" and focused > 0:
                            panes[focused - 1], panes[focused] = panes[focused], panes[focused - 1]
                            focused -= 1
                        elif key == "]" and focused < len(panes) - 1:
                            panes[focused], panes[focused + 1] = panes[focused + 1], panes[focused]
                            focused += 1
                        elif key in {"x", "X"} and len(panes) > 1:
                            removed = panes.pop(focused)
                            if removed.query_handle is not None:
                                removed.query_handle.cancel()
                            focused = min(focused, len(panes) - 1)
                        elif key in {"y", "Y"}:
                            pane.copied = copy_command(
                                format_dashboard_pane_command(
                                    _pane_options(pane),
                                    refresh_interval=options.host.refresh_interval,
                                    sampling_interval=options.host.sampling_interval,
                                )
                            )
                        elif key is not None and _adjustment_key_supported(
                            _pane_options(pane).chart.kind, adjustment_page, key
                        ):
                            component = pane.component
                            base = component.candidate
                            updated = adjust_standalone(base, key)
                            if updated != base:
                                _clear_changes(pane)
                                data_affecting = _query_affecting_adjustment(base.chart.kind, key)
                                component.configure(updated, data_affecting=data_affecting)
                                if data_affecting:
                                    refresh(
                                        focused,
                                        trigger=QueryTrigger.REFRESH,
                                        queue_if_running=True,
                                    )
                    paint()
                    continue
                if adjustment_mode == "global":
                    if key == "\x1b":
                        adjustment_mode = None
                        focused = None
                    elif key in {"a", "A"}:
                        adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                    elif key in {"y", "Y"}:
                        copy_command(full_dashboard_command())
                    elif adjustment_page == "quick" and key in {"t", "T"}:
                        dashboard_theme = _cycle(
                            COLOR_SCHEMES, dashboard_theme, 1 if key == "t" else -1
                        )
                        _set_header_theme(header, dashboard_theme)
                    elif adjustment_page == "quick" and key in {"s", "S"}:
                        dashboard_style = _cycle(
                            DASHBOARD_STYLES, dashboard_style, 1 if key == "s" else -1
                        )
                        divider_style, frame_style = _dashboard_structure(dashboard_style)
                    elif adjustment_page == "quick" and key == "w":
                        header_style = _cycle(
                            ("hidden", "compact", "banner", "panel"), header_style, 1
                        )
                        if header_style != "hidden" and header.summary_period != "none":
                            required = required_summary_coverage(
                                today_for_timezone(header.options.host.timezone),
                                header.summary_period,
                            )
                            if any(not header.coverage.covers(item) for item in required.intervals):
                                refresh_header(
                                    trigger=QueryTrigger.REFRESH, queue_if_running=True
                                )
                    elif adjustment_page == "quick" and key == "u":
                        next_summary = _next_header_summary(header.summary_period)
                        header.summary_period = next_summary
                        header.generation += 1
                        if header_style != "hidden" and next_summary != "none":
                            required = required_summary_coverage(
                                today_for_timezone(header.options.host.timezone), next_summary
                            )
                            if any(not header.coverage.covers(item) for item in required.intervals):
                                refresh_header(
                                    trigger=QueryTrigger.REFRESH, queue_if_running=True
                                )
                    elif adjustment_page == "quick" and key == "z":
                        grid_draft = ""
                        grid_error = None
                    elif adjustment_page == "advanced" and key == "\t":
                        focused = 0 if focused is None else (focused + 1) % len(panes)
                    elif (
                        adjustment_page == "advanced"
                        and key == "["
                        and focused is not None
                        and focused > 0
                    ):
                        panes[focused - 1], panes[focused] = panes[focused], panes[focused - 1]
                        focused -= 1
                    elif (
                        adjustment_page == "advanced"
                        and key == "]"
                        and focused is not None
                        and focused < len(panes) - 1
                    ):
                        panes[focused], panes[focused + 1] = panes[focused + 1], panes[focused]
                        focused += 1
                    elif (
                        adjustment_page == "advanced"
                        and key in {"x", "X"}
                        and focused is not None
                        and len(panes) > 1
                    ):
                        removed = panes.pop(focused)
                        if removed.query_handle is not None:
                            removed.query_handle.cancel()
                        focused = min(focused, len(panes) - 1)
                    elif adjustment_page == "advanced" and key == "+":
                        grid_error = None
                        rows, columns = _grid_shape(active_grid, len(panes))
                        if active_grid != "auto" and rows * columns == len(panes):
                            grid_error = translator.text("error.tui_grid_full", layout=active_grid)
                        else:
                            choice = _choose_pane_type(
                                screen,
                                translator,
                                decoder,
                                height=get_terminal_size().lines,
                            )
                            if choice:
                                panes.append(
                                    _new_pane(
                                        _new_pane_options(choice, options),
                                        allocate_pane_owner_id(),
                                        runtime,
                                    )
                                )
                                focused = len(panes) - 1
                                refresh(focused, trigger=QueryTrigger.STARTUP)
                    else:
                        continue
                    paint()
                    continue
                if key in {"h", "H"}:
                    browse_controls_hidden = not browse_controls_hidden
                    paint(force=True)
                    continue
                if key == "r":
                    for index in range(len(panes)):
                        refresh(
                            index,
                            trigger=QueryTrigger.REFRESH,
                            queue_if_running=True,
                        )
                    refresh_header(
                        trigger=QueryTrigger.REFRESH,
                        queue_if_running=True,
                        aggressive=True,
                    )
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
                    scheduling_paused = not scheduling_paused
                    now = time.monotonic()
                    if scheduling_paused:
                        for item in panes:
                            if isinstance(item.component, MonitorComponent):
                                item.component.pause()
                    else:
                        wall = datetime.now().astimezone()
                        header.refreshed_at = now
                        for item in panes:
                            item.refreshed_at = now
                            if isinstance(item.component, MonitorComponent):
                                item.component.resume(now=now, wall=wall)
                            _clear_changes(item)
                elif key == "g" and body_view == "chart":
                    focused = None
                    adjustment_mode = "global"
                    adjustment_page = "quick"
                elif key == "s" and body_view == "chart":
                    focused = _adjustment_target(focused, key, len(panes))
                    adjustment_mode = "pane" if focused is not None else None
                    adjustment_page = "quick"
                    if focused is not None:
                        panes[focused].copied = False
                else:
                    continue
                paint()
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        screen.finish()
