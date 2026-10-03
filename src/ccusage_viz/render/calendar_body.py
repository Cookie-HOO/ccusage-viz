"""Domain-neutral calendar grid primitives for historical presentations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal

from ccusage_viz.formatting import display_width, pad_width
from ccusage_viz.render.base import RenderContext, background_mark
from ccusage_viz.render.palette import get_color_scheme

CalendarNumber = int | Decimal


def positive_levels(values: list[CalendarNumber]) -> dict[CalendarNumber, int]:
    """Assign positive values to four nearest-rank quantile buckets."""
    positive = sorted(value for value in values if value > 0)
    if not positive:
        return {}
    thresholds = [positive[(len(positive) * quantile - 1) // 4] for quantile in range(1, 5)]
    return {
        value: next(
            level for level, threshold in enumerate(thresholds, start=1) if value <= threshold
        )
        for value in set(positive)
    }


def month_header(
    months: list[tuple[int, str]], *, week_count: int, stride: int, gap_width: int
) -> str:
    grid_width = week_count * stride - gap_width
    last_week, last_label = months[-1]
    width = max(grid_width, last_week * stride + display_width(last_label))
    canvas = [" "] * width
    for month_index, (week, label) in enumerate(months):
        position = week * stride
        next_position = (
            months[month_index + 1][0] * stride if month_index + 1 < len(months) else width
        )
        for character in label:
            character_width = display_width(character)
            if position + character_width > next_position:
                break
            canvas[position] = character
            for offset in range(1, character_width):
                canvas[position + offset] = ""
            position += character_width
    return "".join(canvas).rstrip()


def cell_geometry(week_count: int, context: RenderContext) -> tuple[int, int]:
    """Return square-cell or vertical-bar geometry for the selected style."""
    if context.style != "grid":
        return 1, 0
    available_width = max(1, context.width - 3)
    if week_count * 3 - 1 <= available_width:
        return 2, 1
    if week_count * 2 - 1 <= available_width:
        return 1, 1
    return 1, 0


def fallback_marks(context: RenderContext) -> tuple[str, str, str, str, str]:
    if context.ascii:
        return "-", ".", "o", "O", "#"
    return "·", "░", "▒", "▓", "█"


def render_calendar_grid(
    days: tuple[date, ...],
    values: Mapping[date, CalendarNumber],
    context: RenderContext,
) -> tuple[str, ...]:
    """Render calendar geometry from domain-neutral daily values."""
    first, last = days[0], days[-1]
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    week_count = (end - start).days // 7 + 1
    cell_width, gap_width = cell_geometry(week_count, context)
    stride = cell_width + gap_width
    cells: dict[int, list[str]] = defaultdict(list)
    marks = fallback_marks(context)
    levels = positive_levels(list(values.values()))
    scheme = get_color_scheme(context.color_scheme)
    months: list[tuple[int, str]] = []
    labeled_months: set[tuple[int, int]] = set()

    def fill(mark: str) -> str:
        return mark.ljust(cell_width)

    def cell(level: int, *, valid: bool) -> str:
        if not valid:
            return " " * cell_width
        if context.color:
            return (
                background_mark(" " * cell_width, scheme.calendar[level - 1], context)
                if level
                else " " * cell_width
            )
        return fill(marks[level]) if level else " " * cell_width

    for week in range(week_count):
        week_start = start + timedelta(days=week * 7)
        for weekday in range(7):
            day = week_start + timedelta(days=weekday)
            valid = first <= day <= last
            if valid:
                month = (day.year, day.month)
                if month not in labeled_months:
                    months.append((week, context.translator.text(f"calendar.month.{day.month}")))
                    labeled_months.add(month)
            cells[weekday].append(cell(levels.get(values.get(day, 0), 0), valid=valid))

    separator = " " * gap_width
    lines = [
        " " * 3 + month_header(months, week_count=week_count, stride=stride, gap_width=gap_width)
    ]
    for weekday in range(7):
        label = (
            context.translator.text(f"calendar.weekday.{weekday}") if weekday in {0, 2, 4} else ""
        )
        lines.append(pad_width(label, 2, align="right") + " " + separator.join(cells[weekday]))
    return tuple(lines)
