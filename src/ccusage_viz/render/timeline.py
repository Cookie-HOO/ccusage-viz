from __future__ import annotations

import plotext as plt

from ccusage_viz.chart_models import TimelineModel
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import center_text, clip_width
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
from ccusage_viz.render.palette import categorical_colors, get_color_scheme
from ccusage_viz.render.summary import render_summary


def render_timeline(model: TimelineModel, context: RenderContext) -> str:
    if not model.series:
        return context.translator.text("message.no_data")
    if context.style == "area" and len(model.series) != 1:
        raise UsageError(
            "error.arguments", detail="timeline area style requires exactly one visible series"
        )
    sole_total = len(model.series) == 1 and model.series[0].key in {"total", ("total",)}
    # The default Total view stays uncluttered, but an explicit in-chart legend
    # request should still reveal its sole series while adjusting appearance.
    show_legend = not sole_total or context.legend_position == "inside"
    with isolated_plot():
        configure_plot(context)
        scheme = get_color_scheme(context.color_scheme)
        colors = categorical_colors(
            (series.key for series in model.series if not series.is_other), context.color_scheme
        )
        marker_names = ("dot", "circle", "diamond", "square", "cross", "star", "up", "xmark")
        marker_labels = ("•", "○", "◆", "■", "✚", "✱", "▲", "×")
        ascii_marker_labels = (".", "o", "D", "#", "+", "*", "^", "x")
        legend = (
            clip_width(
                " · ".join(
                    "{} {}".format(
                        colored_mark(
                            "#"
                            if series.is_other and context.ascii
                            else "◆"
                            if series.is_other
                            else (
                                ascii_marker_labels[index % len(ascii_marker_labels)]
                                if context.ascii
                                else marker_labels[index % len(marker_labels)]
                            ),
                            scheme.other if series.is_other else colors[series.key],
                            context,
                        ),
                        context.translator.text("label.other") if series.is_other else series.label,
                    )
                    for index, series in enumerate(model.series)
                ),
                context.width,
            )
            if show_legend and context.legend_position == "below-title"
            else ""
        )
        title = context.translator.text("label.timeline")
        if not show_legend:
            title = f"{title} · {context.translator.text('label.total')}"
        heading = center_text(
            date_range_heading(title, model.days[0], model.days[-1], context), context.width
        )
        plt.figure.plot_size(
            context.width,
            plot_height(
                context,
                text_rows=1
                + int(model.summary is not None)
                + int(show_legend and context.legend_position == "below-title"),
            ),
        )
        for index, series in enumerate(model.series):
            color = scheme.other if series.is_other else colors[series.key]
            marker_name = "." if context.ascii else marker_names[index % len(marker_names)]
            marker = plt.marker(
                marker_name,
                pixel=plt.pixel(foreground=color) if context.color else None,
            )
            x_values = list(range(len(model.days)))
            y_values = [value.total for value in series.values]
            if context.style == "step":
                x_values = [item for index in x_values for item in (index, index + 1)]
                y_values = [item for value in y_values for item in (value, value)]
            signal = plt.figure.signal(x_values, y_values, marker=marker).lines(
                context.style != "stem"
            )
            if context.style == "stem":
                signal.fillx()
            if context.style == "area":
                signal.fillx()
            if show_legend and context.legend_position == "inside":
                signal.label(
                    context.translator.text("label.other") if series.is_other else series.label
                )
            plt.figure.draw(signal)
        if context.legend_position == "inside":
            plt.figure.legend(active=True)
        else:
            plt.figure.legend(False)
        positions, labels = date_ticks(model.days, context)
        plt.figure.ruler("x").ticks(positions, labels)
        configure_y_ticks(value.total for series in model.series for value in series.values)
        chart = plot_text(context)
        summary = render_summary(model.summary, context) if model.summary else ""
        return "\n".join(line for line in (summary, heading, legend, chart) if line)
