from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from math import isfinite
from shutil import get_terminal_size

import plotext as plt

from ccusage_viz.command_copy import copy_command, format_command
from ccusage_viz.demo import generate_demo
from ccusage_viz.diagnostics import format_error
from ccusage_viz.domain import TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import center_text
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions, DateRange, compatible_styles, refresh_date_range
from ccusage_viz.project_identity import project_label, resolve_projects, unique_projects
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.query.models import QueryKind, QueryPlan, QuerySpec
from ccusage_viz.render.base import (
    RenderContext,
    colored_mark,
    configure_plot,
    configure_y_ticks,
    isolated_plot,
    plot_height,
    plot_text,
)
from ccusage_viz.render.palette import COLOR_SCHEMES, categorical_colors, get_color_scheme
from ccusage_viz.schema import parse_usage_records
from ccusage_viz.terminal import InteractiveScreen, Terminal, inspect_terminal
from ccusage_viz.watch import _controls_line, _input_mode, _read_key


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
            current_values: dict[str, TokenUsage], previous_values: dict[str, TokenUsage]
        ) -> dict[str, float]:
            values: dict[str, float] = {}
            for name, usage in current_values.items():
                before = previous_values.get(name)
                if before is None:
                    continue
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
                deltas(current.projects, previous.projects),
            )
        )
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


def _monitor_plan(options: CommandOptions) -> QueryPlan:
    current = refresh_date_range(options.date_range)
    # A monitor begins with no observed history, but includes a one-day rollover
    # margin so cumulative counters remain comparable across midnight.
    since = current.until - timedelta(days=1)
    if options.by == "project" or options.projects:
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
                        current.until.strftime("%Y%m%d"),
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
                    current.until.isoformat(),
                    "--offline",
                    "--no-cost",
                ),
            ),
        )
    )


def _demo_snapshot(options: CommandOptions, ordinal: int) -> tuple[UsageRecord, ...]:
    today = options.date_range.until
    records = generate_demo(
        options.demo or "medium", DateRange(today - timedelta(days=1), today, None)
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


def _render(
    observer: ObservedTPM,
    now: float,
    terminal: Terminal,
    translator: Translator,
    options: CommandOptions,
    *,
    reserved_rows: int = 2,
) -> str:
    window = (
        f"{observer.window_seconds // 3600}h"
        if observer.window_seconds % 3600 == 0
        else f"{observer.window_seconds // 60}m"
    )
    if observer.previous is None:
        state = translator.text("label.monitor_baseline")
    elif not observer.intervals and not observer.rollups:
        state = translator.text("label.monitor_samples")
    else:
        state = translator.text("label.monitor_observed")
    agents = ", ".join(options.agents) if options.agents else translator.text("label.monitor_all")
    mode = translator.text(
        {
            None: "label.monitor_total_mode",
            "agent": "label.monitor_agent_mode",
            "model": "label.monitor_model_mode",
            "project": "label.monitor_project_mode",
        }[observer.by]
    )
    title = translator.text(
        "label.monitor_growth_title"
        if observer.by in {"agent", "project"}
        else "label.monitor_title",
        window=window,
        state=state,
        agents=agents,
        mode=mode,
    )
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
        color_scheme=options.color_scheme,
        style=options.style,
        legend_position=options.legend_position,
    )
    series = {name: [bucket.values.get(name, float("nan")) for bucket in buckets] for name in names}
    show_legend = len(names) > 1 or names != ("Total",)
    colors = categorical_colors((name for name in names if name != "Other"), options.color_scheme)
    scheme = get_color_scheme(options.color_scheme)
    with isolated_plot():
        configure_plot(context)
        plt.figure.plot_size(
            context.width,
            plot_height(
                context,
                text_rows=1 + int(show_legend and options.legend_position == "below-title"),
            ),
        )
        for index, (name, values) in enumerate(series.items()):
            color = scheme.other if name == "Other" else colors[name]
            marker_name = (
                "#" if terminal.ascii else ("dot", "circle", "square", "diamond")[index % 4]
            )
            marker = plt.marker(
                marker_name, pixel=plt.pixel(foreground=color) if terminal.color else None
            )
            x_values = list(range(len(buckets)))
            if options.style == "bars":
                signal = plt.figure.bar(x_values, values, marker=marker, width=0.75)
            else:
                if options.style == "step":
                    x_values = [item for point in x_values for item in (point, point + 1)]
                    values = [item for value in values for item in (value, value)]
                signal = plt.figure.signal(x_values, values, marker=marker).lines(True)
            if show_legend and options.legend_position == "inside":
                signal.label(
                    translator.text("label.other")
                    if name == "Other"
                    else translator.text("label.total")
                    if name == "Total"
                    else name
                )
            plt.figure.draw(signal)
        positions, labels = _elapsed_labels(buckets)
        plt.figure.ruler("x").ticks(positions, labels)
        configure_y_ticks(
            round(value) for values in series.values() for value in values if isfinite(value)
        )
        if options.legend_position != "inside":
            plt.figure.legend(False)
        legend_marks = (".", "o", "#", "D") if terminal.ascii else ("•", "○", "■", "◆")
        legend = (
            " · ".join(
                f"{colored_mark(legend_marks[index % len(legend_marks)], scheme.other if name == 'Other' else colors[name], context)} "
                f"{translator.text('label.other') if name == 'Other' else translator.text('label.total') if name == 'Total' else name}"
                for index, name in enumerate(names)
            )
            if show_legend and options.legend_position == "below-title"
            else ""
        )
        chart = plot_text(context)
        return "\n".join(line for line in (heading, legend, chart) if line)


def run_monitor(options: CommandOptions, translator: Translator) -> int:
    if options.window_seconds is None or options.interval is None:
        raise UsageError(
            "error.arguments", detail="monitor requires an observation window and interval"
        )
    interval = options.interval
    screen = InteractiveScreen()
    current = options
    runner = QueryRunner(options.ccusage_bin, timeout=options.timeout)
    observer = ObservedTPM(
        window_seconds=options.window_seconds,
        by=options.by,
        top=options.top,
        model_selectors=options.models,
    )
    demo_steps = min(24, max(8, options.window_seconds))
    if options.demo:
        demo_now = time.monotonic()
        demo_seconds = options.window_seconds / max(1, demo_steps - 1)
        for ordinal in range(demo_steps):
            observer.add(
                _counters(
                    _project_records(
                        _agent_records(_demo_snapshot(options, ordinal + 1), options.agents),
                        options.projects,
                    )
                ),
                demo_now - (demo_steps - 1 - ordinal) * demo_seconds,
            )
    outcomes: queue.Queue[tuple[tuple[UsageRecord, ...], float] | BaseException] = queue.Queue()
    running = False
    paused = False
    samples = demo_steps if options.demo else 0
    status = translator.text("status.loading")
    next_sample = time.monotonic()
    last_size: tuple[int, int] | None = None
    gap_limit = interval * 2

    def paint() -> None:
        nonlocal last_size
        try:
            size = get_terminal_size()
            last_size = (size.columns, size.lines)
            terminal = inspect_terminal(
                current.command, no_color=current.no_color, ascii=current.ascii, size=size
            )
            controls = _controls_line(
                translator.text("status.monitor_controls"),
                width=terminal.width,
                color=terminal.color,
            )
            screen.paint(
                _render(
                    observer,
                    observer.display_now(time.monotonic()),
                    terminal,
                    translator,
                    current,
                    reserved_rows=2,
                ),
                status,
                controls,
                height=terminal.height,
            )
        except UsageError as exc:
            terminal = Terminal(size.columns, size.lines, False, current.ascii)
            screen.paint(
                format_error(exc, translator, color=False, color_scheme=current.color_scheme),
                status,
                _controls_line(
                    translator.text("status.monitor_controls"),
                    width=terminal.width,
                    color=False,
                ),
                height=terminal.height,
            )

    def pick_appearance() -> None:
        nonlocal current, interval, gap_limit, next_sample
        theme_index = COLOR_SCHEMES.index(current.color_scheme)
        candidate_by = current.by
        candidate_top = current.top
        candidate_models = current.models
        candidate_window = current.window_seconds or observer.window_seconds
        candidate_interval = interval
        style = current.style
        candidate_legend_position = current.legend_position
        preview = _copy_observer(observer)
        copied_status: str | None = None
        if not preview.intervals and not preview.rollups:
            preview_now = time.monotonic()
            for ordinal in range(12):
                preview.add(
                    _counters(
                        _project_records(
                            _agent_records(
                                _demo_snapshot(replace(current, demo="small"), ordinal + 1),
                                current.agents,
                            ),
                            current.projects,
                        )
                    ),
                    preview_now - (12 - ordinal),
                )
        window_choices = (300, 900, 1800, 3600, 21600, 43200, 86400)
        interval_choices = (1.0, 5.0, 15.0, 30.0, 60.0) if current.demo else (5.0, 15.0, 30.0, 60.0)

        def window_label(seconds: int) -> str:
            return f"{seconds // 3600}h" if seconds % 3600 == 0 else f"{seconds // 60}m"

        def candidate_options() -> CommandOptions:
            styles = compatible_styles("monitor", candidate_by)
            candidate_style = style if style in styles else styles[0]
            return replace(
                current,
                by=candidate_by,
                top=candidate_top if candidate_by is not None else None,
                models=candidate_models,
                window_seconds=candidate_window,
                interval=candidate_interval,
                color_scheme=COLOR_SCHEMES[theme_index],
                style=candidate_style,
                legend_position=candidate_legend_position,
            )

        def paint_picker() -> None:
            candidate = candidate_options()
            preview.by = candidate.by
            preview.top = candidate.top
            preview.model_selectors = candidate.models
            preview.window_seconds = candidate.window_seconds or preview.window_seconds
            size = get_terminal_size()
            terminal = inspect_terminal(
                candidate.command, no_color=candidate.no_color, ascii=candidate.ascii, size=size
            )
            mode = translator.text(
                {
                    None: "label.monitor_total_mode",
                    "agent": "label.monitor_agent_mode",
                    "model": "label.monitor_model_mode",
                    "project": "label.monitor_project_mode",
                }[candidate.by]
            )
            top = (
                str(candidate.top)
                if candidate.top is not None
                else translator.text("label.monitor_all")
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
                _controls_line(
                    " · ".join(
                        part
                        for part in (
                            translator.text(
                                "status.monitor_adjust",
                                window=window_label(
                                    candidate.window_seconds or preview.window_seconds
                                ),
                                interval=f"{candidate.interval:g}",
                                mode=mode,
                                top=top,
                                legend_position=translator.text(
                                    f"label.legend_{candidate.legend_position.replace('-', '_')}"
                                ),
                                theme=candidate.color_scheme,
                                style=candidate.style,
                            ),
                            copied_status,
                        )
                        if part is not None
                    ),
                    width=terminal.width,
                    color=terminal.color,
                ),
                _controls_line(
                    translator.text(
                        "status.monitor_adjust_model_keys"
                        if candidate.by == "model"
                        else "status.monitor_adjust_keys"
                    ),
                    width=terminal.width,
                    color=terminal.color,
                ),
                height=terminal.height,
            )

        paint_picker()
        while True:
            key = _read_key(0.1)
            if key in {"q", "Q"}:
                return
            if key in {"y", "Y"}:
                copied_status = (
                    translator.text("status.command_copied")
                    if copy_command(format_command(candidate_options()))
                    else translator.text("status.command_copy_failed")
                )
                paint_picker()
            elif key in {"\r", "\n"}:
                current = candidate_options()
                observer.by = current.by
                observer.top = current.top
                observer.model_selectors = current.models
                observer.window_seconds = current.window_seconds or observer.window_seconds
                interval = current.interval or interval
                gap_limit = interval * 2
                next_sample = time.monotonic() + interval
                return
            elif key in {"n", "N"}:
                theme_index = (theme_index + 1) % len(COLOR_SCHEMES)
                paint_picker()
            elif key in {"p", "P"}:
                theme_index = (theme_index - 1) % len(COLOR_SCHEMES)
                paint_picker()
            elif key == "j":
                styles = compatible_styles("monitor", candidate_by)
                current_style = style if style in styles else styles[0]
                style = styles[(styles.index(current_style) + 1) % len(styles)]
                paint_picker()
            elif key == "k":
                styles = compatible_styles("monitor", candidate_by)
                current_style = style if style in styles else styles[0]
                style = styles[(styles.index(current_style) - 1) % len(styles)]
                paint_picker()
            elif key in {"l", "L"}:
                positions = ("below-title", "inside", "hidden")
                candidate_legend_position = positions[
                    (positions.index(candidate_legend_position) + 1) % len(positions)
                ]
                paint_picker()
            elif key in {"b", "B"}:
                groups = (None, "agent", "model", "project")
                candidate_by = groups[(groups.index(candidate_by) + 1) % len(groups)]
                if candidate_by is not None and candidate_top is None:
                    candidate_top = 3
                if style not in compatible_styles("monitor", candidate_by):
                    style = compatible_styles("monitor", candidate_by)[0]
                paint_picker()
            elif key in {"m", "M"} and candidate_by == "model":
                choices = tuple(sorted(observer.tracked_models, key=str.casefold))
                if choices:
                    try:
                        index = (
                            choices.index(candidate_models[0]) if len(candidate_models) == 1 else -1
                        )
                    except ValueError:
                        index = -1
                    candidate_models = () if index == len(choices) - 1 else (choices[index + 1],)
                paint_picker()
            elif key in {"w", "W"}:
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
            elif key in {"i", "I"}:
                index = min(
                    range(len(interval_choices)),
                    key=lambda item: abs(interval_choices[item] - candidate_interval),
                )
                candidate_interval = interval_choices[(index + 1) % len(interval_choices)]
                paint_picker()
            elif key in {"+", "="} and candidate_by is not None:
                candidate_top = (candidate_top or 0) % 10 + 1
                paint_picker()
            elif key in {"-", "_"} and candidate_by is not None:
                candidate_top = 10 if candidate_top in {None, 1} else candidate_top - 1
                paint_picker()

    def start_sample() -> None:
        nonlocal running, samples
        running = True
        samples += 1

        def work() -> None:
            started = time.monotonic()
            try:
                if current.demo:
                    records = _demo_snapshot(current, samples)
                else:
                    results = runner.run(_monitor_plan(current))
                    records = tuple(
                        record
                        for result in results
                        for record in parse_usage_records(result.kind, result.data)
                    )
                outcomes.put((records, time.monotonic() - started))
            except BaseException as exc:
                outcomes.put(exc)

        threading.Thread(target=work, name="ccusage-viz-monitor", daemon=True).start()

    try:
        with _input_mode():
            paint()
            while True:
                size = get_terminal_size()
                current_size = (size.columns, size.lines)
                if current_size != last_size:
                    paint()
                now = time.monotonic()
                if not paused and not running and now >= next_sample:
                    start_sample()
                    status = translator.text("status.monitor_sampling", seconds=f"{interval:g}")
                    screen.paint_status(status)
                try:
                    outcome = outcomes.get_nowait()
                except queue.Empty:
                    outcome = None
                if outcome is not None:
                    running = False
                    next_sample = time.monotonic() + interval
                    if isinstance(outcome, BaseException):
                        status = translator.text(
                            "status.monitor_source", seconds=f"{interval:g}", source=str(outcome)
                        )
                    else:
                        records, elapsed = outcome
                        counters = _counters(
                            _project_records(
                                _agent_records(records, current.agents), current.projects
                            )
                        )
                        observed_at = time.monotonic()
                        observed_wall = datetime.now().astimezone()
                        if observer.is_discontinuous(observed_at, observed_wall, gap_limit):
                            observer.rebaseline(counters, observed_at, observed_wall)
                            source = "sampling gap · baseline reset"
                        else:
                            observer.add(counters, observed_at, observed_wall)
                            source = "DEMO DATA" if current.demo else f"ccusage {elapsed:.2f}s"
                        status = translator.text(
                            "status.monitor_source", seconds=f"{interval:g}", source=source
                        )
                    paint()
                key = _read_key(0.05)
                if key in {"q", "Q"}:
                    runner.cancel()
                    return 0
                if key in {"r", "R"} and not running:
                    next_sample = time.monotonic()
                elif key in {"m", "M"}:
                    pick_appearance()
                    paint()
                elif key == " ":
                    paused = not paused
                    if not paused and observer.previous is not None:
                        observer.rebaseline(
                            observer.previous, time.monotonic(), datetime.now().astimezone()
                        )
                    status = translator.text(
                        "status.monitor_paused",
                        seconds=f"{interval:g}",
                        state=translator.text("status.paused") if paused else "resumed",
                    )
                    screen.paint_status(status)
    except KeyboardInterrupt:
        runner.cancel()
        return 0
    finally:
        screen.finish()
