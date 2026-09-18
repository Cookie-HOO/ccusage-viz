from __future__ import annotations

from ccusage_viz.options import CommandOptions


def parse_dashboard_pane(
    fragment: str,
    *,
    host: CommandOptions,
) -> CommandOptions:
    """Parse one Dashboard-owned Pane payload into effective chart options."""
    from ccusage_viz.cli import parse_pane_fragment

    return parse_pane_fragment(
        fragment,
        base=host,
        refresh_interval=host.refresh_interval,
        sampling_interval=host.sampling_interval,
    )
