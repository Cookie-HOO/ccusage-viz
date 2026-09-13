from __future__ import annotations

import plotext as plt

from ccusage_viz.chart_models import StackModel
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import center_text
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
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary


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
        plt.figure.plot_size(
            context.width,
            plot_height(context, text_rows=1 + int(show_legend) + int(model.summary is not None)),
        )
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
            marker_names = ("full",) * len(model.components)
        component_markers = marker_names[: len(model.components)]
        markers = [
            plt.marker(
                marker_name,
                plt.pixel(foreground=color) if context.color else None,
            )
            for marker_name, color in zip(component_markers, colors, strict=True)
        ]
        grouped = context.style in {"grouped", "grouped-thin"}
        group_width = 0.8 if context.style == "grouped" else 0.28
        if grouped and context.width < 12 + len(model.days) * 2:
            raise UsageError("error.stack_grouped_width", width=context.width)
        x_positions = list(range(len(model.days)))
        if grouped:
            component_count = len(model.components)
            bar_width = group_width / component_count
            center = (component_count - 1) / 2
            for index, (component, marker) in enumerate(zip(values, markers, strict=True)):
                offset = (index - center) * bar_width
                component_positions = [position + offset for position in x_positions]
                signal = plt.figure.bar(
                    component_positions,
                    component,
                    marker=marker,
                    width=bar_width,
                )
                plt.figure.draw(signal)
        else:
            signal = plt.figure.bar(
                x_positions,
                values,
                marker=markers,
                width=group_width,
                stacked=True,
            )
            plt.figure.draw(signal)
        positions, tick_labels = date_ticks(model.days, context)
        plt.figure.ruler(
            "x",
        ).ticks([x_positions[index] for index in positions], tick_labels)
        if normalized:
            plt.figure.ruler("y").ticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
        else:
            configure_y_ticks(
                sum(component.values[index].total for component in model.components)
                for index in range(len(model.days))
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
        return "\n".join(
            line for line in (prefix.rstrip(), heading, legend_line, plot_text(context)) if line
        )
