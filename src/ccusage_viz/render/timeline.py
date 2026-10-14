from __future__ import annotations

from math import isfinite

from ccusage_viz.chart_models import ScalarSeries, Series, TimelineModel
from ccusage_viz.formatting import center_text, display_width
from ccusage_viz.render.base import (
    RenderContext,
    date_ticks,
    observed_start_marker,
    observed_ticks,
    overlay_plot_column,
    styled_text,
    y_tick_spec,
)
from ccusage_viz.render.headings import (
    HeadingSpec,
    chart_name,
    compose_heading,
    heading_period,
    heading_with_querying,
    monitor_heading_spec,
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary
from ccusage_viz.render.timeline_presentation import (
    TimelinePresentationSeries,
    render_timeline_plot,
)


def _observed_heading(model: TimelineModel, context: RenderContext) -> str:
    scope = model.observed_scope
    if scope is None:
        raise ValueError("observed timeline is missing its scope")
    return heading_with_querying(
        compose_heading(
            monitor_heading_spec(
                unit=model.metric.unit,
                style=context.style,
                window_seconds=scope.window_seconds,
                mode=scope.mode,
                state=scope.state,
                translator=context.translator,
            ),
            context,
        ),
        context,
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

    sole_total = len(series) == 1 and series[0].key in {"total", "Total", ("total",)}
    if observed:
        presentation = tuple(
            TimelinePresentationSeries(
                item.key,
                context.translator.text("label.other") if item.is_other else item.label,
                tuple(
                    0.0
                    if context.style == "bars" and (value is None or not isfinite(value))
                    else float("nan")
                    if value is None
                    else value
                    for value in item.values
                ),
                item.is_other,
            )
            for item in model.observed_series
        )
        values = (
            value for item in model.observed_series for value in item.values if value is not None
        )
        x_values = tuple(range(len(model.observed_at)))
        x_ticks = observed_ticks(model.observed_at)
        y_ticks = y_tick_spec((model.y_axis_max,) if model.y_axis_max is not None else values)
    else:
        presentation = tuple(
            TimelinePresentationSeries(
                item.key,
                context.translator.text("label.other") if item.is_other else item.label,
                tuple(value.total for value in item.values),
                item.is_other,
            )
            for item in model.series
        )
        x_values = tuple(range(len(model.days)))
        x_ticks = date_ticks(model.days, context, aggregation=model.aggregation)
        y_ticks = y_tick_spec(value.total for item in model.series for value in item.values)

    show_legend = (not sole_total and context.legend_position != "hidden") or (
        sole_total and context.legend_position == "inside"
    )
    if observed:
        heading_text = _observed_heading(model, context)
    else:
        dimension = context.title_content
        if dimension in {context.translator.text("label.total"), "Total"}:
            dimension = None
        heading_text = heading_with_querying(
            compose_heading(
                HeadingSpec(
                    metric=context.translator.text("label.tokens_metric"),
                    chart=chart_name("timeline", context.translator),
                    dimension=dimension,
                    period=heading_period(
                        context,
                        since=model.days[0],
                        until=model.days[-1],
                    ),
                ),
                context,
            ),
            context,
        )
    heading = center_text(heading_text, context.width)
    summary = render_summary(model.summary, context) if model.summary else ""
    start_marker = (
        observed_start_marker(
            model.observed_at,
            started_at=model.monitor_started_at,
            context=context,
        )
        if observed
        else None
    )
    plot = render_timeline_plot(
        presentation,
        x_values=x_values,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
        context=context,
        text_rows=(
            1
            + len(summary.splitlines())
            + int(start_marker is not None and start_marker.label is not None)
            + int(show_legend and context.legend_position == "below-title")
        ),
        sole_total=sole_total,
        use_bars=observed and context.style == "bars",
        y_maximum=model.y_axis_max if observed else None,
    )
    chart = plot.chart
    if start_marker is not None:
        axis_width = max(1, context.width - 12)
        column = round(
            start_marker.position / max(1, len(model.observed_at) - 1) * (axis_width - 1)
        )
        glyph = ":" if context.ascii else "┆"
        scheme = get_color_scheme(context.color_scheme)
        chart = overlay_plot_column(
            chart,
            column=5 + column,
            glyph=glyph,
            style=styled_text(glyph, scheme.muted, context, dim=True) if context.color else None,
        )
        if start_marker.label is not None:
            indent = (
                5 + column + 1
                if start_marker.alignment == "right"
                else 5 + column - display_width(start_marker.label) - 1
            )
            chart = f"{chart}\n{' ' * max(0, indent)}{start_marker.label}"
    return "\n".join(line for line in (summary, heading, plot.legend, chart) if line)
