"""Standalone, provider-free terminal host for ccuv animations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import (
    HELP_IDLE_TIMEOUT_SECONDS,
    AdjustmentIdleTimer,
    AdjustmentTimeout,
)
from ccusage_viz.animation import (
    AnimationRenderer,
    AnimationSessionState,
    AnimationTarget,
    animation_spec,
    animation_style_choices,
    new_animation_session,
)
from ccusage_viz.animation_overlay import (
    AnimationOverlayRuntime,
    OverlayHistoryTableState,
    SourceMode,
    compose_overlay_row,
    format_execution_record,
    move_history_selection,
    render_history_table,
)
from ccusage_viz.command_copy import copy_command
from ccusage_viz.editor_help import editor_help_groups
from ccusage_viz.formatting import char_width, clip_width, display_width, pad_width, slice_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import AnimationLaunch
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import (
    FramePainter,
    Terminal,
    compose_frame,
    inspect_terminal,
    set_cursor_visible,
)
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows, controls_line
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    PasteEvent,
    read_event,
    tui_input_mode,
)

_POLL_SECONDS = 0.05


def _format_overlay_interval(seconds: float) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{int(seconds // 3600)}h"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds)}s"


def read_adjustment_event(decoder: InputDecoder, timeout: float) -> str | None:
    """Read one decoded keyboard event for the standalone animation host."""

    event = read_event(decoder, timeout)
    return event.value if isinstance(event, KeyEvent) else None


def cycle_animation_style(
    session: AnimationSessionState, *, target: AnimationTarget = "standalone", step: int, now: float
) -> None:
    """Move through one host's discovered catalog without creating a new session."""

    styles = animation_style_choices(target)
    index = styles.index(session.spec.style)
    session.set_style(animation_spec(styles[(index + step) % len(styles)], target=target), now)


def _cycle_theme(session: AnimationSessionState, *, step: int, now: float) -> None:
    index = COLOR_SCHEMES.index(session.theme)
    session.set_theme(COLOR_SCHEMES[(index + step) % len(COLOR_SCHEMES)], now)


def _terminal(options: AnimationLaunch) -> Terminal:
    return inspect_terminal(
        "animate",
        ascii=options.host.ascii,
        size=get_terminal_size(),
    )


def _frame_rows(
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    *,
    now: float,
    translator: Translator,
    footer_rows: int = 1,
) -> tuple[str, ...]:
    """Project only into space not reserved for status and visible footer rows."""

    result = renderer.render(
        session,
        width=terminal.width,
        height=max(1, terminal.height - 1 - footer_rows),
        color=terminal.color,
        ascii=terminal.ascii,
        now=now,
        translator=translator,
    )
    return result.rows


def _status(session: AnimationSessionState, translator: Translator) -> str:
    state = translator.text(
        "status.animation_paused" if session.host_paused else "status.animation_running"
    )
    return translator.text(
        "status.animation",
        style=session.spec.display_name,
        theme=session.theme,
        state=state,
    )


def _paint_animation(
    screen: FramePainter,
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    translator: Translator,
    *,
    now: float,
    overlay: AnimationOverlayRuntime | None = None,
    force: bool = False,
) -> None:
    footer_count = 1
    rows = list(
        _frame_rows(
            session,
            renderer,
            terminal,
            now=now,
            translator=translator,
            footer_rows=footer_count,
        )
    )
    if overlay is not None:
        overlay.poll(now=now, translator=translator)
        for placement in overlay.placements(width=terminal.width, height=len(rows)):
            if 0 <= placement.row < len(rows):
                rows[placement.row] = compose_overlay_row(
                    rows[placement.row], placement, width=terminal.width
                )
    controls = controls_line(
        translator.text(
            "status.animation_controls",
            action=translator.text("status.resume" if session.host_paused else "status.pause"),
        ),
        width=terminal.width,
        color=terminal.color,
    )
    footer = (controls,)
    screen.paint(
        compose_frame(
            "\n".join(rows),
            _status(session, translator),
            footer,
            height=terminal.height,
        ),
        force=force,
        atomic=True,
    )


def _run_animation_help(
    screen: FramePainter,
    decoder: InputDecoder,
    options: AnimationLaunch,
    translator: Translator,
    *,
    title_key: str = "status.animation_help_title",
    body_key: str = "status.animation_help_body",
    hint_key: str = "status.animation_help_hint",
    body_lines: tuple[str, ...] | None = None,
    close_key: str = "status.animation_help_close",
    close_events: frozenset[str] = frozenset({"h", "q", "Q", "\x1b", "\x03"}),
) -> None:
    """Show a standalone help frame until one of its local close shortcuts."""

    idle_timer = AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS)
    while True:
        terminal = _terminal(options)
        controls = controls_line(
            translator.text(close_key),
            width=terminal.width,
            color=terminal.color,
        )
        last = "\\- " if terminal.ascii else "└─ "
        hint = f"{last}{translator.text(hint_key)}" if hint_key else ""
        contents = body_lines if body_lines is not None else (translator.text(body_key),)
        body = "\n".join(part for part in (*contents, hint) if part)
        screen.paint(
            compose_frame(
                body,
                translator.text(title_key),
                (controls,),
                height=terminal.height,
            )
        )
        event = read_event(decoder, min(_POLL_SECONDS, idle_timer.remaining()))
        if event is None:
            try:
                idle_timer.check()
            except AdjustmentTimeout:
                return
        else:
            idle_timer.record_input()
        if isinstance(event, KeyEvent) and event.value in close_events:
            return


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


def _run_adjustment(
    screen: FramePainter,
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    overlay: AnimationOverlayRuntime,
    decoder: InputDecoder,
    options: AnimationLaunch,
    translator: Translator,
) -> bool:
    """Run the local quick/advanced adjustment pages; return true to exit the host."""

    page = "quick"
    idle_timer = AdjustmentIdleTimer()
    last_size: tuple[int, int] | None = None

    def paint(*, force: bool = False) -> None:
        nonlocal last_size
        terminal = _terminal(options)
        last_size = (terminal.width, terminal.height)
        now = time.monotonic()
        rows = list(_frame_rows(session, renderer, terminal, now=now, translator=translator))
        for placement in overlay.placements(width=terminal.width, height=len(rows)):
            rows[placement.row] = compose_overlay_row(
                rows[placement.row], placement, width=terminal.width
            )
        actions = (
            (
                AdjustmentAction("p/P", translator.text("adjustment.overlay_position"), 0),
                AdjustmentAction("t/T", translator.text("adjustment.animation_theme"), 1),
                AdjustmentAction("s/S", translator.text("adjustment.animation_style"), 2),
            )
            if page == "quick"
            else (
                AdjustmentAction("↑/↓/←/→", translator.text("adjustment.overlay_move"), 0),
                AdjustmentAction("0", translator.text("adjustment.overlay_reset"), 1),
                AdjustmentAction("e", translator.text("adjustment.overlay_edit"), 2),
                AdjustmentAction("i", translator.text("adjustment.overlay_interval"), 3),
                AdjustmentAction("l", translator.text("adjustment.overlay_history"), 4),
            )
        )
        state = translator.text(
            "status.animation_adjust_quick"
            if page == "quick"
            else (
                "status.animation_adjust_advanced_command"
                if overlay.config.command is not None
                else "status.animation_adjust_advanced"
            ),
            style=session.spec.display_name,
            style_index=animation_style_choices("standalone").index(session.spec.style) + 1,
            style_count=len(animation_style_choices("standalone")),
            theme=session.theme,
            theme_index=COLOR_SCHEMES.index(session.theme) + 1,
            theme_count=len(COLOR_SCHEMES),
            position=overlay.presentation.position,
            offset_x=overlay.presentation.offset_x,
            offset_y=overlay.presentation.offset_y,
            interval=_format_overlay_interval(overlay.config.interval),
        )
        controls = adjustment_rows(
            state,
            translator.text(f"adjustment.page_{page}"),
            actions,
            width=terminal.width,
            color=terminal.color,
            switch_action=translator.text(
                "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
            ),
            finish_action=translator.text("adjustment.finish"),
        )
        screen.paint(
            compose_frame(
                "\n".join(rows),
                _status(session, translator),
                controls,
                height=terminal.height,
            ),
            force=force,
        )

    paint()
    while True:
        now = time.monotonic()
        timeout = _wait_seconds(
            session, now, upper_bound=min(_POLL_SECONDS, idle_timer.remaining())
        )
        try:
            key = read_adjustment_event(decoder, timeout)
        except KeyboardInterrupt:
            return True
        now = time.monotonic()
        size = get_terminal_size()
        deadline_due = session.next_deadline is not None and now >= session.next_deadline
        if (
            size.columns != (last_size or (None, None))[0]
            or size.lines != (last_size or (None, None))[1]
        ):
            paint(force=True)
        elif deadline_due:
            paint()
        if key is None:
            try:
                idle_timer.check()
            except AdjustmentTimeout:
                return False
            continue
        idle_timer.record_input()
        if key in {"q", "Q", "\x03", "\x1b"}:
            return True
        if key in {"\r", "\n", "m", "M"}:
            return False
        if key == "a":
            page = "advanced" if page == "quick" else "quick"
        elif page == "quick" and key in {"p", "P"}:
            overlay.cycle_position(1 if key == "p" else -1)
        elif page == "quick" and key == "t":
            _cycle_theme(session, step=1, now=now)
        elif page == "quick" and key == "T":
            _cycle_theme(session, step=-1, now=now)
        elif page == "quick" and key in {"s", "S"}:
            cycle_animation_style(
                session, target="standalone", step=1 if key == "s" else -1, now=now
            )
        elif page == "advanced" and key == "\x1b[A":
            overlay.adjust_offset(dy=-1)
        elif page == "advanced" and key == "\x1b[B":
            overlay.adjust_offset(dy=1)
        elif page == "advanced" and key == "\x1b[C":
            overlay.adjust_offset(dx=1)
        elif page == "advanced" and key == "\x1b[D":
            overlay.adjust_offset(dx=-1)
        elif page == "advanced" and key == "0":
            overlay.reset_offset()
        elif page == "advanced" and key == "e":
            _run_overlay_editor(screen, overlay, decoder, options, translator)
        elif page == "advanced" and key == "i":
            overlay.cycle_interval(now=now)
        elif page == "advanced" and key == "l":
            _run_overlay_history(screen, overlay, decoder, options, translator)
        else:
            continue
        paint()


def _wait_seconds(
    session: AnimationSessionState,
    now: float,
    *,
    overlay: AnimationOverlayRuntime | None = None,
    upper_bound: float = _POLL_SECONDS,
) -> float:
    """Bound an input wait by local animation and overlay repaint deadlines."""

    deadlines = [deadline for deadline in (session.next_deadline,) if deadline is not None]
    if overlay is not None and overlay.next_due is not None:
        deadlines.append(overlay.next_due)
    return upper_bound if not deadlines else min(upper_bound, max(0.0, min(deadlines) - now))


@dataclass(slots=True)
class GalleryState:
    """Live card sessions and selection for the provider-free animation gallery."""

    styles: tuple[str, ...]
    selected_style: str
    playback_requested: bool = True
    sessions: dict[str, AnimationSessionState] = field(default_factory=dict)
    frames: dict[tuple[str, int, int, bool, bool, str], tuple[str, ...]] = field(
        default_factory=dict
    )
    dirty_styles: set[str] = field(default_factory=set)

    def selected_index(self) -> int:
        return self.styles.index(self.selected_style) if self.selected_style in self.styles else 0

    def refresh_catalog(self, styles: tuple[str, ...], *, now: float) -> bool:
        """Reconcile discovery and discard sessions for removed effects."""

        if styles == self.styles:
            return False
        previous = self.selected_style
        self.styles = styles
        self.sessions = {
            style: session for style, session in self.sessions.items() if style in styles
        }
        self.frames = {key: rows for key, rows in self.frames.items() if key[0] in styles}
        self.dirty_styles.update(styles)
        if not styles:
            self.selected_style = ""
            return True
        self.selected_style = previous if previous in styles else styles[0]
        for session in self.sessions.values():
            session.set_visible(False, now)
        return True

    def select(self, index: int) -> None:
        if self.styles:
            self.selected_style = self.styles[index % len(self.styles)]

    def session_for(self, style: str, *, now: float) -> AnimationSessionState:
        session = self.sessions.get(style)
        if session is None:
            session = new_animation_session(
                animation_spec(style, target="standalone"), theme="classic"
            )
            self.sessions[style] = session
        session.set_visible(True, now)
        session.set_playback_requested(self.playback_requested, now)
        return session

    def set_visible_styles(self, styles: tuple[str, ...], *, now: float) -> None:
        """Make the page's sessions immediately eligible for playback."""

        visible = frozenset(styles)
        for style, session in self.sessions.items():
            if style not in visible:
                session.set_visible(False, now)
        for style in styles:
            was_visible = style in self.sessions and self.sessions[style].visible
            self.session_for(style, now=now)
            if not was_visible:
                self.dirty_styles.add(style)

    def set_playback_requested(self, requested: bool, *, now: float) -> None:
        self.playback_requested = requested
        self.dirty_styles.update(self.sessions)
        for session in self.sessions.values():
            session.set_playback_requested(requested, now)

    def mark_theme_changed(self, style: str) -> None:
        self.dirty_styles.add(style)


def _gallery_geometry(terminal: Terminal) -> tuple[int, int, int, int]:
    """Return a fixed two-column, large-card gallery viewport."""

    columns = 1 if terminal.width < 2 else 2
    card_width = max(1, terminal.width // columns)
    available_height = max(1, terminal.height - 3)
    rows = max(1, available_height // 18)
    card_height = max(1, available_height // rows)
    return columns, rows, card_width, card_height


def _gallery_card(
    rows: tuple[str, ...],
    style: str,
    *,
    selected: bool,
    width: int,
    height: int,
    ascii: bool,
) -> tuple[str, ...]:
    """Frame a gallery card without measuring ANSI escape sequences as content."""

    if width < 4 or height < 3:
        return (clip_width(f"> {style}" if selected else style, width),)
    left, right, horizontal, vertical, bottom_left, bottom_right = (
        ("+", "+", "-", "|", "+", "+") if ascii else ("┌", "┐", "─", "│", "└", "┘")
    )
    interior_width = width - 2
    marker = ">" if selected else " "
    title = clip_width(f"{marker} {style}", interior_width)
    body = [title, *rows[: max(0, height - 3)]]
    body.extend("" for _ in range(max(0, height - 2 - len(body))))
    return (
        left + horizontal * interior_width + right,
        *(vertical + pad_width(item, interior_width) + vertical for item in body),
        bottom_left + horizontal * interior_width + bottom_right,
    )


def _gallery_rows(
    state: GalleryState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    translator: Translator,
    *,
    now: float,
) -> tuple[tuple[str, ...], tuple[AnimationSessionState, ...]]:
    if not state.styles:
        return (translator.text("status.animation_gallery_empty"),), ()

    columns, row_count, card_width, card_height = _gallery_geometry(terminal)
    page_size = columns * row_count
    selected_index = state.selected_index()
    page = selected_index // page_size
    start = page * page_size
    visible = state.styles[start : start + page_size]
    state.set_visible_styles(visible, now=now)
    sessions: list[AnimationSessionState] = []
    cards: list[tuple[str, ...]] = []
    for style in visible:
        session = state.session_for(style, now=now)
        sessions.append(session)
        key = (
            style,
            max(1, card_width - 2),
            max(1, card_height - 3),
            terminal.color,
            terminal.ascii,
            session.theme,
        )
        if (
            style in state.dirty_styles
            or key not in state.frames
            or (session.next_deadline is not None and now >= session.next_deadline)
        ):
            state.frames[key] = renderer.render(
                session,
                width=max(1, card_width - 2),
                height=max(1, card_height - 3),
                color=terminal.color,
                ascii=terminal.ascii,
                now=now,
                translator=translator,
            ).rows
            state.dirty_styles.discard(style)
        cards.append(
            _gallery_card(
                state.frames[key],
                style,
                selected=style == state.selected_style,
                width=card_width,
                height=card_height,
                ascii=terminal.ascii,
            )
        )
    output: list[str] = []
    for row in range(row_count):
        group = cards[row * columns : (row + 1) * columns]
        for line in range(card_height):
            output.append(
                clip_width(
                    "".join(pad_width(card[line], card_width) for card in group), terminal.width
                )
            )
    pages = max(1, (len(state.styles) + page_size - 1) // page_size)
    output.append(
        translator.text(
            "status.animation_gallery_page",
            page=page + 1,
            pages=pages,
            start=start + 1,
            end=min(start + len(visible), len(state.styles)),
            count=len(state.styles),
        )
    )
    return tuple(output), tuple(sessions)


def _gallery_wait_seconds(sessions: tuple[AnimationSessionState, ...], now: float) -> float:
    deadlines = tuple(
        session.next_deadline for session in sessions if session.next_deadline is not None
    )
    return _POLL_SECONDS if not deadlines else min(_POLL_SECONDS, max(0.0, min(deadlines) - now))


def _run_gallery(options: AnimationLaunch, translator: Translator) -> int:
    state = GalleryState(animation_style_choices("standalone"), options.animation.style)
    renderer = AnimationRenderer()
    screen = FramePainter()
    last_size: tuple[int, int] | None = None
    try:
        set_cursor_visible(screen.stream, False)
        with tui_input_mode() as decoder:
            while True:
                terminal = _terminal(options)
                size = (terminal.width, terminal.height)
                now = time.monotonic()
                state.refresh_catalog(animation_style_choices("standalone"), now=now)
                rows, sessions = _gallery_rows(state, renderer, terminal, translator, now=now)
                status = translator.text(
                    "status.animation_gallery",
                    state=translator.text(
                        "status.animation_running"
                        if state.playback_requested
                        else "status.animation_paused"
                    ),
                )
                screen.paint(
                    compose_frame(
                        "\n".join(rows),
                        status,
                        translator.text("status.animation_gallery_controls"),
                        height=terminal.height,
                    ),
                    force=last_size is not None and last_size != size,
                    atomic=True,
                )
                last_size = size
                event = read_event(decoder, _gallery_wait_seconds(sessions, time.monotonic()))
                if not isinstance(event, KeyEvent):
                    continue
                key = event.value
                now = time.monotonic()
                if key in {"q", "Q", "\x03"}:
                    break
                if key == " ":
                    state.set_playback_requested(not state.playback_requested, now=now)
                elif key in {"t", "T"} and state.selected_style:
                    session = state.session_for(state.selected_style, now=now)
                    _cycle_theme(session, step=1 if key == "t" else -1, now=now)
                    state.mark_theme_changed(state.selected_style)
                elif key in {"j", "\x1b[C"}:
                    state.select(state.selected_index() + 1)
                elif key in {"k", "\x1b[D"}:
                    state.select(state.selected_index() - 1)
                elif key == "\x1b[B":
                    columns, _, _, _ = _gallery_geometry(terminal)
                    state.select(state.selected_index() + columns)
                elif key == "\x1b[A":
                    columns, _, _, _ = _gallery_geometry(terminal)
                    state.select(state.selected_index() - columns)
    except KeyboardInterrupt:
        pass
    finally:
        screen.finish()
        set_cursor_visible(screen.stream, True)
    return 0


def run_animation(options: AnimationLaunch, translator: Translator) -> int:
    """Run an interactive animation without creating any provider-facing work."""

    if options.gallery:
        return _run_gallery(options, translator)
    session = new_animation_session(options.animation, theme="classic")
    renderer = AnimationRenderer()
    overlay = AnimationOverlayRuntime(options.overlay)
    screen = FramePainter()
    last_size: tuple[int, int] | None = None
    try:
        set_cursor_visible(screen.stream, False)
        with tui_input_mode() as decoder:
            while True:
                terminal = _terminal(options)
                size = (terminal.width, terminal.height)
                now = time.monotonic()
                deadline_due = session.next_deadline is not None and now >= session.next_deadline
                overlay_changed = overlay.poll(now=now)
                if last_size != size or not screen.painted:
                    _paint_animation(
                        screen,
                        session,
                        renderer,
                        terminal,
                        translator,
                        now=now,
                        overlay=overlay,
                        force=last_size is not None,
                    )
                    last_size = size
                elif deadline_due or overlay_changed:
                    _paint_animation(
                        screen, session, renderer, terminal, translator, now=now, overlay=overlay
                    )
                key = read_adjustment_event(
                    decoder, _wait_seconds(session, time.monotonic(), overlay=overlay)
                )
                if key is None:
                    continue
                now = time.monotonic()
                if key in {"q", "Q", "\x1b", "\x03"}:
                    break
                if key == " ":
                    session.set_host_paused(
                        not session.host_paused,
                        now,
                        pause_label=translator.text("status.animation_paused"),
                    )
                elif key in {"m", "M"}:
                    if _run_adjustment(
                        screen, session, renderer, overlay, decoder, options, translator
                    ):
                        break
                elif key == "h":
                    _run_animation_help(screen, decoder, options, translator)
                else:
                    continue
                _paint_animation(
                    screen,
                    session,
                    renderer,
                    _terminal(options),
                    translator,
                    now=time.monotonic(),
                    overlay=overlay,
                )
                last_size = (get_terminal_size().columns, get_terminal_size().lines)
    except KeyboardInterrupt:
        pass
    finally:
        overlay.close()
        screen.finish()
        set_cursor_visible(screen.stream, True)
    return 0
