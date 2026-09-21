from __future__ import annotations

import re
from collections.abc import Hashable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from math import ceil
from typing import Literal, Protocol

import plotext as plt

from ccusage_viz.formatting import display_width, format_tokens, strip_ansi
from ccusage_viz.i18n import Translator
from ccusage_viz.render.palette import get_color_scheme


class ColorContext(Protocol):
    @property
    def color(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RenderAudit:
    accepted_at: datetime | None = None
    query_elapsed: float | None = None
    interval: float | None = None
    cadence: Literal["refresh", "sample"] = "refresh"
    refreshing: bool = False
    querying: bool = False


@dataclass(frozen=True, slots=True)
class RenderContext:
    width: int
    height: int
    translator: Translator
    color: bool = True
    ascii: bool = False
    color_scheme: str = "classic"
    style: str | None = None
    legend_position: str = "below-title"
    hide_upper_right_axes: bool = False
    deltas: Mapping[Hashable, float] | None = None
    rank_deltas: Mapping[Hashable, int] | None = None
    weekday_mode: str = "auto"
    period: str | None = None
    title_content: str | None = None
    filter_summary: str | None = None
    density: Literal["minimal", "compact", "full"] = "full"
    pending: bool = False
    audit: RenderAudit | None = None


@contextmanager
def isolated_plot() -> Iterator[None]:
    """Contain plotext's process-global figure state, including on exceptions."""
    plt.figure.clear()
    plt.figure.theme("default")
    try:
        yield
    finally:
        plt.figure.clear()
        plt.figure.theme("default")


def configure_plot(context: RenderContext) -> None:
    # The simple theme preserves the terminal's foreground and background.
    plt.figure.theme("simple" if context.color else "colorless")
    if context.hide_upper_right_axes:
        plt.figure.axes(False, axis=0, side=1)
        plt.figure.axes(False, axis=1, side=1)


_ANSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


_ASCII_PLOT_GLYPHS = str.maketrans(
    {
        "─": "-",
        "│": "|",
        "┌": "+",
        "┐": "+",
        "└": "+",
        "┘": "+",
        "├": "+",
        "┤": "+",
        "┬": "+",
        "┴": "+",
        "┼": "+",
        "█": "#",
        "▓": "#",
        "▒": "#",
        "░": "#",
    }
)


def render_audit(context: RenderContext) -> str:
    if context.density != "full" or context.audit is None:
        return ""
    audit = context.audit
    parts = []
    if audit.accepted_at is not None:
        parts.append(
            context.translator.text(
                "status.updated",
                time=audit.accepted_at.strftime("%H:%M:%S"),
            )
        )
    if audit.query_elapsed is not None:
        parts.append(
            context.translator.text(
                "status.query_time",
                seconds=f"{audit.query_elapsed:.2f}",
            )
        )
    if audit.interval is not None:
        parts.append(
            context.translator.text(
                "status.sample_every" if audit.cadence == "sample" else "status.refresh_every",
                seconds=f"{audit.interval:g}",
            )
        )
    if audit.refreshing:
        parts.append(
            styled_text(
                context.translator.text("status.refreshing"),
                get_color_scheme(context.color_scheme).muted,
                context,
                dim=True,
            )
        )
    return " · ".join(parts)


def title_with_querying(title: str, context: RenderContext) -> str:
    """Annotate a title with its active scope and incomplete-query state."""
    if context.filter_summary:
        title = f"{title} · {context.filter_summary}"
    if context.audit is None or not context.audit.querying:
        return title
    marker = styled_text(
        context.translator.text("status.querying"),
        get_color_scheme(context.color_scheme).muted,
        context,
        dim=True,
    )
    return f"{title} · {marker}"


def date_range_heading(name: str, since: date, until: date, context: RenderContext) -> str:
    if context.period is not None:
        return title_with_querying(f"{name} · {context.period}", context)
    date_range = context.translator.text(
        "label.date_range", since=since.isoformat(), until=until.isoformat()
    )
    return title_with_querying(f"{name} · {date_range}", context)


def content_heading(name: str, since: date, until: date, context: RenderContext) -> str:
    """Prefix a chart heading with its active content when requested."""
    heading = date_range_heading(name, since, until, context)
    return f"{context.title_content} · {heading}" if context.title_content else heading


def y_tick_spec(values: Iterable[int | float], *, count: int = 5) -> tuple[list[float], list[str]]:
    """Return stable decimal token positions and labels for a y-axis."""
    maximum = max(values, default=0)
    positions = [0] if maximum <= 0 else [maximum * index / (count - 1) for index in range(count)]
    return positions, [format_tokens(round(position)) for position in positions]


def configure_y_ticks(
    values: Iterable[int | float], *, count: int = 5, maximum: float | None = None
) -> None:
    """Use stable decimal labels instead of plotext's scientific notation."""
    positions, labels = y_tick_spec((maximum,) if maximum is not None else values, count=count)
    if maximum is not None:
        plt.figure.ruler("y").lim(0, maximum)
    plt.figure.ruler("y").ticks(positions, labels)


@dataclass(frozen=True, slots=True)
class ObservedStartMarker:
    position: float
    label: str | None
    alignment: Literal["left", "right"] | None


def observed_ticks(points: tuple[datetime, ...]) -> tuple[list[int], list[str]]:
    if not points:
        return [], []
    positions = sorted({0, len(points) // 2, len(points) - 1})
    return positions, [points[index].strftime("%H:%M") for index in positions]


def observed_start_marker(
    points: tuple[datetime, ...], *, started_at: datetime | None, context: RenderContext
) -> ObservedStartMarker | None:
    """Position the Monitor session boundary on an observed wall-clock axis."""
    if started_at is None or len(points) < 2 or points[0] >= points[-1]:
        return None
    if not points[0] <= started_at <= points[-1]:
        return None
    position = (
        (started_at - points[0]).total_seconds()
        / (points[-1] - points[0]).total_seconds()
        * (len(points) - 1)
    )
    if context.density == "minimal":
        return ObservedStartMarker(position, None, None)
    key = (
        "label.monitor_started_full"
        if context.density == "full"
        else "label.monitor_started_compact"
    )
    label = context.translator.text(key, time=started_at.strftime("%H:%M"))
    axis_width = max(1, context.width - 12)
    marker_column = position / max(1, len(points) - 1) * (axis_width - 1)
    tick_positions, tick_labels = observed_ticks(points)
    tick_ranges = [
        (
            index / max(1, len(points) - 1) * (axis_width - 1) - display_width(tick) / 2,
            index / max(1, len(points) - 1) * (axis_width - 1) + display_width(tick) / 2,
        )
        for index, tick in zip(tick_positions, tick_labels, strict=True)
    ]
    for alignment in ("right", "left"):
        if alignment == "right":
            label_range = (marker_column + 1, marker_column + 1 + display_width(label))
        else:
            label_range = (marker_column - 1 - display_width(label), marker_column - 1)
        if label_range[0] < 0 or label_range[1] > axis_width:
            continue
        if any(label_range[0] <= end and start <= label_range[1] for start, end in tick_ranges):
            continue
        return ObservedStartMarker(position, label, alignment)
    return ObservedStartMarker(position, None, None)


def date_ticks(
    days: tuple[date, ...], context: RenderContext, *, aggregation: str = "day"
) -> tuple[list[int], list[str]]:
    """Choose readable, localized date or period ticks for the plot width."""
    if not days:
        return [], []
    crosses_year = days[0].year != days[-1].year
    usable_width = max(1, context.width - 12)
    if aggregation != "day":
        period_width = 7 if aggregation == "month" else 7 if aggregation == "quarter" else 4
        capacity = max(2, usable_width // (period_width + 2))
        step = max(1, ceil((len(days) - 1) / max(1, capacity - 1)))
        positions = list(range(0, len(days), step))
        if positions[-1] != len(days) - 1:
            positions.append(len(days) - 1)
        labels = []
        for index in positions:
            day = days[index]
            labels.append(
                f"{day.year}-{day.month:02d}"
                if aggregation == "month"
                else f"{day.year}-Q{(day.month - 1) // 3 + 1}"
                if aggregation == "quarter"
                else str(day.year)
            )
        return positions, labels
    verbose_width = 11 if crosses_year else 8
    verbose = context.weekday_mode == "show" or (
        context.weekday_mode == "auto" and usable_width >= len(days) * (verbose_width + 1)
    )
    compact_width = 10 if crosses_year else 5
    capacity = max(2, usable_width // (compact_width + 2))
    step = max(1, ceil((len(days) - 1) / max(1, capacity - 1)))
    positions = list(range(0, len(days), step))
    if positions[-1] != len(days) - 1:
        positions.append(len(days) - 1)
    year_boundaries = [
        index for index in range(1, len(days)) if days[index].year != days[index - 1].year
    ]
    positions = sorted(set((*positions, *year_boundaries)))

    labels = []
    for index in positions:
        day = days[index]
        date_label = day.strftime("%Y-%m-%d" if crosses_year else "%m-%d")
        if verbose:
            weekday = context.translator.text(f"calendar.weekday.{day.weekday()}")
            # Plotext does not reserve a second ruler row for embedded newlines;
            # keep both parts visible in its supported single-line tick label.
            date_label = f"{weekday} {date_label}"
        labels.append(date_label)
    return positions, labels


def styled_text(
    text: str,
    color: int,
    context: ColorContext,
    *,
    bold: bool = False,
    dim: bool = False,
) -> str:
    """Style text with foreground only, preserving the terminal background."""
    if not context.color:
        return text
    style = "bold" if bold else "dim" if dim else None
    return plt.colorize(text, plt.pixel(foreground=color, style=style)).string()


def colored_mark(mark: str, color: int, context: RenderContext) -> str:
    return styled_text(mark, color, context)


def background_mark(mark: str, color: int, context: RenderContext) -> str:
    """Render a terminal cell with a themed background when color is available."""
    if not context.color:
        return mark
    return plt.colorize(mark, plt.pixel(background=color)).string()


def overlay_plot_column(
    chart: str,
    *,
    column: int,
    glyph: str,
    style: str | None = None,
) -> str:
    """Overlay one narrow glyph in each plot row without disturbing its ANSI styling."""
    rows = chart.splitlines()
    if len(rows) < 4:
        return chart
    replacement = style if style else glyph

    def replace_cell(row: str) -> str:
        visible = 0
        position = 0
        while position < len(row):
            match = _ANSI_SEQUENCE.match(row, position)
            if match:
                position = match.end()
                continue
            width = display_width(row[position])
            if visible == column and width == 1:
                return f"{row[:position]}{replacement}{row[position + 1 :]}"
            visible += width
            position += 1
        return row

    return "\n".join(
        replace_cell(row) if 0 < index < len(rows) - 3 else row for index, row in enumerate(rows)
    )


def plot_height(context: RenderContext, *, text_rows: int) -> int:
    """Size plotext so its axis rows fill the renderer's available chart area."""
    return max(8, context.height - text_rows + 1)


def plot_text(context: RenderContext) -> str:
    output = plt.figure.build()
    text = output if isinstance(output, str) else str(output)
    if not context.color:
        text = strip_ansi(text)
    return text.translate(_ASCII_PLOT_GLYPHS) if context.ascii else text
