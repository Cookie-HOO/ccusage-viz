import os
import re
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime

import plotext as plt
import pytest

from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    ChangeDirection,
    ComparisonState,
    MetricDescriptor,
    ObservedScope,
    PercentChange,
    PeriodSummary,
    RankingEntry,
    RankingModel,
    ScalarRankingEntry,
    ScalarSeries,
    Series,
    StackModel,
    TimelineModel,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import TokenUsage
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderAudit, RenderContext, isolated_plot, render_audit
from ccusage_viz.render.calendar import render_calendar
from ccusage_viz.render.observation import render_observation
from ccusage_viz.render.palette import (
    CATEGORICAL,
    COLOR_SCHEMES,
    ColorScheme,
    categorical_color,
    categorical_colors,
    get_color_scheme,
)
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.stack import render_stack
from ccusage_viz.render.timeline import render_timeline


def usage(total: int) -> TokenUsage:
    return TokenUsage(total, total, 0, 0, 0)


def context(ascii: bool = False) -> RenderContext:
    return RenderContext(80, 24, load_translator("en"), color=False, ascii=ascii)


def period() -> DateRange:
    return DateRange(date(2026, 1, 1), date(2026, 1, 14), None)


def test_normalized_content_headings_prefix_timeline_and_ranking() -> None:
    translator = load_translator("en")
    timeline = TimelineModel((date(2026, 1, 1),), (Series("total", "Total", (usage(1),)),))
    ranking = RankingModel((RankingEntry("a", "A", usage(1_200)),), period())

    timeline_output = render_timeline(
        timeline,
        RenderContext(80, 24, translator, color=False, period="10d", title_content="Total"),
    )
    ranking_output = render_ranking(
        ranking,
        RenderContext(80, 24, translator, color=False, period="14d", title_content="Project"),
    )

    assert "Total · Timeline · 10d" in timeline_output
    assert "Project · Ranking · 14d" in ranking_output


def test_ranking_heading_shows_hidden_top_coverage() -> None:
    model = RankingModel(
        (RankingEntry("a", "A", usage(60)),),
        period(),
        denominator=usage(100),
        top=1,
        top_share=0.6,
    )

    output = render_ranking(model, context(True))

    assert "Ranking · 2026-01-01–2026-01-14 · Top 1 · 60.0% of total" in output


@pytest.mark.parametrize(
    ("density", "current", "comparison"),
    [
        ("minimal", False, False),
        ("compact", True, False),
        ("full", True, True),
    ],
)
def test_historical_density_controls_summary_structure(
    density: str,
    current: bool,
    comparison: bool,
) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        20,
        PercentChange(ChangeDirection.INCREASE, 25),
        PercentChange(ChangeDirection.DECREASE, 10),
        date(2025, 12, 26),
        filter_count=1,
    )
    model = TimelineModel(
        (date(2026, 1, 2),),
        (Series("total", "Total", (usage(20),)),),
        summary=summary,
    )

    output = render_timeline(
        model,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density=density,
        ),
    )

    assert ("Today’s tokens 20; 1 filter" in output) is current
    assert ("vs yesterday" in output) is comparison
    assert "Timeline" in output


@pytest.mark.parametrize("state", [ComparisonState.PENDING, ComparisonState.FAILED])
def test_full_summary_marks_unknown_applicable_comparisons(state: ComparisonState) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        20,
        None,
        None,
        date(2025, 12, 26),
        sequential_state=state,
        year_over_year_state=state,
    )
    model = TimelineModel(
        (date(2026, 1, 2),),
        (Series("total", "Total", (usage(20),)),),
        summary=summary,
    )

    output = render_timeline(
        model,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density="full",
        ),
    )

    assert output.count("??") == 2
    assert "Today’s tokens 20" in output


@pytest.mark.parametrize(
    ("renderer", "model"),
    [
        (
            render_timeline,
            TimelineModel(
                (date(2026, 1, 2),),
                (Series("total", "Total", (usage(20),)),),
            ),
        ),
        (
            render_calendar,
            CalendarModel((CalendarDay(date(2026, 1, 2), usage(20)),)),
        ),
        (
            render_stack,
            StackModel(
                (date(2026, 1, 2),),
                (Series("input", "input", (usage(20),)),),
            ),
        ),
        (
            render_ranking,
            RankingModel((RankingEntry("a", "A", usage(20)),), period()),
        ),
    ],
)
def test_all_historical_renderers_omit_summary_at_minimal_density(renderer, model) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        20,
        PercentChange(ChangeDirection.UNCHANGED),
        PercentChange(ChangeDirection.UNCHANGED),
        date(2025, 12, 26),
    )
    model = replace(model, summary=summary)

    output = renderer(
        model,
        RenderContext(
            100,
            24,
            load_translator("en"),
            color=False,
            ascii=True,
            density="minimal",
            style="stacked" if isinstance(model, StackModel) else None,
        ),
    )

    assert "Today’s tokens" not in output
    assert "vs yesterday" not in output


def test_summary_shows_filter_dimension_count() -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        20,
        PercentChange(ChangeDirection.UNCHANGED),
        PercentChange(ChangeDirection.UNCHANGED),
        date(2025, 12, 26),
        filter_count=2,
    )
    model = TimelineModel(
        (date(2026, 1, 2),),
        (Series("total", "Total", (usage(20),)),),
        summary=summary,
    )

    assert "Today’s tokens 20; 2 filters" in render_timeline(model, context(True))
    assert "今日 Token 20，2 项筛选" in render_timeline(
        model, RenderContext(80, 24, load_translator("zh"), color=False)
    )


def test_rolling_heading_shows_period_while_fixed_heading_shows_dates() -> None:
    model = RankingModel((RankingEntry("a", "A", usage(1_200)),), period())

    rolling = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, period="14d"),
    )
    fixed = render_ranking(model, context())

    assert "Ranking · 14d" in rolling
    assert "2026-01-01" not in rolling
    assert "Ranking · 2026-01-01–2026-01-14" in fixed


@pytest.mark.parametrize(
    ("render", "model"),
    [
        (
            render_timeline,
            TimelineModel((date(2026, 1, 1),), (Series("a", "A", (usage(1),)),)),
        ),
        (
            render_stack,
            StackModel((date(2026, 1, 1),), (Series("input", "input", (usage(1),)),)),
        ),
        (
            render_calendar,
            CalendarModel((CalendarDay(date(2026, 1, 1), usage(1)),)),
        ),
    ],
)
def test_all_historical_renderers_show_rolling_period_headings(render, model) -> None:
    output = render(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, period="14d"),
    )

    assert "· 14d" in output
    assert "· 2026-01-01–2026-01-01" not in output


def test_ranking_and_custom_calendar_render_without_json_or_table() -> None:
    ranking = render_ranking(
        RankingModel((RankingEntry("a", "项目", usage(1_200)),), period()), context(True)
    )
    assert "Ranking · 2026-01-01–2026-01-14" in ranking
    assert "项目" in ranking and "1.2K" in ranking and "{" not in ranking
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(4)),)), context(True)
    )
    assert "Calendar" in calendar and "Less" in calendar and "#" in calendar


def test_ranking_change_markers_separate_rank_activity_and_value() -> None:
    model = RankingModel(
        (
            RankingEntry(("project", "app"), "app", usage(1_200)),
            RankingEntry(("project", "api"), "api", usage(800)),
        ),
        period(),
    )

    static = render_ranking(model, context(True))
    live = render_ranking(
        model,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            ascii=True,
            deltas={("project", "app"): 100, ("project", "api"): -10},
            rank_deltas={("project", "app"): 1, ("project", "api"): -1},
        ),
    )

    assert "^" not in static
    app_line = next(line for line in live.splitlines() if "app" in line)
    api_line = next(line for line in live.splitlines() if "api" in line)
    assert "1 ^ * app" in app_line
    assert "1.2K ^" in app_line
    assert "2 v * api" in api_line
    assert "800 v" in api_line

    equal = render_ranking(
        model,
        replace(
            context(True),
            deltas={("project", "app"): 0},
            rank_deltas={("project", "app"): 0},
        ),
    )
    equal_line = next(line for line in equal.splitlines() if "app" in line)
    assert "1     app" in equal_line
    assert "1.2K =" in equal_line


def test_ranking_other_has_value_activity_but_no_rank_marker() -> None:
    other = RankingModel(
        (RankingEntry("Other", "Other", usage(500), is_other=True),),
        period(),
    )

    output = render_ranking(
        other,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            ascii=True,
            deltas={"Other": 10},
            rank_deltas={"Other": 1},
        ),
    )

    line = next(line for line in output.splitlines() if "Other" in line)
    assert "1   * Other" in line
    assert "500 ^" in line
    assert "1 ^ * Other" not in line


def test_empty_ranking_keeps_localized_effective_range() -> None:
    output = render_ranking(
        RankingModel((), period()),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )

    lines = output.splitlines()
    assert lines[0].strip() == "累计排名 · 2026-01-01–2026-01-14"
    assert lines[1] == "所选范围内没有 Token 用量。"


def test_observed_timeline_uses_wall_clock_axis_and_metric_heading() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 10, 5)),
        observed_series=(ScalarSeries("Total", "Total", (1000.0, 2500.0)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )

    output = render_timeline(model, context(True))

    assert "Total TPM · recent 15m" in output
    assert "10:00" in output and "10:05" in output
    assert "2026-01-01" not in output


def test_observed_timeline_renders_sampling_state_with_real_translator() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("Total", "Total", (0.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total", "sampling"),
    )

    output = render_timeline(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )

    assert "sampling" in output


@pytest.mark.parametrize(
    ("density", "current"),
    [("minimal", False), ("compact", True), ("full", True)],
)
def test_monitor_density_controls_current_observation(
    density: str,
    current: bool,
) -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("Total", "Total", (1200.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )
    render_context = RenderContext(
        80,
        24,
        load_translator("en"),
        color=False,
        density=density,
    )

    output = render_observation(model, render_context)

    assert ("observed · Total 1.2K TPM" in output) is current
    assert "vs " not in output


def test_full_audit_uses_host_supplied_sample_cadence() -> None:
    output = render_audit(
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density="full",
            audit=RenderAudit(
                datetime(2026, 1, 1, 10, 5),
                0.25,
                15,
                "sample",
            ),
        )
    )

    assert output == "updated 10:05:00 · ccusage 0.25s · sample every 15s"


def test_monitor_titles_use_recent_range_and_current_tpm_wording() -> None:
    model_ranking = RankingModel(
        (),
        None,
        observed_entries=(ScalarRankingEntry("opus", "Opus", 1200.0),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(3600, "model"),
    )
    project_timeline = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("app", "App", (1000.0,)),),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(3600, "project"),
    )

    assert "Model · current TPM" in render_ranking(model_ranking, context(True))
    assert "Project cumulative Token · recent 1h" in render_timeline(
        project_timeline, context(True)
    )


def test_observed_ranking_uses_recent_range_without_historical_percentage() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("alpha", "Alpha", 1200.0),
            ScalarRankingEntry("beta", "Beta", 800.0),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "agent"),
    )

    output = render_ranking(model, context(True))

    assert "Agent · recent 15m Token" in output
    assert "1.2K" in output and "800" in output
    assert "%" not in output
    assert "2026-01-01" not in output


@pytest.mark.parametrize(
    ("ascii", "zero_mark", "levels"),
    [
        (True, "-", (".", "o", "O", "#")),
        (False, "·", ("░", "▒", "▓", "█")),
    ],
)
def test_calendar_grid_separates_valid_zero_days_and_keeps_padding_blank(
    ascii: bool, zero_mark: str, levels: tuple[str, ...]
) -> None:
    calendar = render_calendar(
        CalendarModel(
            tuple(
                CalendarDay(date(2026, 1, day), usage(value))
                for day, value in enumerate((0, 10, 20, 30, 40), start=1)
            )
        ),
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            ascii=ascii,
            style="grid",
        ),
    )
    day_rows = calendar.splitlines()[2:9]

    assert zero_mark in day_rows[3]
    assert all(level in calendar for level in levels)
    assert day_rows[0][3] == " "
    assert "Less" in calendar and "More" in calendar


def test_calendar_relative_and_grid_share_relative_intensity_legend() -> None:
    model = CalendarModel(
        tuple(
            CalendarDay(date(2026, 1, day), usage(value))
            for day, value in enumerate((1, 10, 100, 1_000), start=1)
        )
    )

    relative = render_calendar(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )
    grid = render_calendar(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="grid"),
    )

    for mark in (".", "o", "O", "#"):
        assert mark in relative
        assert mark in grid
    assert "Less . o O # More" in relative
    assert "Less . o O # More" in grid


def test_calendar_footer_separates_activity_usage_and_legend() -> None:
    calendar = render_calendar(
        CalendarModel(
            (
                CalendarDay(date(2026, 1, 1), usage(0)),
                CalendarDay(date(2026, 1, 2), usage(4_000)),
            )
        ),
        RenderContext(100, 24, load_translator("en"), color=False, ascii=True),
    )
    lines = calendar.splitlines()
    activity = next(line for line in lines if "Active days" in line)
    usage_line = next(line for line in lines if "Daily average" in line)
    legend = next(line for line in lines if "Less . o O # More" in line)

    assert "Current streak" in activity and "Longest streak" in activity
    assert "Peak" not in activity
    assert "Peak" in usage_line
    assert lines.index(activity) + 1 == lines.index(usage_line)
    assert lines.index(usage_line) + 1 == lines.index(legend)


def test_calendar_footer_keeps_average_without_peak_and_clips_rows_independently() -> None:
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(0)),)),
        RenderContext(24, 24, load_translator("en"), color=False, ascii=True),
    )
    lines = calendar.splitlines()

    assert any("Daily average" in line for line in lines)
    assert not any("Peak" in line for line in lines)
    assert all(len(line) <= 24 for line in lines)


def test_calendar_labels_follow_selected_language() -> None:
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(4)),)),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )
    assert "1月" in calendar
    assert "四" in calendar
    assert "较少 . o O # 较多" in calendar
    assert "Jan" not in calendar


def test_timeline_area_requires_one_visible_series() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series("a", "A", (usage(1_000),)),
            Series("b", "B", (usage(2_000),)),
        ),
    )
    with pytest.raises(UsageError) as caught:
        render_timeline(model, RenderContext(80, 24, load_translator("en"), style="area"))
    assert caught.value.key == "error.timeline_area_series"


def test_timeline_no_color_has_no_ansi_sequences() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (Series("total", "Total", (usage(1_000),)),),
    )
    assert "\x1b[" not in render_timeline(model, context(True))


def test_timeline_hides_only_the_sole_canonical_total_legend() -> None:
    day = (date(2026, 1, 1),)

    total = render_timeline(
        TimelineModel(day, (Series(("total",), "Total", (usage(1_000),)),)), context(True)
    )
    named = render_timeline(
        TimelineModel(day, (Series(("agent", "claude"), "claude", (usage(1_000),)),)), context(True)
    )

    assert "Timeline · Total" in total
    assert "claude" in named


def test_timeline_displays_an_explicit_legend_for_multiple_series() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series(("model", "terra"), "terra", (usage(1_000),)),
            Series(("model", "sol"), "sol", (usage(2_000),)),
            Series(("other",), "Other", (usage(500),), is_other=True),
        ),
    )

    output = render_timeline(model, context(True))

    assert ". terra · o sol · # Other" in output


def test_timeline_project_legend_uses_recognizable_safe_labels() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series(("project", "one"), "my-app", (usage(1_000),)),
            Series(("project", "two"), "api", (usage(2_000),)),
        ),
    )

    output = render_timeline(model, context(True))

    assert ". my-app · o api" in output
    assert "Project-" not in output


@pytest.mark.parametrize("position", ("inside", "hidden"))
def test_timeline_nondefault_legend_position_hides_external_legend(position: str) -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series(("model", "terra"), "terra", (usage(1_000),)),
            Series(("model", "sol"), "sol", (usage(2_000),)),
        ),
    )

    output = render_timeline(
        model, RenderContext(100, 24, load_translator("en"), ascii=True, legend_position=position)
    )

    assert ". terra · o sol" not in output


def test_colored_plot_inherits_terminal_background() -> None:
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(1_000), usage(2_000))),),
    )
    output = render_timeline(model, RenderContext(100, 24, load_translator("en"), color=True))
    assert "\x1b[" in output
    assert "\x1b[48;" not in output


def test_stack_normalized_style_uses_percent_axis() -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
        ),
    )

    output = render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="normalized")
    )
    assert "100%" in output


def test_stack_legend_has_component_swatches() -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
            Series(("component", "cache"), "cache", (usage(250),)),
        ),
    )
    output = render_stack(model, context(True))
    assert "# Input" in output
    assert "= Output" in output
    assert "+ Cache" in output

    unicode_output = render_stack(model, RenderContext(100, 24, load_translator("en"), color=False))
    assert "█ Input" in unicode_output
    assert "■ Output" in unicode_output
    assert "● Cache" in unicode_output


def test_stack_hidden_legend_keeps_heading_and_omits_component_keys() -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
        ),
    )

    output = render_stack(
        model,
        RenderContext(
            100, 24, load_translator("en"), color=False, ascii=True, legend_position="hidden"
        ),
    )

    assert "Stack · 2026-01-01–2026-01-01" in output
    assert "# Input" not in output
    assert "= Output" not in output


def test_stack_style_selects_solid_or_pattern_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
        ),
    )
    original_bar = plt.figure.bar

    def unexpected_bar(*args: object, **kwargs: object) -> object:
        pytest.fail("non-grouped Stack styles must use the integer-cell renderer")
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", unexpected_bar)
    solid = render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="stacked")
    )
    pattern = render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="stacked-pattern")
    )

    assert "█" in solid
    assert "/" in pattern
    assert "\\" in pattern


def test_stacked_grid_aligns_axis_and_distributes_non_divisible_slots() -> None:
    days = tuple(date(2026, 9, index) for index in range(3, 17))
    model = StackModel(
        days,
        (Series(("component", "input"), "input", tuple(usage(100) for _ in days)),),
    )
    output = render_stack(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )
    chart = output.splitlines()[2:]
    baseline = next(line for line in chart if "+" in line)
    data_row = next(line for line in chart if "|" in line)

    assert baseline.index("+") == data_row.index("|")
    assert all(display_width(line) == 80 for line in chart)


def test_stacked_bars_use_equal_cell_widths_when_plotext_pitch_is_fractional() -> None:
    days = tuple(date(2026, 1, index) for index in range(1, 8))
    model = StackModel(
        days,
        (
            Series(("component", "input"), "input", tuple(usage(100) for _ in days)),
            Series(("component", "output"), "output", tuple(usage(100) for _ in days)),
        ),
    )

    output = render_stack(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )
    widths = [len(run) for run in re.findall(r"#+", output.splitlines()[2])]

    assert widths == [4] * 7


def test_stacked_slots_do_not_change_when_components_or_periods_are_zero() -> None:
    days = tuple(date(2026, 1, index) for index in range(1, 8))
    components = (
        Series(("component", "input"), "input", tuple(usage(100) for _ in days)),
        Series(("component", "output"), "output", tuple(usage(100) for _ in days)),
    )
    baseline = render_stack(
        StackModel(days, components),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )
    with_zeros = render_stack(
        StackModel(
            days,
            (
                Series(
                    ("component", "input"),
                    "input",
                    (
                        usage(100),
                        usage(100),
                        usage(0),
                        usage(100),
                        usage(100),
                        usage(100),
                        usage(100),
                    ),
                ),
                Series(
                    ("component", "output"),
                    "output",
                    (usage(100), usage(0), usage(0), usage(0), usage(100), usage(100), usage(0)),
                ),
            ),
        ),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )

    baseline_starts = [match.start() for match in re.finditer(r"#+", baseline.splitlines()[2])]
    zero_starts = [match.start() for match in re.finditer(r"#+", with_zeros.splitlines()[-3])]

    assert zero_starts == [baseline_starts[index] for index in (0, 1, 3, 4, 5, 6)]


def test_grouped_stack_uses_uniform_day_pitch_and_explicit_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series(("component", "input"), "input", (usage(1_000), usage(500))),
            Series(("component", "output"), "output", (usage(500), usage(1_000))),
            Series(("component", "cache"), "cache", (usage(250), usage(250))),
        ),
    )
    captured: list[dict[str, object]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        captured.append(
            {
                "x": args[0],
                "values": args[1],
                "width": kwargs["width"],
                "stacked": kwargs.get("stacked"),
            }
        )
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped"))

    assert captured == [
        {
            "x": [-0.8 / 3, 1 - 0.8 / 3],
            "values": [1_000, 500],
            "width": 0.8 / 3,
            "stacked": None,
        },
        {"x": [0.0, 1.0], "values": [500, 1_000], "width": 0.8 / 3, "stacked": None},
        {
            "x": [0.8 / 3, 1 + 0.8 / 3],
            "values": [250, 250],
            "width": 0.8 / 3,
            "stacked": None,
        },
    ]


def test_grouped_stack_keeps_component_slots_when_a_value_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)),
        (
            Series(("component", "input"), "input", (usage(100), usage(100), usage(100))),
            Series(("component", "output"), "output", (usage(0), usage(50), usage(50))),
            Series(("component", "cache"), "cache", (usage(25), usage(25), usage(0))),
        ),
    )
    captured: list[tuple[list[float], list[int], float]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        centers, values = args[:2]
        width = kwargs["width"]
        assert isinstance(centers, list)
        assert isinstance(values, list)
        assert isinstance(width, float)
        captured.append((centers, values, width))
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped"))

    assert captured == [
        ([-0.8 / 3, 1 - 0.8 / 3, 2 - 0.8 / 3], [100, 100, 100], 0.8 / 3),
        ([0.0, 1.0, 2.0], [0, 50, 50], 0.8 / 3),
        ([0.8 / 3, 1 + 0.8 / 3, 2 + 0.8 / 3], [25, 25, 0], 0.8 / 3),
    ]


def test_grouped_thin_stack_narrows_bars_without_changing_day_pitch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series(("component", "input"), "input", (usage(1_000), usage(500))),
            Series(("component", "output"), "output", (usage(500), usage(1_000))),
            Series(("component", "cache"), "cache", (usage(250), usage(250))),
        ),
    )
    captured: list[list[tuple[list[float], float]]] = []
    current: list[tuple[list[float], float]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        centers = args[0]
        width = kwargs["width"]
        assert isinstance(centers, list)
        assert isinstance(width, float)
        current.append((centers, width))
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped"))
    captured.append(current.copy())
    current.clear()
    render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped-thin")
    )
    captured.append(current.copy())

    broad, thin = captured
    assert len(broad) == len(thin) == 3
    assert thin[0][1] < broad[0][1]
    assert thin[0][0][1] - thin[0][0][0] == broad[0][0][1] - broad[0][0][0] == 1


def test_grouped_stack_rejects_width_too_narrow_for_components() -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series(("component", "input"), "input", (usage(1_000), usage(500))),
            Series(("component", "output"), "output", (usage(500), usage(1_000))),
            Series(("component", "cache"), "cache", (usage(250), usage(250))),
        ),
    )

    with pytest.raises(UsageError) as caught:
        render_stack(
            model, RenderContext(15, 24, load_translator("en"), color=False, style="grouped")
        )
    assert caught.value.key == "error.stack_grouped_width"


def test_ranking_dots_style_repeats_marks_to_the_scaled_value() -> None:
    model = RankingModel(
        (
            RankingEntry("a", "A", usage(1_000)),
            RankingEntry("b", "B", usage(500)),
        ),
        period(),
    )

    output = render_ranking(
        model, RenderContext(60, 24, load_translator("en"), color=False, style="dots")
    )

    lines = output.splitlines()
    assert lines[1].count("●") > 1
    assert lines[2].count("●") > 1
    assert "·" in lines[2]


def test_ranking_compacts_common_opaque_prefixes() -> None:
    model = RankingModel(
        (
            RankingEntry("a", "-home-example-projects-project-a", usage(1_200)),
            RankingEntry("b", "-home-example-projects-project-b", usage(1_000)),
            RankingEntry("c", "-private-var-folders-unrelated", usage(500)),
        ),
        period(),
    )
    output = render_ranking(model, context(True))
    assert "…project-a" in output
    assert "…project-b" in output
    assert "-home-example-projects" not in output
    assert "-private-var-folders" in output


def test_wide_timeline_ticks_include_localized_weekdays() -> None:
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(1_000), usage(2_000))),),
    )
    output = render_timeline(model, RenderContext(100, 24, load_translator("en"), color=False))
    assert "Th 01-01" in output
    assert "Fr 01-02" in output


def test_color_schemes_include_curated_theme_families() -> None:
    assert COLOR_SCHEMES == (
        "classic",
        "vivid",
        "contrast",
        "dracula",
        "catppuccin",
        "solarized",
        "gruvbox",
        "nord",
        "github",
        "mono",
        "no-color",
    )


def test_github_theme_has_stable_semantic_ansi_256_colors() -> None:
    assert get_color_scheme("github") == ColorScheme(
        categorical=(26, 166, 71, 98, 162, 160, 30, 136),
        calendar=(151, 77, 71, 23),
        other=245,
        input=26,
        output=166,
        cache=71,
        cache_read=30,
        cache_creation=98,
        highlight=26,
    )


def test_color_schemes_allocate_distinct_visible_series() -> None:
    keys = tuple(("project", str(index)) for index in range(8))
    for scheme in COLOR_SCHEMES:
        colors = categorical_colors(keys, scheme)
        assert len(set(colors.values())) == 8
        assert colors == categorical_colors(reversed(keys), scheme)


@pytest.mark.parametrize("scheme", ["classic", "vivid", "contrast"])
def test_summary_uses_theme_semantic_colors(scheme: str) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    output = render_timeline(
        TimelineModel(
            (date(2026, 1, 1), date(2026, 1, 2)),
            (Series("total", "Total", (usage(10), usage(20))),),
            summary=summary,
        ),
        RenderContext(100, 24, load_translator("en"), color=True, color_scheme=scheme),
    )
    palette = get_color_scheme(scheme)
    assert f"\x1b[38;5;{palette.summary_value}m" in output
    assert f"\x1b[38;5;{palette.trend_increase}m" in output
    assert f"\x1b[38;5;{palette.trend_decrease}m" in output


def test_summary_is_localized_and_color_is_foreground_only() -> None:
    days = (date(2026, 1, 1), date(2026, 1, 2))
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    model = TimelineModel(
        days, (Series("total", "Total", (usage(10), usage(20))),), summary=summary
    )
    output = render_timeline(
        model, RenderContext(100, 24, load_translator("zh"), color=True, color_scheme="vivid")
    )
    plain = strip_ansi(output)
    assert "今日 Token 21.4M，环比昨天 ↑ 12.4%，同比上周五 ↓ 23.4%" in plain
    assert "\x1b[38;5;" in output
    assert "\x1b[38;2;" not in output
    assert "\x1b[48;" not in output

    colorless = render_timeline(model, RenderContext(100, 24, load_translator("zh"), color=False))
    assert "\x1b[" not in colorless
    assert "今日 Token 21.4M，环比昨天 ↑ 12.4%，同比上周五 ↓ 23.4%" in colorless


def test_mono_summary_uses_grayscale() -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    output = render_timeline(
        TimelineModel(
            (date(2026, 1, 1), date(2026, 1, 2)),
            (Series("total", "Total", (usage(10), usage(20))),),
            summary=summary,
        ),
        RenderContext(100, 24, load_translator("en"), color=True, color_scheme="mono"),
    )
    assert "\x1b[38;5;255m" in output
    assert "\x1b[38;5;35m" not in output
    assert "\x1b[38;5;166m" not in output


def test_from_zero_summary_describes_the_transition() -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 14),
        58_300_000,
        PercentChange(ChangeDirection.DECREASE, 49.1),
        PercentChange(ChangeDirection.FROM_ZERO),
        date(2026, 1, 7),
    )
    output = render_timeline(
        TimelineModel(
            (date(2026, 1, 7), date(2026, 1, 14)),
            (Series("total", "Total", (usage(0), usage(58_300_000))),),
            summary=summary,
        ),
        RenderContext(100, 24, load_translator("zh"), color=False),
    )
    assert "今日 Token 58.3M，环比昨天 ↓ 49.1%，同比上周三 ↑ 从 0 增至58.3M" in output


def test_categorical_color_follows_entity_key_not_rank() -> None:
    key = ("project", "/workspace/app")

    assert categorical_color(key, 0) == categorical_color(key, 7)


def test_categorical_color_uses_the_readable_palette() -> None:
    colors = {categorical_color(("project", str(index))) for index in range(256)}

    assert colors == set(CATEGORICAL)


def test_categorical_color_is_independent_of_python_hash_seed() -> None:
    command = [
        sys.executable,
        "-c",
        "from ccusage_viz.render.palette import categorical_color; "
        "print(categorical_color(('project', '/workspace/app')))",
    ]
    colors = []
    for seed in ("1", "2"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        colors.append(subprocess.check_output(command, env=environment, text=True).strip())

    assert colors[0] == colors[1]


def test_plotext_state_is_cleared_after_render_scope() -> None:
    with isolated_plot():
        plt.figure.title("private")
    assert "private" not in plt.figure.build()
