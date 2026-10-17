from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time
import webbrowser
from shutil import get_terminal_size
from typing import cast

from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer
from ccusage_viz.command_copy import copy_command
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.dashboard_layout import pane_at as layout_pane_at
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.render.grouped_ranking_viewport import GroupedIdentity
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.custom_rendering import (
    _custom_ranking_clipboard_all_text,
    _custom_ranking_clipboard_text,
    _custom_ranking_copyable_entries,
)
from ccusage_viz.tui.header import _header_lines
from ccusage_viz.tui.models import _DOUBLE_CLICK_SECONDS, TuiCustomPane
from ccusage_viz.tui_input import MouseEvent, WheelEvent


def handle_ranking_wheel(session: TuiSession, event: WheelEvent) -> None:
    if (
        session.displayed_layout is None
        or session.body_view != "chart"
        or session.help_overlay is not None
        or (session.preset_manager is not None)
        or (session.dataset_modal is not None)
        or (session.chooser_overlay is not None)
        or (session.overlay_editor is not None)
        or (session.overlay_history is not None)
        or (session.custom_logs_pane is not None)
    ):
        return
    selected = layout_pane_at(
        session.displayed_layout, event.x - 1, event.y - session.displayed_header_rows - 1
    )
    if selected is None:
        return
    pane = session.panes[selected]
    if (
        isinstance(pane, TuiCustomPane)
        and isinstance(pane.component, CustomHistoricalComponent)
        and ((pane.component.accepted_config or pane.component.candidate).kind == "ranking")
        and (pane.body_view == "chart")
        and pane.active_ranking_viewport.active
    ):
        pane.active_ranking_viewport.scroll(event.delta)


def handle_scrollbar_hover(session: TuiSession, event: MouseEvent) -> bool:
    """Track whether unpressed pointer motion is inside a Ranking scrollbar."""
    blocked = (
        session.body_view != "chart"
        or session.displayed_layout is None
        or session.help_overlay is not None
        or (session.preset_manager is not None)
        or (session.dataset_modal is not None)
        or (session.chooser_overlay is not None)
        or (session.overlay_editor is not None)
        or (session.overlay_history is not None)
        or (session.custom_logs_pane is not None)
    )
    hovered: int | None = None
    if not blocked and (not event.pressed):
        assert session.displayed_layout is not None
        grid_x = event.x - 1
        grid_y = event.y - session.displayed_header_rows - 1
        selected = layout_pane_at(session.displayed_layout, grid_x, grid_y)
        if selected is not None:
            pane = session.panes[selected]
            viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
            if viewport is not None and viewport.active and (viewport.scrollbar is not None):
                rect = session.displayed_layout.pane(selected)
                framed = session.frame_style != "none" or selected == session.focused
                interior_column = grid_x - rect.left - int(framed)
                interior_row = grid_y - rect.top - int(framed)
                if viewport.scrollbar.contains(interior_column, interior_row):
                    hovered = selected
    if session.scrollbar_hovered_pane == hovered:
        return False
    session.scrollbar_hovered_pane = hovered
    return True


def handle_scrollbar_drag(session: TuiSession, event: MouseEvent) -> bool:
    """Let a press, drag, or track click on a Ranking scrollbar move its body."""
    blocked = (
        session.body_view != "chart"
        or session.displayed_layout is None
        or session.help_overlay is not None
        or (session.preset_manager is not None)
        or (session.dataset_modal is not None)
        or (session.chooser_overlay is not None)
        or (session.overlay_editor is not None)
        or (session.overlay_history is not None)
        or (session.custom_logs_pane is not None)
    )
    if blocked:
        session.scrollbar_drag = None
        session.scrollbar_hovered_pane = None
        return False
    if not event.pressed:
        released = session.scrollbar_drag is not None
        session.scrollbar_drag = None
        return released
    assert session.displayed_layout is not None
    motion = bool(event.modifiers & 32)
    grid_x = event.x - 1
    grid_y = event.y - session.displayed_header_rows - 1
    if session.scrollbar_drag is not None and (motion or event.button == 0):
        pane_index, grab = session.scrollbar_drag
        pane = session.panes[pane_index]
        viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
        bar = viewport.scrollbar if viewport is not None else None
        if bar is None or viewport is None:
            session.scrollbar_drag = None
            return False
        rect = session.displayed_layout.pane(pane_index)
        framed = session.frame_style != "none" or pane_index == session.focused
        interior_row = grid_y - rect.top - int(framed)
        viewport.offset = bar.offset_at(interior_row, grab)
        viewport.clamp()
        return True
    if motion or event.button != 0:
        return False
    selected = layout_pane_at(session.displayed_layout, grid_x, grid_y)
    if selected is None:
        return False
    pane = session.panes[selected]
    viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
    bar = viewport.scrollbar if viewport is not None else None
    if bar is None or viewport is None or (not viewport.active):
        return False
    rect = session.displayed_layout.pane(selected)
    framed = session.frame_style != "none" or selected == session.focused
    interior_row = grid_y - rect.top - int(framed)
    interior_column = grid_x - rect.left - int(framed)
    if not bar.contains(interior_column, interior_row):
        return False
    session.scrollbar_hovered_pane = selected
    if bar.on_thumb(interior_row):
        session.scrollbar_drag = (selected, bar.grab_at(interior_row))
    else:
        viewport.offset = bar.page_offset(interior_row)
        viewport.clamp()
    return True


def handle_pane_mouse(session: TuiSession, event: MouseEvent) -> bool:
    from ccusage_viz.tui.painting import grid_geometry

    """Handle pane focus clicks before pane-local modal input consumes them."""
    if (
        session.body_view != "chart"
        or not event.pressed
        or event.button != 0
        or event.modifiers & 96
    ):
        return False
    size = get_terminal_size()
    header_rows = len(
        _header_lines(
            session.header,
            session.header_style,
            session.translator,
            Terminal(
                size.columns, 4, session.dashboard_theme != "no-color", session.options.host.ascii
            ),
            session.last_successful_update,
        )
    )
    layout = grid_geometry(session, size.columns, size.lines, header_rows, 0)
    grid_x = event.x - 1
    grid_y = event.y - header_rows - 1
    selected = layout_pane_at(layout, grid_x, grid_y)
    now = time.monotonic()
    double_click = (
        selected is not None
        and session.last_click is not None
        and (session.last_click[0] == selected)
        and (now - session.last_click[1] <= _DOUBLE_CLICK_SECONDS)
    )
    session.last_click = (selected, now) if selected is not None else None
    if selected is not None and isinstance((pane := session.panes[selected]), TuiCustomPane):
        local_row = grid_y - layout.pane(selected).top
        local_column = grid_x - layout.pane(selected).left
        framed = session.frame_style != "none" or selected == session.focused
        if _copy_custom_ranking_all_at(
            session, pane, row=local_row, column=local_column, framed=framed, now=now
        ) or _copy_custom_ranking_entry_at(
            session, pane, row=local_row, column=local_column, framed=framed, now=now
        ):
            return True
    if session.adjustment_mode == "pane":
        if selected != session.focused and double_click and (selected is not None):
            session.overlay_editor = None
            session.overlay_history = None
            session.custom_logs_pane = None
            session.focused = selected
            session.adjustment_page = "quick"
            session.adjustment_timer = AdjustmentIdleTimer()
        return True
    if session.adjustment_mode in {None, "global"} and double_click and (selected is not None):
        session.focused = selected
        session.adjustment_mode = "pane"
        session.adjustment_page = "quick"
        session.adjustment_timer = AdjustmentIdleTimer()
    return True


def _copy_custom_ranking_all_at(
    session: TuiSession, pane: TuiCustomPane, *, row: int, column: int, framed: bool, now: float
) -> bool:
    """Copy all filtered Dataset Ranking entries from the fixed marker."""
    viewport = pane.active_ranking_viewport
    hit = viewport.copy_all_hit
    if hit is None:
        return False
    interior_row = row - int(framed)
    interior_column = column - int(framed)
    if interior_row != hit[0] or not hit[1] - 2 <= interior_column <= hit[1] + 2:
        return False
    if pane.grouped_ranking_viewport.active:
        payload = pane.grouped_ranking_viewport.clipboard_all_text()
        entries = ()
    elif pane.ranking_viewport.active:
        payload = pane.ranking_viewport.clipboard_all_text()
        entries = ()
    else:
        payload = ""
        entries = tuple(
            (
                (label, description, link)
                for _, _, label, description, link in _custom_ranking_copyable_entries(
                    pane, session.translator
                )
            )
        )
    if not payload and (not entries):
        return False
    copied = copy_command(payload or _custom_ranking_clipboard_all_text(entries))
    if copied:
        pane.copied_ranking_all_until = now + 1.5
    session.copy_feedback.show(
        session.translator.text("status.data_copied" if copied else "status.command_copy_failed"),
        now=now,
    )
    return True


def _copy_custom_ranking_entry_at(
    session: TuiSession, pane: TuiCustomPane, *, row: int, column: int, framed: bool, now: float
) -> bool:
    """Copy one clicked Dataset Ranking entry only when its icon is hit."""
    interior_row = row - int(framed)
    interior_column = column - int(framed)
    target = pane.ranking_copy_rows.get(interior_row)
    if target is None:
        return False
    link_hit = target[2] is not None and target[2] - 1 <= interior_column <= target[2] + 1
    copy_hit = target[1] - 2 <= interior_column <= target[1] + 2
    if not copy_hit and (not link_hit):
        return False
    if pane.grouped_ranking_viewport.active:
        identity = cast(GroupedIdentity, target[0])
        prepared_entry = pane.grouped_ranking_viewport.by_id.get(identity)
        if prepared_entry is None:
            return False
        payload = pane.grouped_ranking_viewport.clipboard_text(identity)
        entry_id = identity
        project_link = getattr(prepared_entry, "project_link", None) or getattr(
            prepared_entry, "link", None
        )
    elif pane.ranking_viewport.active:
        prepared_entry = pane.ranking_viewport.by_id.get(target[0])
        if prepared_entry is None:
            return False
        payload = pane.ranking_viewport.clipboard_text(str(prepared_entry.key))
        entry_id = str(prepared_entry.key)
        label, description, project_link = (
            prepared_entry.label,
            prepared_entry.description,
            prepared_entry.project_link,
        )
    else:
        entries = _custom_ranking_copyable_entries(pane, session.translator)
        entry = next((item for item in entries if item[1] == target[0]), None)
        if entry is None:
            return False
        payload = ""
        _, entry_id, label, description, project_link = entry
    if link_hit and project_link is not None:
        opened = webbrowser.open(project_link)
        session.copy_feedback.show(
            session.translator.text(
                "status.data_copied" if opened else "status.command_copy_failed"
            ),
            now=now,
        )
        return True
    copied = copy_command(
        payload or _custom_ranking_clipboard_text(label, description, project_link)
    )
    if copied:
        pane.copied_ranking_entry_id = entry_id
        pane.copied_ranking_until = now + 1.5
    session.copy_feedback.show(
        session.translator.text("status.data_copied" if copied else "status.command_copy_failed"),
        now=now,
    )
    return True


def capture_custom_ranking_copy_rows(
    session: TuiSession, pane: TuiCustomPane, content: str, *, fixed_rows: int, framed: bool
) -> None:
    """Map rendered copy markers to pane-local rows for the next mouse hit."""
    del fixed_rows, framed
    pane.ranking_copy_rows.clear()
    viewport = pane.active_ranking_viewport
    if viewport.active:
        pane.ranking_copy_rows.update(viewport.hits)
        return
    entries_by_rank = {
        rank: (entry_id, label, description, link)
        for rank, entry_id, label, description, link in _custom_ranking_copyable_entries(
            pane, session.translator
        )
    }
    for row, line in enumerate(content.splitlines()):
        visible = strip_ansi(line)
        marker_column = (
            display_width(visible.rsplit("⊞", 1)[0])
            if "⊞" in visible
            else display_width(visible.rsplit("✓", 1)[0])
            if "✓" in visible
            else None
        )
        if marker_column is None:
            continue
        link_column = display_width(visible.rsplit("→", 1)[0]) if "→" in visible else None
        prefix, _, _ = visible.lstrip().partition(" ")
        if prefix.isdecimal() and (entry := entries_by_rank.get(int(prefix))) is not None:
            pane.ranking_copy_rows[row] = (entry[0], marker_column, link_column)
