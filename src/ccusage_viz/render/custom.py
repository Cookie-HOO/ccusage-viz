"""Native-layout renderers for Decimal custom-command chart projections.

Custom command facts deliberately remain Decimal values.  These renderers share the
same plot, palette, heading, tick, legend, and viewport primitives as built-in
charts without adapting measurements into token-domain models.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import plotext as plt

from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.custom_models import CustomPresentationDescriptor, LocalizedText
from ccusage_viz.formatting import center_text, clip_width
from ccusage_viz.options import CustomChartConfig
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.processing.custom_ranking import (
    CustomProjectedRankingEntry,
    CustomRankingProjection,
)
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    date_range_heading,
    date_ticks,
    isolated_plot,
)
from ccusage_viz.render.calendar_body import render_calendar_footer, render_calendar_grid
from ccusage_viz.render.custom_ranking_preparation import prepare_custom_ranking
from ccusage_viz.render.grouped_ranking import render_grouped_custom_ranking
from ccusage_viz.render.headings import (
    HeadingSpec,
    chart_name,
    compose_heading,
    heading_period,
    heading_with_querying,
)
from ccusage_viz.render.palette import categorical_colors, get_color_scheme
from ccusage_viz.render.ranking_presentation import render_historical_ranking
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

CustomProjection = CustomChartProjection | CustomRankingProjection


def _label(
    series: CustomProjectedSeries | CustomProjectedRankingEntry, context: RenderContext
) -> str:
    if series.is_other:
        return context.translator.text("label.other")
    label = series.label
    return (label.zh_cn if context.translator.language == "zh" else label.en).replace("\n", "\\n")


def _localized(value: LocalizedText, context: RenderContext) -> str:
    return value.zh_cn if context.translator.language == "zh" else value.en


def _metric_title(
    config: CustomChartConfig,
    context: RenderContext,
    descriptor: CustomPresentationDescriptor | None,
) -> str | None:
    """Resolve metric chrome from authoritative presentation metadata, never IDs."""
    if descriptor is not None:
        return _localized(descriptor.dataset.title, context)
    if config.metric_titles is not None:
        return config.metric_titles[1 if context.translator.language == "zh" else 0]
    return None


def custom_heading(
    config: CustomChartConfig,
    context: RenderContext,
    descriptor: CustomPresentationDescriptor | None = None,
) -> str:
    """Render candidate-first custom chart chrome without retaining numeric facts."""

    metric = _metric_title(config, context, descriptor)

    dimension = None
    if config.group_by is not None:
        group = descriptor.group_labels.get(config.group_by) if descriptor is not None else None
        dimension = _localized(group, context) if group is not None else config.group_by
    partition = None
    if config.kind == "ranking" and config.partition_by is not None:
        label = (
            descriptor.partition_labels.get(config.partition_by)
            if descriptor is not None
            else None
        )
        partition = _localized(label, context) if label is not None else config.partition_by

    if isinstance(config.date_range, TimestampRange):
        period = (
            config.date_range.period
            if config.date_range.relative_until and config.date_range.period is not None
            else context.translator.text(
                "label.timestamp_range",
                start_at=config.date_range.start_at.isoformat(),
                end_at=config.date_range.end_at.isoformat(),
            )
        )
    else:
        period = heading_period(
            context,
            since=config.date_range.since,
            until=config.date_range.until,
        )
    heading = compose_heading(
        HeadingSpec(
            metric=metric,
            chart=chart_name(config.kind, context.translator),
            dimension=dimension,
            partition=partition,
            period=period,
        ),
        context,
    )
    return center_text(heading_with_querying(heading, context), context.width)


def _heading(projection: CustomProjection, context: RenderContext) -> str:
    if projection.config is not None:
        return custom_heading(projection.config, context, projection.presentation)
    title = context.translator.text(f"label.{projection.kind}")
    if isinstance(projection, CustomRankingProjection):
        return center_text(title, context.width)
    return center_text(
        date_range_heading(title, projection.days[0], projection.days[-1], context), context.width
    )


def _summary(projection: CustomProjection, context: RenderContext) -> str:
    """Chart responses no longer carry summary facts.

    Pane/Header-owned summary lifecycles provide those facts separately; retain
    the chart layout's summary slot as empty until that wiring is complete.
    """
    del projection, context
    return ""


def _value(value: Decimal, projection: CustomProjection, context: RenderContext) -> str:
    return format_custom_value(value, projection.unit, language=context.translator.language)


def _custom_axis_value(value: Decimal, projection: CustomChartProjection) -> str:
    quantum = Decimal(1).scaleb(-projection.unit.decimal_places)
    return format(value.quantize(quantum), f".{projection.unit.decimal_places}f")


def _custom_timeline_heading(projection: CustomChartProjection, context: RenderContext) -> str:
    return _heading(projection, context)


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


def render_custom_ranking(
    projection: CustomChartProjection | CustomRankingProjection,
    context: RenderContext,
    *,
    descriptions_visible: bool = False,
    search_query: str = "",
    search_editing: bool = False,
    show_visible_count: bool = False,
    copied_entry_id: str | None = None,
    entry_offset: int = 0,
    entry_limit: int | None = None,
) -> str:
    if projection.groups is not None:
        return render_grouped_custom_ranking(
            projection,
            context,
            heading=_heading(projection, context).strip(),
            summary=_summary(projection, context),
            descriptions_visible=descriptions_visible,
        )
    if not projection.series:
        return (
            render_custom_empty(projection.config, context, projection.presentation)
            if projection.config is not None
            else "\n".join(
                (_heading(projection, context), context.translator.text("message.custom_no_data"))
            )
        )
    prepared = prepare_custom_ranking(
        projection,
        context,
        search_query=search_query,
        copy_marker=lambda entry: (
            None if entry.is_other else "✓" if entry.id == copied_entry_id else "⊞"
        ),
    )
    return render_historical_ranking(
        prepared.matched_entries,
        heading=_heading(projection, context).strip(),
        value_formatter=lambda value: _value(cast(Decimal, value), projection, context),
        delta_formatter=lambda value: (
            f"{'+' if value > 0 else '-'}{_value(abs(cast(Decimal, value)), projection, context)}"
        ),
        context=context,
        summary=_summary(projection, context),
        descriptions_visible=descriptions_visible,
        search_query=search_query,
        search_editing=search_editing,
        show_visible_count=show_visible_count,
        comparison_mode=projection.config.ranking_comparison
        if projection.config is not None
        else "full",
        comparison_available=projection.comparison_available,
        show_new_entries=True,
        compact_labels=False,
        label_max_width=48,
        entry_offset=entry_offset,
        entry_limit=entry_limit,
        total_entry_count=len(prepared.full_entries),
        matched_entry_count=len(prepared.matched_entries),
        total=prepared.full_total,
        maximum=prepared.full_maximum,
        show_percentage=projection.show_percentage,
        entries_matched=True,
    )


def render_custom_projection(
    projection: CustomChartProjection | CustomRankingProjection,
    context: RenderContext,
    *,
    descriptions_visible: bool = False,
    search_query: str = "",
    search_editing: bool = False,
    show_visible_count: bool = False,
    copied_entry_id: str | None = None,
    entry_offset: int = 0,
    entry_limit: int | None = None,
) -> str:
    if isinstance(projection, CustomChartProjection):
        if projection.kind == "timeline":
            return render_custom_timeline(projection, context)
        if projection.kind == "stack":
            return render_custom_stack(projection, context)
        if projection.kind == "calendar":
            return render_custom_calendar(projection, context)
    return render_custom_ranking(
        projection,
        context,
        descriptions_visible=descriptions_visible,
        search_query=search_query,
        search_editing=search_editing,
        show_visible_count=show_visible_count,
        copied_entry_id=copied_entry_id,
        entry_offset=entry_offset,
        entry_limit=entry_limit,
    )
