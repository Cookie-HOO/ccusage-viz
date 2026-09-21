from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass

from ccusage_viz.formatting import center_text
from ccusage_viz.historical_component import HistoricalChartComponent
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    HistoricalChartConfig,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.render import RenderContext
from ccusage_viz.render.base import RenderAudit, content_heading, date_range_heading, render_audit
from ccusage_viz.render.filters import active_filter_summary
from ccusage_viz.render.summary import render_summary_placeholder
from ccusage_viz.terminal import Terminal


@dataclass(frozen=True, slots=True)
class RenderedChart:
    chart: str
    notices: tuple[str, ...]


def historical_chart_config(options: StandaloneLaunch) -> HistoricalChartConfig:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical rendering does not support monitor configurations")
    return options.chart


def _title_content(
    options: StandaloneLaunch, translator: Translator, normalize_titles: bool
) -> str | None:
    if not normalize_titles:
        return None
    if options.chart.kind == "timeline":
        return translator.text(f"label.{options.chart.by or 'total'}")
    if options.chart.kind == "ranking":
        return translator.text(f"label.{options.chart.by or 'project'}")
    return None


def _pending_heading(options: StandaloneLaunch, context: RenderContext) -> str:
    chart = historical_chart_config(options)
    title = context.translator.text(f"label.{chart.kind}")
    if isinstance(chart, TimelineConfig) and context.title_content:
        return content_heading(title, chart.date_range.since, chart.date_range.until, context)
    if isinstance(chart, RankingConfig) and context.title_content:
        return content_heading(title, chart.date_range.since, chart.date_range.until, context)
    return date_range_heading(title, chart.date_range.since, chart.date_range.until, context)


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
    reserve_prompt: bool,
    control_rows: int,
    hide_upper_right_axes: bool,
    ranking_deltas: Mapping[Hashable, float] | None,
    ranking_rank_deltas: Mapping[Hashable, int] | None,
    normalize_titles: bool,
    interval: float | None,
    refreshing: bool,
    component: HistoricalChartComponent,
) -> RenderContext:
    chart = historical_chart_config(options)
    return RenderContext(
        terminal.width,
        max(
            1,
            terminal.height
            - 1
            - notice_count
            - int(reserve_prompt)
            - control_rows
            - int(chart.presentation.density == "full"),
        ),
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=chart.presentation.theme,
        style=chart.presentation.style,
        legend_position=chart.presentation.legend,
        hide_upper_right_axes=hide_upper_right_axes,
        deltas=ranking_deltas,
        rank_deltas=ranking_rank_deltas,
        weekday_mode=getattr(chart, "weekdays", "show"),
        period=chart.date_range.period if chart.date_range.relative_until else None,
        title_content=_title_content(options, translator, normalize_titles),
        filter_summary=active_filter_summary(chart.filters, translator, width=terminal.width),
        density=chart.presentation.density,
        pending=component.is_pending,
        audit=RenderAudit(
            component.accepted_at,
            component.snapshot.elapsed if component.snapshot is not None else None,
            interval,
            refreshing=refreshing,
            querying=component.has_pending_unknowns,
        ),
    )


def render_historical_component(
    component: HistoricalChartComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
    hide_upper_right_axes: bool = False,
    ranking_deltas: Mapping[Hashable, float] | None = None,
    ranking_rank_deltas: Mapping[Hashable, int] | None = None,
    normalize_titles: bool = False,
    interval: float | None = None,
    refreshing: bool = False,
) -> RenderedChart:
    accepted_options = component.accepted_options
    model = component.model
    if accepted_options is None or model is None:
        raise RuntimeError("historical component has no accepted model")
    if component.is_pending:
        context = _context(
            component.candidate,
            translator,
            terminal,
            notice_count=0,
            reserve_prompt=reserve_prompt,
            control_rows=control_rows,
            hide_upper_right_axes=hide_upper_right_axes,
            ranking_deltas=None,
            ranking_rank_deltas=None,
            normalize_titles=normalize_titles,
            interval=interval,
            refreshing=True,
            component=component,
        )
        rendered = _render_pending_historical(component.candidate, context)
        audit = render_audit(context)
        return RenderedChart(f"{rendered}\n{audit}" if audit else rendered, ())
    chart = historical_chart_config(accepted_options)
    visible_notices = model.notices
    if chart.presentation.density != "minimal" and model.summary is not None:
        visible_notices += getattr(model, "summary_notices", ())
    context = _context(
        accepted_options,
        translator,
        terminal,
        notice_count=len(visible_notices),
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
        hide_upper_right_axes=hide_upper_right_axes,
        ranking_deltas=ranking_deltas,
        ranking_rank_deltas=ranking_rank_deltas,
        normalize_titles=normalize_titles,
        interval=interval,
        refreshing=refreshing,
        component=component,
    )
    rendered = component.render(context)
    audit = render_audit(context)
    if audit:
        rendered = f"{rendered}\n{audit}"
    notices = tuple(translator.text(notice.key, **notice.values) for notice in visible_notices)
    return RenderedChart(rendered, notices)
