from __future__ import annotations

import time
from collections.abc import Hashable
from dataclasses import dataclass
from datetime import datetime

from ccusage_viz.acquisition import historical_provider_id, historical_query_intent
from ccusage_viz.chart_models import RankingModel
from ccusage_viz.charts.definition import ChartDefinition
from ccusage_viz.charts.registry import ChartRegistry
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.options import MonitorConfig, StandaloneLaunch
from ccusage_viz.processing.historical import HistoricalModel
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult, QueryTrigger
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.base import RenderContext

_EMPTY_COVERAGE = DateCoverage()


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    records: tuple[UsageRecord, ...]
    notices: tuple[Notice, ...]
    elapsed: float
    includes_project_attribution: bool = False
    coverage: DateCoverage = _EMPTY_COVERAGE
    summary_notices: tuple[Notice, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoricalCompletion:
    generation: int
    options: StandaloneLaunch
    snapshot: UsageSnapshot


@dataclass(frozen=True, slots=True)
class HistoricalSubmission:
    generation: int
    options: StandaloneLaunch
    handle: QueryHandle[ProviderResult]
    started: float

    def result(self) -> HistoricalCompletion:
        result = self.handle.result()
        return HistoricalCompletion(
            self.generation,
            self.options,
            snapshot_from_result(result, time.monotonic() - self.started),
        )

    def cancel(self) -> None:
        self.handle.cancel()


class HistoricalChartComponent:
    """One historical chart's host-independent data lifecycle."""

    __slots__ = (
        "accepted_at",
        "accepted_options",
        "candidate",
        "definition",
        "error",
        "generation",
        "model",
        "owner_id",
        "render_revision",
        "runtime",
        "snapshot",
    )

    def __init__(
        self,
        options: StandaloneLaunch,
        *,
        owner_id: str,
        runtime: QueryRuntime | None,
        registry: ChartRegistry,
    ) -> None:
        if isinstance(options.chart, MonitorConfig):
            raise TypeError("historical components do not support monitor configurations")
        definition = registry.get(options.chart.kind)
        if not isinstance(options.chart, definition.config_type):
            raise TypeError(
                f"{definition.chart_id} definition received incompatible configuration"
            )
        self.definition: ChartDefinition = definition
        self.owner_id = owner_id
        self.runtime: QueryRuntime | None = runtime
        self.candidate = options
        self.accepted_options: StandaloneLaunch | None = None
        self.snapshot: UsageSnapshot | None = None
        self.model: HistoricalModel | None = None
        self.generation = 0
        self.render_revision = 0
        self.accepted_at: datetime | None = None
        self.error: BaseException | None = None

    def configure(self, options: StandaloneLaunch, *, data_affecting: bool) -> None:
        self._validate_options(options)
        if options == self.candidate:
            return
        self.candidate = options
        if data_affecting:
            self.generation += 1
        else:
            self.render_revision += 1
            if self.snapshot is not None:
                self.model = self._process(options, self.snapshot)
                self.accepted_options = options

    def submit(
        self,
        trigger: QueryTrigger,
        *,
        coverage: DateCoverage | None = None,
    ) -> HistoricalSubmission:
        if self.runtime is None:
            raise RuntimeError("historical component has no query runtime")
        submitted = self.candidate
        started = time.monotonic()
        intent = historical_query_intent(
            submitted,
            self.runtime.definition(historical_provider_id(submitted)),
            owner_id=self.owner_id,
            generation=self.generation,
            trigger=trigger,
            coverage=coverage,
        )
        handle = self.runtime.submit(intent)
        self.error = None
        return HistoricalSubmission(
            self.generation,
            submitted,
            handle,
            started,
        )

    def accept(
        self,
        completion: HistoricalCompletion,
        *,
        accepted_at: datetime | None = None,
    ) -> bool:
        if completion.generation != self.generation:
            return False
        self._validate_options(completion.options)
        model = self._process(self.candidate, completion.snapshot)
        self.accepted_options = self.candidate
        self.snapshot = completion.snapshot
        self.model = model
        self.error = None
        self.accepted_at = accepted_at or datetime.now().astimezone()
        self.render_revision += 1
        return True

    def fail(self, error: BaseException, *, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.error = error
        return True

    def seed(
        self,
        options: StandaloneLaunch,
        snapshot: UsageSnapshot,
        *,
        accepted_at: datetime | None = None,
    ) -> None:
        completion = HistoricalCompletion(self.generation, options, snapshot)
        if not self.accept(completion, accepted_at=accepted_at):
            raise RuntimeError("initial historical snapshot was rejected")

    def render(self, context: RenderContext) -> str:
        if self.model is None:
            raise RuntimeError("historical component has no accepted model")
        return self.definition.renderer(self.model, context)

    def ranking_values(self) -> dict[Hashable, float]:
        model = self._ranking_model()
        return {entry.key: float(entry.usage.total) for entry in model.entries}

    def ranking_keys(self) -> tuple[Hashable, ...]:
        model = self._ranking_model()
        return tuple(entry.key for entry in model.entries if not entry.is_other)

    def _ranking_model(self) -> RankingModel:
        if not isinstance(self.model, RankingModel):
            raise TypeError("ranking state requires an accepted ranking model")
        return self.model

    def _validate_options(self, options: StandaloneLaunch) -> None:
        if isinstance(options.chart, MonitorConfig) or not isinstance(
            options.chart, self.definition.config_type
        ):
            raise TypeError(
                f"{self.definition.chart_id} component received incompatible configuration"
            )

    def _process(self, options: StandaloneLaunch, snapshot: UsageSnapshot) -> HistoricalModel:
        self._validate_options(options)
        model = self.definition.processor(
            options.chart,
            snapshot.records,
            notices=snapshot.notices,
            summary_notices=snapshot.summary_notices,
            coverage=snapshot.coverage,
        )
        if not isinstance(model, self.definition.model_type):
            raise TypeError(
                f"{self.definition.chart_id} definition produced incompatible model"
            )
        return model


def snapshot_from_result(result: ProviderResult, elapsed: float) -> UsageSnapshot:
    return UsageSnapshot(
        result.records,
        result.notices,
        elapsed,
        result.includes_project_attribution,
        result.coverage,
        result.summary_notices,
    )
