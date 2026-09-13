from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor import (
    CounterSnapshot,
    ObservedTPM,
    _agent_records,
    _counters,
    _elapsed_labels,
    _monitor_plan,
    _render,
)
from ccusage_viz.options import CommandOptions, DateRange
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


def monitor_options(*, by: str | None = None) -> CommandOptions:
    day = datetime(2026, 1, 1, tzinfo=UTC).date()
    return CommandOptions(
        "monitor",
        DateRange(day, day, None),
        by,
        None,
        False,
        False,
        (),
        (),
        (),
        None,
        None,
        "ccusage",
        1,
        True,
        True,
        window_seconds=3600,
        interval=15,
    )


def test_observed_tpm_requires_a_baseline_and_uses_elapsed_monotonic_seconds() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)

    assert not observer.add(snapshot(100), 10.0)
    assert observer.rates(10.0) == {}
    assert observer.add(snapshot(160), 40.0)
    assert observer.rates(40.0) == {"Total": 120.0}


def test_monitor_title_names_the_explicit_total_and_hides_its_sole_legend() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(60), 60.0)

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        monitor_options(),
    )

    assert "Observed Total TPM" in output
    assert "Total\n" not in output


def test_monitor_title_names_model_mode() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(0, terra=0), 0.0)
    observer.add(snapshot(60, terra=60), 60.0)

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        monitor_options(by="model"),
    )

    assert "Observed Model TPM" in output
    assert "terra" in output


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


def test_agent_title_names_token_growth_without_tpm() -> None:
    observer = ObservedTPM(window_seconds=3600, by="agent", top=None)
    observer.add(CounterSnapshot(usage(0), agents={"claude": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(60), agents={"claude": usage(60)}), 60.0)

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        monitor_options(by="agent"),
    )

    assert "Observed Agent Token Growth" in output
    assert "Agent TPM" not in output


def test_project_growth_is_cumulative_within_window() -> None:
    observer = ObservedTPM(window_seconds=120, by="project", top=None)
    observer.add(CounterSnapshot(usage(0), projects={"app": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(30), projects={"app": usage(30)}), 60.0)
    observer.add(CounterSnapshot(usage(70), projects={"app": usage(70)}), 120.0)

    assert [bucket.values for bucket in observer.buckets(120.0, 2)] == [
        {"app": 30.0},
        {"app": 70.0},
    ]


def test_project_title_names_token_growth_without_tpm() -> None:
    observer = ObservedTPM(window_seconds=3600, by="project", top=None)
    observer.add(CounterSnapshot(usage(0), projects={"app": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(60), projects={"app": usage(60)}), 60.0)

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        monitor_options(by="project"),
    )

    assert "Observed Project Token Growth" in output
    assert "Project TPM" not in output


def test_monitor_project_plan_uses_bounded_claude_instances_query() -> None:
    options = replace(monitor_options(by="project"), projects=("app",))
    query = _monitor_plan(options).queries[0]

    assert query.kind.value == "Claude daily projects"
    assert query.args[:4] == ("claude", "daily", "--instances", "--json")
    assert "--offline" in query.args
    assert query.args[query.args.index("--since") + 1].isdigit()
    assert query.args[query.args.index("--until") + 1].isdigit()


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
    assert _elapsed_labels(buckets) == ([0, 1], ["11:59", "12:00"])


def test_observed_tpm_rebaselines_decreased_total_without_negative_rate() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(100), 0.0)
    assert not observer.add(snapshot(10), 60.0)

    assert observer.resets == 1
    assert observer.rates(60.0) == {}
    assert observer.add(snapshot(30), 120.0)
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
