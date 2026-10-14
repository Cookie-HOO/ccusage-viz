"""Surface-neutral rendering for source-owned Dataset Monitor projections."""

from __future__ import annotations

from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.formatting import center_text
from ccusage_viz.options import is_monitor_ranking_style
from ccusage_viz.render import RenderContext
from ccusage_viz.render.headings import (
    HeadingSpec,
    compose_heading,
    duration_label,
    heading_with_querying,
    monitor_view_name,
)
from ccusage_viz.render.monitor_distribution import render_monitor_distribution
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.timeline import render_timeline


def _replace_heading(rendered: str, heading: str) -> str:
    """Keep native chart geometry while replacing its token-specific Monitor title."""

    if not rendered:
        return heading
    first, *rest = rendered.splitlines()
    return "\n".join((heading, *rest))


def render_custom_monitor_heading(
    component: CustomMonitorComponent, context: RenderContext
) -> str:
    """Render the canonical, width-safe heading for any Custom Monitor state."""

    config = component.accepted_config or component.candidate
    metadata = component.heading_metadata(language=context.translator.language)
    heading = heading_with_querying(
        compose_heading(
            HeadingSpec(
                metric=metadata.metric,
                chart=monitor_view_name(config.presentation.style, context.translator),
                dimension=metadata.dimension,
                period=duration_label(metadata.window_seconds),
                window=True,
                status=metadata.status,
            ),
            context,
        ),
        context,
    )
    return center_text(heading, context.width)


def render_custom_monitor(component: CustomMonitorComponent, context: RenderContext) -> str:
    """Render Dataset facts with native Monitor charts and a Dataset-owned heading."""

    config = component.accepted_config or component.candidate
    style = config.presentation.style
    heading = render_custom_monitor_heading(component, context)
    if is_monitor_ranking_style(style):
        return _replace_heading(
            render_ranking(component.ranking_model(language=context.translator.language), context),
            heading,
        )
    if style == "cumulative-bars":
        return _replace_heading(
            render_monitor_distribution(
                component.distribution_model(language=context.translator.language), context
            ),
            heading,
        )
    return _replace_heading(
        render_timeline(component.timeline_model(language=context.translator.language), context),
        heading,
    )
