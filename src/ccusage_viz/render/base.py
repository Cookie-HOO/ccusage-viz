from __future__ import annotations

from collections.abc import Iterable, Iterator
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
    date_range = context.translator.text(
        "label.date_range", since=since.isoformat(), until=until.isoformat()
    )
    return f"{name} · {date_range}"


def configure_y_ticks(values: Iterable[int], *, count: int = 5) -> None:
    """Use stable decimal token labels instead of plotext's scientific notation."""
    maximum = max(values, default=0)
    positions = [0] if maximum <= 0 else [maximum * index / (count - 1) for index in range(count)]
    labels = [format_tokens(round(position)) for position in positions]
    plt.figure.ruler("y").ticks(positions, labels)


def date_ticks(days: tuple[date, ...], context: RenderContext) -> tuple[list[int], list[str]]:
    """Choose readable, localized date ticks for the available plot width."""
    if not days:
        return [], []
    crosses_year = days[0].year != days[-1].year
    verbose_width = 11 if crosses_year else 8
    usable_width = max(1, context.width - 12)
    verbose = usable_width >= len(days) * (verbose_width + 1)
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
