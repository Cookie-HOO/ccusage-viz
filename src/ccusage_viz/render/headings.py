from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ccusage_viz.formatting import clip_width, display_width, strip_ansi, truncate_middle_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme

_TEMPORAL_MONITOR_STYLES = frozenset({"bars", "line", "step", "points", "line-points"})
_RANKING_MONITOR_STYLES = frozenset({"ranking", "ranking-dot"})
_SEPARATOR = " · "


@dataclass(frozen=True, slots=True)
class HeadingSpec:
    metric: str
    chart: str
    dimension: str | None = None
    partition: str | None = None
    period: str | None = None
    window: bool = False
    status: str | None = None


def chart_name(kind: str, translator: Translator) -> str:
    return translator.text(f"label.chart_{kind}")


def monitor_view_name(style: str | None, translator: Translator) -> str:
    if style in _RANKING_MONITOR_STYLES:
        family = "ranking"
    elif style == "list":
        family = "list"
    elif style == "cumulative-bars":
        family = "cumulative_bars"
    else:
        family = "trend"
    return translator.text(f"label.monitor_view_{family}")


def _dimension_text(spec: HeadingSpec, translator: Translator) -> str | None:
    if spec.dimension is None:
        return None
    dimension = translator.dimension(spec.dimension)
    if spec.partition is not None:
        dimension = f"{translator.dimension(spec.partition)} → {dimension}"
    return translator.text("label.heading_by", dimension=dimension)


def _period_text(spec: HeadingSpec, translator: Translator) -> str | None:
    if spec.period is None:
        return None
    if spec.window:
        return translator.text("label.heading_window", duration=spec.period)
    return spec.period


def _plain_status(spec: HeadingSpec, translator: Translator) -> str:
    if spec.status is None:
        return ""
    return translator.text("label.heading_status", status=spec.status)


def _candidate(parts: tuple[str | None, ...], status: str) -> str:
    return _SEPARATOR.join(part for part in parts if part is not None) + status


def _querying_marker(context: RenderContext) -> str | None:
    if context.audit is None or not context.audit.querying:
        return None
    return context.translator.text("status.querying")


def compose_heading(spec: HeadingSpec, context: RenderContext) -> str:
    translator = context.translator
    marker = _querying_marker(context)
    marker_width = display_width(f"{_SEPARATOR}{marker}") if marker is not None else 0
    heading_width = max(0, context.width - marker_width)
    dimension = _dimension_text(spec, translator)
    period = _period_text(spec, translator)
    status = _plain_status(spec, translator)
    candidates = (
        _candidate((spec.metric, spec.chart, dimension, period), status),
        _candidate((spec.metric, spec.chart, period), status),
        _candidate((spec.metric, spec.chart), status),
    )
    plain = next(
        (candidate for candidate in candidates if display_width(candidate) <= heading_width),
        None,
    )
    if plain is None:
        suffix = f"{_SEPARATOR}{spec.chart}{status}"
        metric_width = heading_width - display_width(suffix)
        if metric_width > 0:
            metric = truncate_middle_width(spec.metric, metric_width)
            plain = f"{metric}{suffix}"
        else:
            plain = clip_width(f"{spec.chart}{status}", heading_width)

    if status and plain.endswith(status):
        styled_status = styled_text(
            status,
            get_color_scheme(context.color_scheme).muted,
            context,
            dim=True,
        )
        return f"{plain[: -len(status)]}{styled_status}"
    return plain


def heading_period(
    context: RenderContext,
    *,
    since: date,
    until: date,
) -> str:
    if context.period is not None:
        return context.period
    return context.translator.text(
        "label.date_range",
        since=since.isoformat(),
        until=until.isoformat(),
    )


def heading_with_querying(heading: str, context: RenderContext) -> str:
    marker = _querying_marker(context)
    if marker is None:
        return heading
    marker_suffix = f"{_SEPARATOR}{marker}"
    if strip_ansi(heading).endswith(marker_suffix):
        return clip_width(heading, context.width)
    styled_marker = styled_text(
        marker,
        get_color_scheme(context.color_scheme).muted,
        context,
        dim=True,
    )
    if display_width(marker_suffix) > context.width:
        return clip_width(styled_marker, context.width)
    heading = clip_width(heading, context.width - display_width(marker_suffix))
    return f"{heading}{_SEPARATOR}{styled_marker}"
