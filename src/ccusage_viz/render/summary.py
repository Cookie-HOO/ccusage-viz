from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from ccusage_viz.chart_models import (
    ChangeDirection,
    ComparisonState,
    PercentChange,
    PeriodSummary,
)
from ccusage_viz.custom_models import (
    CustomComparison,
    CustomPaneSummary,
    CustomSummaryMetric,
    CustomUnit,
)
from ccusage_viz.formatting import clip_width, display_width, format_summary_tokens
from ccusage_viz.options import has_complete_content
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
    text = f"{trend_glyph(direction, ascii=context.ascii)} {context.translator.text(key, **values)}"
    scheme = get_color_scheme(context.color_scheme)
    if direction > 0:
        return styled_text(text, scheme.trend_increase, context, bold=True)
    if direction < 0:
        return styled_text(text, scheme.trend_decrease, context, bold=True)
    return styled_text(text, scheme.trend_neutral, context)


def _current_key(period: str, *, all_agents: bool) -> str:
    return f"summary.current.{period}.all_agents" if all_agents else f"summary.current.{period}"


@dataclass(frozen=True, slots=True)
class SummaryBlock:
    """A domain-neutral, indivisible fact in a rendered summary."""

    text: str


SummaryLayout = Literal["wrap", "stack"]


def layout_summary_blocks(
    blocks: tuple[SummaryBlock, ...], context: RenderContext, *, layout: SummaryLayout = "wrap"
) -> tuple[str, ...]:
    """Lay out semantic summary facts with ANSI- and CJK-aware clipping.

    ``wrap`` packs distinct facts onto shared rows when they fit. ``stack``
    preserves one fact per row, which keeps Dashboard header metrics scannable.
    """
    if context.width <= 0:
        return ()
    texts = [clip_width(block.text, context.width) for block in blocks]
    texts = [text for text in texts if text]
    if layout == "stack":
        return tuple(texts)

    separator = context.translator.text("summary.separator")
    rows: list[str] = []
    row = ""
    for text in texts:
        candidate = f"{row}{separator}{text}" if row else text
        if row and display_width(candidate) > context.width:
            rows.append(row)
            row = text
        else:
            row = candidate
    if row:
        rows.append(row)
    return tuple(rows)


def _summary_line(pieces: list[str], context: RenderContext) -> str:
    """Compatibility wrapper for legacy single-line summary callers."""
    separator = context.translator.text("summary.separator")
    return context.translator.text("summary.line", comparisons=separator.join(pieces))


def _pack_summary_pieces(
    pieces: list[str], context: RenderContext, *, layout: SummaryLayout = "wrap"
) -> str:
    """Lay out semantic summary facts for one summary surface."""
    return "\n".join(
        layout_summary_blocks(
            tuple(SummaryBlock(piece) for piece in pieces), context, layout=layout
        )
    )


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
            _current_key(period, all_agents=all_agents),
            value=unknown,
        ),
        context.translator.text(f"summary.sequential.{period}", relation=unknown),
    ]
    if period not in {"week", "year"}:
        values = {"relation": unknown}
        if period == "day":
            previous_week_day = end - timedelta(days=7)
            values["weekday"] = context.translator.text(
                f"calendar.weekday.{previous_week_day.weekday()}"
            )
        pieces.append(context.translator.text(f"summary.year_over_year.{period}", **values))
    return _pack_summary_pieces(pieces, context)


def _duration_part(value: int, singular: str, plural: str, *, language: str) -> str:
    label = singular if language == "zh" or value == 1 else plural
    return f"{value}{label}" if language == "zh" else f"{value} {label}"


def _format_duration(value: Decimal, source: str, *, language: str) -> str:
    """Render at most two adjacent duration units, using hours as the maximum."""
    negative = value < 0
    magnitude = abs(value)
    total_seconds = magnitude * (Decimal(60) if source == "duration-minute" else Decimal(1))
    rounded_seconds = int(total_seconds.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if rounded_seconds == 0:
        minute = source == "duration-minute"
        unit = (
            ("分钟" if minute else "秒") if language == "zh" else ("minute" if minute else "second")
        )
        plural = "minutes" if minute else "seconds"
        parts = [_duration_part(0, unit, plural, language=language)]
    elif rounded_seconds >= 3600:
        total_minutes = int(
            (total_seconds / Decimal(60)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
        hours, minutes = divmod(total_minutes, 60)
        parts = [
            _duration_part(
                hours, "小时" if language == "zh" else "hour", "hours", language=language
            )
        ]
        if minutes:
            parts.append(
                _duration_part(
                    minutes, "分钟" if language == "zh" else "minute", "minutes", language=language
                )
            )
    elif rounded_seconds >= 60:
        minutes, seconds = divmod(rounded_seconds, 60)
        parts = [
            _duration_part(
                minutes, "分钟" if language == "zh" else "minute", "minutes", language=language
            )
        ]
        if seconds:
            parts.append(
                _duration_part(
                    seconds, "秒" if language == "zh" else "second", "seconds", language=language
                )
            )
    else:
        seconds = rounded_seconds
        parts = [
            _duration_part(
                seconds, "秒" if language == "zh" else "second", "seconds", language=language
            )
        ]
    rendered = "".join(parts) if language == "zh" else " ".join(parts)
    return f"-{rendered}" if negative else rendered


def format_custom_value(
    value: Decimal,
    unit: CustomUnit,
    *,
    language: str,
    sum_format: str = "number",
) -> str:
    """Format a Dataset fallback value according to its Metric sum policy.

    Duration formats interpret the Decimal in the declared base unit and choose
    natural hour/minute/second output. Dataset-owned display strings bypass this.
    """
    if sum_format in {"duration-minute", "duration-second"}:
        return _format_duration(value, sum_format, language=language)

    rendered = ""
    for threshold, suffix in ((Decimal("1e9"), "B"), (Decimal("1e6"), "M"), (Decimal("1e3"), "K")):
        if abs(value) >= threshold:
            places = max(2, unit.decimal_places)
            quantum = Decimal(1).scaleb(-places)
            scaled = (value / threshold).quantize(quantum, rounding=ROUND_HALF_UP)
            rendered = f"{scaled:.{places}f}".rstrip("0").rstrip(".") + suffix
            break
    else:
        quantum = Decimal(1).scaleb(-unit.decimal_places)
        rendered = format(
            value.quantize(quantum, rounding=ROUND_HALF_UP), f".{unit.decimal_places}f"
        )
    label = unit.label.zh_cn if language == "zh" else unit.label.en
    return f"{label}{rendered}" if unit.placement == "prefix" else f"{rendered} {label}"


def _custom_relation(
    comparison: CustomComparison, current: Decimal, displayed: str, context: RenderContext
) -> str | None:
    if comparison.status != "ready" or comparison.base_value is None:
        return None
    baseline = comparison.base_value
    if current == baseline:
        change = PercentChange(ChangeDirection.UNCHANGED)
    elif baseline == 0:
        change = PercentChange(ChangeDirection.FROM_ZERO)
    elif current > baseline:
        change = PercentChange(
            ChangeDirection.INCREASE, float((current - baseline) / baseline * 100)
        )
    else:
        change = PercentChange(
            ChangeDirection.DECREASE, float((baseline - current) / baseline * 100)
        )
    return _relation(change, displayed, context)


def _pack_custom_summary_pieces(
    pieces: list[str], context: RenderContext, *, layout: SummaryLayout = "wrap"
) -> str:
    """Lay out source facts while keeping comparison chrome local to ccuv."""
    return _pack_summary_pieces(pieces, context, layout=layout)


def _custom_comparison_pieces(
    metric: CustomSummaryMetric,
    plain_value: str,
    context: RenderContext,
    *,
    period: str | None,
    as_of_date: date | None,
) -> list[str]:
    """Render Custom comparison facts against their accepted summary scope."""
    unknown = styled_text("??", get_color_scheme(context.color_scheme).muted, context)
    comparisons = (
        ("sequential", metric.sequential),
        ("year_over_year", metric.year_over_year),
    )
    pieces: list[str] = []
    for comparison_kind, comparison in comparisons:
        if (comparison_kind == "year_over_year" and period in {"week", "year", "range"}) or (
            comparison_kind == "sequential" and period in {"year", "range"}
        ):
            continue
        relation = (
            _custom_relation(comparison, metric.current.value, plain_value, context) or unknown
        )
        if period is None:
            pieces.append(relation)
            continue
        if comparison_kind == "sequential":
            pieces.append(
                context.translator.text(f"summary.sequential.{period}", relation=relation)
            )
            continue
        values = {"relation": relation}
        if period == "day":
            weekday = (as_of_date or date.today()) - timedelta(days=7)
            values["weekday"] = context.translator.text(f"calendar.weekday.{weekday.weekday()}")
        pieces.append(context.translator.text(f"summary.year_over_year.{period}", **values))
    return pieces


def render_custom_metrics(
    metrics: tuple[CustomSummaryMetric, ...],
    context: RenderContext,
    *,
    period: str | None = None,
    as_of_date: date | None = None,
    layout: SummaryLayout = "wrap",
) -> str:
    """Render source display facts with ccuv-owned comparison chrome."""
    if context.density == "minimal":
        return ""
    rendered: list[str] = []
    for metric in metrics:
        plain = (
            metric.current.display.zh_cn
            if context.translator.language == "zh"
            else metric.current.display.en
        )
        value = styled_text(
            plain, get_color_scheme(context.color_scheme).summary_value, context, bold=True
        )
        label = metric.label.zh_cn if context.translator.language == "zh" else metric.label.en
        pieces = [
            context.translator.text(
                f"summary.custom_current.{period or 'range'}", label=label, value=value
            )
        ]
        if has_complete_content(context.density):
            pieces.extend(
                _custom_comparison_pieces(
                    metric,
                    plain,
                    context,
                    period=period,
                    as_of_date=as_of_date,
                )
            )
        rendered.append(_pack_custom_summary_pieces(pieces, context, layout=layout))
    return "\n".join(rendered)


def render_custom_summary(
    summary: CustomPaneSummary, context: RenderContext, *, period: str = "day"
) -> str:
    """Render the legacy in-process fixture shape during protocol migration."""
    if context.density == "minimal":
        return ""
    metric = summary.metric
    plain = format_custom_value(metric.value, metric.unit, language=context.translator.language)
    value = styled_text(
        plain, get_color_scheme(context.color_scheme).summary_value, context, bold=True
    )
    label = metric.label.zh_cn if context.translator.language == "zh" else metric.label.en
    pieces = [context.translator.text(f"summary.custom_current.{period}", label=label, value=value)]
    if has_complete_content(context.density):
        unknown = styled_text("??", get_color_scheme(context.color_scheme).muted, context)
        for comparison in (metric.sequential, metric.year_over_year):
            pieces.append(_custom_relation(comparison, metric.value, plain, context) or unknown)
    return _pack_custom_summary_pieces(pieces, context)


def render_summary(
    summary: PeriodSummary, context: RenderContext, *, layout: SummaryLayout = "wrap"
) -> str:
    if context.density == "minimal":
        return ""
    plain_value = format_summary_tokens(summary.total)
    value = styled_text(
        plain_value,
        get_color_scheme(context.color_scheme).summary_value,
        context,
        bold=True,
    )
    pieces = [
        context.translator.text(
            _current_key(summary.period, all_agents=summary.all_agents),
            value=value,
        )
    ]
    if summary.filter_count:
        pieces.append(context.translator.text("summary.filters", count=summary.filter_count))
    if context.density == "compact":
        return _pack_summary_pieces(pieces, context, layout=layout)
    scheme = get_color_scheme(context.color_scheme)
    unknown = styled_text("??", scheme.muted, context)
    if summary.sequential_state in {ComparisonState.PENDING, ComparisonState.FAILED}:
        pieces.append(
            context.translator.text(
                f"summary.sequential.{summary.period}",
                relation=unknown,
            )
        )
    elif summary.sequential is not None:
        pieces.append(
            context.translator.text(
                f"summary.sequential.{summary.period}",
                relation=_relation(summary.sequential, plain_value, context),
            )
        )
    if summary.year_over_year_state in {ComparisonState.PENDING, ComparisonState.FAILED}:
        values = {"relation": unknown}
        if summary.period == "day" and summary.previous_week_day is not None:
            values["weekday"] = context.translator.text(
                f"calendar.weekday.{summary.previous_week_day.weekday()}"
            )
        pieces.append(context.translator.text(f"summary.year_over_year.{summary.period}", **values))
    elif summary.year_over_year is not None:
        key = f"summary.year_over_year.{summary.period}"
        values = {"relation": _relation(summary.year_over_year, plain_value, context)}
        if summary.period == "day" and summary.previous_week_day is not None:
            values["weekday"] = context.translator.text(
                f"calendar.weekday.{summary.previous_week_day.weekday()}"
            )
        pieces.append(context.translator.text(key, **values))
    return _pack_summary_pieces(pieces, context, layout=layout)
