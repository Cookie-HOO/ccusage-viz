"""Domain-neutral stack presentation primitives for historical charts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import cast

import plotext as plt

from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import char_width, display_width, format_tokens, pad_width
from ccusage_viz.render.base import RenderContext, plot_height, plot_text, styled_text

StackNumber = float | Decimal


def _numeric_zero(value: StackNumber) -> StackNumber:
    return Decimal() if isinstance(value, Decimal) else 0.0


def _stack_totals(values: Sequence[Sequence[StackNumber]]) -> list[StackNumber]:
    return [
        sum((component[index] for component in values), start=_numeric_zero(values[0][index]))
        for index in range(len(values[0]))
    ]


def _scaled_row(value: StackNumber, maximum: StackNumber, rows: int) -> int:
    if isinstance(value, Decimal) and isinstance(maximum, Decimal):
        return round(value / maximum * rows)
    return round(float(value) / float(maximum) * rows)


def stack_tick_spec(
    values: Sequence[Sequence[StackNumber]], *, normalized: bool
) -> tuple[list[StackNumber], list[str]]:
    """Return the shared axis values for a stack chart."""
    if normalized:
        return [0.0, 25.0, 50.0, 75.0, 100.0], ["0%", "25%", "50%", "75%", "100%"]
    maximum = max(_stack_totals(values), default=0.0)
    positions: list[StackNumber] = (
        [0.0] if maximum <= 0 else [maximum * index / 4 for index in range(5)]
    )
    return positions, [format_tokens(round(position)) for position in positions]


def normalized_stack_values(values: Sequence[Sequence[StackNumber]]) -> list[list[StackNumber]]:
    """Normalize components per date without crossing the numeric-domain boundary."""
    totals = _stack_totals(values)
    return [
        [
            (
                value / cast(Decimal, total) * Decimal(100)
                if isinstance(value, Decimal)
                else value / cast(float, total) * 100.0
            )
            if total
            else _numeric_zero(value)
            for value, total in zip(component, totals, strict=True)
        ]
        for component in values
    ]


def render_grouped_stack_plot(
    values: Sequence[Sequence[StackNumber]],
    *,
    date_count: int,
    date_positions: Sequence[int],
    date_labels: Sequence[str],
    component_marks: Sequence[str],
    colors: Sequence[int],
    context: RenderContext,
    y_ticks: Callable[[], None],
    text_rows: int,
) -> str:
    """Render grouped stack bars from neutral facts through the Plotext boundary."""
    if context.width < 12 + date_count * 2:
        raise UsageError("error.stack_grouped_width", width=context.width)
    group_width = 0.8 if context.style == "grouped" else 0.28
    component_count = len(values)
    bar_width = group_width / component_count
    center = (component_count - 1) / 2
    plt.figure.plot_size(context.width, plot_height(context, text_rows=text_rows))
    for index, component in enumerate(values):
        marker = plt.marker(
            component_marks[index],
            plt.pixel(foreground=colors[index]) if context.color else None,
        )
        signal = plt.figure.bar(
            [day + (index - center) * bar_width for day in range(date_count)],
            [float(value) for value in component],
            marker=marker,
            width=bar_width,
        )
        plt.figure.draw(signal)
    plt.figure.ruler("x").ticks(date_positions, date_labels)
    y_ticks()
    return plot_text(context)


def render_stack_grid(
    values: Sequence[Sequence[StackNumber]],
    *,
    tick_positions: Sequence[StackNumber],
    tick_labels: Sequence[str],
    date_positions: Sequence[int],
    date_labels: Sequence[str],
    component_marks: Sequence[str],
    colors: Sequence[int],
    context: RenderContext,
) -> str:
    """Render stacked columns from neutral numeric facts on a terminal-cell grid."""
    date_count = len(values[0])
    label_width = max(display_width(label) for label in tick_labels)
    gutter = label_width + 2
    plot_width = context.width - gutter
    if plot_width < date_count:
        raise UsageError("error.stack_stacked_width", width=context.width)

    slot_bounds = [index * plot_width // date_count for index in range(date_count + 1)]
    slot_widths = [slot_bounds[index + 1] - slot_bounds[index] for index in range(date_count)]
    bar_width = max(1, min(4, min(slot_widths) - 1))
    bar_starts = [
        slot_bounds[index] + (slot_widths[index] - bar_width) // 2 for index in range(date_count)
    ]
    data_rows = max(4, plot_height(context, text_rows=1) - 4)
    maximum = tick_positions[-1] if tick_positions else 0
    grid = [[" "] * plot_width for _ in range(data_rows)]

    if maximum:
        for day_index in range(date_count):
            cumulative = _numeric_zero(maximum)
            for component_index, component in enumerate(values):
                lower = _scaled_row(cumulative, maximum, data_rows)
                cumulative = (
                    cumulative + cast(Decimal, component[day_index])
                    if isinstance(cumulative, Decimal)
                    else cumulative + cast(float, component[day_index])
                )
                upper = _scaled_row(cumulative, maximum, data_rows)
                for row in range(data_rows - upper, data_rows - lower):
                    if 0 <= row < data_rows:
                        for column in range(
                            bar_starts[day_index], bar_starts[day_index] + bar_width
                        ):
                            grid[row][column] = styled_text(
                                component_marks[component_index], colors[component_index], context
                            )

    tick_rows = (
        {
            data_rows - 1 - _scaled_row(position, maximum, data_rows - 1): label
            for position, label in zip(tick_positions, tick_labels, strict=True)
        }
        if maximum
        else {data_rows - 1: tick_labels[0]}
    )
    axis = "+" if context.ascii else "┼"
    vertical = "|" if context.ascii else "│"
    horizontal = "-" if context.ascii else "─"
    lines = []
    for row, cells in enumerate(grid):
        label = tick_rows.get(row, "")
        lines.append(pad_width(label, label_width, align="right") + f" {vertical}" + "".join(cells))
    lines.append(" " * (label_width + 1) + axis + horizontal * plot_width)

    labels = [" "] * plot_width
    occupied = [False] * plot_width
    for index, label in zip(date_positions, date_labels, strict=True):
        width = display_width(label)
        center = (slot_bounds[index] + slot_bounds[index + 1]) // 2
        start = center - width // 2
        end = start + width
        if start < 0 or end > plot_width:
            continue
        nearby_start = max(0, start - 1)
        nearby_end = min(plot_width, end + 1)
        if any(occupied[nearby_start:nearby_end]):
            continue
        position = start
        for character in label:
            character_width = char_width(character)
            labels[position] = character
            for offset in range(1, character_width):
                labels[position + offset] = ""
            position += character_width
        occupied[start:end] = [True] * width
    lines.append(" " * gutter + "".join(labels))
    return "\n".join(lines)
