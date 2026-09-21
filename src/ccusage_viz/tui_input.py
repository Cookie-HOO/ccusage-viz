from __future__ import annotations

import os
import re
import select
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeyEvent:
    value: str


@dataclass(frozen=True, slots=True)
class MouseEvent:
    button: int
    x: int
    y: int
    pressed: bool
    modifiers: int


InputEvent = KeyEvent | MouseEvent

_MOUSE_ENABLE = "\x1b[?1000h\x1b[?1006h"
_MOUSE_DISABLE = "\x1b[?1000l\x1b[?1006l"


def set_mouse_reporting(enabled: bool) -> None:
    """Enable or disable Dashboard mouse reports for the current terminal."""
    if os.name != "posix":
        return
    sys.stdout.write(_MOUSE_ENABLE if enabled else _MOUSE_DISABLE)
    sys.stdout.flush()


_ESCAPE_DELAY = 0.03
_CONTROL_SEQUENCE_DELAY = 0.1
_MAX_CONTROL_SEQUENCE_LENGTH = 64
_SGR_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_SGR_MOUSE_PREFIX = re.compile(r"\x1b\[<\d*(?:;\d*){0,2}$")
_MALFORMED_SGR_MOUSE = re.compile(r"\x1b\[<[^Mm]{0,61}[Mm]")
_UNKNOWN_CSI = re.compile(r"\x1b\[[0-?]+[ -/]*[@-~]")


class InputDecoder:
    """Decode ordinary keys and xterm SGR mouse reports from a byte buffer."""

    def __init__(self) -> None:
        self.buffer = ""
        self.escape_at: float | None = None
        self.control_at: float | None = None

    def feed(self, value: str) -> None:
        self.buffer += value

    def next(self, *, now: float | None = None) -> InputEvent | None:
        now = time.monotonic() if now is None else now
        if not self.buffer:
            return None
        if self.buffer[0] != "\x1b":
            return self._ordinary_key()
        if not self.buffer.startswith("\x1b["):
            return self._escape(now)
        self.escape_at = None
        return self._control_sequence(now)

    def _ordinary_key(self) -> KeyEvent:
        self.control_at = None
        value, self.buffer = self.buffer[0], self.buffer[1:]
        return KeyEvent(value)

    def _escape(self, now: float) -> KeyEvent | None:
        if len(self.buffer) == 1:
            if self.escape_at is None:
                self.escape_at = now
                return None
            if now - self.escape_at < _ESCAPE_DELAY:
                return None
        self.escape_at = None
        self.buffer = self.buffer[1:]
        return KeyEvent("\x1b")

    def _control_sequence(self, now: float) -> InputEvent | None:
        if self.control_at is None:
            self.control_at = now
        if (
            len(self.buffer) > _MAX_CONTROL_SEQUENCE_LENGTH
            or now - self.control_at >= _CONTROL_SEQUENCE_DELAY
        ):
            self._discard_control_prefix()
            return None

        if len(self.buffer) >= 3 and self.buffer[:3] in {
            "\x1b[A",
            "\x1b[B",
            "\x1b[C",
            "\x1b[D",
        }:
            value, self.buffer = self.buffer[:3], self.buffer[3:]
            self.control_at = None
            return KeyEvent(value)

        mouse = _SGR_MOUSE.match(self.buffer)
        if mouse is not None:
            button, x, y = (int(value) for value in mouse.groups()[:3])
            self.buffer = self.buffer[mouse.end() :]
            self.control_at = None
            return MouseEvent(button & 0b11, x, y, mouse.group(4) == "M", button & ~0b11)

        if self.buffer.startswith("\x1b[<"):
            if _SGR_MOUSE_PREFIX.match(self.buffer):
                return None
            malformed = _MALFORMED_SGR_MOUSE.match(self.buffer)
            if malformed is not None:
                self.buffer = self.buffer[malformed.end() :]
                self.control_at = None
                return None
            self._discard_control_prefix()
            return None

        unknown = _UNKNOWN_CSI.match(self.buffer)
        if unknown is not None:
            self.buffer = self.buffer[unknown.end() :]
            self.control_at = None
            return None
        if re.match(r"\x1b\[[0-?]*[ -/]*$", self.buffer):
            return None

        self._discard_control_prefix()
        return None

    def _discard_control_prefix(self) -> None:
        """Drop only the malformed control prefix and preserve ordinary input."""
        if self.buffer.startswith("\x1b[<"):
            match = re.match(r"\x1b\[<\d*(?:;\d*){0,2}", self.buffer)
            self.buffer = self.buffer[match.end() :] if match is not None else self.buffer[3:]
        else:
            self.buffer = self.buffer[2:]
        self.control_at = None


@contextmanager
def tui_input_mode() -> Iterator[InputDecoder]:
    """Enter cbreak mode and opt into SGR primary-button mouse reports on POSIX."""
    decoder = InputDecoder()
    if os.name != "posix":
        yield decoder
        return
    import termios
    import tty

    if not sys.stdin.isatty():
        from ccusage_viz.errors import UsageError

        raise UsageError("error.tty")
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        attributes = termios.tcgetattr(descriptor)
        attributes[3] &= ~termios.ISIG
        termios.tcsetattr(descriptor, termios.TCSADRAIN, attributes)
        set_mouse_reporting(True)
        yield decoder
    finally:
        try:
            set_mouse_reporting(False)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def read_event(decoder: InputDecoder, timeout: float) -> InputEvent | None:
    event = decoder.next()
    if event is not None:
        return event
    if os.name == "nt":
        import msvcrt

        if msvcrt.kbhit():
            decoder.feed(msvcrt.getwch())
        else:
            time.sleep(timeout)
    else:
        readable, _, _ = select.select([sys.stdin], [], [], timeout)
        if readable:
            decoder.feed(os.read(sys.stdin.fileno(), 4096).decode(errors="replace"))
    return decoder.next()
