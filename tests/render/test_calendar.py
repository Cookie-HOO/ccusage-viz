




from datetime import date

import pytest

from ccusage_viz.chart_models import CalendarDay, CalendarModel, Series, StackModel
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.calendar import render_calendar
from ccusage_viz.render.stack import render_stack

from .helpers import usage


def test_calendar_and_stack_use_canonical_metric_first_headings() -> None:
    calendar_output = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(1)),)),
        RenderContext(80, 24, load_translator("zh"), color=False, period="1y"),
    )
    stack_output = render_stack(
        StackModel((date(2026, 1, 1),), (Series("input", "input", (usage(1),)),)),
        RenderContext(
            80,
            24,
            load_translator("zh"),
            color=False,
            period="14d",
            title_content="模型",
        ),
    )

    assert "Token · 活跃日历 · 1y" in calendar_output
    assert "Token · 分组构成 · by 模型 · 14d" in stack_output

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
