from __future__ import annotations

from datetime import date, timedelta

from ccusage_viz.chart_models import ChangeDirection, DailySummary, PercentChange, PeriodSummary
from ccusage_viz.formatting import clip_width, format_summary_tokens
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.trends import trend_glyph


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _relation(change: PercentChange, value: str, context: RenderContext) -> str:
    key = f"summary.change.{change.direction.value}"
    values: dict[str, str] = {}
    if change.percent is not None:
        values["percent"] = _format_percent(change.percent)
    if change.direction == ChangeDirection.FROM_ZERO:
        values["value"] = value
    direction = (
        1
        if change.direction in {ChangeDirection.INCREASE, ChangeDirection.FROM_ZERO}
        else -1
        if change.direction == ChangeDirection.DECREASE
        else 0
    )
    text = (
        f"{trend_glyph(direction, ascii=context.ascii)} "
        f"{context.translator.text(key, **values)}"
    )
    scheme = get_color_scheme(context.color_scheme)
    if direction > 0:
        return styled_text(text, scheme.trend_increase, context, bold=True)
    if direction < 0:
        return styled_text(text, scheme.trend_decrease, context, bold=True)
    return styled_text(text, scheme.trend_neutral, context)


def _current_key(period: str, *, all_agents: bool, current_filter_total: bool) -> str:
    if all_agents:
        return f"summary.current.{period}.all_agents"
    if current_filter_total:
        return f"summary.current.{period}.current_filter"
    return f"summary.current.{period}"


def _summary_line(pieces: list[str], context: RenderContext) -> str:
    separator = context.translator.text("summary.separator")
    return context.translator.text("summary.line", comparisons=separator.join(pieces))


def render_summary_placeholder(
    period: str,
    end: date,
    context: RenderContext,
    *,
    all_agents: bool = False,
) -> str:
    """Render localized summary structure without fabricating uncovered values."""
    scheme = get_color_scheme(context.color_scheme)
    unknown = styled_text("??", scheme.muted, context)
    pieces = [
        context.translator.text(
            _current_key(period, all_agents=all_agents, current_filter_total=False),
            value=unknown,
        ),
        context.translator.text(f"summary.sequential.{period}", relation=unknown),
    ]
    if period != "year":
        values = {"relation": unknown}
        if period == "day":
            previous_week_day = end - timedelta(days=7)
            values["weekday"] = context.translator.text(
                f"calendar.weekday.{previous_week_day.weekday()}"
            )
        pieces.append(context.translator.text(f"summary.year_over_year.{period}", **values))
    return clip_width(_summary_line(pieces, context), context.width)


def render_summary(summary: PeriodSummary | DailySummary, context: RenderContext) -> str:
    if isinstance(summary, DailySummary):
        summary = PeriodSummary(
            "day",
            summary.day,
            summary.total,
            summary.day_over_day,
            summary.week_over_week,
            summary.previous_week_day,
            summary.all_agents,
            summary.current_filter_total,
            summary.chart_top,
        )
    plain_value = format_summary_tokens(summary.total)
    value = styled_text(
        plain_value,
        get_color_scheme(context.color_scheme).summary_value,
        context,
        bold=True,
    )
    pieces = [
        context.translator.text(
            _current_key(
                summary.period,
                all_agents=summary.all_agents,
                current_filter_total=summary.current_filter_total,
            ),
            value=value,
        )
    ]
    if summary.sequential is not None:
        pieces.append(
            context.translator.text(
                f"summary.sequential.{summary.period}",
                relation=_relation(summary.sequential, plain_value, context),
            )
        )
    if summary.year_over_year is not None:
        key = f"summary.year_over_year.{summary.period}"
        values = {"relation": _relation(summary.year_over_year, plain_value, context)}
        if summary.period == "day" and summary.previous_week_day is not None:
            values["weekday"] = context.translator.text(
                f"calendar.weekday.{summary.previous_week_day.weekday()}"
            )
        pieces.append(context.translator.text(key, **values))
    line = _summary_line(pieces, context)
    if summary.chart_top is not None:
        line = context.translator.text("summary.chart_top", summary=line, top=summary.chart_top)
    return clip_width(line, context.width)
