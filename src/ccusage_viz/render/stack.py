from __future__ import annotations

from ccusage_viz.chart_models import StackModel
from ccusage_viz.formatting import center_text
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    configure_y_ticks,
    date_ticks,
    isolated_plot,
)
from ccusage_viz.render.headings import (
    HeadingSpec,
    chart_name,
    compose_heading,
    heading_period,
    heading_with_querying,
)
from ccusage_viz.render.palette import categorical_colors, get_color_scheme
from ccusage_viz.render.stack_presentation import (
    render_grouped_stack_plot,
    render_stack_grid,
    stack_tick_spec,
)
from ccusage_viz.render.summary import render_summary

# Compatibility aliases for callers that imported the original stack helpers.
_stack_tick_spec = stack_tick_spec
_stack_grid = render_stack_grid


def render_stack(model: StackModel, context: RenderContext) -> str:
    if not model.components or model.total.total == 0:
        return context.translator.text("message.no_data")
    with isolated_plot():
        configure_plot(context)
        heading = center_text(
            heading_with_querying(
                compose_heading(
                    HeadingSpec(
                        metric=context.translator.text("label.tokens_metric"),
                        chart=chart_name("stack", context.translator),
                        dimension=context.title_content,
                        period=heading_period(
                            context,
                            since=model.days[0],
                            until=model.days[-1],
                        ),
                    ),
                    context,
                ),
                context,
            ),
            context.width,
        )
        show_legend = context.legend_position == "below-title"
        raw_values: list[list[float]] = [
            [float(usage.total) for usage in component.values] for component in model.components
        ]
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
            context.translator.text(f"label.{component.label}")
            if model.grouping == "composition"
            else context.translator.text("label.other")
            if component.is_other
            else component.label
            for component in model.components
        ]
        scheme = get_color_scheme(context.color_scheme)
        colors = (
            [scheme.component(component.label) for component in model.components]
            if model.grouping == "composition"
            else [
                scheme.other
                if component.is_other
                else categorical_colors((component.key,), context.color_scheme)[component.key]
                for component in model.components
            ]
        )
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
        positions, tick_labels = date_ticks(model.days, context, aggregation=model.aggregation)
        summary = render_summary(model.summary, context) if model.summary else ""
        if grouped:
            chart = render_grouped_stack_plot(
                values,
                date_count=len(model.days),
                date_positions=positions,
                date_labels=tick_labels,
                component_marks=component_marks,
                colors=colors,
                context=context,
                y_ticks=lambda: configure_y_ticks(
                    sum(component.values[index].total for component in model.components)
                    for index in range(len(model.days))
                ),
                text_rows=1 + int(show_legend) + len(summary.splitlines()),
            )
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
        prefix = f"{summary}\n" if summary else ""
        legend_line = separator.join(legend) if show_legend else ""
        return "\n".join(line for line in (prefix.rstrip(), heading, legend_line, chart) if line)
