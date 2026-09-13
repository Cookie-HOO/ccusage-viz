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

    def paint(
        self,
        body: str,
        status: str,
        controls: str | tuple[str, ...],
        notices: tuple[str, ...] = (),
        *,
        height: int | None = None,
    ) -> None:
        control_lines = (controls,) if isinstance(controls, str) else controls
        body_lines = body.rstrip("\r\n").splitlines() if body else []
        if height is not None:
            body_lines = body_lines[: max(0, height - len(notices) - 1 - len(control_lines))]
        lines = [status, *body_lines, *notices]
        if height is not None:
            lines.extend("" for _ in range(max(0, height - len(lines) - len(control_lines))))
        lines.extend(control_lines)
        content = "\n".join(lines)
        self.stream.write(f"\x1b[H\x1b[2J{content}")
        self.stream.flush()
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
    color = not no_color and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    return Terminal(actual.columns, actual.lines, color, ascii)
