from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from shutil import get_terminal_size
from typing import TextIO

from ccusage_viz.errors import UsageError
from ccusage_viz.options import MINIMUM_SIZES


@dataclass(frozen=True, slots=True)
class Terminal:
    width: int
    height: int
    color: bool
    ascii: bool


@dataclass(frozen=True, slots=True)
class Frame:
    rows: tuple[str, ...]


def compose_frame(
    body: str,
    status: str | None,
    controls: str | tuple[str, ...],
    notices: tuple[str, ...] = (),
    *,
    height: int | None = None,
) -> Frame:
    control_rows = (controls,) if isinstance(controls, str) else controls
    body_rows = body.rstrip("\r\n").splitlines() if body else []
    status_rows = () if status is None else (status,)
    if height is not None:
        body_rows = body_rows[
            : max(0, height - len(notices) - len(status_rows) - len(control_rows))
        ]
    rows = [*status_rows, *body_rows]
    if height is not None:
        rows.extend(
            "" for _ in range(max(0, height - len(rows) - len(notices) - len(control_rows)))
        )
    rows.extend(notices)
    rows.extend(control_rows)
    return Frame(tuple(rows))


class FramePainter:
    def __init__(self, stream: TextIO = sys.stdout) -> None:
        self.stream = stream
        self.painted = False
        self.finished = False
        self._frame: Frame | None = None

    def paint(self, frame: Frame, *, force: bool = False) -> None:
        if force or not self.painted or self._frame is None:
            self.stream.write("\x1b[H\x1b[2J" + "\n".join(frame.rows))
        else:
            updates = []
            for index, row in enumerate(frame.rows):
                if index >= len(self._frame.rows) or self._frame.rows[index] != row:
                    updates.append(f"\x1b[{index + 1};1H\x1b[2K{row}")
            for index in range(len(frame.rows), len(self._frame.rows)):
                updates.append(f"\x1b[{index + 1};1H\x1b[2K")
            if updates:
                self.stream.write("".join(updates))
        self.stream.flush()
        self._frame = frame
        self.painted = True

    def finish(self) -> None:
        if self.painted and not self.finished:
            self.stream.write("\n")
            self.stream.flush()
            self.finished = True


def inspect_terminal(
    command: str,
    *,
    stream: TextIO = sys.stdout,
    no_color: bool = False,
    ascii: bool = False,
    size: os.terminal_size | None = None,
) -> Terminal:
    if not stream.isatty():
        raise UsageError("error.tty")
    if os.environ.get("TERM") == "dumb" and not ascii:
        raise UsageError("error.arguments", detail="TERM=dumb requires explicit --ascii")
    actual = size or get_terminal_size()
    minimum_width, minimum_height = MINIMUM_SIZES[command]
    if actual.columns < minimum_width or actual.lines < minimum_height:
        raise UsageError(
            "error.terminal_size",
            width=actual.columns,
            height=actual.lines,
            command=command,
            minimum_width=minimum_width,
            minimum_height=minimum_height,
        )
    return Terminal(actual.columns, actual.lines, not no_color, ascii)
