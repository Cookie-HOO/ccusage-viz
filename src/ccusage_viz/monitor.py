from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from math import floor, isfinite, log10
from shutil import get_terminal_size

import plotext as plt

from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    wrap_command,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.data_view import BodyView, next_body_view, render_monitor_data
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.demo import generate_demo
from ccusage_viz.diagnostics import format_error
from ccusage_viz.domain import TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
    format_tokens,
    pad_width,
    truncate_width,
)
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    MonitorConfig,
    StandaloneLaunch,
    adjust_standalone,
    compatible_styles,
)
from ccusage_viz.project_identity import project_label, resolve_projects, unique_projects
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.query.models import QueryKind, QueryPlan, QuerySpec
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    isolated_plot,
    plot_height,
    plot_text,
    styled_text,
)
from ccusage_viz.render.palette import COLOR_SCHEMES, categorical_colors, get_color_scheme
from ccusage_viz.schema import parse_usage_records
from ccusage_viz.terminal import InteractiveScreen, Terminal, inspect_terminal
from ccusage_viz.trends import trend_glyph
from ccusage_viz.watch import _controls_line, _dimmed, _input_mode, _read_key


@dataclass(frozen=True, slots=True)
class CounterSnapshot:
    total: TokenUsage
    models: dict[str, TokenUsage] = field(default_factory=dict)
    agents: dict[str, TokenUsage] = field(default_factory=dict)
    projects: dict[str, TokenUsage] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObservedInterval:
    started_at: float
    ended_at: float
    ended_wall: datetime
    seconds: float
    total: float
    models: dict[str, float]
    agents: dict[str, float]
    projects: dict[str, float]


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
    projects: dict[str, float]


@dataclass(frozen=True, slots=True)
class ObservedBucket:
    started_at: float
    ended_at: float
    ended_wall: datetime
    values: dict[str, float]


@dataclass(frozen=True, slots=True)
class MonitorSeries:
    key: str
    label: str
    color: int
    marker_name: str
    marker_glyph: str
    current: float | None


@dataclass(frozen=True, slots=True)
class MonitorSampleResult:
    generation: int
    options: StandaloneLaunch
    records: tuple[UsageRecord, ...]
    elapsed: float


@dataclass(frozen=True, slots=True)
class MonitorSampleFailure:
    generation: int
    error: BaseException


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
            return False
        total_delta = current.total.total - previous.total.total
        if total_delta < 0:
            self.resets += 1
            self._maintain(now)
            return False

        def deltas(
            current_values: dict[str, TokenUsage],
            previous_values: dict[str, TokenUsage],
            *,
            new_as_zero: bool = False,
        ) -> dict[str, float]:
            values: dict[str, float] = {}
            for name, usage in current_values.items():
                before = previous_values.get(name)
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

        self.intervals.append(
            ObservedInterval(
                started_at,
                now,
                wall,
                seconds,
                total_delta,
                deltas(current.models, previous.models),
                deltas(current.agents, previous.agents),
                deltas(current.projects, previous.projects, new_as_zero=True),
            )
        )
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

            def merged(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
                values: defaultdict[str, float] = defaultdict(float, left)
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

    def _values(self, segment: MinuteRollup | ObservedInterval) -> dict[str, float]:
        if self.by is None:
            return {"Total": float(segment.total)}
        values = getattr(segment, f"{self.by}s")
        if self.by != "model" or not self.model_selectors:
            return {name: float(value) for name, value in values.items()}
        selected: defaultdict[str, float] = defaultdict(float)
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
        token_totals: defaultdict[str, float] = defaultdict(float)
        for segment in segments:
            overlap = max(0.0, min(now, segment.ended_at) - max(started_at, segment.started_at))
            duration = segment.ended_at - segment.started_at
            if overlap <= 0 or duration <= 0:
                continue
            for key, value in self._values(segment).items():
                token_totals[key] += value * overlap / duration
        names = _top_names(dict(token_totals), self.top if self.by is not None else None)
        buckets: list[ObservedBucket] = []
        cumulative: defaultdict[str, float] = defaultdict(float)
        for index in range(count):
            bucket_start = started_at + index * width
            bucket_end = bucket_start + width
            values: defaultdict[str, float] = defaultdict(float)
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

    def rates(self, now: float) -> dict[str, float]:
        cutoff = now - self.window_seconds
        tokens: defaultdict[str, float] = defaultdict(float)
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
    copy.tracked_models = set(observer.tracked_models)
    copy.resets = observer.resets
    copy.overflowed_models = observer.overflowed_models
    copy.y_axis_max = observer.y_axis_max
    copy.y_axis_low_samples = observer.y_axis_low_samples
    copy.y_axis_semantics = observer.y_axis_semantics
    copy.sample_generation = observer.sample_generation
    copy.y_axis_generation = observer.y_axis_generation
    return copy


def _top_names(totals: dict[str, float], top: int | None) -> set[str]:
    if top is None or len(totals) <= top:
        return set(totals)
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return {name for name, _ in ordered[:top]}


def _top_other(
    rates: dict[str, float], top: int | None, *, totals: dict[str, float]
) -> dict[str, float]:
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
    projects: defaultdict[str, TokenUsage] = defaultdict(TokenUsage.zero)
    project_refs = unique_projects(
        record.project for record in records if record.project is not None
    )
    for record in records:
        total += record.usage
        agents[record.agent] = agents[record.agent] + record.usage
        if record.project is not None:
            projects[project_label(record.project, project_refs)] += record.usage
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


def _monitor_plan(options: StandaloneLaunch) -> QueryPlan:
    if not isinstance(options.chart, MonitorConfig):
        raise TypeError("monitor query planning requires a monitor configuration")
    # A monitor begins with no observed history, but includes a one-day rollover
    # margin so cumulative counters remain comparable across midnight.
    current_day = datetime.now().astimezone().date()
    since = current_day - timedelta(days=1)
    if options.chart.by == "project" or options.chart.filters.projects:
        return QueryPlan(
            (
                QuerySpec(
                    QueryKind.CLAUDE_DAILY_PROJECTS,
                    (
                        "claude",
                        "daily",
                        "--instances",
                        "--json",
                        "--since",
                        since.strftime("%Y%m%d"),
                        "--until",
                        current_day.strftime("%Y%m%d"),
                        "--offline",
                    ),
                ),
            )
        )
    return QueryPlan(
        (
            QuerySpec(
                QueryKind.UNIFIED_DAILY,
                (
                    "daily",
                    "--by-agent",
                    "--json",
                    "--since",
                    since.isoformat(),
                    "--until",
                    current_day.isoformat(),
                    "--offline",
                    "--no-cost",
                ),
            ),
        )
    )


def _demo_snapshot(options: StandaloneLaunch, ordinal: int) -> tuple[UsageRecord, ...]:
    today = datetime.now().astimezone().date()
    records = generate_demo(
        options.host.demo_size or "medium", DateRange(today - timedelta(days=1), today, None)
    )
    # Cumulative variation is deterministic and remains wholly in memory. The
    # repeating increments create low runs, bursts, and recovery for Demo charts.
    waveform = (1, 1, 2, 1, 6, 14, 5, 2, 1, 3, 8, 2)
    factor = sum(waveform[index % len(waveform)] for index in range(ordinal + 1))
    return tuple(
        UsageRecord(
            record.day,
            record.agent,
            TokenUsage(
                record.usage.total * factor,
                record.usage.input * factor,
                record.usage.output * factor,
                record.usage.cache_read * factor,
                record.usage.cache_creation * factor,
                record.usage.other * factor,
            ),
            record.source,
            record.project,
            tuple(
                type(model)(
                    model.model,
                    TokenUsage(
                        model.usage.total * factor,
                        model.usage.input * factor,
                        model.usage.output * factor,
                        model.usage.cache_read * factor,
                        model.usage.cache_creation * factor,
                        model.usage.other * factor,
                    ),
                )
                for model in record.models
            ),
        )
        for record in records
    )


def _elapsed_labels(buckets: tuple[ObservedBucket, ...]) -> tuple[list[int], list[str]]:
    if not buckets:
        return [], []
    positions = sorted({0, len(buckets) // 2, len(buckets) - 1})
    return positions, [buckets[index].ended_wall.strftime("%H:%M") for index in positions]


def _series_descriptors(
    names: tuple[str, ...],
    series: dict[str, list[float]],
    options: StandaloneLaunch,
    terminal: Terminal,
    translator: Translator,
) -> tuple[MonitorSeries, ...]:
    colors = categorical_colors(
        (name for name in names if name != "Other"), options.chart.presentation.theme
    )
    scheme = get_color_scheme(options.chart.presentation.theme)
    marker_pairs = (("dot", "•"), ("circle", "○"), ("square", "■"), ("diamond", "◆"))
    if terminal.ascii:
        marker_pairs = (("#", "."), ("#", "o"), ("#", "#"), ("#", "D"))
    descriptors = []
    uniform_points = options.chart.presentation.style in {"points", "line-points"}
    for name in names:
        # Stable key ordering prevents a surviving series from changing marker when Top changes.
        index = sum(ord(character) for character in name) % len(marker_pairs)
        marker_name, marker_glyph = (
            (("#", ".") if terminal.ascii else ("dot", "•"))
            if uniform_points
            else marker_pairs[index]
        )
        values = series[name]
        current = next((value for value in reversed(values) if isfinite(value)), None)
        descriptors.append(
            MonitorSeries(
                name,
                translator.text("label.other")
                if name == "Other"
                else translator.text("label.total")
                if name == "Total"
                else name,
                scheme.other if name == "Other" else colors[name],
                marker_name,
                marker_glyph,
                current,
            )
        )
    return tuple(descriptors)


def _monitor_unit(observer: ObservedTPM, translator: Translator) -> str:
    return "TPM" if observer.by in {None, "model"} else translator.text("label.tokens")


def monitor_rank_keys(values: Mapping[str, float]) -> tuple[str, ...]:
    return tuple(
        key
        for key, _ in sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))
        if key != "Other"
    )


def _monitor_value(series: MonitorSeries) -> str:
    return "—" if series.current is None else format_tokens(round(series.current))


def _monitor_value_with_unit(
    series: MonitorSeries, observer: ObservedTPM, translator: Translator
) -> str:
    value = _monitor_value(series)
    return value if value == "—" else f"{value} {_monitor_unit(observer, translator)}"


def _current_heading(mode: str, observer: ObservedTPM, translator: Translator, width: int) -> str:
    unit = _monitor_unit(observer, translator)
    for title in (f"{mode} · {unit}", unit):
        if display_width(title) <= width:
            return center_text(title, width)
    return ""


def _ordered_current(descriptors: tuple[MonitorSeries, ...]) -> list[MonitorSeries]:
    return sorted(
        descriptors,
        key=lambda item: (
            item.current is None,
            -(item.current or 0),
            item.key.casefold(),
            item.label.casefold(),
        ),
    )


def _render_current_rows(
    descriptors: tuple[MonitorSeries, ...],
    context: RenderContext,
    deltas: Mapping[str, float] | None = None,
    rank_deltas: Mapping[str, int] | None = None,
) -> str:
    ordered = _ordered_current(descriptors)
    if not ordered or context.height <= 0 or context.width <= 0:
        return ""

    values = tuple(_monitor_value(item) for item in ordered)
    value_width = max(display_width(value) for value in values)
    rank_width = len(str(len(ordered)))
    delta_values = deltas or {}
    rank_values = rank_deltas or {}
    scheme = get_color_scheme(context.color_scheme)
    value_markers = {}
    rank_markers = {}
    for item in ordered:
        rank_change = rank_values.get(item.key, 0)
        rank_markers[item.key] = (
            styled_text(
                trend_glyph(rank_change, ascii=context.ascii),
                scheme.trend_increase if rank_change > 0 else scheme.trend_decrease,
                context,
                bold=True,
            )
            if item.key != "Other" and rank_change
            else ""
        )
        if item.key not in delta_values:
            value_markers[item.key] = ""
            continue
        change = delta_values[item.key]
        color = (
            scheme.trend_increase
            if change > 0
            else scheme.trend_decrease
            if change < 0
            else scheme.trend_neutral
        )
        value_markers[item.key] = styled_text(
            trend_glyph(change, ascii=context.ascii), color, context, bold=change != 0
        )
    show_rank = any(rank_markers.values())
    show_value = any(value_markers.values())

    fixed_width = rank_width + 2 + value_width
    if show_rank:
        fixed_width += 2
    if show_value:
        fixed_width += 2
    desired_label_width = max(display_width(item.label) for item in ordered)
    minimum_block_width = min(context.width, max(fixed_width + 1, round(context.width * 0.6)))
    label_width = max(1, min(desired_label_width, context.width - fixed_width))
    natural_label_width = max(
        display_width(truncate_width(item.label, label_width)) for item in ordered
    )
    block_width = min(context.width, max(minimum_block_width, fixed_width + natural_label_width))

    max_rows = context.height
    visible_count = min(len(ordered), max_rows)
    if len(ordered) > max_rows:
        visible_count = max(0, max_rows - 1)
    rows = []
    for rank, item in enumerate(ordered[:visible_count], start=1):
        prefix = f"{rank:>{rank_width}} "
        rank_marker = f"{rank_markers[item.key] or ' '} " if show_rank else ""
        value = pad_width(_monitor_value(item), value_width, align="right")
        value_marker = f" {value_markers[item.key] or ' '}" if show_value else ""
        available_label = max(
            1,
            block_width
            - display_width(prefix)
            - display_width(rank_marker)
            - value_width
            - display_width(value_marker)
            - 1,
        )
        label = pad_width(truncate_width(item.label, available_label), available_label)
        row = clip_width(f"{prefix}{rank_marker}{label} {value}{value_marker}", block_width)
        rows.append(center_text(pad_width(row, block_width), context.width))
    if len(ordered) > max_rows:
        remaining = len(ordered) - visible_count
        overflow = clip_width(f"… +{remaining}", block_width)
        rows.append(center_text(pad_width(overflow, block_width), context.width))
    return "\n".join(rows)


def _render(
    observer: ObservedTPM,
    now: float,
    terminal: Terminal,
    translator: Translator,
    options: StandaloneLaunch,
    *,
    buckets: tuple[ObservedBucket, ...] | None = None,
    reserved_rows: int = 2,
    hide_upper_right_axes: bool = False,
    deltas: Mapping[str, float] | None = None,
    rank_deltas: Mapping[str, int] | None = None,
    normalize_title: bool = False,
) -> str:
    window = (
        f"{observer.window_seconds // 3600}h"
        if observer.window_seconds % 3600 == 0
        else f"{observer.window_seconds // 60}m"
    )
    if observer.previous is None:
        state = f" · {translator.text('label.monitor_baseline')}"
    elif not observer.intervals and not observer.rollups:
        state = f" · {translator.text('label.monitor_samples')}"
    else:
        state = ""
    agents = (
        f" · Agent {', '.join(options.chart.filters.agents)}"
        if options.chart.filters.agents
        else ""
    )
    mode = translator.text(
        {
            None: "label.monitor_total_mode",
            "agent": "label.monitor_agent_mode",
            "model": "label.monitor_model_mode",
            "project": "label.monitor_project_mode",
        }[observer.by]
    )
    title = (
        translator.text(
            "label.monitor_compact_growth_title"
            if observer.by in {"agent", "project"}
            else "label.monitor_compact_title",
            window=window,
            mode=mode,
        )
        if normalize_title
        else translator.text(
            "label.monitor_growth_title"
            if observer.by in {"agent", "project"}
            else "label.monitor_title",
            window=window,
            state=state,
            agents=agents,
            mode=mode,
        )
    )
    if buckets is None:
        buckets = observer.buckets(now, max(8, min(32, terminal.width // 4)))
    names = tuple(dict.fromkeys(key for bucket in buckets for key in bucket.values))
    heading = center_text(title, terminal.width)
    if not names:
        return f"{heading}\n{translator.text('message.monitor_empty')}"
    context = RenderContext(
        terminal.width,
        max(1, terminal.height - reserved_rows),
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=options.chart.presentation.theme,
        style=options.chart.presentation.style,
        legend_position=options.chart.presentation.legend,
        hide_upper_right_axes=hide_upper_right_axes,
    )
    series = {name: [bucket.values.get(name, float("nan")) for bucket in buckets] for name in names}
    descriptors = _series_descriptors(names, series, options, terminal, translator)
    if options.chart.presentation.style == "ranking":
        compact_heading = _current_heading(mode, observer, translator, terminal.width)
        rows = _render_current_rows(
            descriptors,
            replace(context, height=max(0, context.height - int(bool(compact_heading)))),
            deltas,
            rank_deltas,
        )
        return "\n".join(line for line in (compact_heading, rows) if line)
    # The default sole Total view stays compact, but explicit value and in-chart
    # presentations remain available while adjusting appearance.
    show_legend = (
        len(names) > 1 or names != ("Total",)
    ) and options.chart.presentation.legend != "hidden"
    show_legend = show_legend or options.chart.presentation.legend in {"inside", "values"}
    below_title = options.chart.presentation.legend in {"below-title", "values"} and show_legend
    with isolated_plot():
        configure_plot(context)
        plt.figure.plot_size(
            context.width,
            plot_height(
                context,
                text_rows=1 + int(below_title),
            ),
        )
        for descriptor in descriptors:
            values = series[descriptor.key]
            marker = plt.marker(
                descriptor.marker_name,
                pixel=plt.pixel(foreground=descriptor.color) if terminal.color else None,
            )
            x_values = list(range(len(buckets)))
            if options.chart.presentation.style == "bars":
                # A missing observation is not zero for lines, but Plotext cannot
                # safely render NaN bar geometry. Keep known zeros intact.
                signal = plt.figure.bar(
                    x_values,
                    [value if isfinite(value) else 0.0 for value in values],
                    marker=marker,
                    width=0.75,
                )
            else:
                if options.chart.presentation.style == "step":
                    x_values = [item for point in x_values for item in (point, point + 1)]
                    values = [item for value in values for item in (value, value)]
                signal = plt.figure.signal(x_values, values, marker=marker).lines(
                    options.chart.presentation.style != "points"
                )
            if show_legend and options.chart.presentation.legend == "inside":
                signal.label(descriptor.label)
            plt.figure.draw(signal)
        positions, labels = _elapsed_labels(buckets)
        plt.figure.ruler("x").ticks(positions, labels)
        y_values = [value for values in series.values() for value in values if isfinite(value)]
        y_max = observer.update_y_axis(max(y_values, default=0.0))
        y_positions = [y_max * index / 4 for index in range(5)]
        plt.figure.ruler("y").lim(0, y_max)
        plt.figure.ruler("y").ticks(
            y_positions, [format_tokens(round(position)) for position in y_positions]
        )
        if options.chart.presentation.legend != "inside":
            plt.figure.legend(False)
        if below_title:
            if options.chart.presentation.legend == "values":
                legend = " · ".join(
                    f"{colored_mark(descriptor.marker_glyph, descriptor.color, context)} "
                    f"{descriptor.label} {_monitor_value_with_unit(descriptor, observer, translator)}"
                    for descriptor in descriptors
                )
            else:
                legend = " · ".join(
                    f"{colored_mark(descriptor.marker_glyph, descriptor.color, context)} {descriptor.label}"
                    for descriptor in descriptors
                )
        else:
            legend = ""
        chart = plot_text(context)
        return "\n".join(line for line in (heading, legend, chart) if line)


def load_monitor_sample(
    options: StandaloneLaunch, runner: QueryRunner, *, demo_ordinal: int = 0
) -> tuple[UsageRecord, ...]:
    """Load one raw cumulative sample for a Monitor pane or standalone monitor."""
    if options.host.demo_size:
        return _demo_snapshot(options, demo_ordinal + 1)
    results = runner.run(_monitor_plan(options))
    return tuple(
        record for result in results for record in parse_usage_records(result.kind, result.data)
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


def render_monitor_snapshot(
    observer: ObservedTPM,
    options: StandaloneLaunch,
    translator: Translator,
    terminal: Terminal,
    *,
    reserved_rows: int = 2,
    hide_upper_right_axes: bool = False,
    deltas: Mapping[str, float] | None = None,
    rank_deltas: Mapping[str, int] | None = None,
) -> str:
    """Render a pane-local Monitor observer without owning terminal input or state.

    ``deltas`` is optional refresh metadata keyed by the stable series key.
    """
    return _render(
        observer,
        observer.display_now(time.monotonic()),
        terminal,
        translator,
        options,
        reserved_rows=reserved_rows,
        hide_upper_right_axes=hide_upper_right_axes,
        deltas=deltas,
        rank_deltas=rank_deltas,
    )


def run_monitor(options: StandaloneLaunch, translator: Translator) -> int:
    if not isinstance(options.chart, MonitorConfig):
        raise TypeError("monitor runtime requires a monitor configuration")
    if options.chart.window_seconds is None or options.host.interval is None:
        raise UsageError(
            "error.arguments", detail="monitor requires an observation window and interval"
        )
    interval = options.host.interval
    screen = InteractiveScreen()
    current = options
    runner = QueryRunner(options.process.ccusage_bin, timeout=options.process.query_timeout)

    def monitor_chart(config: StandaloneLaunch) -> MonitorConfig:
        if not isinstance(config.chart, MonitorConfig):
            raise TypeError("monitor runtime requires a monitor configuration")
        return config.chart

    observer = ObservedTPM(
        window_seconds=options.chart.window_seconds,
        by=options.chart.by,
        top=options.chart.top,
        model_selectors=options.chart.filters.models,
    )
    demo_steps = min(24, max(8, options.chart.window_seconds))
    if options.host.demo_size:
        demo_now = time.monotonic()
        demo_seconds = options.chart.window_seconds / max(1, demo_steps - 1)
        for ordinal in range(demo_steps):
            observer.add(
                _counters(
                    _project_records(
                        _agent_records(
                            _demo_snapshot(options, ordinal + 1), options.chart.filters.agents
                        ),
                        options.chart.filters.projects,
                    )
                ),
                demo_now - (demo_steps - 1 - ordinal) * demo_seconds,
            )
    outcomes: queue.Queue[MonitorSampleResult | MonitorSampleFailure] = queue.Queue()
    running = False
    paused = False
    sample_generation = 0
    rebaseline_pending = False
    controls_hidden = False
    body_view: BodyView = "chart"
    samples = demo_steps if options.host.demo_size else 0
    status = translator.text("status.loading")
    next_sample = time.monotonic()
    last_elapsed: float | None = None
    last_size: tuple[int, int] | None = None
    gap_limit = interval * 2
    refresh_deltas = RefreshDeltas()
    refresh_ranks = RefreshRanks()

    def current_values(now: float) -> dict[str, float]:
        buckets = observer.buckets(observer.display_now(now), 32)
        names = dict.fromkeys(key for bucket in buckets for key in bucket.values)
        return {
            name: value
            for name in names
            if (
                value := next(
                    (bucket.values[name] for bucket in reversed(buckets) if name in bucket.values),
                    None,
                )
            )
            is not None
        }

    if options.host.demo_size:
        initial_values = current_values(time.monotonic())
        refresh_deltas.accept(initial_values)
        refresh_ranks.accept(monitor_rank_keys(initial_values))

    def paint(*, force: bool = False) -> None:
        nonlocal last_size
        try:
            size = get_terminal_size()
            last_size = (size.columns, size.lines)
            terminal = inspect_terminal(
                current.chart.kind,
                no_color=current.chart.presentation.theme == "no-color",
                ascii=current.host.ascii,
                size=size,
            )
            controls = (
                ()
                if controls_hidden
                else _controls_line(
                    translator.text(
                        {
                            "chart": "status.monitor_controls",
                            "command": "status.monitor_command_controls",
                            "full-command": "status.monitor_full_command_controls",
                            "data-table": "status.monitor_data_table_controls",
                            "data-json": "status.monitor_data_json_controls",
                        }[body_view]
                    ),
                    width=terminal.width,
                    color=terminal.color,
                )
            )
            now = time.monotonic()
            displayed_now = observer.display_now(now)
            buckets = observer.buckets(displayed_now, max(8, min(32, terminal.width // 4)))
            body = (
                _render(
                    observer,
                    displayed_now,
                    terminal,
                    translator,
                    current,
                    buckets=buckets,
                    reserved_rows=0 if controls_hidden else 2,
                    deltas={str(key): value for key, value in refresh_deltas.current.items()},
                    rank_deltas={str(key): value for key, value in refresh_ranks.current.items()},
                    normalize_title=True,
                )
                if body_view == "chart"
                else wrap_command(format_command(current), terminal.width)
                if body_view == "command"
                else format_full_command_display(format_full_command(current), terminal.width)
                if body_view == "full-command"
                else render_monitor_data(
                    buckets,
                    by=monitor_chart(current).by,
                    translator=translator,
                    terminal=terminal,
                    view=body_view,
                )
            )
            screen.paint(
                body,
                status,
                controls,
                height=terminal.height,
                force=force,
            )
        except UsageError as exc:
            terminal = Terminal(size.columns, size.lines, False, current.host.ascii)
            screen.paint(
                format_error(
                    exc, translator, color=False, color_scheme=current.chart.presentation.theme
                ),
                status,
                ()
                if controls_hidden
                else _controls_line(
                    translator.text("status.monitor_controls"),
                    width=terminal.width,
                    color=False,
                ),
                height=terminal.height,
                force=force,
            )

    def pick_appearance() -> None:
        nonlocal current, interval, gap_limit, next_sample, sample_generation, rebaseline_pending
        theme_index = COLOR_SCHEMES.index(current.chart.presentation.theme)
        candidate_by = monitor_chart(current).by
        candidate_top = monitor_chart(current).top
        candidate_window = monitor_chart(current).window_seconds
        candidate_interval = interval
        style = current.chart.presentation.style
        candidate_legend = current.chart.presentation.legend
        adjustment_page = "quick"
        preview = _copy_observer(observer)
        copied_status: str | None = None
        if not preview.intervals and not preview.rollups:
            preview_now = time.monotonic()
            for ordinal in range(12):
                preview.add(
                    _counters(
                        _project_records(
                            _agent_records(
                                _demo_snapshot(
                                    replace(current, host=replace(current.host, demo_size="small")),
                                    ordinal + 1,
                                ),
                                current.chart.filters.agents,
                            ),
                            current.chart.filters.projects,
                        )
                    ),
                    preview_now - (12 - ordinal),
                )
        window_choices = (300, 900, 1800, 3600, 21600, 43200, 86400)
        interval_choices = (
            (1.0, 5.0, 15.0, 30.0, 60.0) if current.host.demo_size else (5.0, 15.0, 30.0, 60.0)
        )

        def window_label(seconds: int) -> str:
            return f"{seconds // 3600}h" if seconds % 3600 == 0 else f"{seconds // 60}m"

        def candidate_options() -> StandaloneLaunch:
            styles = compatible_styles("monitor", candidate_by)
            candidate_style = style if style in styles else styles[0]
            return replace(
                current,
                host=replace(current.host, interval=candidate_interval),
                chart=replace(
                    current.chart,
                    by=candidate_by,
                    top=candidate_top if candidate_by is not None else None,
                    window_seconds=candidate_window,
                    presentation=replace(
                        current.chart.presentation,
                        theme=COLOR_SCHEMES[theme_index],
                        style=candidate_style,
                        legend=candidate_legend,
                    ),
                ),
            )

        def paint_picker() -> None:
            candidate = candidate_options()
            preview.by = monitor_chart(candidate).by
            preview.top = monitor_chart(candidate).top
            preview.model_selectors = monitor_chart(candidate).filters.models
            preview.window_seconds = monitor_chart(candidate).window_seconds
            size = get_terminal_size()
            terminal = inspect_terminal(
                candidate.chart.kind,
                no_color=candidate.chart.presentation.theme == "no-color",
                ascii=candidate.host.ascii,
                size=size,
            )
            mode = translator.text(
                {
                    None: "label.monitor_total_mode",
                    "agent": "label.monitor_agent_mode",
                    "model": "label.monitor_model_mode",
                    "project": "label.monitor_project_mode",
                }[monitor_chart(candidate).by]
            )
            top = (
                str(monitor_chart(candidate).top)
                if monitor_chart(candidate).top is not None
                else translator.text("label.monitor_all")
            )
            adjustment_state = _controls_line(
                " · ".join(
                    part
                    for part in (
                        translator.text(
                            f"status.monitor_adjust_{adjustment_page}",
                            **(
                                {
                                    "window": window_label(monitor_chart(candidate).window_seconds),
                                    "interval": f"{candidate.host.interval:g}",
                                    "mode": mode,
                                    "top": top,
                                    "theme": candidate.chart.presentation.theme,
                                    "style": candidate.chart.presentation.style,
                                }
                                if adjustment_page == "quick"
                                else {
                                    "legend_position": translator.text(
                                        f"label.legend_{candidate.chart.presentation.legend.replace('-', '_')}"
                                    )
                                }
                            ),
                        ),
                        copied_status,
                    )
                    if part is not None
                ),
                width=terminal.width,
                color=terminal.color,
            )
            key_help = _controls_line(
                translator.text(f"status.monitor_adjust_{adjustment_page}_keys"),
                width=terminal.width,
                color=terminal.color,
            )
            screen.paint(
                _render(
                    preview,
                    preview.display_now(time.monotonic()),
                    terminal,
                    translator,
                    candidate,
                    reserved_rows=2,
                ),
                translator.text("status.tui_adjust_monitor"),
                (adjustment_state, key_help),
                height=terminal.height,
            )

        paint_picker()
        while True:
            key = _read_key(0.1)
            if key == "\x03":
                raise KeyboardInterrupt
            if key == "\x1b":
                return
            if key in {"y", "Y"}:
                copied_status = (
                    translator.text("status.command_copied")
                    if copy_command(format_command(candidate_options()))
                    else translator.text("status.command_copy_failed")
                )
                paint_picker()
            elif key in {"\r", "\n"}:
                previous = current
                current = candidate_options()
                refresh_deltas.clear()
                refresh_ranks.clear()
                if not isinstance(previous.chart, MonitorConfig):
                    raise TypeError("monitor runtime requires a monitor configuration")
                observation_changed = (
                    previous.chart.by,
                    previous.chart.filters.models,
                    previous.chart.window_seconds,
                ) != (
                    monitor_chart(current).by,
                    monitor_chart(current).filters.models,
                    monitor_chart(current).window_seconds,
                )
                if observation_changed:
                    sample_generation += 1
                    rebaseline_pending = True
                observer.by = monitor_chart(current).by
                observer.top = monitor_chart(current).top
                observer.model_selectors = monitor_chart(current).filters.models
                observer.window_seconds = monitor_chart(current).window_seconds
                interval = current.host.interval or interval
                gap_limit = interval * 2
                next_sample = time.monotonic() + interval
                return
            elif key in {"a", "A"}:
                adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                paint_picker()
            elif adjustment_page == "quick" and key in {"s", "S", "t", "T"}:
                updated = adjust_standalone(candidate_options(), key)
                theme_index = COLOR_SCHEMES.index(updated.chart.presentation.theme)
                style = updated.chart.presentation.style
                paint_picker()
            elif adjustment_page == "advanced" and key in {"l", "L"}:
                positions = ("below-title", "inside", "values", "hidden")
                candidate_legend = positions[
                    (positions.index(candidate_legend) + 1) % len(positions)
                ]
                paint_picker()
            elif adjustment_page == "quick" and key in {"b", "B"}:
                groups = (None, "agent", "model", "project")
                candidate_by = groups[(groups.index(candidate_by) + 1) % len(groups)]
                if candidate_by is not None and candidate_top is None:
                    candidate_top = 3
                if style not in compatible_styles("monitor", candidate_by):
                    style = compatible_styles("monitor", candidate_by)[0]
                paint_picker()
            elif adjustment_page == "quick" and key in {"w", "W"}:
                candidate_window = window_choices[
                    (
                        min(
                            range(len(window_choices)),
                            key=lambda i: abs(window_choices[i] - candidate_window),
                        )
                        + 1
                    )
                    % len(window_choices)
                ]
                paint_picker()
            elif adjustment_page == "quick" and key in {"i", "I"}:
                index = min(
                    range(len(interval_choices)),
                    key=lambda item: abs(interval_choices[item] - candidate_interval),
                )
                candidate_interval = interval_choices[(index + 1) % len(interval_choices)]
                paint_picker()
            elif adjustment_page == "quick" and key in {"+", "="} and candidate_by is not None:
                candidate_top = (candidate_top or 0) + 1
                paint_picker()
            elif adjustment_page == "quick" and key in {"-", "_"} and candidate_by is not None:
                candidate_top = max(1, (candidate_top or 1) - 1)
                paint_picker()

    def start_sample() -> None:
        nonlocal running, samples
        running = True
        samples += 1
        generation = sample_generation
        submitted = current
        ordinal = samples

        def work(
            generation: int = generation,
            submitted: StandaloneLaunch = submitted,
            ordinal: int = ordinal,
        ) -> None:
            started = time.monotonic()
            try:
                if submitted.host.demo_size:
                    records = _demo_snapshot(submitted, ordinal)
                else:
                    results = runner.run(_monitor_plan(submitted))
                    records = tuple(
                        record
                        for result in results
                        for record in parse_usage_records(result.kind, result.data)
                    )
                outcomes.put(
                    MonitorSampleResult(generation, submitted, records, time.monotonic() - started)
                )
            except BaseException as exc:
                outcomes.put(MonitorSampleFailure(generation, exc))

        threading.Thread(target=work, name="ccusage-viz-monitor", daemon=True).start()

    try:
        with _input_mode():
            paint()
            while True:
                size = get_terminal_size()
                current_size = (size.columns, size.lines)
                if current_size != last_size:
                    paint(force=True)
                now = time.monotonic()
                if not paused and not running and now >= next_sample:
                    start_sample()
                    status = translator.text(
                        "status.monitor_sampling",
                        seconds=f"{last_elapsed:.2f}" if last_elapsed is not None else "…",
                        interval=f"{interval:g}",
                    )
                    prefix = translator.text(
                        "status.monitor_sampling_prefix",
                        seconds=f"{last_elapsed:.2f}" if last_elapsed is not None else "…",
                        interval=f"{interval:g}",
                    )
                    screen.paint_status(
                        prefix
                        + _dimmed(
                            translator.text("status.monitor_sampling_active"),
                            color=current.chart.presentation.theme != "no-color",
                        )
                    )
                try:
                    outcome = outcomes.get_nowait()
                except queue.Empty:
                    outcome = None
                if outcome is not None:
                    running = False
                    next_sample = time.monotonic() + interval
                    if outcome.generation != sample_generation:
                        next_sample = time.monotonic()
                        continue
                    if isinstance(outcome, MonitorSampleFailure):
                        status = translator.text(
                            "status.monitor_source",
                            source=str(outcome.error),
                            interval=f"{interval:g}",
                            state=f" · {translator.text('status.paused')}",
                        )
                    else:
                        last_elapsed = outcome.elapsed
                        counters = monitor_counters(outcome.options, outcome.records)
                        observed_at = time.monotonic()
                        observed_wall = datetime.now().astimezone()
                        if rebaseline_pending or observer.is_discontinuous(
                            observed_at, observed_wall, gap_limit
                        ):
                            rebaseline_pending = False
                            observer.rebaseline(counters, observed_at, observed_wall)
                            refresh_deltas.clear()
                            refresh_ranks.clear()
                        else:
                            observer.add(counters, observed_at, observed_wall)
                            values = current_values(observed_at)
                            refresh_deltas.accept(values)
                            refresh_ranks.accept(monitor_rank_keys(values))
                        status = translator.text(
                            "status.monitor_source",
                            source="DEMO DATA"
                            if outcome.options.host.demo_size
                            else f"ccusage {outcome.elapsed:.2f}s",
                            interval=f"{interval:g}",
                            state="",
                        ).rstrip(" ·")
                    paint()
                key = _read_key(0.05)
                if key == "\x03":
                    raise KeyboardInterrupt
                if key == "r" and not running:
                    next_sample = time.monotonic()
                elif key in {"h", "H"}:
                    controls_hidden = not controls_hidden
                    paint(force=True)
                elif key in {"v", "V"}:
                    body_view = next_body_view(body_view)
                    paint(force=True)
                elif key in {"y", "Y"} and body_view != "chart":
                    terminal = inspect_terminal(
                        current.chart.kind,
                        no_color=current.chart.presentation.theme == "no-color",
                        ascii=current.host.ascii,
                        size=get_terminal_size(),
                    )
                    copied = (
                        format_command(current)
                        if body_view == "command"
                        else format_full_command(current)
                        if body_view == "full-command"
                        else render_monitor_data(
                            observer.buckets(
                                observer.display_now(time.monotonic()),
                                max(8, min(32, terminal.width // 4)),
                            ),
                            by=monitor_chart(current).by,
                            translator=translator,
                            terminal=terminal,
                            view=body_view,
                            complete=True,
                        )
                    )
                    copied_successfully = copy_command(copied)
                    status = translator.text(
                        "status.command_copied"
                        if copied_successfully and body_view in {"command", "full-command"}
                        else "status.data_copied"
                        if copied_successfully
                        else "status.command_copy_failed"
                    )
                    paint()
                elif key in {"m", "M"} and body_view == "chart":
                    pick_appearance()
                    paint()
                elif key == " ":
                    paused = not paused
                    refresh_deltas.clear()
                    refresh_ranks.clear()
                    if not paused and observer.previous is not None:
                        observer.rebaseline(
                            observer.previous, time.monotonic(), datetime.now().astimezone()
                        )
                    status = translator.text(
                        "status.monitor_paused",
                        source=(
                            f"ccusage {last_elapsed:.2f}s"
                            if last_elapsed is not None
                            else "ccusage …"
                        ),
                        interval=f"{interval:g}",
                        state=f" · {translator.text('status.paused')}" if paused else "",
                    )
                    screen.paint_status(status)
    except KeyboardInterrupt:
        runner.cancel()
        return 0
    finally:
        screen.finish()
