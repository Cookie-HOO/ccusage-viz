from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

from ccusage_viz.animation import default_animation_spec
from ccusage_viz.options import (
    AnimationPaneConfig,
    CustomChartPaneConfig,
    EmptyPaneConfig,
    PaneConfig,
)
from ccusage_viz.tui.models import TuiPane
from ccusage_viz.tui.pane_lifecycle import _new_pane, _new_pane_options


def allocate_pane_id(session: TuiSession) -> int:
    pane_id = session.next_pane_id
    session.next_pane_id += 1
    return pane_id

def create_pane(session: TuiSession, command: PaneConfig | str, *, pane_id: int | None=None) -> TuiPane:
    pane_id = allocate_pane_id(session) if pane_id is None else pane_id
    if isinstance(command, CustomChartPaneConfig):
        pane = _new_pane(session.options, command, f'dashboard:pane:{pane_id}', session.runtime)
    elif command == 'empty':
        pane = _new_pane(session.options, EmptyPaneConfig())
    elif command == 'animate':
        pane = _new_pane(session.options, AnimationPaneConfig(default_animation_spec('pane')))
    else:
        assert isinstance(command, str)
        pane = _new_pane(_new_pane_options(command, session.options), f'dashboard:pane:{pane_id}', session.runtime)
    pane.pane_id = pane_id
    return pane
