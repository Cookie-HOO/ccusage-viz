"""Lifecycle state for source-owned Dataset V2 Monitor observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ccusage_viz.custom_protocol import V2MonitorResponse
from ccusage_viz.custom_models import V2HistoricalChartCapability, V2ProbeDescriptor
from ccusage_viz.options import CustomChartConfig


@dataclass(frozen=True, slots=True)
class CustomMonitorCompletion:
    generation: int
    config: CustomChartConfig
    response: V2MonitorResponse


class CustomMonitorComponent:
    """Keep the latest source-owned monitor fact without locally aggregating it."""

    __slots__ = (
        "accepted_at",
        "accepted_config",
        "accepted_response",
        "candidate",
        "error",
        "generation",
        "render_revision",
    )

    def __init__(self, config: CustomChartConfig) -> None:
        if config.kind != "monitor":
            raise ValueError("custom monitor component requires a monitor configuration")
        self.candidate = config
        self.accepted_config: CustomChartConfig | None = None
        self.accepted_response: V2MonitorResponse | None = None
        self.accepted_at: datetime | None = None
        self.error: BaseException | None = None
        self.generation = 0
        self.render_revision = 0

    @property
    def pending(self) -> bool:
        return self.accepted_config != self.candidate

    def configure(self, config: CustomChartConfig, *, data_affecting: bool) -> None:
        if config.kind != "monitor":
            raise ValueError("custom monitor component requires a monitor configuration")
        if config == self.candidate:
            return
        self.candidate = config
        if data_affecting:
            self.generation += 1
            self.error = None
        self.render_revision += 1

    def accept(self, completion: CustomMonitorCompletion, *, accepted_at: datetime) -> bool:
        if completion.generation != self.generation or completion.config != self.candidate:
            return False
        if self.candidate.metric_id is not None and completion.response.metric_id != self.candidate.metric_id:
            return False
        self.accepted_config = completion.config
        self.accepted_response = completion.response
        self.accepted_at = accepted_at
        self.error = None
        self.render_revision += 1
        return True

    def fail(self, error: BaseException, *, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.error = error
        self.render_revision += 1
        return True


def resolve_metric(config: CustomChartConfig, descriptor: V2ProbeDescriptor) -> CustomChartConfig:
    """Resolve an omitted Metric from a V2 Probe without guessing ambiguous sources."""

    if config.metric_id is not None:
        metric = next((metric for metric in descriptor.metrics if metric.id == config.metric_id), None)
        if metric is None:
            raise ValueError("selected metric is not declared by runtime probe")
        ranking = metric.capabilities.charts.get("ranking")
        periods = ranking.periods if isinstance(ranking, V2HistoricalChartCapability) else ()
        return replace(config, metric_summary=metric.summary, metric_periods=periods, metric_titles=(metric.title.en, metric.title.zh_cn))
    selected = descriptor.default_metric_id
    if selected is None and len(descriptor.metrics) == 1:
        selected = descriptor.metrics[0].id
    if selected is None:
        raise ValueError("dataset declares multiple metrics; specify --metric")
    metric = next(metric for metric in descriptor.metrics if metric.id == selected)
    ranking = metric.capabilities.charts.get("ranking")
    periods = ranking.periods if isinstance(ranking, V2HistoricalChartCapability) else ()
    return replace(config, metric_id=selected, metric_summary=metric.summary, metric_periods=periods, metric_titles=(metric.title.en, metric.title.zh_cn))
