from __future__ import annotations

from ccusage_viz.chart_models import ChangeDirection, DailySummary, PercentChange
from ccusage_viz.formatting import clip_width, format_summary_tokens
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import (
    SUMMARY_DECREASE_COLOR,
    SUMMARY_INCREASE_COLOR,
    SUMMARY_VALUE_COLOR,
)


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _relation(change: PercentChange, value: str, context: RenderContext) -> str:
    key = f"summary.change.{change.direction.value}"
    values: dict[str, str] = {}
    if change.percent is not None:
        values["percent"] = _format_percent(change.percent)
    if change.direction == ChangeDirection.FROM_ZERO:
        values["value"] = value
    text = context.translator.text(key, **values)
    if context.color_scheme == "mono":
        return styled_text(text, 255, context, bold=change.direction != ChangeDirection.UNCHANGED)
    if change.direction in {ChangeDirection.INCREASE, ChangeDirection.FROM_ZERO}:
        return styled_text(text, SUMMARY_INCREASE_COLOR, context, bold=True)
    if change.direction == ChangeDirection.DECREASE:
        return styled_text(text, SUMMARY_DECREASE_COLOR, context, bold=True)
    return text


def render_summary(summary: DailySummary, context: RenderContext) -> str:
    plain_value = format_summary_tokens(summary.total)
    value = styled_text(
        plain_value,
        255 if context.color_scheme == "mono" else SUMMARY_VALUE_COLOR,
        context,
        bold=True,
    )
    today = context.translator.text("summary.today", value=value)
    day_over_day = context.translator.text(
        "summary.day_over_day", relation=_relation(summary.day_over_day, plain_value, context)
    )
    weekday = context.translator.text(f"calendar.weekday.{summary.previous_week_day.weekday()}")
    week_over_week = context.translator.text(
        "summary.week_over_week",
        weekday=weekday,
        relation=_relation(summary.week_over_week, plain_value, context),
    )
    line = context.translator.text(
        "summary.line", today=today, day_over_day=day_over_day, week_over_week=week_over_week
    )
    return clip_width(line, context.width)
