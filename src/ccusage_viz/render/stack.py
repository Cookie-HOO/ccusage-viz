from __future__ import annotations

import plotext as plt

from ccusage_viz.chart_models import StackModel
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import center_text, char_width, display_width, pad_width
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    configure_y_ticks,
    date_range_heading,
    date_ticks,
    isolated_plot,
    plot_height,
    plot_text,
    styled_text,
    y_tick_spec,
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary


def _stack_tick_spec(
    values: list[list[float]], *, normalized: bool
) -> tuple[list[float], list[str]]:
    if normalized:
        return [0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"]
    return y_tick_spec(
        sum(component[index] for component in values) for index in range(len(values[0]))
    )


def _stack_grid(
    values: list[list[float]],
    *,
    tick_positions: list[float],
    tick_labels: list[str],
    date_positions: list[int],
    date_labels: list[str],
    component_marks: tuple[str, ...],
    colors: list[int],
    context: RenderContext,
) -> str:
    """Render stacked columns on a preallocated terminal-cell grid."""
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
            cumulative = 0.0
            for component_index, component in enumerate(values):
                lower = round(cumulative / maximum * data_rows)
                cumulative += component[day_index]
                upper = round(cumulative / maximum * data_rows)
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
            data_rows - 1 - round(position / maximum * (data_rows - 1)): label
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


def render_stack(model: StackModel, context: RenderContext) -> str:
    if not model.components or model.total.total == 0:
        return context.translator.text("message.no_data")
    with isolated_plot():
        configure_plot(context)
        heading = center_text(
            date_range_heading(
                context.translator.text("label.stack"), model.days[0], model.days[-1], context
            ),
            context.width,
        )
        show_legend = context.legend_position == "below-title"
        raw_values = [[usage.total for usage in component.values] for component in model.components]
        normalized = context.style == "normalized"
        if normalized:
            values = [
                [
                    value / sum(component[index] for component in raw_values) * 100
                    if sum(component[index] for component in raw_values)
                    else 0
                    for index, value in enumerate(component)
                ]
                for component in raw_values
            ]
        else:
            values = raw_values
        labels = [
            context.translator.text(f"label.{component.label}") for component in model.components
        ]
        scheme = get_color_scheme(context.color_scheme)
        colors = [scheme.component(component.label) for component in model.components]
        if context.style == "stacked-pattern":
            marker_names = (
                ("#", "=", "+", ":", "%", "@") if context.ascii else ("/", "\\", "x", "=", "+", ":")
            )
        else:
            marker_names = (
                ("#",) * len(model.components) if context.ascii else ("█",) * len(model.components)
            )
        component_marks = marker_names[: len(model.components)]
        grouped = context.style in {"grouped", "grouped-thin"}
        group_width = 0.8 if context.style == "grouped" else 0.28
        x_positions = list(range(len(model.days)))
        positions, tick_labels = date_ticks(model.days, context, aggregation=model.aggregation)
        if grouped:
            if context.width < 12 + len(model.days) * 2:
                raise UsageError("error.stack_grouped_width", width=context.width)
            plt.figure.plot_size(
                context.width,
                plot_height(
                    context, text_rows=1 + int(show_legend) + int(model.summary is not None)
                ),
            )
            component_count = len(model.components)
            bar_width = group_width / component_count
            center = (component_count - 1) / 2
            for index, (component, marker_name, color) in enumerate(
                zip(values, component_marks, colors, strict=True)
            ):
                offset = (index - center) * bar_width
                component_positions = [position + offset for position in x_positions]
                signal = plt.figure.bar(
                    component_positions,
                    component,
                    marker=plt.marker(
                        marker_name,
                        plt.pixel(foreground=color) if context.color else None,
                    ),
                    width=bar_width,
                )
                plt.figure.draw(signal)
            plt.figure.ruler("x").ticks([x_positions[index] for index in positions], tick_labels)
            configure_y_ticks(
                sum(component.values[index].total for component in model.components)
                for index in range(len(model.days))
            )
            chart = plot_text(context)
        else:
            tick_positions, y_labels = _stack_tick_spec(values, normalized=normalized)
            chart = _stack_grid(
                values,
                tick_positions=tick_positions,
                tick_labels=y_labels,
                date_positions=positions,
                date_labels=tick_labels,
                component_marks=component_marks,
                colors=colors,
                context=context,
            )
        legend_marks = (
            ("#", "=", "+", ":", "%", "@")[: len(model.components)]
            if context.ascii
            else ("█", "■", "●", "◆", "✚", "•")[: len(model.components)]
        )
        legend = [
            f"{colored_mark(mark, color, context)} {label}"
            for mark, label, color in zip(legend_marks, labels, colors, strict=True)
        ]
        separator = " / " if context.ascii else " · "
        prefix = f"{render_summary(model.summary, context)}\n" if model.summary else ""
        legend_line = separator.join(legend) if show_legend else ""
        return "\n".join(line for line in (prefix.rstrip(), heading, legend_line, chart) if line)
