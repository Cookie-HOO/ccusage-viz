"""Lifecycle state for source-owned Dataset V2 Monitor observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ccusage_viz.custom_protocol import V2MonitorResponse
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
        if config.kind != "monitor" or config.metric_id is None:
            raise ValueError("custom monitor component requires a metric monitor configuration")
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
        if config.kind != "monitor" or config.metric_id is None:
            raise ValueError("custom monitor component requires a metric monitor configuration")
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
        if completion.response.metric_id != self.candidate.metric_id:
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
