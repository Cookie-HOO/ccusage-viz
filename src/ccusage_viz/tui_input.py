from __future__ import annotations

import os
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


class InputDecoder:
    """Decode ordinary keys and xterm SGR mouse reports from a byte buffer."""

    def __init__(self) -> None:
        self.buffer = ""
        self.escape_at: float | None = None

    def feed(self, value: str) -> None:
        self.buffer += value

    def next(self, *, now: float | None = None) -> InputEvent | None:
        now = time.monotonic() if now is None else now
        if not self.buffer:
            return None
        if self.buffer[0] != "\x1b":
            value, self.buffer = self.buffer[0], self.buffer[1:]
            return KeyEvent(value)
        if not self.buffer.startswith("\x1b["):
            if len(self.buffer) == 1:
                if self.escape_at is None:
                    self.escape_at = now
                    return None
                if now - self.escape_at < 0.03:
                    return None
            self.escape_at = None
            self.buffer = self.buffer[1:]
            return KeyEvent("\x1b")
        self.escape_at = None
        final = next(
            (index for index, char in enumerate(self.buffer[2:], 2) if "@" <= char <= "~"), None
        )
        if final is None:
            return None
        sequence, self.buffer = self.buffer[: final + 1], self.buffer[final + 1 :]
        if sequence in {"\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D"}:
            return KeyEvent(sequence)
        if sequence.startswith("\x1b[<") and sequence[-1] in {"M", "m"}:
            try:
                button, x, y = (int(value) for value in sequence[3:-1].split(";"))
            except ValueError:
                return None
            return MouseEvent(button & 0b11, x, y, sequence[-1] == "M", button & ~0b11)
        return None


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
        sys.stdout.write("\x1b[?1000h\x1b[?1006h")
        sys.stdout.flush()
        yield decoder
    finally:
        sys.stdout.write("\x1b[?1000l\x1b[?1006l")
        sys.stdout.flush()
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
