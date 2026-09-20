from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ccusage_viz.chart_models import CalendarModel
from ccusage_viz.formatting import center_text, clip_width, display_width, format_tokens, pad_width
from ccusage_viz.render.base import RenderContext, background_mark, date_range_heading
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary


def _positive_levels(values: list[int]) -> dict[int, int]:
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


def _month_header(
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


def _cell_geometry(week_count: int, context: RenderContext) -> tuple[int, int]:
    """Return square-cell or vertical-bar geometry for the selected style."""
    if context.style != "grid":
        return 1, 0
    available_width = max(1, context.width - 3)
    if week_count * 3 - 1 <= available_width:
        return 2, 1
    if week_count * 2 - 1 <= available_width:
        return 1, 1
    return 1, 0


def _fallback_marks(context: RenderContext) -> tuple[str, str, str, str, str]:
    if context.ascii:
        return "-", ".", "o", "O", "#"
    return "·", "░", "▒", "▓", "█"


def render_calendar(model: CalendarModel, context: RenderContext) -> str:
    if not model.days:
        return context.translator.text("message.no_data")
    usage = {item.day: item.usage.total for item in model.days}
    first, last = model.days[0].day, model.days[-1].day
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    week_count = (end - start).days // 7 + 1
    cell_width, gap_width = _cell_geometry(week_count, context)
    stride = cell_width + gap_width
    cells: dict[int, list[str]] = defaultdict(list)
    fallback_marks = _fallback_marks(context)
    levels = _positive_levels(list(usage.values()))
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
        return fill(fallback_marks[level]) if level else " " * cell_width

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
            cells[weekday].append(cell(levels.get(usage.get(day, 0), 0), valid=valid))

    separator = " " * gap_width
    lines = []
    summary = render_summary(model.summary, context) if model.summary else ""
    if summary:
        lines.append(summary)
    lines.append(
        center_text(
            date_range_heading(context.translator.text("label.calendar"), first, last, context),
            context.width,
        )
    )
    label_width = 2
    prefix_width = label_width + 1
    lines.append(
        " " * prefix_width
        + _month_header(months, week_count=week_count, stride=stride, gap_width=gap_width)
    )
    for weekday in range(7):
        weekday_name = (
            context.translator.text(f"calendar.weekday.{weekday}") if weekday in {0, 2, 4} else ""
        )
        lines.append(
            pad_width(weekday_name, label_width, align="right")
            + " "
            + separator.join(cells[weekday])
        )

    peak = model.peak
    activity = " · ".join(
        (
            context.translator.text("label.active_days", count=model.active_days),
            context.translator.text("label.current_streak", count=model.current_streak),
            context.translator.text("label.longest_streak", count=model.longest_streak),
        )
    )
    usage_stats = [
        context.translator.text("label.average", value=format_tokens(round(model.average)))
    ]
    if peak:
        usage_stats.append(
            context.translator.text(
                "label.peak", date=peak.day.isoformat(), value=format_tokens(peak.usage.total)
            )
        )

    def legend_cell(level: int) -> str:
        if context.color:
            return background_mark(" " * cell_width, scheme.calendar[level - 1], context)
        return fallback_marks[level]

    legend_cells = (1, 2, 3, 4)
    legend = " ".join(
        (
            context.translator.text("calendar.legend.less"),
            *(legend_cell(level) for level in legend_cells),
            context.translator.text("calendar.legend.more"),
        )
    )
    lines.extend((activity, " · ".join(usage_stats), legend))
    return "\n".join(
        clip_width(line, context.width) if display_width(line) > context.width else line
        for line in lines
    )
