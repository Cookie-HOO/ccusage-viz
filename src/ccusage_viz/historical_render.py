from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass

from ccusage_viz.historical_component import HistoricalChartComponent
from ccusage_viz.i18n import Translator
from ccusage_viz.options import HistoricalChartConfig, MonitorConfig, StandaloneLaunch
from ccusage_viz.render import RenderContext
from ccusage_viz.render.base import RenderAudit, render_audit
from ccusage_viz.terminal import Terminal


@dataclass(frozen=True, slots=True)
class RenderedChart:
    chart: str
    notices: tuple[str, ...]


def historical_chart_config(options: StandaloneLaunch) -> HistoricalChartConfig:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical rendering does not support monitor configurations")
    return options.chart


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
) -> RenderedChart:
    options = component.accepted_options
    model = component.model
    if options is None or model is None:
        raise RuntimeError("historical component has no accepted model")
    chart = historical_chart_config(options)
    visible_notices = model.notices
    if chart.presentation.density != "minimal" and model.summary is not None:
        visible_notices += getattr(model, "summary_notices", ())
    title_content = (
        translator.text(f"label.{options.chart.by or 'total'}")
        if normalize_titles and options.chart.kind == "timeline"
        else translator.text(f"label.{options.chart.by or 'project'}")
        if normalize_titles and options.chart.kind == "ranking"
        else None
    )
    context = RenderContext(
        terminal.width,
        max(
            1,
            terminal.height
            - 1
            - len(visible_notices)
            - int(reserve_prompt)
            - control_rows
            - int(chart.presentation.density == "full"),
        ),
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=options.chart.presentation.theme,
        style=options.chart.presentation.style,
        legend_position=options.chart.presentation.legend,
        hide_upper_right_axes=hide_upper_right_axes,
        deltas=ranking_deltas,
        rank_deltas=ranking_rank_deltas,
        weekday_mode=getattr(options.chart, "weekdays", "show"),
        period=chart.date_range.period if chart.date_range.relative_until else None,
        title_content=title_content,
        density=chart.presentation.density,
        audit=RenderAudit(
            component.accepted_at,
            component.snapshot.elapsed if component.snapshot is not None else None,
            interval,
        ),
    )
    rendered = component.render(context)
    audit = render_audit(context)
    if audit:
        rendered = f"{rendered}\n{audit}"
    notices = tuple(translator.text(notice.key, **notice.values) for notice in visible_notices)
    return RenderedChart(rendered, notices)
