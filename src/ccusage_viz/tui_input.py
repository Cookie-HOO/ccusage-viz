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


@dataclass(frozen=True, slots=True)
class PasteEvent:
    """One complete terminal bracketed-paste payload."""

    value: str


InputEvent = KeyEvent | MouseEvent | PasteEvent

_MOUSE_ENABLE = "\x1b[?1000h\x1b[?1006h\x1b[?2004h"
_MOUSE_DISABLE = "\x1b[?1000l\x1b[?1006l\x1b[?2004l"
_MOUSE_BUTTON_MASK = 0b11
_MOUSE_MOTION = 0b100000
_MOUSE_WHEEL = 0b1000000


def set_mouse_reporting(enabled: bool) -> None:
    """Enable or disable Dashboard mouse reports for the current terminal."""
    if os.name != "posix":
        return
    sys.stdout.write(_MOUSE_ENABLE if enabled else _MOUSE_DISABLE)
    sys.stdout.flush()


_ESCAPE_DELAY = 0.03
_CONTROL_SEQUENCE_DELAY = 0.1
_MAX_CONTROL_SEQUENCE_LENGTH = 64
_MAX_PENDING_INPUT_CHARS = 8_192
_MAX_BRACKETED_PASTE_CHARS = 1_048_576
_OVERLOAD_HIGH_WATER_CHARS = 512
_OVERLOAD_EVENT_INTERVAL = 1 / 120
_BRACKETED_PASTE_START = "\x1b[200~"
_BRACKETED_PASTE_END = "\x1b[201~"
_SGR_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
_SGR_MOUSE_PREFIX = re.compile(r"\x1b\[<\d*(?:;\d*){0,2}$")
_MALFORMED_SGR_MOUSE = re.compile(r"\x1b\[<[^Mm]{0,61}[Mm]")
_UNKNOWN_CSI = re.compile(r"\x1b\[[0-?]+[ -/]*[@-~]")


class InputDecoder:
    """Decode bounded terminal input while pacing only pathological backlogs."""

    def __init__(self) -> None:
        self.buffer = ""
        self.escape_at: float | None = None
        self.control_at: float | None = None
        self.overloaded = False
        self.last_emitted_at: float | None = None

    def feed(self, value: str) -> None:
        """Append terminal input, retaining one bounded bracketed paste atomically."""

        accepting_paste = self.buffer.startswith(_BRACKETED_PASTE_START)
        limit = _MAX_BRACKETED_PASTE_CHARS if accepting_paste else _MAX_PENDING_INPUT_CHARS
        if len(self.buffer) + len(value) > limit:
            self.buffer = ""
            self.escape_at = None
            self.control_at = None
            self.overloaded = False
            self.last_emitted_at = None
            return
        self.buffer += value
        self.overloaded = self.overloaded or len(self.buffer) > _OVERLOAD_HIGH_WATER_CHARS

    def pacing_remaining(self, *, now: float | None = None) -> float:
        """Return the overload delay before another ordinary event may be emitted."""

        if not self.overloaded or self.last_emitted_at is None:
            return 0.0
        now = time.monotonic() if now is None else now
        return max(0.0, self.last_emitted_at + _OVERLOAD_EVENT_INTERVAL - now)

    @property
    def awaiting_paste(self) -> bool:
        """Whether a complete bracketed paste needs another terminal read."""

        return (
            self.buffer.startswith(_BRACKETED_PASTE_START)
            and _BRACKETED_PASTE_END not in self.buffer[len(_BRACKETED_PASTE_START) :]
        )

    def next(self, *, now: float | None = None) -> InputEvent | None:
        now = time.monotonic() if now is None else now
        if self.pacing_remaining(now=now) > 0 and not self.buffer.startswith(
            _BRACKETED_PASTE_START
        ):
            return None
        while self.buffer:
            pending_before = len(self.buffer)
            if self.buffer.startswith(_BRACKETED_PASTE_START):
                event = self._bracketed_paste()
            elif self.buffer[0] != "\x1b":
                event = self._ordinary_key()
            elif not (self.buffer.startswith("\x1b[") or self.buffer.startswith("\x1bO")):
                event = self._escape(now)
            else:
                self.escape_at = None
                event = self._control_sequence(now)
            if event is None:
                if len(self.buffer) < pending_before:
                    continue
                return None
            if isinstance(event, PasteEvent):
                if not self.buffer:
                    self.overloaded = False
                return event
            self.last_emitted_at = now
            if not self.buffer:
                self.overloaded = False
            return event
        self.overloaded = False
        return None

    def _bracketed_paste(self) -> PasteEvent | None:
        end = self.buffer.find(_BRACKETED_PASTE_END, len(_BRACKETED_PASTE_START))
        if end < 0:
            if len(self.buffer) > _MAX_BRACKETED_PASTE_CHARS:
                self.buffer = ""
                self.escape_at = None
                self.control_at = None
            return None
        value = self.buffer[len(_BRACKETED_PASTE_START) : end]
        self.buffer = self.buffer[end + len(_BRACKETED_PASTE_END) :]
        self.control_at = None
        return PasteEvent(value)

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
        if now - self.control_at >= _CONTROL_SEQUENCE_DELAY:
            self._discard_control_prefix()
            return None

        if len(self.buffer) >= 3 and self.buffer[:3] in {
            "\x1b[A",
            "\x1b[B",
            "\x1b[C",
            "\x1b[D",
            "\x1b[H",
            "\x1b[F",
            "\x1bOH",
        }:
            value, self.buffer = self.buffer[:3], self.buffer[3:]
            self.control_at = None
            return KeyEvent("\x1b[H" if value == "\x1bOH" else value)
        if self.buffer.startswith("\x1b[1~"):
            self.buffer = self.buffer[4:]
            self.control_at = None
            return KeyEvent("\x1b[H")

        mouse = _SGR_MOUSE.match(self.buffer)
        if mouse is not None:
            button, x, y = (int(value) for value in mouse.groups()[:3])
            self.buffer = self.buffer[mouse.end() :]
            self.control_at = None
            modifiers = button & ~_MOUSE_BUTTON_MASK
            if modifiers & _MOUSE_WHEEL:
                return None
            return MouseEvent(button & _MOUSE_BUTTON_MASK, x, y, mouse.group(4) == "M", modifiers)

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
        attributes[0] &= ~termios.ICRNL
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
    """Return one event without reading ahead of pending decoder input."""

    event = decoder.next()
    if event is not None:
        return event
    if decoder.buffer:
        delay = decoder.pacing_remaining()
        if delay > 0:
            time.sleep(min(timeout, delay))
            return decoder.next()
        if not decoder.awaiting_paste and not decoder.buffer.startswith("\x1b"):
            return None
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
