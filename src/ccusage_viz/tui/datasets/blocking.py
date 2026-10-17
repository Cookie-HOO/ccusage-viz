from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import AdjustmentTimeout
from ccusage_viz.options import CustomChartConfig, CustomChartPaneConfig
from ccusage_viz.terminal import Terminal, compose_frame
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.tui.datasets.chooser import _choose_dataset_pane_config, _choose_pane_type
from ccusage_viz.tui.header import _header_lines


def show_chooser_help(session: TuiSession, action: str, selected: str) -> None:
    from ccusage_viz.tui.help import close_help, open_help, process_help_event
    from ccusage_viz.tui.input import raise_if_interrupt, read_adjustment_event

    open_help(session, context="chooser", action=action, selected=selected)
    while session.help_overlay is not None:
        try:
            event = raise_if_interrupt(session, read_adjustment_event(session, session.decoder))
        except AdjustmentTimeout:
            close_help(session)
            return
        process_help_event(session, event)


def choose_pane_type_blocking(
    session: TuiSession, action: str, pane_index: int, *, initial: CustomChartConfig | None = None
) -> CustomChartPaneConfig | str | None:
    from ccusage_viz.tui.input import raise_if_interrupt, read_adjustment_event
    from ccusage_viz.tui.painting import grid_geometry, paint

    def chooser_height() -> int:
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                session.header,
                session.header_style,
                session.translator,
                Terminal(
                    size.columns,
                    4,
                    session.dashboard_theme != "no-color",
                    session.options.host.ascii,
                ),
                session.last_successful_update,
            )
        )
        layout = grid_geometry(session, size.columns, size.lines, header_rows, 0)
        cell_height = layout.pane(pane_index).height
        framed = session.frame_style != "none" or pane_index == session.focused
        return max(1, cell_height - 2 if framed else cell_height)

    def paint_choices(
        choices: str, title: str, chooser_controls: str, chooser_notices: tuple[str, ...]
    ) -> None:
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                session.header,
                session.header_style,
                session.translator,
                Terminal(
                    size.columns,
                    4,
                    session.dashboard_theme != "no-color",
                    session.options.host.ascii,
                ),
                session.last_successful_update,
            )
        )
        layout = grid_geometry(session, size.columns, size.lines, header_rows, 0)
        cell_height = layout.pane(pane_index).height
        framed = session.frame_style != "none" or pane_index == session.focused
        interior_height = max(1, cell_height - 2 if framed else cell_height)
        formatted_notices = format_notice_lines(
            chooser_notices,
            width=size.columns,
            color=session.dashboard_theme != "no-color",
            ascii=session.options.host.ascii,
            translator=session.translator,
            color_scheme=session.dashboard_theme,
        )
        chooser_frame = compose_frame(
            choices, title, chooser_controls, formatted_notices, height=interior_height
        )
        session.chooser_overlay = (pane_index, "\n".join(chooser_frame.rows))
        paint(session)

    try:
        choice = _choose_pane_type(
            session.screen,
            session.translator,
            session.decoder,
            height=chooser_height(),
            action=action,
            paint_choices=paint_choices,
            read_input=lambda: raise_if_interrupt(
                session, read_adjustment_event(session, session.decoder)
            ),
            on_help=lambda selected: show_chooser_help(session, action, selected),
        )
        if choice != "datasets":
            return choice
        return _choose_dataset_pane_config(
            session.screen,
            session.translator,
            session.decoder,
            height=chooser_height(),
            dashboard=session.options,
            initial=initial,
            paint_choices=paint_choices,
            read_input=lambda: raise_if_interrupt(
                session, read_adjustment_event(session, session.decoder)
            ),
        )
    finally:
        session.chooser_overlay = None
