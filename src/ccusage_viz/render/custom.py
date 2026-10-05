"""Native-layout renderers for Decimal custom-command chart projections.

Custom command facts deliberately remain Decimal values.  These renderers share the
same plot, palette, heading, tick, legend, and viewport primitives as built-in
charts without adapting measurements into token-domain models.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import plotext as plt

from ccusage_viz.custom_models import CustomPresentationDescriptor
from ccusage_viz.formatting import center_text, clip_width
from ccusage_viz.options import CustomChartConfig
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    content_heading,
    date_range_heading,
    date_ticks,
    isolated_plot,
)
from ccusage_viz.render.calendar_body import render_calendar_footer, render_calendar_grid
from ccusage_viz.render.palette import categorical_colors, get_color_scheme
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    render_historical_ranking,
)
from ccusage_viz.render.stack_presentation import (
    normalized_stack_values,
    render_grouped_stack_plot,
    render_stack_grid,
)
from ccusage_viz.render.summary import format_custom_value
from ccusage_viz.render.timeline_presentation import (
    TimelinePresentationSeries,
    render_timeline_plot,
)


def _label(series: CustomProjectedSeries, context: RenderContext) -> str:
    if series.is_other:
        return context.translator.text("label.other")
    label = series.label
    return label.zh_cn if context.translator.language == "zh" else label.en


def custom_heading(
    config: CustomChartConfig,
    context: RenderContext,
    descriptor: CustomPresentationDescriptor | None = None,
) -> str:
    """Render candidate-first custom chart chrome without retaining numeric facts."""

    labels: list[str] = []
    if descriptor is not None:
        dataset = descriptor.dataset.title
        labels.append(dataset.zh_cn if context.translator.language == "zh" else dataset.en)
    if config.kind == "ranking":
        if config.group_by is None:
            labels.append(context.translator.text("label.total"))
        elif descriptor is not None and config.group_by in descriptor.group_labels:
            group = descriptor.group_labels[config.group_by]
            labels.append(group.zh_cn if context.translator.language == "zh" else group.en)
        else:
            labels.append(config.group_by)
    labels.append(context.translator.text(f"label.{config.kind}"))
    title = " · ".join(labels)
    heading = (
        content_heading(title, config.date_range.since, config.date_range.until, context)
        if context.title_content
        else date_range_heading(title, config.date_range.since, config.date_range.until, context)
    )
    return center_text(heading, context.width)


def _heading(projection: CustomChartProjection, context: RenderContext) -> str:
    if projection.config is not None:
        return custom_heading(projection.config, context, projection.presentation)
    title = context.translator.text(f"label.{projection.kind}")
    return center_text(
        date_range_heading(title, projection.days[0], projection.days[-1], context), context.width
    )


def _summary(projection: CustomChartProjection, context: RenderContext) -> str:
    """Chart responses no longer carry summary facts.

    Pane/Header-owned summary lifecycles provide those facts separately; retain
    the chart layout's summary slot as empty until that wiring is complete.
    """
    del projection, context
    return ""


def _value(value: Decimal, projection: CustomChartProjection, context: RenderContext) -> str:
    return format_custom_value(value, projection.unit, language=context.translator.language)


def _custom_axis_value(value: Decimal, projection: CustomChartProjection) -> str:
    quantum = Decimal(1).scaleb(-projection.unit.decimal_places)
    return format(value.quantize(quantum), f".{projection.unit.decimal_places}f")


def _custom_timeline_heading(projection: CustomChartProjection, context: RenderContext) -> str:
    label = (
        projection.unit.label.zh_cn
        if context.translator.language == "zh"
        else projection.unit.label.en
    )
    heading = _heading(projection, context).strip()
    text = (
        f"{label} · {heading}" if projection.unit.placement == "prefix" else f"{heading} · {label}"
    )
    return center_text(text, context.width)


def _configure_custom_y_ticks(
    values: list[Decimal], projection: CustomChartProjection, context: RenderContext
) -> None:
    maximum = max(values, default=Decimal())
    positions = [Decimal()] if maximum <= 0 else [maximum * index / 4 for index in range(5)]
    plt.figure.ruler("y").ticks(
        [float(position) for position in positions],
        [_custom_axis_value(position, projection) for position in positions],
    )


def render_custom_pending(
    config: CustomChartConfig,
    context: RenderContext,
    descriptor: CustomPresentationDescriptor | None = None,
) -> str:
    """Render a source-independent placeholder for a pending primary request."""
    return "\n".join(
        (
            custom_heading(config, context, descriptor),
            context.translator.text("message.data_loading"),
        )
    )


def render_custom_empty(
    config: CustomChartConfig,
    context: RenderContext,
    descriptor: CustomPresentationDescriptor | None = None,
) -> str:
    """Render a titled, metric-neutral empty custom chart state."""
    return "\n".join(
        (
            custom_heading(config, context, descriptor),
            context.translator.text("message.custom_no_data"),
        )
    )


def render_custom_failure(
    config: CustomChartConfig,
    context: RenderContext,
    descriptor: CustomPresentationDescriptor | None = None,
) -> str:
    """Render only the current selection's chart chrome after a failed replacement."""
    return custom_heading(config, context, descriptor)


def render_custom_timeline(projection: CustomChartProjection, context: RenderContext) -> str:
    if not projection.series:
        return (
            render_custom_empty(projection.config, context, projection.presentation)
            if projection.config is not None
            else "\n".join(
                (_heading(projection, context), context.translator.text("message.custom_no_data"))
            )
        )
    sole_total = len(projection.series) == 1 and projection.series[0].id == "total"
    show_legend = (not sole_total and context.legend_position != "hidden") or (
        sole_total and context.legend_position == "inside"
    )
    summary = _summary(projection, context)
    values = [value for series in projection.series for value in series.values]
    maximum = max(values, default=Decimal())
    y_positions = [Decimal()] if maximum <= 0 else [maximum * index / 4 for index in range(5)]
    plot = render_timeline_plot(
        tuple(
            TimelinePresentationSeries(
                series.id,
                _label(series, context),
                series.values,
                series.is_other,
            )
            for series in projection.series
        ),
        x_values=tuple(range(len(projection.days))),
        x_ticks=date_ticks(projection.days, context, aggregation=projection.granularity),
        y_ticks=(
            y_positions,
            [_custom_axis_value(position, projection) for position in y_positions],
        ),
        context=context,
        text_rows=(
            len(summary.splitlines())
            + 1
            + int(show_legend and context.legend_position == "below-title")
        ),
        sole_total=sole_total,
        use_bars=context.style == "bars",
    )
    return "\n".join(
        line
        for line in (
            summary,
            _custom_timeline_heading(projection, context),
            plot.legend,
            plot.chart,
        )
        if line
    )


def _custom_stack_ticks(
    values: list[list[Decimal]], projection: CustomChartProjection, context: RenderContext
) -> tuple[list[Decimal], list[str]]:
    if context.style == "normalized":
        return [Decimal(value) for value in (0, 25, 50, 75, 100)], [
            "0%",
            "25%",
            "50%",
            "75%",
            "100%",
        ]
    totals = [
        sum((component[index] for component in values), start=Decimal())
        for index in range(len(values[0]))
    ]
    maximum = max(totals, default=Decimal())
    positions = [Decimal()] if maximum <= 0 else [maximum * index / 4 for index in range(5)]
    return positions, [_value(position, projection, context) for position in positions]


def render_custom_stack(projection: CustomChartProjection, context: RenderContext) -> str:
    if not projection.series or projection.total == 0:
        return (
            render_custom_empty(projection.config, context, projection.presentation)
            if projection.config is not None
            else "\n".join(
                (_heading(projection, context), context.translator.text("message.custom_no_data"))
            )
        )
    with isolated_plot():
        configure_plot(context)
        scheme = get_color_scheme(context.color_scheme)
        colors = categorical_colors(
            (item.id for item in projection.series if not item.is_other), context.color_scheme
        )
        raw_values = [list(series.values) for series in projection.series]
        normalized = context.style == "normalized"
        values = (
            cast(list[list[Decimal]], normalized_stack_values(raw_values))
            if normalized
            else raw_values
        )
        grouped = context.style in {"grouped", "grouped-thin"}
        positions, labels = date_ticks(projection.days, context, aggregation=projection.granularity)
        if grouped:
            totals = [
                sum(
                    (series.values[day] for series in projection.series),
                    start=Decimal(),
                )
                for day in range(len(projection.days))
            ]
            chart = render_grouped_stack_plot(
                values,
                date_count=len(projection.days),
                date_positions=positions,
                date_labels=labels,
                component_marks=("#" if context.ascii else "█",) * len(values),
                colors=[
                    scheme.other if series.is_other else colors[series.id]
                    for series in projection.series
                ],
                context=context,
                y_ticks=lambda: _configure_custom_y_ticks(totals, projection, context),
                text_rows=2 + int(context.density != "minimal"),
            )
        else:
            tick_positions, tick_labels = _custom_stack_ticks(values, projection, context)
            marks = (
                ("#", "=", "+", ":", "%", "@")
                if context.style == "stacked-pattern" and context.ascii
                else ("/", "\\", "x", "=", "+", ":")
                if context.style == "stacked-pattern"
                else ("#",) * len(values)
                if context.ascii
                else ("█",) * len(values)
            )
            chart = render_stack_grid(
                values,
                tick_positions=tick_positions,
                tick_labels=tick_labels,
                date_positions=positions,
                date_labels=labels,
                component_marks=marks[: len(values)],
                colors=[
                    scheme.other if series.is_other else colors[series.id]
                    for series in projection.series
                ],
                context=context,
            )
        legend = (
            " · ".join(
                f"{colored_mark('#' if context.ascii else '█', scheme.other if series.is_other else colors[series.id], context)} {_label(series, context)}"
                for series in projection.series
            )
            if context.legend_position == "below-title"
            else ""
        )
        return "\n".join(
            line
            for line in (
                _summary(projection, context),
                _heading(projection, context),
                legend,
                chart,
            )
            if line
        )


def render_custom_calendar(projection: CustomChartProjection, context: RenderContext) -> str:
    if not projection.series:
        return (
            render_custom_empty(projection.config, context, projection.presentation)
            if projection.config is not None
            else "\n".join(
                (_heading(projection, context), context.translator.text("message.custom_no_data"))
            )
        )
    values = {
        day: value for day, value in zip(projection.days, projection.series[0].values, strict=True)
    }
    lines = [
        line for line in (_summary(projection, context), _heading(projection, context)) if line
    ]
    lines.extend(render_calendar_grid(projection.days, values, context))
    lines.extend(
        render_calendar_footer(
            projection.days,
            values,
            context,
            value_formatter=lambda value: _value(cast(Decimal, value), projection, context),
        )
    )
    return "\n".join(clip_width(line, context.width) for line in lines)


def render_custom_ranking(projection: CustomChartProjection, context: RenderContext) -> str:
    if not projection.series:
        return (
            render_custom_empty(projection.config, context, projection.presentation)
            if projection.config is not None
            else "\n".join(
                (_heading(projection, context), context.translator.text("message.custom_no_data"))
            )
        )
    return render_historical_ranking(
        tuple(
            RankingPresentationEntry(
                entry.id,
                _label(entry, context),
                entry.total,
                entry.previous_total,
                entry.comparison_ready,
                entry.is_other,
                entry.previous_rank,
            )
            for entry in projection.series
        ),
        heading=_heading(projection, context).strip(),
        value_formatter=lambda value: _value(cast(Decimal, value), projection, context),
        delta_formatter=lambda value: (
            f"{'+' if value > 0 else '-'}{_value(abs(cast(Decimal, value)), projection, context)}"
        ),
        context=context,
        summary=_summary(projection, context),
    )


def render_custom_projection(projection: CustomChartProjection, context: RenderContext) -> str:
    if projection.kind == "timeline":
        return render_custom_timeline(projection, context)
    if projection.kind == "stack":
        return render_custom_stack(projection, context)
    if projection.kind == "calendar":
        return render_custom_calendar(projection, context)
    return render_custom_ranking(projection, context)
