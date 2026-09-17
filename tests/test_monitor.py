from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor import (
    CounterSnapshot,
    MonitorSeries,
    ObservedTPM,
    _agent_records,
    _copy_observer,
    _counters,
    _elapsed_labels,
    _monitor_plan,
    _nice_y_max,
    _render,
    _render_current_rows,
    _series_descriptors,
    _stable_y_max,
)
from ccusage_viz.options import CommandOptions, DateRange
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.palette import get_color_scheme
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
    assert observer.rates(10.0) == {}
    assert observer.add(snapshot(160), 40.0)
    assert observer.rates(40.0) == {"Total": 120.0}


def test_monitor_uniform_point_styles_use_the_same_marker_for_every_series() -> None:
    terminal = Terminal(100, 24, color=False, ascii=False)
    series = {"terra": [1.0], "sol": [2.0], "Other": [3.0]}

    for style in ("points", "line-points"):
        descriptors = _series_descriptors(
            tuple(series),
            series,
            replace(monitor_options(by="model"), style=style),
            terminal,
            load_translator("en"),
        )
        assert {
            (descriptor.marker_name, descriptor.marker_glyph) for descriptor in descriptors
        } == {("dot", "•")}


def test_monitor_titles_keep_filters_and_transitional_states_only() -> None:
    terminal = Terminal(100, 24, color=False, ascii=True)
    translator = load_translator("en")
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)

    baseline = _render(
        observer,
        0.0,
        terminal,
        translator,
        replace(monitor_options(), agents=("claude",)),
    )
    observer.add(snapshot(0), 0.0)
    collecting = _render(observer, 0.0, terminal, translator, monitor_options())

    assert "Agent claude · collecting baseline" in baseline
    assert "Agent all" not in baseline
    assert "collecting samples" in collecting


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

    assert "Total TPM · window 1h" in output
    assert "Observed" not in output
    assert "Total\n" not in output


def test_monitor_compact_title_uses_mode_metric_and_window() -> None:
    observer = ObservedTPM(window_seconds=3600, by="project", top=None)
    observer.add(CounterSnapshot(usage(0), projects={"project": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(60), projects={"project": usage(60)}), 60.0)

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        monitor_options(by="project"),
        normalize_title=True,
    )

    assert "Project · Token growth · 1h" in output
    assert "Observed Project" not in output


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

    assert "Model TPM · window 1h" in output
    assert "Observed" not in output
    assert "terra" in output


def test_monitor_values_display_lists_each_visible_model_observation() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(0, sonnet=0, opus=0, haiku=0), 0.0)
    observer.add(snapshot(600, sonnet=300, opus=200, haiku=100), 60.0)
    options = replace(monitor_options(by="model"), legend_position="values")

    output = _render(
        observer,
        60.0,
        Terminal(120, 24, color=False, ascii=True),
        load_translator("en"),
        options,
    )

    assert "D sonnet 300 TPM" in output
    assert "D opus 200 TPM" in output
    assert "# haiku 100 TPM" in output
    assert len(output.splitlines()) > 3


def test_monitor_values_display_uses_tokens_for_agent_and_project_growth() -> None:
    observer = ObservedTPM(window_seconds=3600, by="agent", top=None)
    observer.add(CounterSnapshot(usage(0), agents={"Claude": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(60), agents={"Claude": usage(60)}), 60.0)
    options = replace(monitor_options(by="agent"), legend_position="values")

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        options,
    )

    assert "Claude 60 tokens" in output
    assert "Claude 60 TPM" not in output


def test_monitor_ranking_style_orders_current_values_without_chart() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(0, alpha=0, beta=0, gamma=0), 0.0)
    observer.add(snapshot(600, alpha=100, beta=300, gamma=200), 60.0)
    options = replace(monitor_options(by="model"), style="ranking")

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        options,
    )

    assert "1 " in output
    assert "2 " in output
    assert "3 " in output
    assert "1." not in output
    assert output.index("beta") < output.index("gamma") < output.index("alpha")
    assert output.count("TPM") == 1
    assert "█" not in output
    assert "|" not in output


def test_monitor_ranking_style_ignores_legend_positions() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(0, sonnet=0, opus=0), 0.0)
    observer.add(snapshot(300, sonnet=200, opus=100), 60.0)

    outputs = []
    for legend_position in ("inside", "values"):
        options = replace(
            monitor_options(by="model"),
            style="ranking",
            legend_position=legend_position,
        )
        outputs.append(
            _render(
                observer,
                60.0,
                Terminal(100, 24, color=False, ascii=True),
                load_translator("en"),
                options,
            )
        )

    assert outputs[0] == outputs[1]
    assert "D sonnet" not in outputs[0]
    assert "# opus" not in outputs[0]


def test_monitor_ranking_style_uses_tokens_for_project_growth() -> None:
    observer = ObservedTPM(window_seconds=3600, by="project", top=None)
    observer.add(CounterSnapshot(usage(0), projects={"app": usage(0)}), 0.0)
    observer.add(CounterSnapshot(usage(60), projects={"app": usage(60)}), 60.0)
    options = replace(monitor_options(by="project"), style="ranking")

    output = _render(
        observer,
        60.0,
        Terminal(100, 24, color=False, ascii=True),
        load_translator("en"),
        options,
    )

    assert "app" in output
    assert output.count("tokens") == 1
    assert "60 tokens" not in output
    assert "TPM" not in output


def test_monitor_ranking_style_fits_narrow_pane_width() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=None)
    observer.add(snapshot(0, 宽模型名称=0, another_very_long_model_name=0), 0.0)
    observer.add(snapshot(300, 宽模型名称=200, another_very_long_model_name=100), 60.0)
    options = replace(monitor_options(by="model"), style="ranking")
    terminal = Terminal(22, 8, color=False, ascii=True)

    output = _render(observer, 60.0, terminal, load_translator("en"), options)

    assert "TPM" in output
    assert "200" in output
    assert "100" in output
    assert "D " not in output and "# " not in output
    assert all(display_width(line) <= terminal.width for line in output.splitlines())
    assert "█" not in output


def test_monitor_ranking_rows_are_centered_as_one_natural_block() -> None:
    descriptors = (
        MonitorSeries("alpha", "alpha", 1, "#", "A", 300),
        MonitorSeries("beta", "longer beta", 2, "#", "B", 20),
    )
    context = RenderContext(40, 4, load_translator("en"), color=False, ascii=True)

    lines = _render_current_rows(descriptors, context).splitlines()

    assert len(lines) == 2
    assert len(lines[0]) == len(lines[1])
    assert len(lines[0]) < context.width
    assert len(lines[0]) - len(lines[0].lstrip()) == len(lines[1]) - len(lines[1].lstrip())


def test_monitor_ranking_short_height_reserves_overflow_row() -> None:
    descriptors = tuple(
        MonitorSeries(str(index), f"entity-{index}", index, "#", "#", 100 - index)
        for index in range(5)
    )
    context = RenderContext(40, 3, load_translator("en"), color=False, ascii=True)

    lines = _render_current_rows(descriptors, context).splitlines()

    assert len(lines) == 3
    assert "entity-0" in lines[0]
    assert "entity-1" in lines[1]
    assert "… +3" in lines[2]


def test_monitor_ranking_markers_separate_rank_activity_and_value_by_stable_key() -> None:
    descriptors = (
        MonitorSeries("stable-a", "Alpha", 1, "#", "A", 30),
        MonitorSeries("stable-b", "Beta", 2, "#", "B", 20),
        MonitorSeries("stable-c", "Gamma", 3, "#", "C", 10),
    )
    unicode_context = RenderContext(48, 4, load_translator("en"), color=False, ascii=False)
    ascii_context = replace(unicode_context, ascii=True)
    deltas = {"stable-a": 1, "stable-b": -1, "stable-c": 0, "Alpha": -1}

    ranks = {"stable-a": 1, "stable-b": -1, "stable-c": 0, "Alpha": -1}
    unicode_output = _render_current_rows(descriptors, unicode_context, deltas, ranks)
    ascii_output = _render_current_rows(descriptors, ascii_context, deltas, ranks)

    assert "1 ↑ Alpha" in unicode_output
    assert "30 ↑" in unicode_output
    assert "2 ↓ Beta" in unicode_output
    assert "20 ↓" in unicode_output
    assert "3   Gamma" in unicode_output
    assert "10 —" in unicode_output
    assert "●" not in unicode_output
    assert "1 ^ Alpha" in ascii_output
    assert "30 ^" in ascii_output
    assert "2 v Beta" in ascii_output
    assert "20 v" in ascii_output
    assert "3   Gamma" in ascii_output
    assert "10 =" in ascii_output
    assert "*" not in ascii_output


def test_monitor_ranking_markers_follow_theme_semantic_colors() -> None:
    descriptors = (
        MonitorSeries("increase", "Increase", 1, "#", "A", 30),
        MonitorSeries("decrease", "Decrease", 2, "#", "B", 20),
        MonitorSeries("stable", "Stable", 3, "#", "C", 10),
    )
    context = RenderContext(
        64,
        4,
        load_translator("en"),
        color=True,
        ascii=False,
        color_scheme="vivid",
    )

    output = _render_current_rows(
        descriptors,
        context,
        {"increase": 1, "decrease": -1, "stable": 0},
        {"increase": 1, "decrease": -1, "stable": 0},
    )
    scheme = get_color_scheme("vivid")

    assert f"\x1b[38;5;{scheme.trend_increase}m" in output
    assert f"\x1b[38;5;{scheme.trend_decrease}m" in output
    assert f"\x1b[38;5;{scheme.trend_neutral}m" in output
    assert f"\x1b[38;5;{scheme.highlight}m" not in output
    assert "10 \x1b[" in output


def test_monitor_ranking_first_seen_values_have_no_change_markers() -> None:
    descriptors = (
        MonitorSeries("alpha", "Alpha", 1, "#", "A", 30),
        MonitorSeries("beta", "Beta", 2, "#", "B", 20),
    )
    context = RenderContext(48, 4, load_translator("en"), color=False, ascii=False)

    output = _render_current_rows(descriptors, context)

    assert "↑" not in output
    assert "↓" not in output
    assert "—" not in output
    assert "●" not in output


def test_monitor_ranking_other_never_shows_rank_movement() -> None:
    descriptors = (
        MonitorSeries("Other", "Other", 1, "#", "#", 30),
        MonitorSeries("stable", "Stable", 2, "#", "#", 20),
    )
    context = RenderContext(48, 4, load_translator("en"), color=False, ascii=True)

    output = _render_current_rows(
        descriptors,
        context,
        {"Other": 1, "stable": 1},
        {"Other": 1, "stable": -1},
    )

    other_line = next(line for line in output.splitlines() if "Other" in line)
    stable_line = next(line for line in output.splitlines() if "Stable" in line)
    assert "1   Other" in other_line
    assert "30 ^" in other_line
    assert "1 ^ Other" not in other_line
    assert "2 v Stable" in stable_line
    assert "*" not in output


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

    assert "Agent Token Growth · window 1h" in output
    assert "Observed" not in output
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

    assert "Project Token Growth · window 1h" in output
    assert "Observed" not in output
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
