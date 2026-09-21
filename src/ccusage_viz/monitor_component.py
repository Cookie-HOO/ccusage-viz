from __future__ import annotations

import time
from collections.abc import Hashable
from dataclasses import dataclass
from datetime import date, datetime

from ccusage_viz.acquisition import historical_provider_id, monitor_query_intent
from ccusage_viz.chart_models import (
    MetricDescriptor,
    ObservedScope,
    RankingModel,
    ScalarRankingEntry,
    ScalarSeries,
    TimelineModel,
)
from ccusage_viz.charts.definition import ChartDefinition
from ccusage_viz.charts.registry import ChartRegistry
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.domain import UsageRecord
from ccusage_viz.options import MonitorConfig, StandaloneLaunch
from ccusage_viz.processing.monitor import (
    MonitorKey,
    ObservedTPM,
    _copy_observer,
    monitor_counters,
    monitor_key_sort_key,
    monitor_rank_keys,
)
from ccusage_viz.project_identity import ExactProjectDisplayKey
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult, QueryTrigger
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.base import RenderContext, render_audit
from ccusage_viz.render.observation import render_observation


@dataclass(frozen=True, slots=True)
class MonitorCompletion:
    generation: int
    options: StandaloneLaunch
    records: tuple[UsageRecord, ...]
    elapsed: float


@dataclass(frozen=True, slots=True)
class MonitorSubmission:
    generation: int
    options: StandaloneLaunch
    handle: QueryHandle[ProviderResult]
    started: float

    def result(self) -> MonitorCompletion:
        result = self.handle.result()
        return MonitorCompletion(
            self.generation,
            self.options,
            result.records,
            time.monotonic() - self.started,
        )

    def cancel(self) -> None:
        self.handle.cancel()


class MonitorComponent:
    """One Monitor runtime's host-independent cumulative-sample lifecycle."""

    __slots__ = (
        "accepted_at",
        "accepted_options",
        "accepted_records",
        "candidate",
        "display_query_pending",
        "error",
        "generation",
        "last_elapsed",
        "monitor_started_at",
        "observer",
        "owner_id",
        "rank_changes",
        "rebaseline_pending",
        "refreshed_at",
        "registry",
        "render_revision",
        "runtime",
        "value_changes",
    )

    def __init__(
        self,
        options: StandaloneLaunch,
        *,
        registry: ChartRegistry,
        owner_id: str = "monitor",
        runtime: QueryRuntime | None = None,
        monitor_started_at: datetime | None = None,
    ) -> None:
        chart = self._monitor_config(options)
        self.registry = registry
        self.owner_id = owner_id
        self.runtime = runtime
        self.candidate = options
        self.accepted_options: StandaloneLaunch | None = None
        self.accepted_records: tuple[UsageRecord, ...] = ()
        self.observer = ObservedTPM(
            window_seconds=chart.window_seconds,
            by=chart.by,
            top=chart.top,
            model_selectors=chart.filters.models,
        )
        self.generation = 0
        self.render_revision = 0
        self.accepted_at: datetime | None = None
        self.refreshed_at: float | None = None
        self.last_elapsed: float | None = None
        self.monitor_started_at = monitor_started_at
        self.error: BaseException | None = None
        self.rebaseline_pending = False
        self.display_query_pending = False
        self.value_changes = RefreshDeltas()
        self.rank_changes = RefreshRanks()

    @property
    def deltas(self) -> dict[Hashable, float]:
        return self.value_changes.current

    @property
    def rank_deltas(self) -> dict[Hashable, int]:
        return self.rank_changes.current

    def configure(self, options: StandaloneLaunch, *, data_affecting: bool) -> None:
        self._monitor_config(options)
        if options == self.candidate:
            return
        self.candidate = options
        if data_affecting:
            self.generation += 1
            self.rebaseline_pending = True
            self.observer.current_interval = None
            self.clear_changes()
        else:
            self._configure_observer(self._monitor_config(options))
            self.render_revision += 1
            if self.accepted_options is not None:
                self.accepted_options = options

    def submit(
        self,
        trigger: QueryTrigger,
        *,
        sample_ordinal: int = 0,
        today: date | None = None,
    ) -> MonitorSubmission:
        if self.runtime is None:
            raise RuntimeError("monitor component has no query runtime")
        submitted = self.candidate
        started = time.monotonic()
        provider_id = historical_provider_id(submitted)
        intent = monitor_query_intent(
            submitted,
            self.runtime.definition(provider_id),
            owner_id=self.owner_id,
            generation=self.generation,
            trigger=trigger,
            sample_ordinal=sample_ordinal,
            today=today,
        )
        handle = self.runtime.submit(intent)
        if trigger is QueryTrigger.STARTUP and self.monitor_started_at is None:
            self.monitor_started_at = datetime.now().astimezone()
        self.error = None
        return MonitorSubmission(self.generation, submitted, handle, started)

    def accept(
        self,
        completion: MonitorCompletion,
        *,
        now: float,
        wall: datetime | None = None,
        detect_gap: bool = True,
    ) -> bool:
        if completion.generation != self.generation:
            return False
        self._monitor_config(completion.options)
        chart = self._monitor_config(self.candidate)
        wall = wall or datetime.now().astimezone()
        counters = monitor_counters(self.candidate, completion.records)
        self._configure_observer(chart)
        gap_limit = self.candidate.host.interval * 2
        should_rebaseline = self.rebaseline_pending or (
            detect_gap and self.observer.is_discontinuous(now, wall, gap_limit)
        )
        if should_rebaseline:
            self.observer.rebaseline(counters, now, wall)
            self.clear_changes()
            self.rebaseline_pending = False
            values = self.observer.current_values()
            self.observer.update_y_axis(max(values.values(), default=0.0))
        else:
            self.observer.add(counters, now, wall)
            values = self.observer.current_values()
            if values:
                self.value_changes.accept(values)
                self.rank_changes.accept(monitor_rank_keys(values))
            else:
                self.clear_changes()
            self.observer.update_y_axis(max(values.values(), default=0.0))
        self.accepted_options = self.candidate
        self.accepted_records = completion.records
        self.accepted_at = wall
        self.refreshed_at = now
        self.last_elapsed = completion.elapsed
        self.error = None
        self.render_revision += 1
        return True

    def fail(self, error: BaseException, *, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.error = error
        return True

    def preview(self, options: StandaloneLaunch) -> MonitorComponent:
        """Return a display-only view of ``options`` without changing accepted data.

        A Monitor sample is interpreted using its window, filters, and grouping.
        Reusing the accepted observer for a candidate that changes any of those
        settings would give old observations candidate labels or scope.  Such a
        candidate therefore gets an intentionally empty sampling view until its
        first matching sample is accepted.
        """
        preview = MonitorComponent(
            options,
            registry=self.registry,
            monitor_started_at=self.monitor_started_at,
        )
        preview.accepted_options = options
        preview.accepted_at = self.accepted_at
        preview.refreshed_at = self.refreshed_at
        preview.last_elapsed = self.last_elapsed
        preview.render_revision = self.render_revision
        preview.display_query_pending = self._data_configuration_changed(
            self.accepted_options, options
        )
        if preview.display_query_pending:
            return preview

        preview.accepted_records = self.accepted_records
        preview.observer = _copy_observer(self.observer)
        preview._configure_observer(self._monitor_config(options))
        preview.value_changes = RefreshDeltas(
            dict(self.value_changes.previous),
            dict(self.value_changes.current),
            self.value_changes.initialized,
        )
        preview.rank_changes = RefreshRanks(
            dict(self.rank_changes.previous),
            dict(self.rank_changes.current),
        )
        return preview

    def display(self) -> MonitorComponent:
        """Return the safe immediate display view for the current candidate."""
        return self if self.display_query_pending else self.preview(self.candidate)

    def clear_changes(self) -> None:
        self.value_changes.clear()
        self.rank_changes.clear()

    def pause(self) -> None:
        self.observer.current_interval = None
        self.clear_changes()

    def resume(self, *, now: float, wall: datetime | None = None) -> None:
        wall = wall or datetime.now().astimezone()
        if self.observer.previous is not None:
            self.observer.rebaseline(self.observer.previous, now, wall)
        self.clear_changes()

    def current_values(
        self, now: float, *, wall: datetime | None = None
    ) -> dict[MonitorKey, float]:
        del now, wall
        return self.observer.current_values()

    def timeline_model(
        self,
        *,
        now: float,
        count: int,
        wall: datetime | None = None,
    ) -> TimelineModel:
        buckets = self._buckets(now, count, wall)
        names = tuple(dict.fromkeys(key for bucket in buckets for key in bucket.values))
        series = tuple(
            ScalarSeries(
                name,
                name,
                tuple(bucket.values.get(name) for bucket in buckets),
                name == "Other",
            )
            for name in names
        )
        return TimelineModel(
            (),
            (),
            observed_at=tuple(bucket.ended_wall for bucket in buckets),
            monitor_started_at=self.monitor_started_at,
            observed_series=series,
            metric=self._metric(),
            observed_scope=self._scope(),
            y_axis_max=self.observer.y_axis_max,
            observed_current=self._current_entries(),
        )

    def ranking_model(
        self,
        *,
        now: float,
        count: int = 32,
        wall: datetime | None = None,
    ) -> RankingModel:
        values = self.current_values(now, wall=wall)
        entries = tuple(
            self._observed_entry(name, value)
            for name, value in sorted(
                values.items(), key=lambda item: (-item[1], monitor_key_sort_key(item[0]))
            )
        )
        return RankingModel(
            (),
            None,
            observed_entries=entries,
            metric=self._metric(),
            observed_scope=self._scope(),
        )

    def model(
        self,
        *,
        now: float,
        count: int,
        wall: datetime | None = None,
    ) -> TimelineModel | RankingModel:
        chart = self._monitor_config(self._active_options())
        if chart.presentation.style in {"ranking", "list"}:
            return self.ranking_model(now=now, count=count, wall=wall)
        return self.timeline_model(now=now, count=count, wall=wall)

    def render(
        self,
        context: RenderContext,
        *,
        now: float,
        count: int,
        wall: datetime | None = None,
    ) -> str:
        model = self.model(now=now, count=count, wall=wall)
        definition = self._definition(model)
        chart = definition.renderer(model, context)
        observation = render_observation(model, context)
        audit = render_audit(context)
        return "\n".join(line for line in (observation, chart, audit) if line)

    def buckets(self, count: int, *, now: float | None = None, wall: datetime | None = None):
        """Project buckets at the last accepted sample, ignoring repaint-time clocks."""
        projection_now = self.refreshed_at if self.refreshed_at is not None else now
        if projection_now is None:
            projection_now = 0.0
        projection_wall = self.accepted_at if self.accepted_at is not None else wall
        return self.observer.buckets(
            self.observer.display_now(projection_now), count, projection_wall
        )

    def _buckets(self, now: float, count: int, wall: datetime | None):
        return self.buckets(count, now=now, wall=wall)

    @staticmethod
    def _observed_entry(name: MonitorKey, value: float) -> ScalarRankingEntry:
        if isinstance(name, ExactProjectDisplayKey):
            return ScalarRankingEntry(name, name.label, value, agent=name.agent)
        return ScalarRankingEntry(name, str(name), value, name == "Other")

    def _current_entries(self) -> tuple[ScalarRankingEntry, ...]:
        return tuple(
            self._observed_entry(name, value)
            for name, value in self.observer.current_values().items()
        )

    def _scope(self) -> ObservedScope:
        chart = self._monitor_config(self._active_options())
        state = (
            "baseline"
            if self.observer.previous is None
            else "ready"
            if self.observer.current_interval is not None
            else "sampling"
        )
        return ObservedScope(
            chart.window_seconds,
            chart.by or "total",
            state,
            chart.filters.agents,
        )

    def _metric(self) -> MetricDescriptor:
        chart = self._monitor_config(self._active_options())
        return MetricDescriptor("tpm" if chart.by in {None, "model"} else "tokens")

    def _active_options(self) -> StandaloneLaunch:
        return self.accepted_options or self.candidate

    def _configure_observer(self, chart: MonitorConfig) -> None:
        self.observer.window_seconds = chart.window_seconds
        self.observer.by = chart.by
        self.observer.top = chart.top
        self.observer.model_selectors = chart.filters.models

    def _definition(self, model: TimelineModel | RankingModel) -> ChartDefinition:
        chart_id = "ranking" if isinstance(model, RankingModel) else "timeline"
        definition = self.registry.get(chart_id)
        if not isinstance(model, definition.model_type):
            raise TypeError(f"{chart_id} definition received incompatible Monitor model")
        return definition

    @staticmethod
    def _data_configuration_changed(
        accepted: StandaloneLaunch | None, candidate: StandaloneLaunch
    ) -> bool:
        if accepted is None:
            return False
        previous = MonitorComponent._monitor_config(accepted)
        proposed = MonitorComponent._monitor_config(candidate)
        return (previous.by, previous.filters) != (proposed.by, proposed.filters)

    @staticmethod
    def _monitor_config(options: StandaloneLaunch) -> MonitorConfig:
        if not isinstance(options.chart, MonitorConfig):
            raise TypeError("monitor components require a monitor configuration")
        return options.chart
