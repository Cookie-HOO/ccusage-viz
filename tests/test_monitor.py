from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from os import terminal_size
from typing import Literal

import pytest

import ccusage_viz.monitor as monitor_host
from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import QueryTrigger
from ccusage_viz.options import (
    ChartPresentation,
    Filters,
    MonitorConfig,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
)
from ccusage_viz.processing.monitor import (
    CounterSnapshot,
    ObservedTPM,
    _agent_records,
    _copy_observer,
    _counters,
    _nice_y_max,
    _stable_y_max,
)
from ccusage_viz.terminal import Terminal


def usage(total: int) -> TokenUsage:
    return TokenUsage.from_parts(
        total=total,
        input=total,
        output=0,
        cache_read=0,
        cache_creation=0,
    )


def snapshot(total: int, **models: int) -> CounterSnapshot:
    return CounterSnapshot(usage(total), {name: usage(value) for name, value in models.items()})


def monitor_options(*, by: str | None = None) -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(query_timeout=1),
        StandaloneHostConfig(ascii=True, interval=15),
        MonitorConfig(
            "monitor",
            3600,
            presentation=ChartPresentation(theme="no-color", style="bars"),
            by=by,
        ),
    )


def test_nice_y_max_uses_padded_decimal_one_two_five_bounds() -> None:
    assert _nice_y_max(0) == 1
    assert _nice_y_max(1) == 2
    assert _nice_y_max(101) == 200
    assert _nice_y_max(201) == 500
    assert _nice_y_max(501) == 1000


def test_stable_y_max_expands_immediately_and_shrinks_after_sustained_low_values() -> None:
    assert _stable_y_max(101, 100) == (200, 0)
    assert _stable_y_max(199, 200) == (200, 0)
    assert _stable_y_max(100, 200) == (200, 0)
    assert _stable_y_max(89, 200, 0) == (200, 1)
    assert _stable_y_max(89, 200, 3) == (100, 0)


def test_observer_y_axis_resets_only_when_measure_semantics_change() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=3)
    assert observer.update_y_axis(101) == 200

    observer.top = 1
    assert observer.update_y_axis(100) == 200
    assert observer.y_axis_semantics == ("model", 3600, 1, ())

    observer.window_seconds = 300
    assert observer.update_y_axis(99) == 200

    observer.model_selectors = ("sonnet",)
    assert observer.update_y_axis(99) == 200

    observer.by = None
    assert observer.update_y_axis(201) == 500


def test_observer_rebaseline_resets_stable_y_axis_state() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(60), 60.0)
    assert observer.update_y_axis(101) == 200

    observer.rebaseline(snapshot(120), 120.0)

    assert observer.y_axis_max == 0
    assert observer.y_axis_low_samples == 0
    assert observer.update_y_axis(9) == 10


def test_observer_y_axis_updates_once_per_accepted_sample() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(60), 60.0)

    assert observer.update_y_axis(101) == 200
    assert observer.update_y_axis(501) == 200

    observer.add(snapshot(120), 120.0)
    assert observer.update_y_axis(501) == 1000


def test_copy_observer_preserves_independent_y_axis_state() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.update_y_axis(101)

    copied = _copy_observer(observer)

    assert copied.y_axis_max == 200
    assert copied.y_axis_semantics == ("model", 3600, None, ())
    assert copied.y_axis_low_samples == 0
    assert copied.sample_generation == observer.sample_generation
    assert copied.y_axis_generation == observer.y_axis_generation
    copied.sample_generation += 1
    copied.update_y_axis(501)
    assert copied.y_axis_max == 1000
    assert observer.y_axis_max == 200


def test_observed_tpm_requires_a_baseline_and_uses_elapsed_monotonic_seconds() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)

    assert not observer.add(snapshot(100), 10.0)
    assert observer.current_values() == {}
    assert observer.rates(10.0) == {}
    assert observer.add(snapshot(160), 40.0)
    assert observer.current_values() == {"Total": 120.0}
    assert observer.rates(40.0) == {"Total": 120.0}


def test_current_values_use_only_newest_valid_interval_without_history_fallback() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(100), 0.0)
    observer.add(snapshot(160), 60.0)
    assert observer.current_values() == {"Total": 60.0}

    observer.rebaseline(snapshot(160), 120.0)
    assert observer.current_values() == {}
    assert observer.rates(120.0) == {"Total": 60.0}

    observer.add(snapshot(190), 180.0)
    assert observer.current_values() == {"Total": 30.0}


@pytest.mark.parametrize("by", ("agent", "project"))
def test_agent_and_project_current_values_are_latest_pair_token_delta(
    by: Literal["agent", "project"],
) -> None:
    observer = ObservedTPM(window_seconds=3600, by=by, top=None)
    if by == "agent":
        before = CounterSnapshot(usage(100), agents={"claude": usage(100)})
        after = CounterSnapshot(usage(130), agents={"claude": usage(130)})
    else:
        before = CounterSnapshot(usage(100), projects={"claude": usage(100)})
        after = CounterSnapshot(usage(130), projects={"claude": usage(130)})
    observer.add(before, 0.0)
    observer.add(after, 10.0)
    assert observer.current_values() == {"claude": 30.0}

    observer.add(after, 20.0)
    assert observer.current_values() == {"claude": 0.0}


def test_model_projection_preserves_authoritative_total_with_residual_other() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(100, sonnet=60), 0.0)
    observer.add(snapshot(200, sonnet=110), 60.0)

    assert observer.rates(60.0) == {"sonnet": 50.0, "Other": 50.0}
    observer.by = None
    assert observer.rates(60.0) == {"Total": 100.0}


def test_model_top_is_projection_only_and_history_remains_reversible() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=1)
    observer.add(snapshot(0, sonnet=0, opus=0), 0.0)
    observer.add(snapshot(100, sonnet=60, opus=40), 60.0)

    assert observer.rates(60.0) == {"sonnet": 60.0, "Other": 40.0}
    observer.top = None
    assert observer.rates(60.0) == {"sonnet": 60.0, "opus": 40.0}


def test_model_selection_projects_selected_models_and_other_without_changing_total() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None, model_selectors=("son",))
    observer.add(snapshot(0, sonnet=0, opus=0), 0.0)
    observer.add(snapshot(100, sonnet=60, opus=40), 60.0)

    assert observer.rates(60.0) == {"sonnet": 60.0, "Other": 40.0}
    observer.by = None
    assert observer.rates(60.0) == {"Total": 100.0}


def test_agent_growth_is_cumulative_within_window() -> None:
    observer = ObservedTPM(window_seconds=120, by="agent", top=None)
    observer.add(CounterSnapshot(usage(0), agents={"claude": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(30), agents={"claude": usage(30)}), 60.0)
    observer.add(CounterSnapshot(usage(70), agents={"claude": usage(70)}), 120.0)

    assert [bucket.values for bucket in observer.buckets(120.0, 2)] == [
        {"claude": 30.0},
        {"claude": 70.0},
    ]


def test_project_growth_is_cumulative_within_window() -> None:
    observer = ObservedTPM(window_seconds=120, by="project", top=None)
    observer.add(CounterSnapshot(usage(0), projects={"app": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(30), projects={"app": usage(30)}), 60.0)
    observer.add(CounterSnapshot(usage(70), projects={"app": usage(70)}), 120.0)

    assert [bucket.values for bucket in observer.buckets(120.0, 2)] == [
        {"app": 30.0},
        {"app": 70.0},
    ]


def test_project_first_attributed_sample_does_not_become_other() -> None:
    observer = ObservedTPM(window_seconds=3600, by="project", top=None)
    observer.add(CounterSnapshot(usage(100), projects={}), 0.0)
    observer.add(CounterSnapshot(usage(160), projects={"app": usage(60)}), 60.0)

    assert observer.rates(60.0) == {"app": 60.0}


def test_project_zero_growth_is_not_rendered() -> None:
    observer = ObservedTPM(window_seconds=3600, by="project", top=None)
    observer.add(CounterSnapshot(usage(100), projects={"idle": usage(10)}), 0.0)
    observer.add(CounterSnapshot(usage(160), projects={"idle": usage(10), "app": usage(60)}), 60.0)

    buckets = observer.buckets(60.0, 2)

    assert all("idle" not in bucket.values for bucket in buckets)
    assert buckets[-1].values["app"] == 60.0


def test_counters_keep_project_display_labels_safe_and_distinct() -> None:
    records = (
        UsageRecord(
            None,
            "claude",
            usage(10),
            SourceKind.CLAUDE_DAILY_PROJECTS,
            ProjectRef("claude", "/safe/a/app", "app"),
        ),
        UsageRecord(
            None,
            "codex",
            usage(20),
            SourceKind.CODEX_SESSIONS,
            ProjectRef("codex", "/safe/b/app", "app"),
        ),
    )

    assert set(_counters(records).projects) == {"app (claude)", "app (codex)"}


def test_agent_selection_is_applied_before_counters() -> None:
    records = (
        UsageRecord(None, "Claude Code", usage(60), SourceKind.UNIFIED_DAILY, None, ()),
        UsageRecord(None, "Codex", usage(40), SourceKind.UNIFIED_DAILY, None, ()),
    )

    selected = _agent_records(records, ("claude",))
    assert tuple(record.agent for record in selected) == ("Claude Code",)
    assert sum(record.usage.total for record in selected) == 60


def test_observed_tpm_splits_intervals_across_display_buckets() -> None:
    observer = ObservedTPM(window_seconds=120, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(120), 120.0)

    wall = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    buckets = observer.buckets(120.0, 2, wall)
    assert [bucket.values for bucket in buckets] == [{"Total": 60.0}, {"Total": 60.0}]
    assert [bucket.ended_wall for bucket in buckets] == [
        datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
        wall,
    ]


def test_observed_tpm_rebaselines_decreased_total_without_negative_rate() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(100), 0.0)
    assert not observer.add(snapshot(10), 60.0)

    assert observer.resets == 1
    assert observer.current_values() == {}
    assert observer.rates(60.0) == {}
    assert observer.add(snapshot(30), 120.0)
    assert observer.current_values() == {"Total": 20.0}
    assert observer.rates(120.0) == {"Total": 20.0}


def test_native_history_rolls_up_after_one_hour_and_evicts_after_24_hours() -> None:
    observer = ObservedTPM(window_seconds=24 * 3600, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(60), 60.0)
    observer.add(snapshot(120), 120.0)

    observer.rates(3721.0)
    assert not observer.intervals
    assert len(observer.rollups) == 2

    observer.rates(24 * 3600 + 121.0)
    assert not observer.rollups


def test_model_identity_cap_folds_overflow_into_other() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    before = {f"model-{index:03d}": 0 for index in range(257)}
    after = {name: 1 for name in before}
    observer.add(snapshot(0, **before), 0.0)
    observer.add(snapshot(257, **after), 60.0)

    rates = observer.rates(60.0)
    assert observer.overflowed_models
    assert len(observer.tracked_models) == 256
    assert rates["Other"] == 1.0
    assert sum(rates.values()) == 257.0


def test_total_and_models_ignore_component_redistribution() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    before = TokenUsage(100, 80, 20, 0, 0)
    after = TokenUsage(110, 70, 40, 0, 0)
    observer.add(CounterSnapshot(before, {"sonnet": before}), 0.0)

    assert observer.add(CounterSnapshot(after, {"sonnet": after}), 60.0)
    assert observer.resets == 0
    assert observer.rates(60.0) == {"sonnet": 10.0}


def test_overflow_membership_churn_is_authoritative_residual_other() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    before = {f"model-{index:03d}": 100 for index in range(257)}
    after = {name: value + 1 for name, value in before.items() if name != "model-256"}
    after["replacement"] = 50
    observer.add(snapshot(sum(before.values()), **before), 0.0)
    observer.add(snapshot(sum(before.values()) + 257, **after), 60.0)

    rates = observer.rates(60.0)
    assert rates["Other"] == 1.0
    assert sum(rates.values()) == 257.0


def test_attributed_models_exceeding_total_maps_total_to_other() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(100, sonnet=50), 0.0)
    observer.add(snapshot(110, sonnet=70), 60.0)

    assert observer.rates(60.0) == {"Other": 10.0}
    assert observer.resets == 1


def test_maintenance_splits_native_boundary_and_minutes_without_double_coverage() -> None:
    observer = ObservedTPM(window_seconds=7200, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(120), 120.0)

    assert observer.rates(3665.0) == {"Total": 60.0}
    assert [(rollup.started_at, rollup.ended_at) for rollup in observer.rollups] == [
        (0.0, 60),
        (60, 65.0),
    ]
    assert [(interval.started_at, interval.ended_at) for interval in observer.intervals] == [
        (65.0, 120.0)
    ]


def test_same_minute_rollups_merge_across_maintenance_calls() -> None:
    observer = ObservedTPM(window_seconds=7200, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(120), 120.0)

    observer.rates(3665.0)
    observer.rates(3670.0)

    assert [(item.started_at, item.ended_at) for item in observer.rollups] == [
        (0.0, 60),
        (60, 70.0),
    ]
    assert observer.rollups[-1].covered_seconds == 10.0
    assert observer.rollups[-1].total == 10.0


def test_retention_clips_exactly_at_24_hour_cutoff() -> None:
    observer = ObservedTPM(window_seconds=24 * 3600, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(120), 120.0)

    assert observer.rates(24 * 3600 + 30.0) == {"Total": 60.0}
    assert observer.rollups[0].started_at == 30.0
    assert sum(item.total for item in observer.rollups) == 90.0


def test_wall_clock_sleep_gap_rebaselines_on_logical_clock_and_leaves_empty_buckets() -> None:
    observer = ObservedTPM(window_seconds=3 * 3600, by=None, top=None)
    wall = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    observer.add(snapshot(0), 100.0, wall)
    observer.add(snapshot(60), 115.0, wall + timedelta(seconds=15))
    wake_wall = wall + timedelta(hours=2, seconds=30)

    assert observer.is_discontinuous(130.0, wake_wall, 30.0)
    observer.rebaseline(snapshot(60), 130.0, wake_wall)
    logical_now = observer.display_now(130.0)
    buckets = observer.buckets(logical_now, 3, wake_wall)

    assert buckets[0].values == {"Total": 240.0}
    assert buckets[1].values == {}
    assert buckets[2].values == {}


def test_standalone_pause_discards_active_sample_and_preserves_paused_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = monitor_options()
    events: list[tuple[object, ...]] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    runtime = Runtime()

    class Submission:
        generation = 0
        options = launch
        handle: "Submission"

        def __init__(self) -> None:
            self.handle = self
            self.cancelled = False

        def done(self) -> bool:
            return self.cancelled

        def cancel(self) -> None:
            self.cancelled = True
            events.append(("submission-cancel",))

        def result(self) -> object:
            raise RuntimeError("cancelled sample must stay hidden")

    class Component:
        def __init__(self, selected: StandaloneLaunch, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.error = None
            self.accepted_at = None
            self.last_elapsed = None
            self.deltas = {}
            self.rank_deltas = {}
            self.generation = 0

        def submit(self, trigger: object, *, sample_ordinal: int) -> Submission:
            events.append(("submit", trigger, sample_ordinal))
            return Submission()

        def render(self, *_args: object, **_kwargs: object) -> str:
            return "monitor chart"

        def pause(self) -> None:
            events.append(("pause",))

        def fail(self, error: BaseException, *, generation: int) -> bool:
            events.append(("fail", str(error), generation))
            self.error = error
            return True

    class Screen:
        def paint(self, frame: object, **_kwargs: object) -> None:
            events.append(("paint", frame))

        def finish(self) -> None:
            events.append(("finish",))

    keys = iter((" ", "\x03"))
    monkeypatch.setattr(monitor_host, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(monitor_host, "build_chart_registry", lambda: object())
    monkeypatch.setattr(monitor_host, "MonitorComponent", Component)
    monkeypatch.setattr(monitor_host, "FramePainter", Screen)
    monkeypatch.setattr(monitor_host, "input_mode", nullcontext)
    monkeypatch.setattr(monitor_host, "read_key", lambda _timeout: next(keys))
    monkeypatch.setattr(monitor_host, "get_terminal_size", lambda: terminal_size((100, 30)))
    monkeypatch.setattr(
        monitor_host,
        "inspect_terminal",
        lambda *_args, **_kwargs: Terminal(100, 30, False, True),
    )

    assert monitor_host.run_monitor(launch, load_translator("en")) == 0
    assert ("submit", QueryTrigger.STARTUP, 1) in events
    assert ("pause",) in events
    assert ("submission-cancel",) in events
    assert not any(event[0] == "fail" for event in events)
    assert any(event[0] == "paint" and "paused" in str(event[1]) for event in events)
    assert events[-2:] == [("runtime-cancel",), ("finish",)]


@pytest.mark.parametrize(
    ("edited", "expected_configures", "expected_submits"),
    (
        (
            Filters(agents=("Claude Code",)),
            [("configure", True, 1)],
            [
                ("submit", QueryTrigger.STARTUP, 1, 0),
                ("submit", QueryTrigger.REFRESH, 2, 1),
            ],
        ),
        (None, [], [("submit", QueryTrigger.STARTUP, 1, 0)]),
    ),
)
def test_monitor_filter_editor_commits_once_or_discards_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
    edited: Filters | None,
    expected_configures: list[tuple[object, ...]],
    expected_submits: list[tuple[object, ...]],
) -> None:
    launch = monitor_options()
    events: list[tuple[object, ...]] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Handle:
        def done(self) -> bool:
            return True

    class Submission:
        def __init__(self, generation: int, ordinal: int) -> None:
            self.generation = generation
            self.options = launch
            self.ordinal = ordinal
            self.handle = Handle()

        def cancel(self) -> None:
            events.append(("submission-cancel", self.generation))

        def result(self) -> object:
            return object()

    class Component:
        def __init__(self, selected: StandaloneLaunch, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.accepted_records = ()
            self.error = None
            self.accepted_at = None
            self.last_elapsed = None
            self.deltas = {}
            self.rank_deltas = {}
            self.generation = 0

        def configure(self, selected: StandaloneLaunch, *, data_affecting: bool) -> None:
            if selected == self.candidate:
                return
            self.candidate = selected
            if data_affecting:
                self.generation += 1
            events.append(("configure", data_affecting, self.generation))

        def submit(self, trigger: QueryTrigger, *, sample_ordinal: int) -> Submission:
            events.append(("submit", trigger, sample_ordinal, self.generation))
            return Submission(self.generation, sample_ordinal)

        def accept(self, _completion: object, **_kwargs: object) -> bool:
            self.accepted_options = self.candidate
            self.accepted_records = ()
            return True

        def preview(self, selected: StandaloneLaunch):
            self.candidate = selected
            return self

        def render(self, *_args: object, **_kwargs: object) -> str:
            return "monitor chart"

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            return True

    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            events.append(("finish",))

    keys = iter(("m", "a", "f", "\x1b", "\x03"))
    monkeypatch.setattr(monitor_host, "build_query_runtime", Runtime)
    monkeypatch.setattr(monitor_host, "build_chart_registry", lambda: object())
    monkeypatch.setattr(monitor_host, "MonitorComponent", Component)
    monkeypatch.setattr(monitor_host, "FramePainter", Screen)
    monkeypatch.setattr(monitor_host, "input_mode", nullcontext)
    monkeypatch.setattr(monitor_host, "read_key", lambda _timeout: next(keys))
    monkeypatch.setattr(monitor_host, "run_filter_editor", lambda *_args, **_kwargs: edited)
    monkeypatch.setattr(monitor_host, "get_terminal_size", lambda: terminal_size((100, 30)))
    monkeypatch.setattr(
        monitor_host,
        "inspect_terminal",
        lambda *_args, **_kwargs: Terminal(100, 30, False, True),
    )

    assert monitor_host.run_monitor(launch, load_translator("en")) == 0
    assert [event for event in events if event[0] == "configure"] == expected_configures
    assert [event for event in events if event[0] == "submit"] == expected_submits
    assert events[-2:] == [("runtime-cancel",), ("finish",)]
