from __future__ import annotations

from collections.abc import Hashable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from math import ceil

import plotext as plt

from ccusage_viz.formatting import format_tokens, strip_ansi
from ccusage_viz.i18n import Translator


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


def date_range_heading(name: str, since: date, until: date, context: RenderContext) -> str:
    if context.period is not None:
        return f"{name} · {context.period}"
    date_range = context.translator.text(
        "label.date_range", since=since.isoformat(), until=until.isoformat()
    )
    return f"{name} · {date_range}"


def content_heading(name: str, since: date, until: date, context: RenderContext) -> str:
    """Prefix a chart heading with its active content when requested."""
    heading = date_range_heading(name, since, until, context)
    return f"{context.title_content} · {heading}" if context.title_content else heading


def y_tick_spec(values: Iterable[int], *, count: int = 5) -> tuple[list[float], list[str]]:
    """Return stable decimal token positions and labels for a y-axis."""
    maximum = max(values, default=0)
    positions = [0] if maximum <= 0 else [maximum * index / (count - 1) for index in range(count)]
    return positions, [format_tokens(round(position)) for position in positions]


def configure_y_ticks(values: Iterable[int], *, count: int = 5) -> None:
    """Use stable decimal token labels instead of plotext's scientific notation."""
    positions, labels = y_tick_spec(values, count=count)
    plt.figure.ruler("y").ticks(positions, labels)


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
    context: RenderContext,
    *,
    bold: bool = False,
) -> str:
    """Style text with foreground only, preserving the terminal background."""
    if not context.color:
        return text
    style = "bold" if bold else None
    return plt.colorize(text, plt.pixel(foreground=color, style=style)).string()


def colored_mark(mark: str, color: int, context: RenderContext) -> str:
    return styled_text(mark, color, context)


def plot_height(context: RenderContext, *, text_rows: int) -> int:
    """Reserve renderer-owned text rows and plotext's final margin."""
    return max(8, context.height - text_rows - 1)


def plot_text(context: RenderContext) -> str:
    output = plt.figure.build()
    text = output if isinstance(output, str) else str(output)
    if not context.color:
        text = strip_ansi(text)
    return text.translate(_ASCII_PLOT_GLYPHS) if context.ascii else text
