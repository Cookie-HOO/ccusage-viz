from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import cast

from ccusage_viz.chart_models import RankingModel
from ccusage_viz.formatting import center_text
from ccusage_viz.historical_component import HistoricalChartComponent
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    CustomChartConfig,
    HistoricalChartConfig,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.render import RenderContext
from ccusage_viz.render.base import render_audit
from ccusage_viz.render.filters import active_filter_summary
from ccusage_viz.render.headings import (
    HeadingSpec,
    chart_name,
    compose_heading,
    heading_period,
    heading_with_querying,
)
from ccusage_viz.render.summary import render_summary_placeholder
from ccusage_viz.render.surfaces import (
    EMPTY_SURFACE_CONTROLS,
    HistoricalPresentationSurface,
    SurfaceControls,
    SurfacePresentation,
    standalone_surface,
)
from ccusage_viz.terminal import Terminal


@dataclass(frozen=True, slots=True)
class RenderedChart:
    chart: str
    notices: tuple[str, ...]


def historical_chart_config(options: StandaloneLaunch) -> HistoricalChartConfig:
    if isinstance(options.chart, (CustomChartConfig, MonitorConfig)):
        raise TypeError("historical rendering does not support custom or monitor configurations")
    return options.chart


def _title_content(
    options: StandaloneLaunch, translator: Translator, normalize_titles: bool
) -> str | None:
    if not normalize_titles:
        return None
    chart = historical_chart_config(options)
    if isinstance(chart, TimelineConfig):
        return translator.text(f"label.{chart.by or 'total'}")
    if isinstance(chart, StackConfig):
        return translator.text(f"label.{chart.by}")
    if isinstance(chart, RankingConfig):
        return translator.text(f"label.{chart.by or 'project'}")
    return None


def _pending_heading(options: StandaloneLaunch, context: RenderContext) -> str:
    chart = historical_chart_config(options)
    dimension = context.title_content
    partition = None
    if dimension in {context.translator.text("label.total"), "Total"}:
        dimension = None
    if isinstance(chart, RankingConfig) and chart.project_aggregation == "exact":
        dimension = context.translator.text("label.project")
        partition = context.translator.text("label.agent")
    heading = compose_heading(
        HeadingSpec(
            metric=context.translator.text("label.tokens_metric"),
            chart=chart_name(chart.kind, context.translator),
            dimension=dimension,
            partition=partition,
            period=heading_period(
                context,
                since=chart.date_range.since,
                until=chart.date_range.until,
            ),
        ),
        context,
    )
    return heading_with_querying(heading, context)


def _pending_summary(options: StandaloneLaunch, context: RenderContext) -> str:
    chart = historical_chart_config(options)
    if context.density == "minimal":
        return ""
    period = "day"
    if isinstance(chart, (TimelineConfig, StackConfig)):
        period = chart.granularity
    return render_summary_placeholder(period, chart.date_range.until, context)


def _render_pending_historical(
    options: StandaloneLaunch,
    context: RenderContext,
) -> str:
    """Render candidate configuration without treating accepted facts as current."""
    heading = center_text(_pending_heading(options, context), context.width)
    return "\n".join(
        line
        for line in (
            _pending_summary(options, context),
            heading,
            context.translator.text("message.data_loading"),
        )
        if line
    )


def _context(
    options: StandaloneLaunch,
    translator: Translator,
    terminal: Terminal,
    *,
    notice_count: int,
    controls: SurfaceControls,
    surface: HistoricalPresentationSurface,
    ranking_deltas: Mapping[Hashable, float] | None,
    ranking_rank_deltas: Mapping[Hashable, int] | None,
    normalize_titles: bool,
    interval: float | None,
    refreshing: bool,
    component: HistoricalChartComponent,
) -> RenderContext:
    chart = historical_chart_config(options)
    presentation = SurfacePresentation(
        chart.kind,
        chart.presentation.theme,
        chart.presentation.style,
        chart.presentation.legend,
        chart.presentation.density,
        getattr(chart, "weekdays", "show"),
        chart.date_range.period if chart.date_range.relative_until else None,
        _title_content(options, translator, normalize_titles),
        active_filter_summary(chart.filters, translator, width=terminal.width),
        component.accepted_at,
        component.snapshot.elapsed if component.snapshot is not None else None,
        interval,
        refreshing=refreshing,
        querying=component.has_pending_unknowns,
        pending=component.is_pending,
        deltas=ranking_deltas,
        rank_deltas=ranking_rank_deltas,
    )
    return surface.context(
        terminal,
        translator,
        presentation,
        notices=notice_count,
        controls=controls,
    )


def render_historical_component(
    component: HistoricalChartComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
    surface: HistoricalPresentationSurface | None = None,
    normalize_titles: bool = False,
    ranking_deltas: Mapping[Hashable, float] | None = None,
    ranking_rank_deltas: Mapping[Hashable, int] | None = None,
    interval: float | None = None,
    refreshing: bool = False,
    ranking_search_query: str = "",
    ranking_search_editing: bool = False,
    ranking_show_visible_count: bool = False,
) -> RenderedChart:
    accepted_options = component.accepted_options
    model = component.model
    if accepted_options is None or model is None:
        raise RuntimeError("historical component has no accepted model")
    selected_surface = surface or standalone_surface(historical_chart_config(accepted_options).kind)
    if component.is_pending:
        context = _context(
            component.candidate,
            translator,
            terminal,
            notice_count=0,
            controls=controls,
            surface=selected_surface,
            ranking_deltas=None,
            ranking_rank_deltas=None,
            normalize_titles=normalize_titles,
            interval=interval,
            refreshing=True,
            component=component,
        )
        rendered = _render_pending_historical(component.candidate, context)
        audit = render_audit(context)
        return RenderedChart(rendered.rstrip("\n") + "\n" + audit if audit else rendered, ())
    chart = historical_chart_config(accepted_options)
    visible_notices = model.notices
    if chart.presentation.density != "minimal" and (
        model.summary is not None or getattr(model, "summary_notices", ())
    ):
        visible_notices += getattr(model, "summary_notices", ())
    context = _context(
        accepted_options,
        translator,
        terminal,
        notice_count=len(visible_notices),
        controls=controls,
        surface=selected_surface,
        ranking_deltas=ranking_deltas,
        ranking_rank_deltas=ranking_rank_deltas,
        normalize_titles=normalize_titles,
        interval=interval,
        refreshing=refreshing,
        component=component,
    )
    if isinstance(chart, RankingConfig) and (ranking_search_query or ranking_show_visible_count):
        from ccusage_viz.render.ranking import render_ranking

        rendered = render_ranking(
            cast(RankingModel, model),
            context,
            search_query=ranking_search_query,
            search_editing=ranking_search_editing,
            show_visible_count=ranking_show_visible_count,
        )  # type: ignore[arg-type]
    else:
        rendered = component.definition.renderer(model, context)
    audit = render_audit(context)
    if audit:
        rendered = rendered.rstrip("\n") + "\n" + audit
    notices = tuple(translator.text(notice.key, **notice.values) for notice in visible_notices)
    return RenderedChart(rendered, notices)
