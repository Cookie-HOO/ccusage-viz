from __future__ import annotations

from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer
from ccusage_viz.animation_host.overlay_editor import (
    _editor_line_end,
    _editor_line_start,
    _editor_next_word,
    _editor_previous_word,
)
from ccusage_viz.animation_overlay import format_execution_record, move_history_selection
from ccusage_viz.command_copy import copy_command
from ccusage_viz.data_view import cycle_dashboard_body_view
from ccusage_viz.lifecycle import LifecycleTrigger
from ccusage_viz.text_viewport import next_text_offset
from ccusage_viz.tui.adjustments import (
    _adjustment_target,
)
from ccusage_viz.tui.custom_adjustments import (
    _ranking_search_eligible,
)
from ccusage_viz.tui.dashboard_events import handle_dashboard_adjustment
from ccusage_viz.tui.datasets.modal import (
    handle_dataset_modal,
)
from ccusage_viz.tui.help import open_help, process_help_event
from ccusage_viz.tui.history import (
    apply_dashboard_state,
    execute_preset_command,
    full_dashboard_command,
    open_preset_manager,
    preset_catalog,
    record_mutation,
)
from ccusage_viz.tui.layout import parse_grid
from ccusage_viz.tui.models import (
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
)
from ccusage_viz.tui.painting import adjust_pane_weight, paint
from ccusage_viz.tui.pane_events import handle_pane_adjustment
from ccusage_viz.tui.pointer import (
    handle_pane_mouse,
    handle_ranking_wheel,
    handle_scrollbar_drag,
    handle_scrollbar_hover,
)
from ccusage_viz.tui.queries import (
    refresh,
    refresh_custom_summaries,
    refresh_header,
)
from ccusage_viz.tui.session import TuiSession
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    WheelEvent,
)
from ccusage_viz.tui_preset_manager import reconcile_preset_manager, reduce_preset_manager


def dispatch_event(session: TuiSession, event: object, *, now: float) -> None:
    if isinstance(event, WheelEvent):
        scrolling = tuple(
            pane.active_ranking_viewport
            for pane in session.panes
            if isinstance(pane, TuiCustomPane)
        )
        before = tuple(viewport.offset for viewport in scrolling)
        handle_ranking_wheel(session, event)
        if isinstance(session.decoder, InputDecoder):
            for buffered in session.decoder.drain_wheel():
                handle_ranking_wheel(session, buffered)
        if before != tuple(viewport.offset for viewport in scrolling):
            paint(session)
        return
    if session.help_overlay is not None:
        process_help_event(session, event)
        return
    if session.preset_manager is not None:
        if isinstance(event, (KeyEvent, PasteEvent)):
            update = reduce_preset_manager(session.preset_manager, preset_catalog(session), event)
            session.preset_manager = update.state
            if update.command is not None:
                execute_preset_command(session, update.command)
            if session.preset_manager is not None:
                session.preset_manager = reconcile_preset_manager(
                    session.preset_manager,
                    preset_catalog(session),
                    visible_rows=max(1, get_terminal_size().lines - 4),
                )
        paint(session)
        return
    if session.dataset_modal is not None:
        handle_dataset_modal(session, event)
        paint(session)
        return
    if isinstance(event, MouseEvent):
        hover_changed = handle_scrollbar_hover(session, event)
        if handle_scrollbar_drag(session, event):
            paint(session)
            return
        if handle_pane_mouse(session, event):
            paint(session)
            return
        if hover_changed:
            paint(session)
        return
    if session.overlay_editor is not None:
        if not isinstance(event, (KeyEvent, PasteEvent)):
            return
        pane = session.panes[session.overlay_editor.pane_index]
        assert isinstance(pane, TuiAnimationPane)
        animation_pane = pane
        if isinstance(event, PasteEvent):
            cursor = session.overlay_editor.cursor
            session.overlay_editor.replace_draft(
                session.overlay_editor.draft[:cursor]
                + event.value
                + session.overlay_editor.draft[cursor:]
            )
            session.overlay_editor.cursor = cursor + len(event.value)
            paint(session)
            return
        key = event.value
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "\x1b":
            session.overlay_editor = None
        elif key == "\t":
            session.overlay_editor.mode = (
                "command" if session.overlay_editor.mode == "text" else "text"
            )
        elif key == "\r":
            mode = session.overlay_editor.mode
            draft = session.overlay_editor.draft
            pane_index = session.overlay_editor.pane_index
            record_mutation(
                session,
                ("pane", pane_index, "overlay-source"),
                lambda pane=animation_pane: pane.overlay.apply_draft(mode, draft),  # ty: ignore[invalid-argument-type]
            )
            session.overlay_editor = None
        elif key in {"\n", "\x0b"}:
            adjust_pane_weight(
                session,
                session.overlay_editor.pane_index,
                axis="row",
                delta=1 if key == "\x0b" else -1,
            )
        elif key == "?":
            open_help(session, context="editor")
        elif key == "\x15":
            session.overlay_editor.replace_draft("")
            session.overlay_editor.cursor = 0
            session.copy_feedback.show(session.translator.text("status.overlay_editor_cleared"))
        elif key == "\x19":
            session.copy_feedback.show(
                session.translator.text(
                    "status.command_copied"
                    if copy_command(session.overlay_editor.draft)
                    else "status.command_copy_failed"
                )
            )
        elif key == "\x12":
            session.overlay_editor.replace_draft(
                pane.overlay.config.text or ""
                if session.overlay_editor.mode == "text"
                else pane.overlay.config.command or ""
            )
            session.overlay_editor.cursor = len(session.overlay_editor.draft)
        elif key in {"\x7f", "\x08"} and session.overlay_editor.cursor:
            cursor = session.overlay_editor.cursor
            session.overlay_editor.replace_draft(
                session.overlay_editor.draft[: cursor - 1] + session.overlay_editor.draft[cursor:]
            )
            session.overlay_editor.cursor = cursor - 1
        elif key in {"\x1b[3~", "\x04"}:
            cursor = session.overlay_editor.cursor
            session.overlay_editor.replace_draft(
                session.overlay_editor.draft[:cursor] + session.overlay_editor.draft[cursor + 1 :]
            )
        elif key == "\x1b[D":
            session.overlay_editor.cursor = max(0, session.overlay_editor.cursor - 1)
        elif key == "\x1b[C":
            session.overlay_editor.cursor = min(
                len(session.overlay_editor.draft), session.overlay_editor.cursor + 1
            )
        elif key in {"\x1b[H", "\x01"}:
            session.overlay_editor.cursor = _editor_line_start(
                session.overlay_editor.draft, session.overlay_editor.cursor
            )
        elif key == "\x02":
            session.overlay_editor.cursor = _editor_previous_word(
                session.overlay_editor.draft, session.overlay_editor.cursor
            )
        elif key == "\x17":
            session.overlay_editor.cursor = _editor_next_word(
                session.overlay_editor.draft, session.overlay_editor.cursor
            )
        elif key in {"\x1b[F", "\x05"}:
            session.overlay_editor.cursor = _editor_line_end(
                session.overlay_editor.draft, session.overlay_editor.cursor
            )
        elif len(key) == 1 and key.isprintable():
            cursor = session.overlay_editor.cursor
            session.overlay_editor.replace_draft(
                session.overlay_editor.draft[:cursor] + key + session.overlay_editor.draft[cursor:]
            )
            session.overlay_editor.cursor = cursor + 1
        paint(session)
        return
    if session.custom_logs_pane is not None:
        if not isinstance(event, KeyEvent):
            return
        key = event.value
        pane = session.panes[session.custom_logs_pane]
        assert isinstance(pane, TuiCustomPane)
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "\x1b":
            session.custom_logs_pane = None
        elif key in {"y", "Y"}:
            session.copy_feedback.show(
                session.translator.text(
                    "status.data_copied"
                    if copy_command(
                        "\n".join(
                            f"{record.timestamp.isoformat()} {record.status}: {record.detail}"
                            for record in pane.logs
                        )
                    )
                    else "status.command_copy_failed"
                )
            )
        paint(session)
        return
    if session.overlay_history is not None:
        if not isinstance(event, KeyEvent):
            return
        key = event.value
        pane = session.panes[session.overlay_history.pane_index]
        assert isinstance(pane, TuiAnimationPane)
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "h":
            open_help(session, context="history")
            return
        if key == "\x1b":
            session.overlay_history = None
        else:
            records = tuple(pane.overlay.history)
            if key in {"y", "\r", "\n"} and session.overlay_history.table.selected is not None:
                session.copy_feedback.show(
                    session.translator.text(
                        "status.command_copied"
                        if copy_command(
                            format_execution_record(session.overlay_history.table.selected)
                        )
                        else "status.command_copy_failed"
                    )
                )
            elif key == "\x1b[A":
                move_history_selection(session.overlay_history.table, records, -1)
            elif key == "\x1b[B":
                move_history_selection(session.overlay_history.table, records, 1)
            elif key in {"{", "}", "J", "K"}:
                adjust_pane_weight(
                    session,
                    session.overlay_history.pane_index,
                    axis="column" if key in {"{", "}"} else "row",
                    delta=1 if key in {"}", "K"} else -1,
                )
        paint(session)
        return
    if isinstance(event, MouseEvent):
        return
    if session.focused is not None and _ranking_search_eligible(session.panes[session.focused]):
        search = session.panes[session.focused].ranking_search  # ty: ignore[unresolved-attribute]
        if search.editing:
            if isinstance(event, PasteEvent):
                search.query += event.value
            elif isinstance(event, KeyEvent):
                key = event.value
                if key == "\x1b":
                    search.query = ""
                    search.editing = False
                    search.density_notice = None
                elif key in {"\r", "\n"}:
                    search.editing = False
                elif key in {"\x7f", "\x08"}:
                    search.query = search.query[:-1]
                elif len(key) == 1 and key.isprintable():
                    search.query += key
            paint(session)
            return
        if isinstance(event, KeyEvent) and event.value == "/":
            search.editing = True
            search.density_notice = None
            paint(session)
            return
    key = event.value if isinstance(event, KeyEvent) else None
    if key == "\x03":
        raise KeyboardInterrupt
    if session.grid_draft is not None:
        if key == "\x1b":
            session.grid_draft = None
            session.grid_error = None
        elif key in {"\r", "\n"}:
            parsed = parse_grid(session.grid_draft, len(session.panes))
            if parsed is None:
                session.grid_error = session.translator.text(
                    "error.tui_grid_runtime", value=session.grid_draft, count=len(session.panes)
                )
            else:
                changed_grid = parsed != session.active_grid or session.active_layout is not None
                if changed_grid:

                    def apply_grid() -> None:
                        session.active_grid = parsed
                        session.active_layout = None
                        session.column_weights = None
                        session.row_weights = None

                    record_mutation(session, ("layout", "topology"), apply_grid)
                session.grid_draft = None
                session.grid_error = None
        elif key in {"\x7f", "\x08"}:
            session.grid_draft = session.grid_draft[:-1]
        elif key and (key.isalnum() or key in {"x", "X", "-"}):
            session.grid_draft += key
        paint(session)
        return
    if key in {"u", "U"}:
        restored = session.history.undo() if key == "u" else session.history.redo()
        if restored is session.history:
            session.copy_feedback.show(
                session.translator.text(
                    "status.tui_history_empty_undo"
                    if key == "u"
                    else "status.tui_history_empty_redo"
                )
            )
        else:
            session.history = restored
            apply_dashboard_state(session, session.history.current)
        paint(session)
        return
    animation_move_left = (
        key == "h"
        and session.adjustment_mode == "pane"
        and session.adjustment_page == "advanced"
        and session.focused is not None
        and isinstance(session.panes[session.focused], TuiAnimationPane)
    )
    if key == "h" and not animation_move_left:
        open_help(session)
        return
    if key == "c":
        session.controls_hidden = not session.controls_hidden
        paint(session, force=True)
        return
    if session.adjustment_mode == "pane":
        handle_pane_adjustment(session, event, key, now=now)
        return
    if session.adjustment_mode == "global":
        handle_dashboard_adjustment(session, event, key)
        return
    if session.body_view != "chart" and key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
        offset = next_text_offset(
            key,
            offset=session.dashboard_text_offset,
            line_count=session.dashboard_text_line_count,
            visible_rows=session.dashboard_text_visible_rows,
        )
        assert offset is not None
        session.dashboard_text_offset = offset
        paint(session, force=True)
        return
    if session.body_view == "chart" and key == "r":
        session.manual_refresh_operations.clear()
        for index in range(len(session.panes)):
            if refresh(session, index, trigger=LifecycleTrigger.MANUAL, replace_active=True):
                pane = session.panes[index]
                if (
                    isinstance(pane, (TuiChartPane, TuiCustomPane))
                    and pane.lifecycle.active is not None
                ):
                    session.manual_refresh_operations.add(pane.lifecycle.active)
        if refresh_header(session, trigger=LifecycleTrigger.MANUAL, replace_active=True):
            operation = session.header.lifecycle.active
            if operation is not None:
                session.manual_refresh_operations.add(operation)
        session.manual_refresh_operations.update(
            refresh_custom_summaries(session, trigger=LifecycleTrigger.MANUAL, replace_active=True)
        )
        paint(session, force=True)
    elif key == "\x0f" and session.body_view == "chart":
        open_preset_manager(session)
        paint(session)
        return
    elif key == "\x13" and session.body_view == "chart":
        open_preset_manager(session, save=True)
        paint(session)
        return
    elif key in {"v", "V"}:

        def cycle_dashboard_view() -> None:
            session.body_view = cycle_dashboard_body_view(
                session.body_view, step=1 if key == "v" else -1
            )

        record_mutation(session, ("dashboard", "view"), cycle_dashboard_view)
    elif key in {"y", "Y"} and session.body_view != "chart":
        session.copy_feedback.show(
            session.translator.text(
                "status.command_copied"
                if copy_command(full_dashboard_command(session))
                else "status.command_copy_failed"
            )
        )
    elif key == "\t":
        return
    elif key == "d" and session.body_view == "chart":
        session.focused = None
        session.adjustment_mode = "global"
        session.adjustment_page = "quick"
        session.adjustment_timer = AdjustmentIdleTimer()
    elif key == "m" and session.body_view == "chart":
        session.focused = _adjustment_target(session.focused, key, len(session.panes))
        session.adjustment_mode = "pane" if session.focused is not None else None
        session.adjustment_page = "quick"
        session.adjustment_timer = AdjustmentIdleTimer() if session.focused is not None else None
    else:
        return
    paint(session)
