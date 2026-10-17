from __future__ import annotations

import time

from ccusage_viz.animation_host.runtime import (
    _POLL_SECONDS,
    _run_animation_help,
    _terminal,
    read_adjustment_event,
)
from ccusage_viz.animation_overlay import (
    AnimationOverlayRuntime,
    OverlayHistoryTableState,
    SourceMode,
    format_execution_record,
    move_history_selection,
    render_history_table,
)
from ccusage_viz.command_copy import copy_command
from ccusage_viz.editor_help import editor_help_groups
from ccusage_viz.formatting import char_width, display_width, slice_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import AnimationLaunch
from ccusage_viz.terminal import FramePainter, compose_frame
from ccusage_viz.terminal_ui import controls_line
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent, read_event


def _editor_line_start(draft: str, cursor: int) -> int:
    """Return the first insertion point on the current physical line."""

    cursor = max(0, min(cursor, len(draft)))
    return draft.rfind("\n", 0, cursor) + 1

def _editor_line_end(draft: str, cursor: int) -> int:
    """Return the final insertion point on the current physical line."""

    cursor = max(0, min(cursor, len(draft)))
    newline = draft.find("\n", cursor)
    return len(draft) if newline < 0 else newline

def _editor_word_kind(character: str) -> int:
    """Classify whitespace, keyword characters, and punctuation like Vim motions."""

    if character.isspace():
        return 0
    return 1 if character.isalnum() or character == "_" else 2

def _editor_previous_word(draft: str, cursor: int) -> int:
    """Return the Vim-style ``b`` destination before ``cursor``."""

    cursor = max(0, min(cursor, len(draft)))
    while cursor and _editor_word_kind(draft[cursor - 1]) == 0:
        cursor -= 1
    if not cursor:
        return 0
    kind = _editor_word_kind(draft[cursor - 1])
    while cursor and _editor_word_kind(draft[cursor - 1]) == kind:
        cursor -= 1
    return cursor

def _editor_next_word(draft: str, cursor: int) -> int:
    """Return the Vim-style ``w`` destination after ``cursor``."""

    cursor = max(0, min(cursor, len(draft)))
    if cursor == len(draft):
        return cursor
    kind = _editor_word_kind(draft[cursor])
    while cursor < len(draft) and _editor_word_kind(draft[cursor]) == kind:
        cursor += 1
    while cursor < len(draft) and _editor_word_kind(draft[cursor]) == 0:
        cursor += 1
    return cursor

def _overlay_editor_controls(
    translator: Translator, *, width: int, color: bool, dashboard: bool = False
) -> tuple[str, ...]:
    """Render the editor shortcuts for a standalone or Dashboard host."""

    keys = (
        "status.overlay_editor_controls_draft",
        "status.overlay_editor_controls_navigation",
        "status.overlay_editor_controls_dashboard_overall"
        if dashboard
        else "status.overlay_editor_controls_complete",
    )
    return tuple(controls_line(translator.text(key), width=width, color=color) for key in keys)

def _editor_help_lines(translator: Translator, *, ascii: bool) -> tuple[str, ...]:
    """Render shared editor Help groups for the standalone frame."""

    branch = "|- " if ascii else "├─ "
    last = "\\- " if ascii else "└─ "
    lines: list[str] = []
    for group_index, group in enumerate(editor_help_groups()):
        lines.append(translator.text(group.heading_key))
        for item_index, item_key in enumerate(group.item_keys):
            lines.append(
                f"{last if item_index == len(group.item_keys) - 1 else branch}"
                f"{translator.text(item_key)}"
            )
        if group_index != len(editor_help_groups()) - 1:
            lines.append("")
    return tuple(lines)

def _editor_viewport(
    draft: str, cursor: int, width: int, *, cursor_visible: bool
) -> tuple[str, int]:
    """Render a fixed-cell editor cursor without shifting the source text."""

    cursor = max(0, min(cursor, len(draft)))
    before_width = display_width(draft[:cursor])
    cursor_width = char_width(draft[cursor]) if cursor < len(draft) else 1
    start = max(0, before_width - max(0, width - cursor_width))
    visible = slice_width(draft, start, width)
    cursor_column = before_width - start
    if not cursor_visible:
        return visible, start
    if cursor < len(draft) and cursor_column + cursor_width <= width:
        target = slice_width(draft, before_width, cursor_width)
        prefix = slice_width(visible, 0, cursor_column)
        suffix = slice_width(
            visible, cursor_column + cursor_width, width - cursor_column - cursor_width
        )
        return f"{prefix}\x1b[7m{target}\x1b[0m{suffix}", start
    if cursor_column < width:
        return visible + "\x1b[7m \x1b[0m", start
    return visible, start

def _run_overlay_editor(
    screen: FramePainter,
    overlay: AnimationOverlayRuntime,
    decoder: InputDecoder,
    options: AnimationLaunch,
    translator: Translator,
) -> None:
    """Edit retained text/command drafts; Enter commits and Escape discards."""
    mode: SourceMode = "command" if overlay.config.command is not None else "text"
    text_draft = overlay.text_draft
    command_draft = overlay.command_draft
    cursors = {"text": len(text_draft), "command": len(command_draft)}
    feedback: str | None = None
    while True:
        terminal = _terminal(options)
        draft = command_draft if mode == "command" else text_draft
        cursor_index = cursors[mode]
        visible_draft, _ = _editor_viewport(
            draft,
            cursor_index,
            terminal.width,
            cursor_visible=int(time.monotonic() * 2) % 2 == 0,
        )
        controls = _overlay_editor_controls(translator, width=terminal.width, color=terminal.color)
        editor_status = feedback or translator.text(
            "status.overlay_editor_mode_title",
            mode=translator.text(f"status.overlay_editor_mode_{mode}"),
        )
        screen.paint(
            compose_frame(
                visible_draft,
                editor_status,
                controls,
                height=terminal.height,
            )
        )
        event = read_event(decoder, min(_POLL_SECONDS, 0.5))
        key = event.value if isinstance(event, KeyEvent) else None
        feedback = None
        if isinstance(event, PasteEvent):
            content = event.value
            updated = draft[:cursor_index] + content + draft[cursor_index:]
            cursors[mode] += len(content)
            if mode == "text":
                text_draft = updated
            else:
                command_draft = updated
        elif key in {"\x1b", "\x03"}:
            return
        elif key == "\t":
            mode = "command" if mode == "text" else "text"
        elif key in {"\r", "\n"}:
            overlay.apply_draft(mode, draft)
            return
        elif key == "\x08":
            _run_animation_help(
                screen,
                decoder,
                options,
                translator,
                title_key="status.tui_help_editor_title",
                body_lines=_editor_help_lines(translator, ascii=terminal.ascii),
                hint_key="",
                close_key="status.overlay_editor_help_close",
                close_events=frozenset({"h", "\x08", "\x1b", "\r", "\n", "\x03"}),
            )
        elif key == "\x15":
            if mode == "text":
                text_draft = ""
            else:
                command_draft = ""
            cursors[mode] = 0
            feedback = translator.text("status.overlay_editor_cleared")
        elif key == "\x19":
            feedback = translator.text(
                "status.command_copied" if copy_command(draft) else "status.command_copy_failed"
            )
        elif key == "\x12":
            updated = overlay.config.text or "" if mode == "text" else overlay.config.command or ""
            cursors[mode] = len(updated)
            if mode == "text":
                text_draft = updated
            else:
                command_draft = updated
        elif key == "\x7f" and cursor_index:
            updated = draft[: cursor_index - 1] + draft[cursor_index:]
            cursors[mode] -= 1
            if mode == "text":
                text_draft = updated
            else:
                command_draft = updated
        elif key in {"\x1b[3~", "\x04"}:
            updated = draft[:cursor_index] + draft[cursor_index + 1 :]
            if mode == "text":
                text_draft = updated
            else:
                command_draft = updated
        elif key == "\x1b[D":
            cursors[mode] = max(0, cursor_index - 1)
        elif key == "\x1b[C":
            cursors[mode] = min(len(draft), cursor_index + 1)
        elif key in {"\x1b[H", "\x01"}:
            cursors[mode] = _editor_line_start(draft, cursor_index)
        elif key == "\x02":
            cursors[mode] = _editor_previous_word(draft, cursor_index)
        elif key == "\x17":
            cursors[mode] = _editor_next_word(draft, cursor_index)
        elif key in {"\x1b[F", "\x05"}:
            cursors[mode] = _editor_line_end(draft, cursor_index)
        elif key is not None and len(key) == 1 and key.isprintable():
            updated = draft[:cursor_index] + key + draft[cursor_index:]
            cursors[mode] += 1
            if mode == "text":
                text_draft = updated
            else:
                command_draft = updated

def _run_overlay_history(
    screen: FramePainter,
    overlay: AnimationOverlayRuntime,
    decoder: InputDecoder,
    options: AnimationLaunch,
    translator: Translator,
) -> None:
    """Show command execution records without mutating overlay configuration."""
    state = OverlayHistoryTableState()
    feedback: str | None = None
    while True:
        terminal = _terminal(options)
        table = render_history_table(
            tuple(overlay.history),
            state,
            available_width=terminal.width,
            available_height=terminal.height - 1,
            empty=translator.text("status.overlay_history_empty"),
        )
        controls = controls_line(
            translator.text("status.overlay_history_controls"),
            width=terminal.width,
            color=terminal.color,
        )
        notices = (feedback,) if feedback is not None else ()
        screen.paint(
            compose_frame(
                table.body,
                None,
                (controls,),
                notices,
                height=terminal.height,
            )
        )
        key = read_adjustment_event(decoder, _POLL_SECONDS)
        feedback = None
        if key in {"\x1b", "\x03"}:
            return
        records = tuple(overlay.history)
        selected = render_history_table(
            records,
            state,
            available_width=terminal.width,
            available_height=terminal.height - 1,
            empty=translator.text("status.overlay_history_empty"),
        ).selected
        if key in {"y", "\r", "\n"} and selected is not None:
            feedback = translator.text(
                "status.command_copied"
                if copy_command(format_execution_record(selected))
                else "status.command_copy_failed"
            )
        elif key == "\x1b[A":
            move_history_selection(state, records, -1)
        elif key == "\x1b[B":
            move_history_selection(state, records, 1)
