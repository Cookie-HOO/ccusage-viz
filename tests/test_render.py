import os
import re
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import plotext as plt
import pytest

import ccusage_viz.render.stack as stack_renderer
import ccusage_viz.render.timeline as timeline_renderer
from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    ChangeDirection,
    ComparisonState,
    DistributionCoverage,
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
    TimeOfDayBucket,
    TimeOfDayDistributionModel,
    TimeOfDaySeries,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomDataset,
    CustomPresentationDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.domain import TokenUsage
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    CalendarConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    Filters,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
    CustomProjectedRankingGroup,
    CustomProjectedSeries,
)
from ccusage_viz.render.base import (
    RenderAudit,
    RenderContext,
    audit_row_visible,
    isolated_plot,
    observed_start_marker,
    render_audit,
)
from ccusage_viz.render.calendar import render_calendar
from ccusage_viz.render.custom import render_custom_projection
from ccusage_viz.render.filters import active_filter_summary
from ccusage_viz.render.monitor_distribution import render_monitor_distribution
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
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    render_historical_ranking,
)
from ccusage_viz.render.stack import render_stack
from ccusage_viz.render.summary import SummaryBlock, layout_summary_blocks, render_summary
from ccusage_viz.render.surfaces import (
    SurfaceControls,
    SurfacePresentation,
    dashboard_pane_surface,
    standalone_surface,
)
from ccusage_viz.render.timeline import render_timeline
from ccusage_viz.terminal import Terminal


def _grouped_ranking_projection(
    *,
    groups: tuple[CustomProjectedRankingGroup, ...] | None = None,
    period: str = "14d",
    show_percentage: bool = True,
    comparison_available: bool = True,
) -> CustomChartProjection:
    unit = CustomUnit("request", LocalizedText("requests", "次请求"), "suffix", 0)
    dataset = CustomDataset(LocalizedText("Router", "路由"), LocalizedText("", ""), unit)
    source = CustomCommandSource("router", ("router-dataset",))
    date_range = DateRange(date(2026, 10, 1), date(2026, 10, 14), period=period)
    config = CustomChartConfig(
        "ranking",
        source,
        date_range,
        group_by="real_model",
        partition_by="logical_model",
    )
    presentation = CustomPresentationDescriptor(
        dataset,
        {"real_model": LocalizedText("Real Model", "真实模型")},
        partition_labels={"logical_model": LocalizedText("Logical Model", "逻辑模型")},
    )
    if groups is None:
        groups = (
            CustomProjectedRankingGroup(
                "coding",
                LocalizedText("Coding Model", "代码模型"),
                (
                    CustomProjectedSeries(
                        "coding-a",
                        LocalizedText("coding-a", "编码-a"),
                        (Decimal("8"),),
                        rank=1,
                        description=LocalizedText(
                            "Read [safe docs](https://example.com/coding)",
                            "阅读文档",
                        ),
                    ),
                    CustomProjectedSeries(
                        "coding-b", LocalizedText("coding-b", "编码-b"), (Decimal("-2"),), rank=2
                    ),
                ),
                Decimal("6"),
                Decimal("4"),
                True,
                Decimal("8"),
                description=LocalizedText("Routes coding workloads", "路由编码工作负载"),
                display=LocalizedText("source-owned total", "来源总计"),
                comparison_display=LocalizedText("+2 requests", "+2 次请求"),
                link="https://example.com/groups/coding",
            ),
            CustomProjectedRankingGroup(
                "general",
                LocalizedText("General Model", "通用模型"),
                (
                    CustomProjectedSeries(
                        "general-a", LocalizedText("general-a", "通用-a"), (Decimal("800"),), rank=1
                    ),
                ),
                Decimal("800"),
                None,
                False,
                Decimal("800"),
            ),
        )
    return CustomChartProjection(
        "ranking",
        (date(2026, 10, 1),),
        (),
        unit,
        date_range,
        "day",
        config,
        presentation,
        comparison_available,
        show_percentage,
        groups,
    )


def test_grouped_custom_ranking_renders_dataset_order_arrow_heading_and_independent_rows() -> None:
    output = render_custom_projection(
        _grouped_ranking_projection(),
        RenderContext(
            100,
            30,
            load_translator("en"),
            color=False,
            ascii=True,
            style="bars",
            density="detailed",
        ),
        descriptions_visible=True,
    )
    lines = output.splitlines()

    assert "Router · Logical Model → Real Model · Ranking" in output
    assert lines.index(next(line for line in lines if "Coding Model" in line)) < lines.index(
        next(line for line in lines if "General Model" in line)
    )
    coding_heading = next(line for line in lines if "Coding Model" in line)
    assert "#" not in coding_heading and not coding_heading.lstrip().startswith("1 ")
    assert sum(line.lstrip().startswith("1 ") for line in lines) == 2
    coding_row = next(line for line in lines if "coding-a" in line)
    general_row = next(line for line in lines if "general-a" in line)
    assert coding_row.count("#") == general_row.count("#")
    assert "source-owned total" in coding_heading
    assert "+2 requests" in coding_heading
    assert "Routes coding workloads" in output
    assert "safe docs" in strip_ansi(output)
    assert "https://example.com/coding" not in strip_ansi(output)


def test_grouped_custom_ranking_centers_main_heading_and_aligns_shared_value_columns() -> None:
    groups = (
        CustomProjectedRankingGroup(
            "first",
            LocalizedText("First", "第一"),
            (CustomProjectedSeries("a", LocalizedText("a", "甲"), (Decimal("9"),), rank=1),),
            Decimal("9"),
            Decimal("4"),
            True,
            Decimal("9"),
            display=LocalizedText("9 requests", "9 次请求"),
            comparison_display=LocalizedText("+5 requests", "+5 次请求"),
        ),
        CustomProjectedRankingGroup(
            "second",
            LocalizedText("Second", "第二"),
            (
                CustomProjectedSeries(
                    "long", LocalizedText("long", "长"), (Decimal("12345"),), rank=1
                ),
            ),
            Decimal("12345"),
            Decimal("12000"),
            True,
            Decimal("12345"),
            display=LocalizedText("12.3K requests", "1.23万 次请求"),
            comparison_display=LocalizedText("+345 requests", "+345 次请求"),
        ),
    )
    context = RenderContext(
        100, 30, load_translator("en"), color=False, ascii=True, density="detailed"
    )
    output = strip_ansi(
        render_custom_projection(_grouped_ranking_projection(groups=groups), context)
    )
    lines = output.splitlines()
    assert lines[0] == lines[0].strip().center(context.width).rstrip()

    first_heading = next(line for line in lines if "First" in line)
    second_heading = next(line for line in lines if "Second" in line)
    first_row = next(line for line in lines if " a " in line)
    second_row = next(line for line in lines if " long " in line)
    assert first_heading.index("9 requests") + len("9 requests") == second_heading.index(
        "12.3K requests"
    ) + len("12.3K requests")
    assert first_heading.index("+5 requests") + len("+5 requests") == second_heading.index(
        "+345 requests"
    ) + len("+345 requests")
    assert first_heading.rindex("0.1%") + len("0.1%") == second_heading.rindex("99.9%") + len(
        "99.9%"
    )
    assert first_heading.index("9 requests") + len("9 requests") == first_row.index(
        "9 requests"
    ) + len("9 requests")
    assert second_heading.index("12.3K requests") + len("12.3K requests") == second_row.index(
        "12345 requests"
    ) + len("12345 requests")


def test_grouped_custom_ranking_premeasures_extreme_inner_shares_with_each_group_total() -> None:
    groups = (
        CustomProjectedRankingGroup(
            "ordinary",
            LocalizedText("Ordinary", "普通"),
            (
                CustomProjectedSeries(
                    "ordinary-item",
                    LocalizedText("ordinary-item", "普通项"),
                    (Decimal("10"),),
                    rank=1,
                ),
            ),
            Decimal("10"),
            None,
            False,
            Decimal("10"),
        ),
        CustomProjectedRankingGroup(
            "signed",
            LocalizedText("Signed", "有符号"),
            (
                CustomProjectedSeries(
                    "positive", LocalizedText("positive", "正"), (Decimal("100"),), rank=1
                ),
                CustomProjectedSeries(
                    "negative", LocalizedText("negative", "负"), (Decimal("-99"),), rank=2
                ),
            ),
            Decimal("1"),
            None,
            False,
            Decimal("100"),
        ),
    )
    context = RenderContext(
        100, 30, load_translator("en"), color=False, ascii=True, density="detailed"
    )
    lines = strip_ansi(
        render_custom_projection(_grouped_ranking_projection(groups=groups), context)
    ).splitlines()

    ordinary = next(line for line in lines if "ordinary-item" in line)
    positive = next(line for line in lines if "positive" in line)
    negative = next(line for line in lines if "negative" in line)
    assert "10000.0%" in positive
    assert "-9900.0%" in negative
    assert ordinary.rindex("100.0%") + len("100.0%") == positive.rindex("10000.0%") + len(
        "10000.0%"
    )
    assert len({display_width(line) for line in (ordinary, positive, negative)}) == 1
    assert all(display_width(line) <= context.width for line in lines)


def test_grouped_custom_ranking_new_group_uses_localized_full_comparison_only() -> None:
    projection = _grouped_ranking_projection()
    assert projection.config is not None

    for language, expected in (("en", "New"), ("zh", "新增")):
        context = RenderContext(
            100,
            30,
            load_translator(language),
            color=False,
            ascii=True,
            density="detailed",
        )
        output = strip_ansi(render_custom_projection(projection, context))
        new_group_label = "General Model" if language == "en" else "通用模型"
        heading = next(line for line in output.splitlines() if new_group_label in line)
        assert expected in heading

    rank_output = render_custom_projection(
        replace(projection, config=replace(projection.config, ranking_comparison="rank")),
        RenderContext(100, 30, load_translator("en"), color=False, ascii=True, density="detailed"),
    )
    none_output = render_custom_projection(
        replace(projection, config=replace(projection.config, ranking_comparison="none")),
        RenderContext(100, 30, load_translator("en"), color=False, ascii=True, density="detailed"),
    )
    all_output = render_custom_projection(
        replace(projection, date_range=replace(projection.date_range, period="all")),
        RenderContext(
            100,
            30,
            load_translator("en"),
            color=False,
            ascii=True,
            density="detailed",
            period="all",
        ),
    )
    for output in (rank_output, none_output, all_output):
        heading = next(line for line in strip_ansi(output).splitlines() if "General Model" in line)
        assert "New" not in heading


def test_grouped_custom_ranking_unchanged_group_ignores_custom_comparison_display() -> None:
    groups = (
        CustomProjectedRankingGroup(
            "unchanged",
            LocalizedText("Unchanged", "未变化"),
            (CustomProjectedSeries("item", LocalizedText("Item", "项目"), (Decimal("7"),), rank=1),),
            Decimal("7"),
            Decimal("7"),
            True,
            Decimal("7"),
            comparison_display=LocalizedText("same as before", "与之前相同"),
        ),
    )
    output = strip_ansi(
        render_custom_projection(
            _grouped_ranking_projection(groups=groups),
            RenderContext(
                100, 20, load_translator("en"), color=False, ascii=True, density="detailed"
            ),
        )
    )
    heading = next(line for line in output.splitlines() if "Unchanged" in line)

    assert "same as before" not in heading
    assert re.search(r"7 requests\s+0\s+100\.0%", heading)


def test_pending_grouped_custom_ranking_suppresses_group_and_entry_comparisons() -> None:
    output = strip_ansi(
        render_custom_projection(
            _grouped_ranking_projection(),
            RenderContext(
                100,
                30,
                load_translator("en"),
                color=False,
                ascii=True,
                density="detailed",
                pending=True,
            ),
        )
    )
    coding_heading = next(line for line in output.splitlines() if "Coding Model" in line)
    general_heading = next(line for line in output.splitlines() if "General Model" in line)

    assert "+2 requests" not in coding_heading
    assert "New" not in general_heading
    assert "+" not in output and "New" not in output


def test_grouped_custom_ranking_rank_mode_suppresses_group_value_delta() -> None:
    projection = _grouped_ranking_projection()
    assert projection.config is not None
    output = render_custom_projection(
        replace(projection, config=replace(projection.config, ranking_comparison="rank")),
        RenderContext(100, 30, load_translator("en"), color=False, ascii=True, density="detailed"),
    )

    assert "+2 requests" not in output
    assert "Rank Δ" in output


def test_grouped_custom_ranking_handles_empty_zero_signed_and_hidden_shares() -> None:
    groups = (
        CustomProjectedRankingGroup(
            "zero",
            LocalizedText("Zero", "零"),
            (
                CustomProjectedSeries(
                    "positive", LocalizedText("Positive", "正"), (Decimal("5"),), rank=1
                ),
                CustomProjectedSeries(
                    "negative", LocalizedText("Negative", "负"), (Decimal("-5"),), rank=2
                ),
            ),
            Decimal(),
            None,
            False,
            Decimal("5"),
        ),
        CustomProjectedRankingGroup(
            "empty", LocalizedText("Empty", "空"), (), Decimal(), None, False, Decimal()
        ),
    )
    output = render_custom_projection(
        _grouped_ranking_projection(groups=groups),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )
    without_shares = render_custom_projection(
        _grouped_ranking_projection(groups=groups, show_percentage=False),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )

    assert "Zero" in output and "Empty" in output
    assert "No data in this group." in output
    assert "nan" not in output.lower() and "inf" not in output.lower()
    assert "%" not in output
    assert "%" not in without_shares


def test_grouped_custom_ranking_negative_item_with_nonzero_total_stays_within_terminal_width() -> (
    None
):
    groups = (
        CustomProjectedRankingGroup(
            "signed",
            LocalizedText("Signed", "有符号"),
            (
                CustomProjectedSeries(
                    "positive", LocalizedText("Positive", "正"), (Decimal("8"),), rank=1
                ),
                CustomProjectedSeries(
                    "negative", LocalizedText("Negative", "负"), (Decimal("-2"),), rank=2
                ),
            ),
            Decimal("6"),
            None,
            False,
            Decimal("8"),
        ),
    )
    context = RenderContext(58, 20, load_translator("en"), color=False, ascii=True, style="bars")
    output = render_custom_projection(_grouped_ranking_projection(groups=groups), context)
    negative = next(line for line in output.splitlines() if "Negative" in line)

    assert "-2 requests" in negative
    assert "-33.3%" in negative
    assert display_width(negative) <= context.width
    assert "#" not in negative


def test_grouped_custom_ranking_all_period_and_narrow_density_hide_comparison_and_descriptions() -> (
    None
):
    output = render_custom_projection(
        _grouped_ranking_projection(period="all"),
        RenderContext(
            38, 20, load_translator("en"), color=False, ascii=True, density="minimal", period="all"
        ),
        descriptions_visible=True,
    )

    assert "Coding Model" in output and "coding-a" in output
    assert "+2 requests" not in output
    assert "Routes coding workloads" not in output
    assert all(display_width(line) <= 38 for line in output.splitlines())


def test_timeline_surfaces_have_independent_axis_and_control_budgets() -> None:
    presentation = SurfacePresentation(
        "timeline",
        "no-color",
        "linear",
        "below-title",
        "detailed",
        "show",
        "14d",
        "Total",
        None,
        None,
        None,
        60,
    )
    terminal = Terminal(80, 20, color=False, ascii=True)
    controls = SurfaceControls(rows=("standalone controls",), reserves_prompt=True)

    standalone = standalone_surface("timeline").context(
        terminal, load_translator("en"), presentation, notices=1, controls=controls
    )
    dashboard = dashboard_pane_surface("timeline").context(
        terminal, load_translator("en"), presentation, notices=1
    )

    assert not standalone.hide_upper_right_axes
    assert dashboard.hide_upper_right_axes
    assert standalone.height == 15
    assert dashboard.height == 18


def test_detailed_surfaces_do_not_reserve_empty_audit_rows() -> None:
    presentation = SurfacePresentation(
        "timeline",
        "no-color",
        "linear",
        "below-title",
        "detailed",
        "show",
        "14d",
        "Total",
        None,
        None,
        None,
        None,
    )
    terminal = Terminal(80, 20, color=False, ascii=True)

    standalone = standalone_surface("timeline").context(
        terminal, load_translator("en"), presentation
    )
    dashboard = dashboard_pane_surface("timeline").context(
        terminal, load_translator("en"), presentation
    )

    assert standalone.height == 19
    assert dashboard.height == 20


def usage(total: int) -> TokenUsage:
    return TokenUsage(total, total, 0, 0, 0)


def context(ascii: bool = False) -> RenderContext:
    return RenderContext(80, 24, load_translator("en"), color=False, ascii=ascii)


def period() -> DateRange:
    return DateRange(date(2026, 1, 1), date(2026, 1, 14))


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


def test_layout_summary_blocks_stacks_facts_without_separators() -> None:
    context = RenderContext(10, 1, load_translator("zh"), color=False)

    rows = layout_summary_blocks(
        (SummaryBlock("甲乙"), SummaryBlock("\x1b[1m丙丁\x1b[0m"), SummaryBlock("戊己")),
        context,
        layout="stack",
    )

    assert rows == ("甲乙", "\x1b[1m丙丁\x1b[0m", "戊己")
    assert all(display_width(row) <= context.width for row in rows)


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


def test_historical_ranking_heading_is_centered_once() -> None:
    context = RenderContext(80, 24, load_translator("zh"), color=False, period="14d")
    model = RankingModel((RankingEntry("a", "A", usage(1_200)),), period())

    heading = render_ranking(model, context).splitlines()[0]

    assert heading.lstrip() == "累计排名 · 14d"
    assert (
        len(heading) - len(heading.lstrip())
        == (context.width - display_width(heading.lstrip())) // 2
    )


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


def test_pending_historical_ranking_masks_stale_figures() -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 14),
        60,
        PercentChange(ChangeDirection.INCREASE, 20),
        PercentChange(ChangeDirection.DECREASE, 10),
        date(2026, 1, 7),
    )
    model = RankingModel(
        (RankingEntry("a", "A", usage(60)),),
        period(),
        summary=summary,
        denominator=usage(100),
        top=1,
        top_share=0.6,
    )

    output = render_ranking(
        model,
        RenderContext(
            100,
            24,
            load_translator("en"),
            color=False,
            pending=True,
            deltas={"a": 1},
            rank_deltas={"a": 1},
        ),
    )

    assert "??" in output
    assert "60.0% of total" not in output
    assert " 60 " not in output
    assert "60.0%" not in output


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


def test_exact_project_ranking_qualifies_safe_labels_and_title() -> None:
    model = RankingModel(
        (
            RankingEntry(
                ("project", "exact", "claude", "-private-work-py-ccusage-viz"),
                "py-ccusage-viz",
                usage(1_200),
            ),
            RankingEntry(
                ("project", "exact", "codex", "/private/work/py-ccusage-viz"),
                "py-ccusage-viz",
                usage(800),
            ),
            RankingEntry("Other", "Other", usage(500), is_other=True),
        ),
        period(),
        project_aggregation="exact",
    )

    output = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, period="14d"),
    )
    rows = output.splitlines()[-3:]

    assert "Agent · Project · cumulative ranking · 14d" in output
    assert "claude · py-ccusage-viz" not in rows[0]
    assert "codex · py-ccusage-viz" not in rows[1]
    assert "claude" in rows[0] and "py-ccusage-viz" in rows[0]
    assert "codex" in rows[1] and "py-ccusage-viz" in rows[1]
    assert "Other" in rows[2]
    assert "-private-work-py-ccusage-viz" not in output
    assert "/private/work/py-ccusage-viz" not in output


def test_name_project_ranking_keeps_plain_label_for_exact_identity() -> None:
    model = RankingModel(
        (RankingEntry(("project", "exact", "claude", "-private-work-app"), "app", usage(1_200)),),
        period(),
    )

    output = render_ranking(model, context(True))

    assert "Ranking · 2026-01-01–2026-01-14" in output
    assert "claude app" not in output
    assert "app" in output


def test_exact_project_ranking_keeps_agent_visible_in_narrow_context() -> None:
    model = RankingModel(
        (
            RankingEntry(
                ("project", "exact", "claude", "-private-work-very-long-project"),
                "very-long-project",
                usage(1_200),
            ),
            RankingEntry(
                ("project", "exact", "codex", "/private/work/very-long-project"),
                "very-long-project",
                usage(800),
            ),
        ),
        period(),
        project_aggregation="exact",
    )
    output = render_ranking(
        model,
        RenderContext(40, 24, load_translator("en"), color=False, ascii=True),
    )

    rows = output.splitlines()[-2:]
    assert "claude" in rows[0]
    assert "codex" in rows[1]
    assert all("claude ·" not in row and "codex ·" not in row for row in rows)
    assert all("very-long-project" not in row for row in rows)


def test_historical_ranking_derives_comparison_markers_from_entry_facts() -> None:
    model = RankingModel(
        (
            RankingEntry(
                ("project", "api"),
                "api",
                usage(300),
                previous_usage=usage(100),
                comparison_ready=True,
                previous_rank=2,
            ),
            RankingEntry(
                ("project", "app"),
                "app",
                usage(100),
                previous_usage=usage(200),
                comparison_ready=True,
                previous_rank=1,
            ),
        ),
        period(),
    )

    output = render_ranking(model, context(True))

    header = next(line for line in output.splitlines() if "Rank Δ" in line)
    api_line = next(line for line in output.splitlines() if "api" in line)
    app_line = next(line for line in output.splitlines() if "app" in line)
    assert "vs prior" in header
    assert "+200" in api_line
    assert "^" in api_line
    assert "-100" in app_line
    assert "v" in app_line


def test_historical_ranking_full_uses_labeled_value_delta_without_rank_comparison() -> None:
    entries = (
        RankingPresentationEntry(
            "api", "api", 300, previous=100, comparison_ready=True, previous_rank=2
        ),
        RankingPresentationEntry(
            "app", "app", 100, previous=200, comparison_ready=True, previous_rank=1
        ),
        RankingPresentationEntry("other", "Other", 20, is_other=True),
    )
    output = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        delta_formatter=lambda value: f"{value:+}",
        context=RenderContext(
            100, 24, load_translator("en"), color=False, ascii=True, density="full"
        ),
        total=420,
    )
    header, api, app, other = output.splitlines()[1:]

    assert "Rank" in header and "Current" in header and "vs prior" in header
    assert "Rank Δ" not in header
    assert "+200" in api and "^" not in api
    assert "-100" in app and "v" not in app
    assert "—" in other
    assert all(display_width(row) <= 100 for row in output.splitlines())


def test_historical_ranking_all_period_omits_comparison_columns_and_uses_available_width() -> None:
    context = RenderContext(
        120, 24, load_translator("en"), color=False, style="dot", density="detailed", period="all"
    )
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "Alpha", 100),
            RankingPresentationEntry("b", "Beta", 50),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
    )
    _heading, *rows = output.splitlines()

    assert all("vs prior" not in row and "Rank Δ" not in row for row in rows)
    assert all(display_width(row) == context.width for row in rows)


def test_historical_ranking_rank_comparison_hides_growth_but_retains_rank_delta() -> None:
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "api", "API", 300, previous=100, comparison_ready=True, previous_rank=2
            ),
            RankingPresentationEntry(
                "app", "App", 100, previous=200, comparison_ready=True, previous_rank=1
            ),
        ),
        heading="Ranking",
        value_formatter=str,
        delta_formatter=lambda value: f"{value:+}",
        context=RenderContext(
            100, 24, load_translator("en"), color=False, ascii=True, density="detailed"
        ),
        total=400,
        comparison_mode="rank",
    )

    header, api, app = output.splitlines()[1:]
    assert "vs prior" not in header
    assert "Rank Δ" in header
    assert "+200" not in api and "-100" not in app
    assert "^" in api and "v" in app


def test_historical_ranking_none_comparison_hides_all_comparison_columns() -> None:
    output = render_historical_ranking(
        (RankingPresentationEntry("api", "API", 300, previous=100, comparison_ready=True),),
        heading="Ranking",
        value_formatter=str,
        context=RenderContext(100, 24, load_translator("en"), color=False, density="detailed"),
        comparison_mode="none",
    )

    assert "vs prior" not in output
    assert "Rank Δ" not in output


def test_historical_ranking_shows_refresh_activity_and_rank_changes() -> None:
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

    assert "^" not in static.splitlines()[-1]
    assert "v" not in static.splitlines()[-1]
    app_line = next(line for line in live.splitlines() if "app" in line)
    api_line = next(line for line in live.splitlines() if "api" in line)
    assert "1 ^ * app" in app_line
    assert "1.2K ^" in app_line
    assert "2 v * api" in api_line
    assert "800 v" in api_line


def test_historical_ranking_other_ignores_refresh_activity() -> None:
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
    assert "^" not in line
    assert "*" not in line


def test_empty_ranking_keeps_localized_effective_range() -> None:
    output = render_ranking(
        RankingModel((), period()),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )

    lines = output.splitlines()
    assert lines[0].strip() == "累计排名 · 2026-01-01–2026-01-14"
    assert lines[1] == "所选范围内没有 Token 用量。"


def test_observed_monitor_heading_marks_only_query_pending_candidates() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(datetime(2026, 1, 1, 10, 0),),
        observed_series=(ScalarSeries("Total", "Total", (1000.0,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total", "sampling"),
    )

    querying = render_timeline(
        model, replace(context(), audit=RenderAudit(querying=True), pending=True)
    )
    refreshing = render_timeline(model, replace(context(), audit=RenderAudit(refreshing=True)))

    assert "querying" in querying
    assert "refreshing" not in refreshing


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


def test_observed_start_marker_is_density_aware_and_time_anchored() -> None:
    points = (
        datetime(2026, 1, 1, 10, 0),
        datetime(2026, 1, 1, 10, 5),
        datetime(2026, 1, 1, 10, 10),
    )
    started_at = datetime(2026, 1, 1, 10, 2)

    render_context = replace(context(), width=140)
    full = observed_start_marker(points, started_at=started_at, context=render_context)
    compact = observed_start_marker(
        points, started_at=started_at, context=replace(render_context, density="compact")
    )
    minimal = observed_start_marker(
        points, started_at=started_at, context=replace(render_context, density="minimal")
    )

    assert full is not None
    assert full.position == pytest.approx(0.4)
    assert full.label == "Monitor started 10:02"
    assert compact is not None
    assert compact.label == "Started 10:02"
    assert minimal is not None
    assert minimal.label is None
    assert (
        observed_start_marker(points, started_at=datetime(2026, 1, 1, 9, 59), context=context())
        is None
    )


def test_observed_timeline_labels_visible_monitor_start_by_density() -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 10, 5),
            datetime(2026, 1, 1, 10, 10),
        ),
        monitor_started_at=datetime(2026, 1, 1, 10, 2),
        observed_series=(ScalarSeries("Total", "Total", (1000.0, 1500.0, 2000.0)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )

    full = render_timeline(model, replace(context(), width=140, density="full"))
    detailed = render_timeline(model, replace(context(), width=140, density="detailed"))
    compact = render_timeline(model, replace(context(), width=140, density="compact"))
    minimal = render_timeline(model, replace(context(), width=140, density="minimal"))

    assert "Monitor started 10:02" in full
    assert "Monitor started 10:02" in detailed
    assert "Started 10:02" in compact
    assert "Monitor started 10:02" not in minimal
    assert "Started 10:02" not in minimal


def test_observed_timeline_overlays_a_thin_start_marker_without_plotext_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = TimelineModel(
        (),
        (),
        observed_at=(
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 10, 5),
            datetime(2026, 1, 1, 10, 10),
        ),
        monitor_started_at=datetime(2026, 1, 1, 10, 2),
        observed_series=(ScalarSeries("Total", "Total", (1000.0, 1500.0, 2000.0)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
    )

    monkeypatch.setattr(plt.figure, "line", lambda *args, **kwargs: pytest.fail("line called"))
    unicode = render_timeline(model, replace(context(), width=100, density="minimal"))
    ascii = render_timeline(model, replace(context(ascii=True), width=100, density="minimal"))

    assert unicode.count("┆") > 4
    assert "┆" not in ascii
    assert ascii.count(":") > 4


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
    [
        ("minimal", False),
        ("compact", False),
        ("full", True),
        ("detailed", True),
    ],
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
        observed_current=(ScalarRankingEntry("Total", "Total", 1200.0),),
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


def test_detailed_audit_uses_host_supplied_sample_cadence() -> None:
    output = render_audit(
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density="detailed",
            audit=RenderAudit(
                datetime(2026, 1, 1, 10, 5),
                0.25,
                15,
                "sample",
            ),
        )
    )

    assert output == "updated 10:05:00 · ccusage 0.25s · sample every 15s"


def test_detailed_audit_appends_localized_muted_refreshing_suffix() -> None:
    audit = RenderAudit(datetime(2026, 1, 1, 10, 5), 0.25, 15, "sample", refreshing=True)
    plain = render_audit(
        RenderContext(80, 24, load_translator("en"), color=False, density="detailed", audit=audit)
    )
    colored = render_audit(
        RenderContext(80, 24, load_translator("en"), density="detailed", audit=audit)
    )
    chinese = render_audit(
        RenderContext(80, 24, load_translator("zh"), color=False, density="detailed", audit=audit)
    )

    assert plain == "updated 10:05:00 · ccusage 0.25s · sample every 15s · refreshing"
    assert strip_ansi(colored) == plain
    assert "\x1b[2m" in colored
    assert "\n" not in colored
    assert chinese.endswith(" · 刷新中")


@pytest.mark.parametrize(
    ("density", "audit", "visible"),
    (
        ("detailed", RenderAudit(), False),
        ("detailed", RenderAudit(querying=True), False),
        ("detailed", RenderAudit(accepted_at=datetime(2026, 1, 1)), True),
        ("detailed", RenderAudit(query_elapsed=0.25), True),
        ("detailed", RenderAudit(interval=60), True),
        ("detailed", RenderAudit(refreshing=True), True),
        ("full", RenderAudit(interval=60), False),
        ("compact", RenderAudit(interval=60), False),
        ("minimal", RenderAudit(interval=60), False),
    ),
)
def test_audit_row_visibility_matches_rendered_footer(
    density: str, audit: RenderAudit, visible: bool
) -> None:
    context = RenderContext(
        80, 24, load_translator("en"), color=False, density=density, audit=audit
    )

    assert audit_row_visible(density, audit) is visible
    assert bool(render_audit(context)) is visible


@pytest.mark.parametrize("density", ("minimal", "compact", "full"))
def test_non_detailed_audit_hides_refreshing_suffix(density: str) -> None:
    output = render_audit(
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            density=density,
            audit=RenderAudit(refreshing=True),
        )
    )

    assert output == ""


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

    assert "Agent · current Token" in output
    assert "1.2K" in output and "800" in output
    assert "%" not in output
    assert "2026-01-01" not in output


def test_observed_ranking_reclaims_percentage_space_for_labels() -> None:
    label = "gpt-5.6-very-long-model-name"
    model = RankingModel(
        (),
        None,
        observed_entries=(ScalarRankingEntry("model", label, 1200.0),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "model"),
    )

    wide = render_ranking(model, context(True)).splitlines()[-1]
    narrow = render_ranking(
        model,
        RenderContext(40, 24, load_translator("en"), color=False, ascii=True),
    )

    assert "gpt-5.6-very-long-model-name" in wide
    assert display_width(wide) <= 80
    assert all(display_width(line) <= 40 for line in narrow.splitlines())


def test_observed_ranking_uses_content_driven_label_width() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("a", "A", 1200.0),
            ScalarRankingEntry("b", "B", 800.0),
        ),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "model"),
    )

    row = render_ranking(model, context(True)).splitlines()[-2]

    assert "A #" in row
    assert "A           " not in row


def test_monitor_ranking_dot_replaces_the_middle_bar_with_a_single_dot_track() -> None:
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

    dotted = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, style="ranking-dot"),
    )
    ascii_dotted = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="ranking-dot"),
    )
    ranking = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, style="ranking"),
    )

    dotted_rows = dotted.splitlines()[-2:]
    ascii_rows = ascii_dotted.splitlines()[-2:]
    ranking_rows = ranking.splitlines()[-2:]

    assert all(not row.startswith(("● ", "o ")) for row in (*dotted_rows, *ascii_rows))
    assert all("●" in row and "·" in row for row in dotted_rows)
    assert all("o" in row and "." in row for row in ascii_rows)
    assert all("█" in row for row in ranking_rows)
    assert all("●" not in row and "·" not in row for row in ranking_rows)
    assert all(display_width(row) <= 80 for row in dotted_rows)


def test_monitor_list_is_centered_and_omits_bar_tracks() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("alpha", "Alpha", 1200.0),
            ScalarRankingEntry("beta", "Beta", 800.0),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "model"),
    )
    render_context = RenderContext(
        80,
        24,
        load_translator("en"),
        color=False,
        ascii=True,
        style="list",
        deltas={"alpha": 1.0, "beta": -1.0},
        rank_deltas={"alpha": 1, "beta": -1},
    )

    output = render_ranking(model, render_context)
    rows = output.splitlines()[-2:]

    assert all("#" not in row for row in rows)
    assert "1.2K" in rows[0] and "800" in rows[1]
    assert "^" in rows[0] and "v" in rows[1]
    assert all(
        abs((80 - display_width(row.lstrip())) // 2 - (len(row) - len(row.lstrip()))) <= 1
        for row in rows
    )
    assert all(display_width(line) <= 80 for line in output.splitlines())


def test_monitor_project_ranking_and_list_preserve_exact_agent_labels() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("claude-app", "claude · app", 1_200.0, agent="claude"),
            ScalarRankingEntry("codex-app", "codex · app", 800.0, agent="codex"),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "project"),
        project_aggregation="exact",
    )

    ranking = render_ranking(model, context(True))
    listing = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="list"),
    )

    assert "Project · current Token" in ranking
    assert "claude · app" in ranking and "codex · app" in ranking
    assert "claude · app" in listing and "codex · app" in listing


def test_observed_ranking_does_not_compact_shared_model_prefixes() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("terna", "gpt-5.6-terna", 1_000_000.0),
            ScalarRankingEntry("luna", "gpt-5.6-luna", 510_000.0),
            ScalarRankingEntry("sol", "gpt-5.6-sol", 0.0),
        ),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "model"),
    )

    output = render_ranking(model, context(True))

    assert "gpt-5.6-terna" in output
    assert "gpt-5.6-luna" in output
    assert "gpt-5.6-sol" in output
    assert "…5.6-" not in output


@pytest.mark.parametrize("ascii", [True, False])
def test_calendar_styles_use_geometry_not_zero_cell_outlines(ascii: bool) -> None:
    model = CalendarModel(
        tuple(
            CalendarDay(date(2026, 1, day), usage(value))
            for day, value in enumerate((0, 10, 20, 30, 40), start=1)
        )
    )
    relative = render_calendar(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=ascii, style="relative"),
    )
    grid = render_calendar(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=ascii, style="grid"),
    )
    marks = (".", "o", "O", "#") if ascii else ("░", "▒", "▓", "█")

    assert all(mark in relative and mark in grid for mark in marks)
    assert relative.splitlines()[5][3:] == "  "
    assert grid.splitlines()[5][3:] == "     "
    full_mark = "#" if ascii else "█"
    assert relative.splitlines()[2][3:] == f" {full_mark}"
    assert grid.splitlines()[2][3:] == f"   {full_mark} "
    assert relative != grid


def test_calendar_keeps_seven_rows_with_sparse_aligned_weekday_labels() -> None:
    calendar = render_calendar(
        CalendarModel(tuple(CalendarDay(date(2026, 1, day), usage(day)) for day in range(1, 8))),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )
    day_rows = calendar.splitlines()[2:9]

    assert [row[:3] for row in day_rows] == ["Mo ", "   ", "We ", "   ", "Fr ", "   ", "   "]
    assert all(display_width(row[:3]) == 3 for row in day_rows)


def test_calendar_month_labels_align_to_the_first_week_containing_the_month() -> None:
    calendar = render_calendar(
        CalendarModel(
            tuple(CalendarDay(date(2026, 1, day), usage(1)) for day in range(26, 32))
            + tuple(CalendarDay(date(2026, 2, day), usage(1)) for day in range(1, 3))
        ),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True),
    )
    month_header, monday = calendar.splitlines()[1:3]

    assert month_header.index("Fe") == 3
    assert monday[3] == "."


def test_calendar_color_styles_use_background_swatches_and_distinct_geometry() -> None:
    model = CalendarModel(
        tuple(
            CalendarDay(date(2026, 1, day), usage(value))
            for day, value in enumerate((0, 10, 20, 30, 40), start=1)
        )
    )
    relative = render_calendar(
        model,
        RenderContext(
            80, 24, load_translator("en"), color=True, style="relative", color_scheme="github"
        ),
    )
    grid = render_calendar(
        model,
        RenderContext(
            80, 24, load_translator("en"), color=True, style="grid", color_scheme="github"
        ),
    )

    for color in (151, 77, 71, 23):
        assert f"\x1b[48;5;{color}m" in relative
        assert f"\x1b[48;5;{color}m" in grid
    assert "\x1b[48;5;245m" not in relative + grid
    assert "\x1b[38;5;" not in relative + grid
    assert all(
        mark not in "\n".join((relative.splitlines()[-1], grid.splitlines()[-1]))
        for mark in ("·", "░", "▒", "▓", "█")
    )
    assert strip_ansi(relative).splitlines()[5][3:] == "  "
    assert strip_ansi(grid).splitlines()[5][3:] == "     "
    assert strip_ansi(relative).splitlines()[2][3:] == "  "
    assert strip_ansi(grid).splitlines()[2][3:] == "     "
    assert relative != grid


@pytest.mark.parametrize(
    ("density", "has_stats", "has_streaks", "has_legend"),
    (
        ("minimal", False, False, False),
        ("compact", False, False, False),
        ("full", True, False, False),
        ("detailed", True, True, True),
    ),
)
def test_calendar_footer_follows_density(
    density: str, has_stats: bool, has_streaks: bool, has_legend: bool
) -> None:
    calendar = render_calendar(
        CalendarModel(
            (
                CalendarDay(date(2026, 1, 1), usage(0)),
                CalendarDay(date(2026, 1, 2), usage(4_000)),
            )
        ),
        RenderContext(100, 24, load_translator("en"), color=False, ascii=True, density=density),
    )

    assert ("Active days" in calendar) is has_stats
    assert ("Daily average" in calendar) is has_stats
    assert ("Peak" in calendar) is has_stats
    assert ("Current streak" in calendar) is has_streaks
    assert ("Longest streak" in calendar) is has_streaks
    assert ("Less . o O # More" in calendar) is has_legend


def test_calendar_grid_uses_only_positive_color_swatches() -> None:
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
            ascii=True,
            style="grid",
            color_scheme="github",
        ),
    )

    assert "\x1b[48;5;245m" not in calendar
    assert "\x1b[48;5;151m" in calendar
    assert "\x1b[48;5;77m" in calendar
    assert "\x1b[48;5;71m" in calendar
    assert "\x1b[48;5;23m" in calendar
    assert "\x1b[38;5;" not in calendar
    assert "Less" in calendar and "More" in calendar


def test_calendar_uses_one_cell_per_week_when_width_requires_compact_stride() -> None:
    first = date(2025, 1, 1)
    calendar = render_calendar(
        CalendarModel(
            tuple(
                CalendarDay(first.fromordinal(first.toordinal() + offset), usage(offset + 1))
                for offset in range(365)
            )
        ),
        RenderContext(58, 24, load_translator("en"), color=False, ascii=True),
    )
    day_rows = calendar.splitlines()[2:9]

    assert all(len(row[3:]) == 53 for row in day_rows)
    assert all(display_width(line) <= 58 for line in calendar.splitlines())


def test_calendar_footer_keeps_average_without_peak_and_clips_rows_independently() -> None:
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(0)),)),
        RenderContext(32, 24, load_translator("en"), color=False, ascii=True, density="full"),
    )
    lines = calendar.splitlines()

    assert any("Daily average" in line for line in lines)
    assert not any("Peak" in line for line in lines)
    assert all(len(line) <= 32 for line in lines)


def test_calendar_labels_follow_selected_language() -> None:
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(4)),)),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )
    assert "1月" in calendar
    assert "一" in calendar and "三" in calendar and "五" in calendar
    assert "较少 . o O # 较多" in calendar
    assert "Jan" not in calendar


def _distribution_model() -> TimeOfDayDistributionModel:
    started = datetime(2026, 9, 22, 9, 0).astimezone()
    first_end = datetime(2026, 9, 22, 10, 0).astimezone()
    second_end = datetime(2026, 9, 22, 11, 0).astimezone()
    third_end = datetime(2026, 9, 22, 12, 0).astimezone()
    return TimeOfDayDistributionModel(
        (
            TimeOfDayBucket(started, first_end, DistributionCoverage.UNOBSERVED),
            TimeOfDayBucket(
                first_end,
                second_end,
                DistributionCoverage.PARTIAL,
                {"alpha": 60.0, "beta": 40.0},
            ),
            TimeOfDayBucket(
                second_end,
                third_end,
                DistributionCoverage.FULL,
                {"alpha": 0.0, "beta": 0.0},
            ),
        ),
        (TimeOfDaySeries("alpha", "Alpha"), TimeOfDaySeries("beta", "Beta")),
        datetime(2026, 9, 22, 9, 18).astimezone(),
        "today",
        "hour",
    )


def test_distribution_renderer_keeps_observation_metadata_outside_the_chart() -> None:
    output = render_monitor_distribution(_distribution_model(), context(True))

    assert "Total · Token cumulative bars · Today · Hourly" in output
    assert "observed from" not in output
    assert "not observed" in output
    assert "#" in output
    assert "09" in output and "11" in output
    assert "09:00" not in output and "11:00" not in output


def test_distribution_renderer_centers_hour_labels_on_bar_columns() -> None:
    model = _distribution_model()
    output = render_monitor_distribution(
        model,
        RenderContext(80, 16, load_translator("en"), color=False, ascii=True),
    )
    lines = output.splitlines()
    second_bar = next(line.index("+") for line in lines[2:-2] if "+" in line)
    second_tick = lines[-1].index("10")

    assert second_tick + 1 == second_bar + 1


def test_distribution_renderer_keeps_half_hour_tick_precision() -> None:
    model = replace(_distribution_model(), granularity="half-hour")
    output = render_monitor_distribution(model, context(True))

    assert "09:00" in output and "11:00" in output


def test_distribution_renderer_uses_available_panel_height() -> None:
    output = render_monitor_distribution(
        _distribution_model(),
        RenderContext(80, 20, load_translator("en"), color=False, ascii=True),
    )

    assert len(output.splitlines()) == 20


@pytest.mark.parametrize(
    ("legend", "expected", "missing"),
    [
        ("below-title", "Alpha", "Alpha 60"),
        ("inside", "Alpha", "Alpha 60"),
        ("values", "Alpha 60", "not observed"),
        ("hidden", "", "Alpha"),
    ],
)
def test_distribution_renderer_honors_every_monitor_legend_mode(
    legend: str, expected: str, missing: str
) -> None:
    output = render_monitor_distribution(
        _distribution_model(),
        RenderContext(
            80, 16, load_translator("en"), color=False, ascii=True, legend_position=legend
        ),
    )

    assert expected in output
    if missing:
        assert missing not in output


def test_distribution_renderer_ascii_no_color_is_safe_and_width_bounded() -> None:
    output = render_monitor_distribution(
        _distribution_model(),
        RenderContext(40, 16, load_translator("en"), color=False, ascii=True),
    )

    assert "\x1b[" not in output
    assert all(display_width(line) <= 40 for line in output.splitlines())
    assert "▒" not in output and "░" not in output and "█" not in output


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

    assert "Grouped composition · 2026-01-01–2026-01-01" in output
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
    rows = lines[2:]
    assert rows[0].count("●") > 1
    assert rows[1].count("●") > 1
    assert "·" in rows[1]


def test_historical_ranking_search_filters_casefolded_fields_and_reports_visible_count() -> None:
    context = RenderContext(
        80, 20, load_translator("en"), color=False, style="dot", density="normal"
    )
    entries = (
        RankingPresentationEntry("a", "Alpha", 12),
        RankingPresentationEntry("b", "Claude worker", 8, description="Release validation"),
    )
    output = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=context,
        search_query="claude",
        show_visible_count=True,
    )
    assert "Search: claude" in output
    assert "Showing 1/2 item(s)" in output
    assert "Alpha" not in output
    assert any(line.lstrip().startswith("2 ") for line in output.splitlines())

    description = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
        search_query="VALIDATION",
        show_visible_count=True,
    )
    assert "Claude worker" in description
    assert "Release validation" in description

    empty = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=context,
        search_query="missing",
        show_visible_count=True,
    )
    assert 'No ranking entries match "missing".' in empty

    minimal = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=replace(context, density="minimal"),
        show_visible_count=True,
    )
    assert "Showing" not in minimal


def test_historical_ranking_descriptions_are_muted_wrapped_and_density_aware() -> None:
    context = RenderContext(36, 24, load_translator("en"), color=False, style="dot")
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "api",
                "API",
                10,
                description="Release validation and regression testing account for most activity.",
            ),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
    )

    rows = output.splitlines()
    description_rows = rows[-2:]
    assert len(description_rows) == 2
    assert all(row.startswith(" " * 7) for row in description_rows)
    assert all(display_width(row) <= context.width for row in description_rows)
    assert description_rows[-1].endswith("…")

    minimal = render_historical_ranking(
        (RankingPresentationEntry("api", "API", 10, description="Release validation"),),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, density="minimal"),
        descriptions_visible=True,
    )
    assert "Release validation" not in minimal


def test_historical_ranking_wraps_plain_description_before_styling() -> None:
    context = RenderContext(
        50, 24, load_translator("en"), color=True, style="dot", density="detailed"
    )
    description = "The remarkable Paper Pro drinks your ink and answers in a flowing hand"
    output = render_historical_ranking(
        (RankingPresentationEntry("paper-pro", "Paper Pro", 10, description=description),),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
    )

    rows = [row for row in output.splitlines() if "remarkable" in row or "flowing" in row]
    assert len(rows) == 2
    assert all(display_width(row) <= context.width for row in rows)
    assert all("\x1b" in row for row in rows)


def test_historical_ranking_description_links_are_clickable_and_searchable() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="Read [release notes](https://example.com/openai/release) now.",
    )
    escaped_link = "\x1b]8;;https://example.com/openai/release\x1b\\"

    plain = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )
    assert "release notes" in strip_ansi(plain)
    assert "https://example.com/openai/release" not in strip_ansi(plain)
    assert plain.count(escaped_link) == 2
    assert all(display_width(row) <= context.width for row in plain.splitlines())

    linked = render_historical_ranking(
        (entry,),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, color=True),
        descriptions_visible=True,
    )
    assert "\x1b[38;5;245m\x1b[2;4mrelease notes\x1b[0m" in linked
    assert "release notes ↗" in strip_ansi(linked)

    label_match = render_historical_ranking(
        (entry,),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, color=True),
        descriptions_visible=True,
        search_query="notes",
    )
    assert "\x1b]8;;https://example.com/openai/release\x1b\\" in label_match
    assert "\x1b]8;;\x1b\\" in label_match
    assert "\x1b[38;5;245m\x1b[2;4mrelease notes\x1b[0m" in label_match
    assert "release notes ↗" in strip_ansi(label_match)

    target_match = render_historical_ranking(
        (entry,),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, color=True),
        descriptions_visible=True,
        search_query="openai",
    )
    assert "release notes ↗" in strip_ansi(target_match)
    assert target_match.count(escaped_link) == 2


def test_historical_ranking_description_links_reject_unsafe_markup_and_controls() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="[local](file:///secret) [broken](https://) \x1b[2Jsafe",
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    assert "[local](file:///secret) [broken](https://) safe" in strip_ansi(output)
    assert "\x1b]8;;" not in output
    assert "\x1b[2J" not in output


def test_historical_ranking_description_supports_star_emphasis_only() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=True, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description=(
            "Use **important steps** and *carefully review* "
            "[*release notes*](https://example.com/release)."
        ),
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    visible = strip_ansi(output)
    assert "Use important steps and carefully review release notes ↗." in visible
    assert "**" not in visible and "*release notes*" not in visible
    assert "\x1b[2;1mimportant steps\x1b[0m" in output
    assert "\x1b[2;3mcarefully review\x1b[0m" in output
    assert "\x1b[4;2;3mrelease notes\x1b[0m" in output
    assert output.count("\x1b]8;;https://example.com/release\x1b\\") == 2
    assert all(display_width(row) <= context.width for row in output.splitlines())


def test_historical_ranking_description_keeps_unsupported_star_markup_literal() -> None:
    context = RenderContext(100, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="__underlined__ **nested *stars*** * unclosed ** ** **",
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    assert "__underlined__ **nested *stars*** * unclosed ** ** **" in strip_ansi(output)


def test_historical_ranking_project_link_follows_the_copy_marker() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    linked = RankingPresentationEntry(
        "api",
        "API",
        10,
        copy_marker="⊞",
        project_link="https://example.com/projects/api",
    )
    output = render_historical_ranking(
        (linked,), heading="Ranking", value_formatter=str, context=context
    )

    assert "API | ⊞ · →" in strip_ansi(output)
    assert output.count("\x1b]8;;https://example.com/projects/api\x1b\\") == 1
    assert all(display_width(row) <= context.width for row in output.splitlines())


@pytest.mark.parametrize("style", ("dot", "dots", "bars"))
def test_historical_ranking_aligns_tracks_and_right_value_column(style: str) -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style=style)
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "A", 10),
            RankingPresentationEntry("b", "A much longer project name", 5, display="five units"),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        summary="Today Units 15",
    )
    summary, heading, header, *rows = output.splitlines()

    track_marks = {"dot": ("●", "·"), "dots": ("●", "·"), "bars": ("█", "░")}[style]
    track_starts = [min(row.index(mark) for mark in track_marks if mark in row) for row in rows]
    assert summary == "Today Units 15"
    assert heading.strip() == "Ranking"
    assert "Current" in header
    assert "vs prior" in header
    assert len(heading) - len(heading.lstrip()) == (context.width - display_width("Ranking")) // 2
    assert track_starts[0] == track_starts[1]
    assert "10" in rows[0] and "—" in rows[0] and rows[0].endswith("66.7%")
    assert "five units" in rows[1] and "—" in rows[1] and rows[1].endswith("33.3%")


def test_historical_ranking_deemphasizes_fixed_project_buckets_like_other() -> None:
    scheme = get_color_scheme("classic")
    model = RankingModel(
        (
            RankingEntry(("project", "real"), "real-project", usage(100)),
            RankingEntry(("project", "fixed", "unassigned"), "Unassigned", usage(50)),
            RankingEntry(("other",), "Other", usage(25), is_other=True),
        ),
        period(),
    )

    output = render_ranking(
        model, RenderContext(80, 24, load_translator("en"), color=True, style="dot")
    )

    rows = output.splitlines()[2:]
    assert f"\x1b[38;5;{scheme.highlight}m●" in rows[0]
    assert f"\x1b[38;5;{scheme.other}m●" in rows[1]
    assert f"\x1b[38;5;{scheme.other}m●" in rows[2]


def test_historical_ranking_list_keeps_label_and_value_columns_aligned() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="list")
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "A", 10),
            RankingPresentationEntry("b", "A much longer project name", 5, display="five units"),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        summary="Today Units 15",
    )
    summary, heading, header, *rows = output.splitlines()

    assert summary == "Today Units 15"
    assert heading.strip() == "Ranking"
    assert "Current" in header
    assert "Scale" not in header
    project_start = header.index("Project")
    current_start = header.index("Current")
    assert rows[0].index("A") == project_start
    assert rows[0].index("10") + len("10") == current_start + len("Current")
    assert "A" in rows[0]
    assert "A much longer" in rows[1]
    assert rows[0].endswith("66.7%")
    assert rows[1].endswith("33.3%")
    assert display_width(rows[0]) == display_width(rows[1])


def test_historical_ranking_description_starts_with_its_label_column() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "A", 10, description="First item description."),
            RankingPresentationEntry("b", "Longer label", 5),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
    )
    _heading, _columns, primary, description, *_rest = output.splitlines()

    label_start = primary.index("A")
    assert description.index("First item description.") == label_start


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


def test_timeline_budgets_each_wrapped_summary_row(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(10), usage(20))),),
        summary=summary,
    )
    context = RenderContext(28, 12, load_translator("en"), color=False)
    captured: dict[str, object] = {}
    original = timeline_renderer.render_timeline_plot

    def capture(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(timeline_renderer, "render_timeline_plot", capture)

    output = render_timeline(model, context)

    assert len(render_summary(summary, context).splitlines()) == 3
    assert captured["text_rows"] == 4
    assert len(output.splitlines()) == context.height
    assert "01-01" in output.splitlines()[-1]
    assert "01-02" in output.splitlines()[-1]


def test_timeline_ignores_plotext_ambient_terminal_height_limit() -> None:
    days = tuple(date(2026, 9, 20) + timedelta(days=index) for index in range(14))
    model = TimelineModel(
        days,
        (
            Series(
                "total",
                "Total",
                tuple(usage(100_000 * (index + 1)) for index in range(len(days))),
            ),
        ),
        summary=PeriodSummary(
            "day",
            days[-1],
            1_400_000,
            PercentChange(ChangeDirection.DECREASE, 35.0),
            PercentChange(ChangeDirection.DECREASE, 40.2),
            days[-8],
        ),
    )
    context = RenderContext(
        108,
        25,
        load_translator("zh"),
        color=False,
        style="points",
        density="detailed",
        weekday_mode="show",
        period="14d",
        title_content="总量",
        hide_upper_right_axes=True,
    )

    output = render_timeline(model, context)

    assert len(output.splitlines()) == context.height
    assert days[0].strftime("%m-%d") in output.splitlines()[-1]
    assert days[-2].strftime("%m-%d") in output.splitlines()[-1]


def test_grouped_stack_budgets_each_wrapped_summary_row(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series("input", "input", (usage(10), usage(20))),
            Series("output", "output", (usage(5), usage(10))),
        ),
        summary=summary,
    )
    context = RenderContext(28, 12, load_translator("en"), color=False, style="grouped")
    captured: dict[str, object] = {}
    original = stack_renderer.render_grouped_stack_plot

    def capture(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(stack_renderer, "render_grouped_stack_plot", capture)

    render_stack(model, context)

    assert len(render_summary(summary, context).splitlines()) == 3
    assert captured["text_rows"] == 5


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
    original_limits = tuple(plt.terminal._limit)
    with isolated_plot():
        plt.figure.title("private")
        plt.terminal.limit(False, False)
    assert "private" not in plt.figure.build()
    assert tuple(plt.terminal._limit) == original_limits
