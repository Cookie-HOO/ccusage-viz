"""Pure V2 Metric Group switching rules shared by Custom chart hosts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ccusage_viz.custom_models import (
    V2HistoricalChartCapability,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.options import CustomChartConfig


@dataclass(frozen=True, slots=True)
class MetricSwitchRejection:
    field: Literal["kind", "range.period", "query.group_by", "query.granularity"]
    value: str | None


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


def validate_metric_switch(
    config: CustomChartConfig, target: V2MetricDescriptor
) -> MetricSwitchRejection | None:
    """Return a cheap declaration-based rejection without querying the Dataset."""

    capability = target.capabilities.charts.get(config.kind)
    if capability is None:
        return MetricSwitchRejection("kind", config.kind)
    if isinstance(capability, V2MonitorCapability):
        if config.group_by not in capability.group_by:
            return MetricSwitchRejection("query.group_by", config.group_by)
        return None
    if not isinstance(capability, V2HistoricalChartCapability):
        return MetricSwitchRejection("kind", config.kind)
    if capability.periods and config.date_range.period not in capability.periods:
        return MetricSwitchRejection("range.period", config.date_range.period)
    if config.group_by not in capability.group_by:
        return MetricSwitchRejection("query.group_by", config.group_by)
    if config.granularity not in capability.granularities:
        return MetricSwitchRejection("query.granularity", config.granularity)
    return None
