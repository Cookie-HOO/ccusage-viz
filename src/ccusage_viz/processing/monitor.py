from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import floor, isfinite, log10
from typing import Any, TypeAlias, cast

from ccusage_viz.domain import TokenUsage, UsageRecord
from ccusage_viz.options import StandaloneLaunch
from ccusage_viz.project_identity import (
    ExactProjectDisplayKey,
    exact_project_display_key,
    resolve_projects,
    unique_projects,
)

MonitorKey: TypeAlias = str | ExactProjectDisplayKey


def monitor_key_sort_key(key: MonitorKey) -> tuple[str, str, str]:
    """Sort Monitor dimensions without treating display text as identity."""
    if isinstance(key, ExactProjectDisplayKey):
        return ("project", key.label.casefold(), key.agent.casefold())
    return ("scalar", key.casefold(), "")


@dataclass(frozen=True, slots=True)
class CounterSnapshot:
    total: TokenUsage
    models: dict[str, TokenUsage] = field(default_factory=dict)
    agents: dict[str, TokenUsage] = field(default_factory=dict)
    projects: dict[ExactProjectDisplayKey, TokenUsage] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObservedInterval:
    started_at: float
    ended_at: float
    ended_wall: datetime
    seconds: float
    total: float
    models: dict[str, float]
    agents: dict[str, float]
    projects: dict[MonitorKey, float]


@dataclass(frozen=True, slots=True)
class MinuteRollup:
    minute: int
    started_at: float
    ended_at: float
    ended_wall: datetime
    covered_seconds: float
    total: float
    models: dict[str, float]
    agents: dict[str, float]
    projects: dict[MonitorKey, float]


@dataclass(frozen=True, slots=True)
class ObservedBucket:
    started_at: float
    ended_at: float
    ended_wall: datetime
    values: dict[MonitorKey, float]


class ObservedTPM:
    """Retain authoritative Total and Model deltas independently of the active view."""

    model_limit = 256
    native_seconds = 3600
    retention_seconds = 24 * 3600

    def __init__(
        self,
        *,
        window_seconds: int,
        by: str | None,
        top: int | None,
        model_selectors: tuple[str, ...] = (),
    ) -> None:
        self.window_seconds = window_seconds
        self.by = by
        self.top = top
        self.model_selectors = model_selectors
        self.previous: CounterSnapshot | None = None
        self.previous_at: float | None = None
        self.previous_raw_at: float | None = None
        self.previous_wall: datetime | None = None
        self.clock_offset = 0.0
        self.intervals: deque[ObservedInterval] = deque()
        self.rollups: deque[MinuteRollup] = deque()
        self.current_interval: ObservedInterval | None = None
        self.tracked_models: set[str] = set()
        self.resets = 0
        self.overflowed_models = False
        self.y_axis_max: float | None = None
        self.y_axis_low_samples = 0
        self.y_axis_semantics = self._scale_semantics()
        self.sample_generation = 0
        self.y_axis_generation = -1

    def _scale_semantics(self) -> tuple[str | None, int, int | None, tuple[str, ...]]:
        return (
            self.by,
            self.window_seconds,
            self.top,
            self.model_selectors if self.by == "model" else (),
        )

    def update_y_axis(self, maximum: float) -> float:
        """Return a stable upper bound without rescaling on display-only repaints."""
        semantics = self._scale_semantics()
        semantics_changed = semantics != self.y_axis_semantics
        if semantics_changed:
            self.y_axis_max = None
            self.y_axis_low_samples = 0
            self.y_axis_semantics = semantics
            self.y_axis_generation = -1
        if self.y_axis_max is not None and self.y_axis_generation == self.sample_generation:
            return self.y_axis_max
        self.y_axis_max, self.y_axis_low_samples = _stable_y_max(
            maximum, self.y_axis_max, self.y_axis_low_samples
        )
        self.y_axis_generation = self.sample_generation
        return self.y_axis_max

    def _normalize(self, snapshot: CounterSnapshot) -> CounterSnapshot:
        # A bounded identity set keeps monitor memory finite. Agent/project labels
        # remain independent projections; model tracking preserves existing behavior.
        available = self.model_limit - len(self.tracked_models)
        if available > 0:
            self.tracked_models.update(
                sorted(set(snapshot.models) - self.tracked_models)[:available]
            )
        overflowed = any(name not in self.tracked_models for name in snapshot.models)
        self.overflowed_models = self.overflowed_models or overflowed
        models = {
            name: snapshot.models[name]
            for name in sorted(self.tracked_models)
            if name in snapshot.models
        }
        return CounterSnapshot(
            snapshot.total, models, dict(snapshot.agents), dict(snapshot.projects)
        )

    def add(self, counters: CounterSnapshot, now: float, wall: datetime | None = None) -> bool:
        """Accept a cumulative snapshot; return whether it created an observed interval."""
        wall = wall or datetime.now().astimezone()
        current = self._normalize(counters)
        display_now = now + self.clock_offset
        if self.previous is None or self.previous_at is None:
            self.current_interval = None
            self.previous = current
            self.previous_at = display_now
            self.previous_raw_at = now
            self.previous_wall = wall
            return False
        seconds = now - (self.previous_raw_at if self.previous_raw_at is not None else now)
        previous = self.previous
        started_at = self.previous_at
        self.previous = current
        self.previous_at = display_now
        self.previous_raw_at = now
        self.previous_wall = wall
        now = display_now
        if seconds <= 0:
            self.current_interval = None
            return False
        total_delta = current.total.total - previous.total.total
        resets_before = self.resets
        if total_delta < 0:
            self.current_interval = None
            self.resets += 1
            self._maintain(now)
            return False

        def deltas(
            current_values: Mapping[Any, TokenUsage],
            previous_values: Mapping[Any, TokenUsage],
            *,
            new_as_zero: bool = False,
        ) -> dict[MonitorKey, float]:
            values: dict[MonitorKey, float] = {}
            for raw_name, usage in current_values.items():
                name = cast(MonitorKey, raw_name)
                before = previous_values.get(raw_name)
                if before is None:
                    if not new_as_zero:
                        continue
                    before = TokenUsage.zero()
                delta = usage.total - before.total
                if delta < 0:
                    self.resets += 1
                    continue
                values[name] = delta
            if sum(values.values()) > total_delta:
                self.resets += 1
                return {"Other": total_delta} if total_delta else {}
            residual = total_delta - sum(values.values())
            if residual:
                values["Other"] = values.get("Other", 0) + residual
            return values

        interval = ObservedInterval(
            started_at,
            now,
            wall,
            seconds,
            total_delta,
            cast(dict[str, float], deltas(current.models, previous.models)),
            cast(dict[str, float], deltas(current.agents, previous.agents)),
            deltas(current.projects, previous.projects, new_as_zero=True),
        )
        self.intervals.append(interval)
        self.current_interval = interval if self.resets == resets_before else None
        self.sample_generation += 1
        self._maintain(now)
        return True

    def is_discontinuous(self, now: float, wall: datetime, gap_limit: float) -> bool:
        if self.previous_raw_at is None or self.previous_wall is None:
            return False
        raw_elapsed = now - self.previous_raw_at
        wall_elapsed = (wall - self.previous_wall).total_seconds()
        return (
            raw_elapsed > gap_limit
            or wall_elapsed > gap_limit
            or wall_elapsed - raw_elapsed > gap_limit
        )

    def rebaseline(
        self, counters: CounterSnapshot, now: float, wall: datetime | None = None
    ) -> None:
        """Discard a discontinuous sampling interval without clearing retained history."""
        wall = wall or datetime.now().astimezone()
        if self.previous_raw_at is not None and self.previous_wall is not None:
            raw_elapsed = max(0.0, now - self.previous_raw_at)
            wall_elapsed = max(0.0, (wall - self.previous_wall).total_seconds())
            self.clock_offset += max(0.0, wall_elapsed - raw_elapsed)
        display_now = now + self.clock_offset
        self.current_interval = None
        self.previous = self._normalize(counters)
        self.previous_at = display_now
        self.previous_raw_at = now
        self.previous_wall = wall
        self.y_axis_max = 0.0
        self.y_axis_low_samples = 0
        self.y_axis_generation = -1
        self._maintain(display_now)

    def display_now(self, now: float) -> float:
        return now + self.clock_offset

    @staticmethod
    def _slice_interval(
        interval: ObservedInterval, started_at: float, ended_at: float
    ) -> ObservedInterval:
        fraction = (ended_at - started_at) / interval.seconds
        return ObservedInterval(
            started_at,
            ended_at,
            interval.ended_wall - timedelta(seconds=interval.ended_at - ended_at),
            ended_at - started_at,
            interval.total * fraction,
            {name: value * fraction for name, value in interval.models.items()},
            {name: value * fraction for name, value in interval.agents.items()},
            {name: value * fraction for name, value in interval.projects.items()},
        )

    def _append_rollup(self, interval: ObservedInterval) -> None:
        minute = int(interval.started_at // 60)
        rollup = MinuteRollup(
            minute,
            interval.started_at,
            interval.ended_at,
            interval.ended_wall,
            interval.seconds,
            interval.total,
            dict(interval.models),
            dict(interval.agents),
            dict(interval.projects),
        )
        if self.rollups and self.rollups[-1].minute == minute:
            previous = self.rollups.pop()

            def merged(left: Mapping[Any, float], right: Mapping[Any, float]) -> dict[Any, float]:
                values: defaultdict[Any, float] = defaultdict(float, left)
                for name, value in right.items():
                    values[name] += value
                return dict(values)

            rollup = MinuteRollup(
                minute,
                min(previous.started_at, rollup.started_at),
                max(previous.ended_at, rollup.ended_at),
                max(previous.ended_wall, rollup.ended_wall),
                previous.covered_seconds + rollup.covered_seconds,
                previous.total + rollup.total,
                merged(previous.models, rollup.models),
                merged(previous.agents, rollup.agents),
                merged(previous.projects, rollup.projects),
            )
        self.rollups.append(rollup)

    def _maintain(self, now: float) -> None:
        native_cutoff = now - self.native_seconds
        while self.intervals and self.intervals[0].started_at < native_cutoff:
            interval = self.intervals.popleft()
            old_end = min(interval.ended_at, native_cutoff)
            cursor = interval.started_at
            while cursor < old_end:
                end = min(old_end, (int(cursor // 60) + 1) * 60)
                self._append_rollup(self._slice_interval(interval, cursor, end))
                cursor = end
            if interval.ended_at > native_cutoff:
                self.intervals.appendleft(
                    self._slice_interval(interval, native_cutoff, interval.ended_at)
                )
                break

        cutoff = now - self.retention_seconds
        while self.rollups and self.rollups[0].ended_at <= cutoff:
            self.rollups.popleft()
        if self.rollups and self.rollups[0].started_at < cutoff:
            rollup = self.rollups.popleft()
            duration = rollup.ended_at - rollup.started_at
            fraction = (rollup.ended_at - cutoff) / duration
            self.rollups.appendleft(
                MinuteRollup(
                    rollup.minute,
                    cutoff,
                    rollup.ended_at,
                    rollup.ended_wall,
                    rollup.covered_seconds * fraction,
                    rollup.total * fraction,
                    {name: value * fraction for name, value in rollup.models.items()},
                    {name: value * fraction for name, value in rollup.agents.items()},
                    {name: value * fraction for name, value in rollup.projects.items()},
                )
            )

    def _segments(self, now: float) -> tuple[MinuteRollup | ObservedInterval, ...]:
        self._maintain(now)
        return (*self.rollups, *self.intervals)

    def _values(self, segment: MinuteRollup | ObservedInterval) -> dict[MonitorKey, float]:
        if self.by is None:
            return {"Total": float(segment.total)}
        values = getattr(segment, f"{self.by}s")
        if self.by != "model" or not self.model_selectors:
            return {name: float(value) for name, value in values.items()}
        selected: defaultdict[MonitorKey, float] = defaultdict(float)
        for name, value in values.items():
            key = name if _matches_selector(name, self.model_selectors) else "Other"
            selected[key] += value
        return dict(selected)

    @staticmethod
    def _covered_seconds(
        segment: MinuteRollup | ObservedInterval, overlap: float, duration: float
    ) -> float:
        covered = segment.covered_seconds if isinstance(segment, MinuteRollup) else segment.seconds
        return covered * overlap / duration

    def buckets(
        self, now: float, count: int, wall: datetime | None = None
    ) -> tuple[ObservedBucket, ...]:
        count = max(2, count)
        wall = wall or datetime.now().astimezone()
        started_at = now - self.window_seconds
        width = self.window_seconds / count
        segments = self._segments(now)
        token_totals: defaultdict[MonitorKey, float] = defaultdict(float)
        for segment in segments:
            overlap = max(0.0, min(now, segment.ended_at) - max(started_at, segment.started_at))
            duration = segment.ended_at - segment.started_at
            if overlap <= 0 or duration <= 0:
                continue
            for key, value in self._values(segment).items():
                token_totals[key] += value * overlap / duration
        names = _top_names(dict(token_totals), self.top if self.by is not None else None)
        buckets: list[ObservedBucket] = []
        cumulative: defaultdict[MonitorKey, float] = defaultdict(float)
        for index in range(count):
            bucket_start = started_at + index * width
            bucket_end = bucket_start + width
            values: defaultdict[MonitorKey, float] = defaultdict(float)
            covered = 0.0
            for segment in segments:
                overlap = min(bucket_end, segment.ended_at) - max(bucket_start, segment.started_at)
                duration = segment.ended_at - segment.started_at
                if overlap <= 0 or duration <= 0:
                    continue
                covered += self._covered_seconds(segment, overlap, duration)
                for key, value in self._values(segment).items():
                    if value <= 0:
                        continue
                    mapped = key if key in names else "Other"
                    values[mapped] += value * overlap / duration
            if self.by in {"agent", "project"}:
                for key, value in values.items():
                    cumulative[key] += value
                projected = dict(cumulative)
            else:
                projected = (
                    {key: value / covered * 60 for key, value in values.items()} if covered else {}
                )
            ended_wall = wall - timedelta(seconds=max(0.0, now - bucket_end))
            buckets.append(ObservedBucket(bucket_start, bucket_end, ended_wall, projected))
        return tuple(buckets)

    def current_values(self) -> dict[MonitorKey, float]:
        """Project only the newest valid sample pair into the current display."""
        interval = self.current_interval
        if interval is None:
            return {}
        values = self._values(interval)
        if self.by in {None, "model"}:
            values = {key: value / interval.seconds * 60 for key, value in values.items()}
        return _top_other(
            values,
            self.top if self.by is not None else None,
            totals=self._values(interval),
        )

    def rates(self, now: float) -> dict[MonitorKey, float]:
        cutoff = now - self.window_seconds
        tokens: defaultdict[MonitorKey, float] = defaultdict(float)
        seconds = 0.0
        for segment in self._segments(now):
            overlap = max(0.0, min(now, segment.ended_at) - max(cutoff, segment.started_at))
            duration = segment.ended_at - segment.started_at
            if overlap <= 0 or duration <= 0:
                continue
            seconds += self._covered_seconds(segment, overlap, duration)
            for key, value in self._values(segment).items():
                tokens[key] += value * overlap / duration
        if seconds <= 0:
            return {}
        rates = {key: value / seconds * 60 for key, value in tokens.items()}
        return _top_other(rates, self.top if self.by is not None else None, totals=dict(tokens))


def _nice_y_max(maximum: float) -> float:
    """Add headroom and round a finite non-negative maximum to 1/2/5 × 10ⁿ."""
    if not isfinite(maximum) or maximum <= 0:
        return 1.0
    padded = maximum * 1.1
    exponent = floor(log10(padded))
    magnitude = 10.0**exponent
    fraction = padded / magnitude
    step = 1.0 if fraction <= 1 else 2.0 if fraction <= 2 else 5.0 if fraction <= 5 else 10.0
    return step * magnitude


def _stable_y_max(
    maximum: float, previous: float | None, low_samples: int = 0, *, shrink_after: int = 4
) -> tuple[float, int]:
    """Expand immediately and shrink only after sustained low utilization."""
    candidate = _nice_y_max(maximum)
    if previous is None or not isfinite(previous) or previous <= 0 or maximum > previous:
        return candidate, 0
    if maximum < previous * 0.5 and candidate < previous:
        low_samples += 1
        return (candidate, 0) if low_samples >= shrink_after else (previous, low_samples)
    return previous, 0


def _copy_observer(observer: ObservedTPM) -> ObservedTPM:
    copy = ObservedTPM(
        window_seconds=observer.window_seconds,
        by=observer.by,
        top=observer.top,
        model_selectors=observer.model_selectors,
    )
    copy.previous = observer.previous
    copy.previous_at = observer.previous_at
    copy.previous_raw_at = observer.previous_raw_at
    copy.previous_wall = observer.previous_wall
    copy.clock_offset = observer.clock_offset
    copy.intervals = deque(observer.intervals)
    copy.rollups = deque(observer.rollups)
    copy.current_interval = observer.current_interval
    copy.tracked_models = set(observer.tracked_models)
    copy.resets = observer.resets
    copy.overflowed_models = observer.overflowed_models
    copy.y_axis_max = observer.y_axis_max
    copy.y_axis_low_samples = observer.y_axis_low_samples
    copy.y_axis_semantics = observer.y_axis_semantics
    copy.sample_generation = observer.sample_generation
    copy.y_axis_generation = observer.y_axis_generation
    return copy


def _top_names(totals: Mapping[MonitorKey, float], top: int | None) -> set[MonitorKey]:
    if top is None or len(totals) <= top:
        return set(totals)
    ordered = sorted(totals.items(), key=lambda item: (-item[1], monitor_key_sort_key(item[0])))
    return {name for name, _ in ordered[:top]}


def _top_other(
    rates: dict[MonitorKey, float],
    top: int | None,
    *,
    totals: Mapping[MonitorKey, float],
) -> dict[MonitorKey, float]:
    names = _top_names(totals, top)
    if len(names) == len(rates):
        return rates
    kept = {name: rates[name] for name in names}
    kept["Other"] = sum(value for name, value in rates.items() if name not in names)
    return kept


def _matches_selector(value: str, selectors: tuple[str, ...]) -> bool:
    """Match monitor startup selectors without changing their stored spelling."""
    normalized = value.casefold()
    return any(selector.casefold() in normalized for selector in selectors)


def _agent_records(
    records: tuple[UsageRecord, ...], agents: tuple[str, ...]
) -> tuple[UsageRecord, ...]:
    """Apply startup-only agent selection before measuring cumulative counters."""
    if not agents:
        return records
    return tuple(record for record in records if _matches_selector(record.agent, agents))


def _counters(records: tuple[UsageRecord, ...]) -> CounterSnapshot:
    total = TokenUsage.zero()
    models: defaultdict[str, TokenUsage] = defaultdict(TokenUsage.zero)
    agents: defaultdict[str, TokenUsage] = defaultdict(TokenUsage.zero)
    projects: defaultdict[ExactProjectDisplayKey, TokenUsage] = defaultdict(TokenUsage.zero)
    project_refs = unique_projects(
        record.project for record in records if record.project is not None
    )
    for record in records:
        total += record.usage
        agents[record.agent] = agents[record.agent] + record.usage
        if record.project is not None:
            projects[exact_project_display_key(record.project, project_refs)] += record.usage
        for model in record.models:
            models[model.model] = models[model.model] + model.usage
    return CounterSnapshot(total, dict(models), dict(agents), dict(projects))


def _project_records(
    records: tuple[UsageRecord, ...], projects: tuple[str, ...]
) -> tuple[UsageRecord, ...]:
    if not projects:
        return records
    chosen = {
        item.key
        for item in resolve_projects(
            projects, (record.project for record in records if record.project)
        )
    }
    return tuple(
        record for record in records if record.project is not None and record.project.key in chosen
    )


def monitor_rank_keys(values: Mapping[MonitorKey, float]) -> tuple[MonitorKey, ...]:
    return tuple(
        key
        for key, _ in sorted(
            values.items(), key=lambda item: (-item[1], monitor_key_sort_key(item[0]))
        )
        if key != "Other"
    )


def monitor_counters(
    options: StandaloneLaunch, records: tuple[UsageRecord, ...]
) -> CounterSnapshot:
    """Build the cumulative counters represented by one filtered Monitor sample."""
    selected = _project_records(
        _agent_records(records, options.chart.filters.agents), options.chart.filters.projects
    )
    return _counters(selected)


def add_monitor_sample(
    observer: ObservedTPM, options: StandaloneLaunch, records: tuple[UsageRecord, ...], now: float
) -> bool:
    """Apply Monitor filters and add a cumulative sample to one observer."""
    return observer.add(monitor_counters(options, records), now)
