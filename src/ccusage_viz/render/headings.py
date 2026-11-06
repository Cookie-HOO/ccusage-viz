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
    metric: str | None
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


def duration_label(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def monitor_heading_spec(
    *,
    unit: str,
    style: str | None,
    window_seconds: int,
    mode: str,
    state: str,
    translator: Translator,
    dimension: str | None = None,
) -> HeadingSpec:
    if dimension is None and mode != "total":
        dimension = mode
    return HeadingSpec(
        metric="TPM" if unit == "tpm" else translator.text("label.tokens_metric"),
        chart=monitor_view_name(style, translator),
        dimension=dimension,
        period=duration_label(window_seconds),
        window=True,
        status=None if state == "ready" else translator.text(f"label.monitor_{state}"),
    )


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
    return (
        translator.text("label.heading_window", duration=spec.period)
        if spec.window
        else spec.period
    )


def _plain_status(spec: HeadingSpec, translator: Translator) -> str:
    return (
        "" if spec.status is None else translator.text("label.heading_status", status=spec.status)
    )


def _candidate(parts: tuple[str | None, ...], status: str) -> str:
    return _SEPARATOR.join(part for part in parts if part is not None) + status


def _querying_marker(context: RenderContext) -> str | None:
    if context.audit is None or not context.audit.querying:
        return None
    return context.translator.text("status.querying")


def _scope_candidates(context: RenderContext) -> tuple[str | None, ...]:
    """Return filter summaries from most to least informative, then no scope."""
    summaries = context.filter_summaries or (
        (context.filter_summary,) if context.filter_summary else ()
    )
    return (*dict.fromkeys(summary for summary in summaries if summary), None)


def _suffix(scope: str | None, marker: str | None) -> str:
    return "".join(f"{_SEPARATOR}{part}" for part in (scope, marker) if part)


def _compose_plain(spec: HeadingSpec, context: RenderContext, *, width: int) -> str:
    translator = context.translator
    dimension = _dimension_text(spec, translator)
    period = _period_text(spec, translator)
    status = _plain_status(spec, translator)
    candidates = (
        _candidate((spec.metric, spec.chart, dimension, period), status),
        _candidate((spec.metric, spec.chart, period), status),
        _candidate((spec.metric, spec.chart), status),
    )
    plain = next((candidate for candidate in candidates if display_width(candidate) <= width), None)
    if plain is None:
        if spec.metric is None:
            plain = clip_width(f"{spec.chart}{status}", width)
        else:
            suffix = f"{_SEPARATOR}{spec.chart}{status}"
            metric_width = width - display_width(suffix)
            plain = (
                f"{truncate_middle_width(spec.metric, metric_width)}{suffix}"
                if metric_width > 0
                else clip_width(f"{spec.chart}{status}", width)
            )
    if status and plain.endswith(status):
        styled_status = styled_text(
            status, get_color_scheme(context.color_scheme).muted, context, dim=True
        )
        return f"{plain[: -len(status)]}{styled_status}"
    return plain


def compose_heading(spec: HeadingSpec, context: RenderContext) -> str:
    """Compose a width-safe title, retaining the richest fitting active filter scope."""
    marker = _querying_marker(context)
    if marker is not None and display_width(marker) > context.width:
        styled_marker = styled_text(
            marker, get_color_scheme(context.color_scheme).muted, context, dim=True
        )
        return clip_width(styled_marker, context.width)

    baseline = _compose_plain(spec, context, width=context.width)
    for scope in _scope_candidates(context)[:-1]:
        suffix = _suffix(scope, marker)
        plain = _compose_plain(spec, context, width=max(0, context.width - display_width(suffix)))
        # A filter is optional chrome: only include it when the unfiltered title
        # does not have to lose information or characters to make room.
        if strip_ansi(plain) == strip_ansi(baseline):
            return _append_suffix(plain, scope, marker, context)

    suffix = _suffix(None, marker)
    plain = _compose_plain(spec, context, width=max(0, context.width - display_width(suffix)))
    return (
        _append_suffix(plain, None, marker, context)
        if plain
        else clip_width(marker or "", context.width)
    )


def _append_suffix(
    heading: str, scope: str | None, marker: str | None, context: RenderContext
) -> str:
    parts = [heading]
    if scope:
        parts.append(scope)
    if marker:
        parts.append(
            styled_text(marker, get_color_scheme(context.color_scheme).muted, context, dim=True)
        )
    return _SEPARATOR.join(parts)


def heading_period(context: RenderContext, *, since: date, until: date) -> str:
    if context.period is not None:
        return context.period
    return context.translator.text(
        "label.date_range", since=since.isoformat(), until=until.isoformat()
    )


def heading_with_querying(heading: str, context: RenderContext) -> str:
    """Compatibility wrapper for non-semantic headings; semantic headings use compose_heading."""
    marker = _querying_marker(context)
    scopes = _scope_candidates(context)
    if any(scope and strip_ansi(heading).endswith(_suffix(scope, marker)) for scope in scopes):
        return clip_width(heading, context.width)
    if marker and strip_ansi(heading).endswith(_suffix(None, marker)):
        return clip_width(heading, context.width)
    for scope in scopes:
        suffix = _suffix(scope, marker)
        if display_width(suffix) >= context.width:
            continue
        base = clip_width(heading, context.width - display_width(suffix))
        if base:
            return _append_suffix(base, scope, marker, context)
    return clip_width(heading, context.width)
