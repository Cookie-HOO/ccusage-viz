import os
import subprocess
import sys
from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    ChangeDirection,
    ComparisonState,
    PercentChange,
    PeriodSummary,
    RankingEntry,
    RankingModel,
    Series,
    StackModel,
    TimelineModel,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    CalendarConfig,
    ChartPresentation,
    Filters,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.render.base import (
    RenderAudit,
    RenderContext,
)
from ccusage_viz.render.calendar import render_calendar
from ccusage_viz.render.filters import active_filter_summary
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
from ccusage_viz.render.summary import SummaryBlock, layout_summary_blocks, render_summary
from ccusage_viz.render.timeline import render_timeline
from ccusage_viz.terminal import Terminal

from .helpers import context, period, usage


def test_layout_summary_blocks_wraps_semantic_facts_with_ansi_and_cjk_widths() -> None:
    context = RenderContext(10, 1, load_translator("zh"), color=False)

    rows = layout_summary_blocks(
        (
            SummaryBlock("甲乙"),
            SummaryBlock("\x1b[1m丙丁\x1b[0m"),
            SummaryBlock("戊己"),
        ),
        context,
    )

    assert rows == ("甲乙，\x1b[1m丙丁\x1b[0m", "戊己")
    assert all(display_width(row) <= context.width for row in rows)

def test_layout_summary_blocks_clips_only_an_oversized_block() -> None:
    context = RenderContext(6, 1, load_translator("en"), color=False)

    rows = layout_summary_blocks((SummaryBlock("Current"), SummaryBlock("Today")), context)

    assert rows == ("Curren", "Today")

@pytest.mark.parametrize(
    "config",
    (
        TimelineConfig("timeline", period(), presentation=ChartPresentation(theme="no-color")),
        CalendarConfig(
            "calendar", period(), presentation=ChartPresentation(theme="no-color", style="relative")
        ),
        StackConfig(
            "stack", period(), presentation=ChartPresentation(theme="no-color", style="stacked")
        ),
        RankingConfig(
            "ranking", period(), presentation=ChartPresentation(theme="no-color", style="bar")
        ),
    ),
)
def test_pending_historical_component_renders_candidate_safe_placeholder(config) -> None:
    accepted = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), config)
    component = HistoricalChartComponent(
        accepted, owner_id="render-test", runtime=None, registry=build_chart_registry()
    )
    component.seed(accepted, UsageSnapshot((), (), 0.1))
    candidate = replace(
        accepted,
        chart=replace(
            config,
            date_range=DateRange(
                date(2026, 2, 1), date(2026, 2, 14), period="14d", relative_until=True
            ),
        ),
    )
    component.configure(candidate, data_affecting=True)

    output = render_historical_component(
        component, load_translator("en"), Terminal(100, 30, False, False)
    ).chart

    assert "14d" in output
    assert "Loading data…" in output
    assert "??" in output
    assert "querying" in output
    assert "2026-01-01" not in output

def test_title_shows_only_querying_marker() -> None:
    querying = RenderContext(
        80,
        24,
        load_translator("zh"),
        color=False,
        audit=RenderAudit(querying=True),
    )
    refreshing = RenderContext(
        80,
        24,
        load_translator("en"),
        color=False,
        audit=RenderAudit(refreshing=True),
    )
    model = TimelineModel((date(2026, 1, 1),), (Series("total", "Total", (usage(1),)),))

    assert "查询中" in render_timeline(model, querying)
    assert "refreshing" not in render_timeline(model, refreshing)

def test_historical_headings_are_metric_first_and_omit_total_grouping() -> None:
    translator = load_translator("en")
    timeline = TimelineModel((date(2026, 1, 1),), (Series("total", "Total", (usage(1),)),))
    ranking = RankingModel((RankingEntry("a", "A", usage(1_200)),), period())

    timeline_output = render_timeline(
        timeline,
        RenderContext(80, 24, translator, color=False, period="1w", title_content="Total"),
    )
    ranking_output = render_ranking(
        ranking,
        RenderContext(80, 24, translator, color=False, period="1mo", title_content="Project"),
    )

    assert "Tokens · Timeline · 1w" in timeline_output
    assert "Tokens · Ranking · by Project · 1mo" in ranking_output
    assert "Total" not in timeline_output.splitlines()[0]

@pytest.mark.parametrize(
    ("density", "current", "comparison"),
    [
        ("minimal", False, False),
        ("compact", True, False),
        ("full", True, True),
        ("detailed", True, True),
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
            density="detailed",
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

def test_active_filter_summary_orders_dimension_values_and_compacts() -> None:
    filters = Filters(("dsh", "claude"), ("deepseek/chat",), ("ccusage-viz", "collector"))

    full = active_filter_summary(filters, load_translator("en"), width=120)
    compact = active_filter_summary(filters, load_translator("en"), width=72)
    counted = active_filter_summary(filters, load_translator("zh"), width=16)

    assert (
        full == "Filters: Agent dsh, claude · Model deepseek/chat · Project ccusage-viz, collector"
    )
    assert compact == "Filters: Agent dsh +1 · Model deepseek/chat · Project ccusage-viz +1"
    assert counted == "筛选：Agent 2 · 模型 1 · 项目 2"
    assert active_filter_summary(Filters(), load_translator("en"), width=80) == ""

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

def test_full_summary_wraps_between_semantic_blocks() -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    context = RenderContext(28, 24, load_translator("en"), color=False)

    rows = render_summary(summary, context).splitlines()

    assert rows == ["Today’s tokens 21.4M", "vs yesterday ↑ 12.4%", "vs last Fr ↓ 23.4%"]
    assert all(display_width(row) <= context.width for row in rows)

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
