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


class InteractiveScreen:
    def __init__(self, stream: TextIO = sys.stdout) -> None:
        self.stream = stream
        self.painted = False
        self.finished = False
        self._lines: tuple[str, ...] = ()
        self._height: int | None = None

    def paint(
        self,
        body: str,
        status: str | None,
        controls: str | tuple[str, ...],
        notices: tuple[str, ...] = (),
        *,
        height: int | None = None,
        force: bool = False,
    ) -> None:
        control_lines = (controls,) if isinstance(controls, str) else controls
        body_lines = body.rstrip("\r\n").splitlines() if body else []
        status_lines = () if status is None else (status,)
        if height is not None:
            body_lines = body_lines[
                : max(0, height - len(notices) - len(status_lines) - len(control_lines))
            ]
        lines = [*status_lines, *body_lines]
        if height is not None:
            lines.extend(
                "" for _ in range(max(0, height - len(lines) - len(notices) - len(control_lines)))
            )
        lines.extend(notices)
        lines.extend(control_lines)
        next_lines = tuple(lines)
        if force or not self.painted or self._height != height:
            content = "\n".join(next_lines)
            self.stream.write(f"\x1b[H\x1b[2J{content}")
        else:
            updates = []
            for index, line in enumerate(next_lines):
                if index >= len(self._lines) or self._lines[index] != line:
                    updates.append(f"\x1b[{index + 1};1H\x1b[2K{line}")
            for index in range(len(next_lines), len(self._lines)):
                updates.append(f"\x1b[{index + 1};1H\x1b[2K")
            if updates:
                self.stream.write("".join(updates))
        self.stream.flush()
        self._lines = next_lines
        self._height = height
        self.painted = True

    def paint_status(self, status: str) -> None:
        self.stream.write(f"\x1b[H\x1b[2K{status}")
        self.stream.flush()
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
    color = not no_color and os.environ.get("TERM") != "dumb"
    return Terminal(actual.columns, actual.lines, color, ascii)
