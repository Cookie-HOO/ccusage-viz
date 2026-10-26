from __future__ import annotations

from dataclasses import replace

from ccusage_viz.dashboard_state import DashboardPaneState, DashboardState
from ccusage_viz.options import EmptyPaneConfig


def test_dashboard_state_is_immutable_declarative_value() -> None:
    pane = DashboardPaneState(pane_id=7, config=EmptyPaneConfig(), body_view="chart")
    state = DashboardState(
        panes=(pane,),
        columns=1,
        spotlight=0,
        column_weights=None,
        row_weights=None,
        theme="classic",
        style="split",
        header_style="panel",
        header_summary="day",
        body_view="chart",
    )

    assert replace(state, theme="mono").theme == "mono"
    assert state.panes[0].pane_id == 7
