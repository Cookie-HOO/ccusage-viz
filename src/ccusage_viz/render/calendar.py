from __future__ import annotations

from datetime import timedelta

from ccusage_viz.chart_models import CalendarModel
from ccusage_viz.formatting import center_text, clip_width, display_width, format_tokens
from ccusage_viz.render.base import RenderContext, date_range_heading
from ccusage_viz.render.calendar_body import (
    cell_geometry as _cell_geometry,
)
from ccusage_viz.render.calendar_body import (
    fallback_marks as _fallback_marks,
)
from ccusage_viz.render.calendar_body import (
    render_calendar_grid,
)
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_summary


def render_calendar(model: CalendarModel, context: RenderContext) -> str:
    if not model.days:
        return context.translator.text("message.no_data")
    usage = {item.day: item.usage.total for item in model.days}
    first, last = model.days[0].day, model.days[-1].day
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
    lines.extend(render_calendar_grid(tuple(usage), usage, context))

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

    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    week_count = (end - start).days // 7 + 1
    cell_width, _ = _cell_geometry(week_count, context)
    scheme = get_color_scheme(context.color_scheme)
    fallback_marks = _fallback_marks(context)

    def legend_cell(level: int) -> str:
        from ccusage_viz.render.base import background_mark

        if context.color:
            return background_mark(" " * cell_width, scheme.calendar[level - 1], context)
        return fallback_marks[level]

    legend = " ".join(
        (
            context.translator.text("calendar.legend.less"),
            *(legend_cell(level) for level in (1, 2, 3, 4)),
            context.translator.text("calendar.legend.more"),
        )
    )
    lines.extend((activity, " · ".join(usage_stats), legend))
    return "\n".join(
        clip_width(line, context.width) if display_width(line) > context.width else line
        for line in lines
    )
