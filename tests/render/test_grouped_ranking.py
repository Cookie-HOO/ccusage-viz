import re
from dataclasses import replace
from decimal import Decimal

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.processing.custom_historical import (
    CustomProjectedRankingGroup,
    CustomProjectedSeries,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_projection

from .helpers import _grouped_ranking_projection


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

    assert "Router · Ranking · by Logical Model → Real Model · 2026-10-01–2026-10-14" in output
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


def test_grouped_custom_ranking_sanitizes_scalar_metadata_and_keeps_trusted_group_link() -> None:
    controls = "\x1b[2J\x1b]52;c;YXR0YWNr\x07"
    groups = (
        CustomProjectedRankingGroup(
            "unsafe-group",
            LocalizedText(f"Group {controls}visible", "组"),
            (
                CustomProjectedSeries(
                    "unsafe-entry",
                    LocalizedText("Entry", "项"),
                    (Decimal("9"),),
                    previous_total=Decimal("4"),
                    comparison_ready=True,
                    display=LocalizedText(f"Entry {controls}display", "值"),
                    comparison_display=LocalizedText(f"Delta {controls}display", "差"),
                    rank=1,
                ),
            ),
            Decimal("9"),
            Decimal("4"),
            True,
            Decimal("9"),
            display=LocalizedText(f"Group {controls}display", "值"),
            comparison_display=LocalizedText(f"Group delta {controls}display", "差"),
            link="https://example.com/groups/safe",
        ),
    )
    output = render_custom_projection(
        _grouped_ranking_projection(groups=groups),
        RenderContext(100, 20, load_translator("en"), color=True, ascii=True, density="detailed"),
    )

    assert "\x1b[2J" not in output
    assert "\x1b]52;" not in output
    assert "Group visible" in strip_ansi(output)
    assert "Entry display" in strip_ansi(output)
    assert "Delta display" in strip_ansi(output)
    assert "\x1b]8;;https://example.com/groups/safe\x1b\\" in output


def test_grouped_custom_ranking_bounds_adversarial_scalar_columns() -> None:
    huge = "界" * 100
    groups = (
        CustomProjectedRankingGroup(
            "huge",
            LocalizedText("Huge", "大"),
            (
                CustomProjectedSeries(
                    "huge-entry",
                    LocalizedText("Entry", "项"),
                    (Decimal("100"),),
                    previous_total=Decimal("1"),
                    comparison_ready=True,
                    display=LocalizedText(huge, huge),
                    comparison_display=LocalizedText(huge, huge),
                    rank=1,
                ),
            ),
            Decimal("100"),
            Decimal("1"),
            True,
            Decimal("100"),
            display=LocalizedText(huge, huge),
            comparison_display=LocalizedText(huge, huge),
        ),
    )
    context = RenderContext(
        58, 20, load_translator("en"), color=False, ascii=True, density="detailed"
    )
    output = render_custom_projection(_grouped_ranking_projection(groups=groups), context)

    assert all(display_width(line) <= context.width for line in output.splitlines())
    assert any("…" in line for line in output.splitlines())


def test_flat_custom_ranking_bounds_adversarial_scalar_columns() -> None:
    huge = "X" * 200
    projection = _grouped_ranking_projection()
    entry = CustomProjectedSeries(
        "huge-entry",
        LocalizedText("Entry", "项"),
        (Decimal("100"),),
        previous_total=Decimal("1"),
        comparison_ready=True,
        display=LocalizedText(huge, huge),
        comparison_display=LocalizedText(huge, huge),
    )
    context = RenderContext(
        58, 20, load_translator("en"), color=False, ascii=True, density="detailed"
    )
    output = render_custom_projection(replace(projection, series=(entry,), groups=None), context)

    assert all(display_width(line) <= context.width for line in output.splitlines())


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
            (
                CustomProjectedSeries(
                    "item", LocalizedText("Item", "项目"), (Decimal("7"),), rank=1
                ),
            ),
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
