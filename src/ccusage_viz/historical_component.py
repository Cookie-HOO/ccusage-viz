from __future__ import annotations

import time
from collections.abc import Hashable
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum

from ccusage_viz.acquisition import historical_provider_id, historical_query_intent
from ccusage_viz.chart_models import RankingModel
from ccusage_viz.charts.definition import ChartDefinition
from ccusage_viz.charts.registry import ChartRegistry
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.options import (
    HistoricalChartConfig,
    MonitorConfig,
    StackConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.processing.historical import HistoricalModel
from ccusage_viz.processing.summaries import required_summary_coverage
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


class HistoricalPurpose(StrEnum):
    PRIMARY = "primary"
    SUPPLEMENTAL = "supplemental"


@dataclass(frozen=True, slots=True)
class HistoricalCompletion:
    generation: int
    options: StandaloneLaunch
    snapshot: UsageSnapshot
    purpose: HistoricalPurpose = HistoricalPurpose.PRIMARY
    requested_coverage: DateCoverage = _EMPTY_COVERAGE


@dataclass(frozen=True, slots=True)
class HistoricalSubmission:
    generation: int
    options: StandaloneLaunch
    handle: QueryHandle[ProviderResult]
    started: float
    purpose: HistoricalPurpose = HistoricalPurpose.PRIMARY
    requested_coverage: DateCoverage = _EMPTY_COVERAGE

    def result(self) -> HistoricalCompletion:
        result = self.handle.result()
        return HistoricalCompletion(
            self.generation,
            self.options,
            snapshot_from_result(result, time.monotonic() - self.started),
            self.purpose,
            self.requested_coverage,
        )

    def cancel(self) -> None:
        self.handle.cancel()


class HistoricalChartComponent:
    """One historical chart's host-independent data lifecycle."""

    __slots__ = (
        "accepted_at",
        "accepted_generation",
        "accepted_options",
        "candidate",
        "definition",
        "error",
        "supplemental_error",
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
            raise TypeError(f"{definition.chart_id} definition received incompatible configuration")
        self.definition: ChartDefinition = definition
        self.owner_id = owner_id
        self.runtime: QueryRuntime | None = runtime
        self.candidate = options
        self.accepted_generation: int | None = None
        self.accepted_options: StandaloneLaunch | None = None
        self.snapshot: UsageSnapshot | None = None
        self.model: HistoricalModel | None = None
        self.generation = 0
        self.render_revision = 0
        self.accepted_at: datetime | None = None
        self.error: BaseException | None = None
        self.supplemental_error: BaseException | None = None

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

    def _candidate_chart(self) -> HistoricalChartConfig:
        chart = self.candidate.chart
        if isinstance(chart, MonitorConfig):
            raise TypeError("historical components do not support monitor configurations")
        return chart

    def display_coverage(self) -> DateCoverage:
        chart = self._candidate_chart()
        return DateCoverage.from_interval(chart.date_range.since, chart.date_range.until)

    def required_coverage(self) -> DateCoverage:
        chart = self._candidate_chart()
        required = self.display_coverage()
        if chart.date_range.fixed_bounds or chart.presentation.density != "full":
            return required
        period = chart.granularity if isinstance(chart, (TimelineConfig, StackConfig)) else "day"
        return required.merge(required_summary_coverage(chart.date_range.until, period))

    def missing_comparison_coverage(self) -> DateCoverage:
        accepted = self.snapshot.coverage if self.snapshot is not None else DateCoverage()
        required = self.required_coverage()
        display = self.display_coverage()
        comparison = DateCoverage(
            tuple(
                interval
                for required_interval in required.intervals
                for interval in DateCoverage(display.intervals).missing(required_interval)
            )
        )
        return accepted.missing_coverage(comparison)

    def submit(
        self,
        trigger: QueryTrigger,
        *,
        coverage: DateCoverage | None = None,
        purpose: HistoricalPurpose = HistoricalPurpose.PRIMARY,
        required_coverage: DateCoverage | None = None,
    ) -> HistoricalSubmission:
        if self.runtime is None:
            raise RuntimeError("historical component has no query runtime")
        submitted = self.candidate
        started = time.monotonic()
        required = required_coverage or (
            self.missing_comparison_coverage()
            if purpose is HistoricalPurpose.SUPPLEMENTAL
            else self.display_coverage()
        )
        intent = historical_query_intent(
            submitted,
            self.runtime.definition(historical_provider_id(submitted)),
            owner_id=self.owner_id,
            generation=self.generation,
            trigger=trigger,
            coverage=coverage,
            required_coverage=required,
        )
        handle = self.runtime.submit(intent)
        if purpose is HistoricalPurpose.PRIMARY:
            self.error = None
        else:
            self.supplemental_error = None
        return HistoricalSubmission(
            self.generation,
            submitted,
            handle,
            started,
            purpose,
            required,
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
        snapshot = self._merge_snapshot(completion)
        supplemental_error = self.supplemental_error
        if completion.purpose is HistoricalPurpose.SUPPLEMENTAL:
            self.supplemental_error = None
        try:
            model = self._process(self.candidate, snapshot)
        except BaseException:
            self.supplemental_error = supplemental_error
            raise
        self.accepted_generation = self.generation
        self.accepted_options = self.candidate
        self.snapshot = snapshot
        self.model = model
        if completion.purpose is HistoricalPurpose.PRIMARY:
            self.error = None
        else:
            self.supplemental_error = None
        self.accepted_at = accepted_at or datetime.now().astimezone()
        self.render_revision += 1
        return True

    def fail(
        self,
        error: BaseException,
        *,
        generation: int,
        purpose: HistoricalPurpose = HistoricalPurpose.PRIMARY,
    ) -> bool:
        if generation != self.generation:
            return False
        if purpose is HistoricalPurpose.SUPPLEMENTAL:
            self.supplemental_error = error
            if self.snapshot is not None:
                self.model = self._process(self.candidate, self.snapshot)
                self.render_revision += 1
        else:
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

    def _merge_snapshot(self, completion: HistoricalCompletion) -> UsageSnapshot:
        incoming = completion.snapshot
        if (
            completion.purpose is HistoricalPurpose.PRIMARY
            and self.accepted_generation != self.generation
        ):
            return incoming
        if self.snapshot is None:
            return incoming
        returned = incoming.coverage
        records = (
            tuple(
                record
                for record in self.snapshot.records
                if record.day is None or not _coverage_contains(returned, record.day)
            )
            + incoming.records
        )
        notices = (
            incoming.notices
            if completion.purpose is HistoricalPurpose.PRIMARY
            else self.snapshot.notices
        )
        summary_notices = (
            incoming.summary_notices
            if completion.purpose is HistoricalPurpose.PRIMARY
            else self.snapshot.summary_notices
        )
        return replace(
            incoming,
            records=records,
            notices=notices,
            includes_project_attribution=(
                self.snapshot.includes_project_attribution or incoming.includes_project_attribution
            ),
            coverage=self.snapshot.coverage.merge(returned),
            summary_notices=summary_notices,
        )

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
        notices = snapshot.notices
        if self.supplemental_error is not None:
            notices += (Notice("notice.comparison_refresh_failed"),)
        model = self.definition.processor(
            options.chart,
            snapshot.records,
            notices=notices,
            summary_notices=snapshot.summary_notices,
            coverage=snapshot.coverage,
        )
        if not isinstance(model, self.definition.model_type):
            raise TypeError(f"{self.definition.chart_id} definition produced incompatible model")
        return model


def _coverage_contains(coverage: DateCoverage, day: date) -> bool:
    return coverage.covers(DateInterval(day, day))


def snapshot_from_result(result: ProviderResult, elapsed: float) -> UsageSnapshot:
    return UsageSnapshot(
        result.records,
        result.notices,
        elapsed,
        result.includes_project_attribution,
        result.coverage,
        result.summary_notices,
    )
