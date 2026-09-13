from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ccusage_viz.chart_models import CalendarModel
from ccusage_viz.formatting import center_text, clip_width, display_width, format_tokens
from ccusage_viz.render.base import RenderContext, colored_mark, date_range_heading
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


_ABSOLUTE_THRESHOLDS = (1_000, 10_000, 100_000, 1_000_000)


def _absolute_levels(values: list[int]) -> dict[int, int]:
    return {
        value: next(
            (
                level
                for level, threshold in enumerate(_ABSOLUTE_THRESHOLDS, start=1)
                if value <= threshold
            ),
            4,
        )
        for value in set(values)
        if value > 0
    }


def _month_header(months: list[tuple[int, str]], *, week_count: int, stride: int) -> str:
    grid_width = week_count * stride - (stride - 1)
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


def render_calendar(model: CalendarModel, context: RenderContext) -> str:
    if not model.days:
        return context.translator.text("message.no_data")
    usage = {item.day: item.usage.total for item in model.days}
    first, last = model.days[0].day, model.days[-1].day
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    week_count = (end - start).days // 7 + 1
    # Prefer separated cells, but a full year still fits at the minimum width
    # by falling back to one terminal cell per week.
    stride = 2 if 3 + week_count * 2 - 1 <= context.width else 1
    cells: dict[int, list[str]] = defaultdict(list)
    marks = (" ", "░", "▒", "▓", "█") if not context.ascii else (" ", ".", "o", "O", "#")
    levels = (
        _absolute_levels(list(usage.values()))
        if context.style == "absolute"
        else _positive_levels(list(usage.values()))
    )
    colors = get_color_scheme(context.color_scheme).calendar
    months: list[tuple[int, str]] = []
    previous_month = None
    for week in range(week_count):
        week_start = start + timedelta(days=week * 7)
        label_month = first.month if week == 0 else week_start.month
        if label_month != previous_month:
            months.append((week, context.translator.text(f"calendar.month.{label_month}")))
            previous_month = label_month
        for weekday in range(7):
            day = week_start + timedelta(days=weekday)
            if first <= day <= last:
                level = levels.get(usage.get(day, 0), 0)
                mark = marks[level]
                if level:
                    mark = colored_mark(mark, colors[level - 1], context)
            else:
                mark = " "
            cells[weekday].append(mark)

    separator = " " * (stride - 1)
    lines = [
        center_text(
            date_range_heading(context.translator.text("label.calendar"), first, last, context),
            context.width,
        )
    ]
    if model.summary:
        lines.append(render_summary(model.summary, context))
    lines.append("   " + _month_header(months, week_count=week_count, stride=stride))
    for weekday in range(7):
        weekday_name = context.translator.text(f"calendar.weekday.{weekday}")
        lines.append(f"{weekday_name:>2} " + separator.join(cells[weekday]))

    peak = model.peak
    stats = [
        context.translator.text("label.active_days", count=model.active_days),
        context.translator.text("label.current_streak", count=model.current_streak),
        context.translator.text("label.longest_streak", count=model.longest_streak),
        context.translator.text("label.average", value=format_tokens(round(model.average))),
    ]
    if peak:
        stats.append(
            context.translator.text(
                "label.peak", date=peak.day.isoformat(), value=format_tokens(peak.usage.total)
            )
        )
    legend_labels = (
        ("≤1K", "≤10K", "≤100K", ">100K") if context.style == "absolute" else ("1", "2", "3", "4")
    )
    legend = " ".join(
        f"{colored_mark(marks[level], colors[level - 1], context)}{legend_labels[level - 1]}"
        for level in range(1, 5)
    )
    lines.extend((" · ".join(stats), legend))
    return "\n".join(
        clip_width(line, context.width) if display_width(line) > context.width else line
        for line in lines
    )
