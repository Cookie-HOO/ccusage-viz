from __future__ import annotations

from math import isfinite

import plotext as plt

from ccusage_viz.chart_models import ScalarSeries, Series, TimelineModel
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import center_text, clip_width
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    configure_y_ticks,
    content_heading,
    date_range_heading,
    date_ticks,
    isolated_plot,
    observed_ticks,
    plot_height,
    plot_text,
)
from ccusage_viz.render.palette import categorical_colors, get_color_scheme
from ccusage_viz.render.summary import render_summary


def _observed_heading(model: TimelineModel, context: RenderContext) -> str:
    scope = model.observed_scope
    if scope is None:
        raise ValueError("observed timeline is missing its scope")
    window = (
        f"{scope.window_seconds // 3600}h"
        if scope.window_seconds % 3600 == 0
        else f"{scope.window_seconds // 60}m"
    )
    mode = context.translator.text(f"label.monitor_{scope.mode}_mode")
    state = (
        f" · {context.translator.text(f'label.monitor_{scope.state}')}"
        if scope.state != "ready"
        else ""
    )
    agents = f" · Agent {', '.join(scope.agents)}" if scope.agents else ""
    return context.translator.text(
        "label.monitor_growth_title" if model.metric.unit == "tokens" else "label.monitor_title",
        window=window,
        state=state,
        agents=agents,
        mode=mode,
    )


def render_timeline(model: TimelineModel, context: RenderContext) -> str:
    scope = model.observed_scope
    observed = scope is not None
    series: tuple[Series | ScalarSeries, ...] = model.observed_series if observed else model.series
    if not series:
        if observed:
            heading = center_text(_observed_heading(model, context), context.width)
            return f"{heading}\n{context.translator.text('message.monitor_empty')}"
        return context.translator.text("message.no_data")
    if context.style == "area" and len(series) != 1:
        raise UsageError("error.timeline_area_series")
    sole_total = len(series) == 1 and series[0].key in {"total", "Total", ("total",)}
    # The default Total view stays uncluttered, but any explicit legend position
    # should be honored while adjusting appearance.
    show_legend = (
        not sole_total
        and context.legend_position != "hidden"
        or (sole_total and context.legend_position == "inside")
    )
    with isolated_plot():
        configure_plot(context)
        scheme = get_color_scheme(context.color_scheme)
        colors = categorical_colors(
            (item.key for item in series if not item.is_other), context.color_scheme
        )
        marker_names = ("dot", "circle", "diamond", "square", "cross", "star", "up", "xmark")
        marker_labels = ("•", "○", "◆", "■", "✚", "✱", "▲", "×")
        ascii_marker_labels = (".", "o", "D", "#", "+", "*", "^", "x")
        uniform_points = context.style in {"points", "line-points"}

        def legend_mark(index: int, is_other: bool) -> str:
            if uniform_points:
                return "." if context.ascii else "•"
            if is_other:
                return "#" if context.ascii else "◆"
            return (
                ascii_marker_labels[index % len(ascii_marker_labels)]
                if context.ascii
                else marker_labels[index % len(marker_labels)]
            )

        legend = (
            clip_width(
                " · ".join(
                    "{} {}".format(
                        colored_mark(
                            legend_mark(index, series.is_other),
                            scheme.other if series.is_other else colors[series.key],
                            context,
                        ),
                        context.translator.text("label.other") if series.is_other else series.label,
                    )
                    for index, series in enumerate(series)
                ),
                context.width,
            )
            if show_legend and context.legend_position == "below-title"
            else ""
        )
        title = context.translator.text("label.timeline")
        if observed:
            heading_text = _observed_heading(model, context)
        elif context.title_content:
            heading_text = content_heading(title, model.days[0], model.days[-1], context)
        else:
            if not show_legend:
                title = f"{title} · {context.translator.text('label.total')}"
            heading_text = date_range_heading(title, model.days[0], model.days[-1], context)
        heading = center_text(heading_text, context.width)
        plt.figure.plot_size(
            context.width,
            plot_height(
                context,
                text_rows=1
                + int(model.summary is not None)
                + int(show_legend and context.legend_position == "below-title"),
            ),
        )
        for index, item in enumerate(series):
            color = scheme.other if item.is_other else colors[item.key]
            marker_name = (
                "."
                if context.ascii
                else "dot"
                if uniform_points
                else marker_names[index % len(marker_names)]
            )
            marker = plt.marker(
                marker_name,
                pixel=plt.pixel(foreground=color) if context.color else None,
            )
            x_values = list(range(len(model.observed_at) if observed else len(model.days)))
            if isinstance(item, ScalarSeries):
                y_values = [float("nan") if value is None else value for value in item.values]
                if context.style == "bars":
                    y_values = [value if isfinite(value) else 0.0 for value in y_values]
            else:
                y_values = [value.total for value in item.values]
            if context.style == "step":
                x_values = [item for index in x_values for item in (index, index + 1)]
                y_values = [item for value in y_values for item in (value, value)]
            if observed and context.style == "bars":
                signal = plt.figure.bar(x_values, y_values, marker=marker, width=0.75)
            else:
                signal = plt.figure.signal(x_values, y_values, marker=marker).lines(
                    context.style not in {"no-line", "points", "stem"}
                )
                if context.style in {"stem", "area"}:
                    signal.fillx()
            if show_legend and context.legend_position == "inside":
                signal.label(context.translator.text("label.other") if item.is_other else item.label)
            plt.figure.draw(signal)
        if context.legend_position == "inside":
            plt.figure.legend(active=True)
        else:
            plt.figure.legend(False)
        positions, labels = (
            observed_ticks(model.observed_at)
            if observed
            else date_ticks(model.days, context, aggregation=model.aggregation)
        )
        plt.figure.ruler("x").ticks(positions, labels)
        values = (
            (
                value
                for series in model.observed_series
                for value in series.values
                if value is not None
            )
            if observed
            else (value.total for series in model.series for value in series.values)
        )
        configure_y_ticks(values, maximum=model.y_axis_max if observed else None)
        chart = plot_text(context)
        summary = render_summary(model.summary, context) if model.summary else ""
        return "\n".join(line for line in (summary, heading, legend, chart) if line)
