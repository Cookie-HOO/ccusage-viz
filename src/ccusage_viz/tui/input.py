from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time

from ccusage_viz.terminal import set_cursor_visible
from ccusage_viz.tui.rendering import _pane_animation_deadline
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    WheelEvent,
    read_event,
)


def set_screen_cursor_visible(session: TuiSession, visible: bool) -> None:
    stream = getattr(session.screen, "stream", None)
    if stream is not None:
        set_cursor_visible(stream, visible)


def end_adjustment(session: TuiSession) -> None:
    session.adjustment_mode = None
    session.adjustment_timer = None
    session.focused = None
    session.grid_draft = None
    session.grid_error = None


def read_adjustment_event(session: TuiSession, decoder: InputDecoder) -> object:
    timeout = 0.1
    if session.help_overlay is not None:
        timeout = min(timeout, session.help_overlay.timer.remaining())
    deadline = animation_deadline(session)
    if deadline is not None:
        timeout = min(timeout, max(0.0, deadline - time.monotonic()))
    remaining = session.copy_feedback.remaining(now=time.monotonic())
    if remaining is not None:
        timeout = min(timeout, remaining)
    if session.help_overlay is not None:
        event = read_event(decoder, timeout)
        if isinstance(event, (KeyEvent, MouseEvent, PasteEvent, WheelEvent)) and (
            not (isinstance(event, KeyEvent) and event.value == "\x03")
        ):
            session.help_overlay.timer.record_input()
        elif event is None:
            session.help_overlay.timer.check()
        return event
    if session.adjustment_timer is None:
        return read_event(decoder, timeout)
    event = read_event(decoder, min(timeout, session.adjustment_timer.remaining()))
    if isinstance(event, (KeyEvent, MouseEvent, PasteEvent, WheelEvent)):
        session.adjustment_timer.record_input()
    elif event is None:
        session.adjustment_timer.check()
    return event


def raise_if_interrupt(session: TuiSession, event: object) -> object:
    """Route decoded Ctrl-C through the TUI's controlled cleanup path."""
    if isinstance(event, KeyEvent) and event.value == "\x03":
        raise KeyboardInterrupt
    return event


def animation_deadline(session: TuiSession) -> float | None:
    return min(
        (
            deadline
            for pane in session.panes
            if (deadline := _pane_animation_deadline(pane)) is not None
        ),
        default=None,
    )
