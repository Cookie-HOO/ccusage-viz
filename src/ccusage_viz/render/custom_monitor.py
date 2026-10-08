"""Surface-neutral rendering for source-owned Dataset Monitor projections."""

from __future__ import annotations

from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.formatting import center_text
from ccusage_viz.render import RenderContext
from ccusage_viz.render.monitor_distribution import render_monitor_distribution
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.timeline import render_timeline


def _replace_heading(rendered: str, heading: str, context: RenderContext) -> str:
    """Keep native chart geometry while replacing its token-specific Monitor title."""

    if not rendered:
        return heading
    first, *rest = rendered.splitlines()
    return "\n".join((center_text(heading, context.width), *rest))


def render_custom_monitor(component: CustomMonitorComponent, context: RenderContext) -> str:
    """Render Dataset facts with native Monitor charts and a Dataset-owned heading."""

    style = component.candidate.presentation.style
    heading = component.heading(language=context.translator.language)
    if style in {"ranking", "list"}:
        return _replace_heading(
            render_ranking(component.ranking_model(language=context.translator.language), context),
            heading,
            context,
        )
    if style == "cumulative-bars":
        return _replace_heading(
            render_monitor_distribution(
                component.distribution_model(language=context.translator.language), context
            ),
            heading,
            context,
        )
    return _replace_heading(
        render_timeline(component.timeline_model(language=context.translator.language), context),
        heading,
        context,
    )
