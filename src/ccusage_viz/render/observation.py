from __future__ import annotations

from ccusage_viz.chart_models import RankingModel, TimelineModel
from ccusage_viz.formatting import clip_width, format_tokens
from ccusage_viz.render.base import RenderContext


def _format_value(value: int | float) -> str:
    return format_tokens(round(value))


def _timeline_values(model: TimelineModel) -> tuple[tuple[str, int | float], ...]:
    values = []
    for series in model.observed_series:
        current = next((value for value in reversed(series.values) if value is not None), None)
        if current is not None:
            values.append((series.label, current))
    return tuple(values)


def render_observation(
    model: TimelineModel | RankingModel,
    context: RenderContext,
) -> str:
    if context.density == "minimal" or not model.is_observed:
        return ""
    values = (
        _timeline_values(model)
        if isinstance(model, TimelineModel)
        else tuple((entry.label, entry.value) for entry in model.observed_entries)
    )
    if not values:
        return ""
    unit = "TPM" if model.metric.unit == "tpm" else context.translator.text("label.tokens")
    label = context.translator.text(
        "label.monitor_observed" if model.metric.unit == "tpm" else "label.monitor_growth"
    )
    details = " · ".join(f"{name} {_format_value(value)} {unit}" for name, value in values)
    return clip_width(f"{label} · {details}", context.width)
