from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ccusage_viz.chart_models import CalendarModel
from ccusage_viz.formatting import center_text, clip_width, display_width, format_tokens, pad_width
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
    empty_mark = "-" if context.ascii else "·"
    marks = (empty_mark, ".", "o", "O", "#") if context.ascii else (empty_mark, "░", "▒", "▓", "█")
    levels = _positive_levels(list(usage.values()))
    colors = get_color_scheme(context.color_scheme).calendar
    months: list[tuple[int, str]] = []
    labeled_months: set[tuple[int, int]] = set()
    for week in range(week_count):
        week_start = start + timedelta(days=week * 7)
        for weekday in range(7):
            day = week_start + timedelta(days=weekday)
            if first <= day <= last:
                month = (day.year, day.month)
                if month not in labeled_months:
                    months.append((week, context.translator.text(f"calendar.month.{day.month}")))
                    labeled_months.add(month)
                level = levels.get(usage.get(day, 0), 0)
                mark = marks[level]
                if level:
                    mark = colored_mark(mark, colors[level - 1], context)
            else:
                mark = " "
            cells[weekday].append(mark)

    separator = " " * (stride - 1)
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
    lines.append(" " * prefix_width + _month_header(months, week_count=week_count, stride=stride))
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
    legend = " ".join(
        (
            context.translator.text("calendar.legend.less"),
            marks[0],
            *(colored_mark(marks[level], colors[level - 1], context) for level in range(1, 5)),
            context.translator.text("calendar.legend.more"),
        )
    )
    lines.extend((activity, " · ".join(usage_stats), legend))
    return "\n".join(
        clip_width(line, context.width) if display_width(line) > context.width else line
        for line in lines
    )
