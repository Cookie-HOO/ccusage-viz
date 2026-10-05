from __future__ import annotations

from ccusage_viz.chart_models import CalendarModel
from ccusage_viz.formatting import center_text, clip_width, display_width, format_tokens
from ccusage_viz.render.base import RenderContext, date_range_heading
from ccusage_viz.render.calendar_body import render_calendar_footer, render_calendar_grid
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

    lines.extend(
        render_calendar_footer(
            tuple(usage),
            usage,
            context,
            value_formatter=lambda value: format_tokens(round(value)),
        )
    )
    return "\n".join(
        clip_width(line, context.width) if display_width(line) > context.width else line
        for line in lines
    )
