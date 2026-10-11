"""Pure V2 Metric Group switching and normalization rules."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from ccusage_viz.custom_models import V2MetricDescriptor, V2ProbeDescriptor
from ccusage_viz.options import CustomChartConfig, resolve_date_range

SwitchNormalization = Literal["period", "group_by", "granularity", "filters", "top"]


def switch_candidates(
    descriptor: V2ProbeDescriptor, *, current_metric_id: str, kind: str
) -> tuple[V2MetricDescriptor, ...]:
    """Return same-Group Metrics that support ``kind`` in declaration order."""

    current = next((metric for metric in descriptor.metrics if metric.id == current_metric_id), None)
    if current is None or current.group_id is None or not descriptor.metric_groups:
        return ()
    return tuple(
        metric
        for metric in descriptor.metrics
        if metric.group_id == current.group_id and kind in metric.capabilities.charts
    )


def cycle_switch_metric(
    descriptor: V2ProbeDescriptor, *, current_metric_id: str, kind: str, step: int
) -> V2MetricDescriptor | None:
    """Return the adjacent related Metric, or ``None`` without an alternative."""

    candidates = switch_candidates(descriptor, current_metric_id=current_metric_id, kind=kind)
    if len(candidates) < 2:
        return None
    current_index = next(index for index, metric in enumerate(candidates) if metric.id == current_metric_id)
    return candidates[(current_index + (1 if step >= 0 else -1)) % len(candidates)]


def normalization_category(field: str) -> SwitchNormalization | None:
    """Map a Dataset unsupported field to its one switch-normalization category."""

    if field == "range.period":
        return "period"
    if field == "query.group_by":
        return "group_by"
    if field == "query.granularity":
        return "granularity"
    if field == "query.top":
        return "top"
    if field == "query.filters" or field.startswith("query.filters."):
        return "filters"
    return None


def normalize_switch_config(
    config: CustomChartConfig,
    target: V2MetricDescriptor,
    category: SwitchNormalization,
) -> CustomChartConfig | None:
    """Apply one target-Metric default, or return ``None`` when it cannot change config."""

    defaults = target.defaults.get(config.kind)
    if category == "filters":
        filters = () if defaults is None else defaults.filters
        updated = config if filters == config.filters else replace(config, filters=filters)
    elif defaults is None:
        return None
    elif category == "period" and defaults.period is not None:
        if config.date_range.period == defaults.period:
            return None
        updated = replace(
            config,
            date_range=resolve_date_range(config.kind, period=defaults.period, since=None, until=None),
        )
    elif category == "group_by":
        updated = replace(config, group_by=defaults.group_by)
    elif category == "granularity" and defaults.granularity is not None:
        updated = replace(config, granularity=defaults.granularity)
    elif category == "top":
        updated = replace(config, top=defaults.top)
    else:
        return None
    return None if updated == config else updated
