from __future__ import annotations

import os
import select
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import WARNING_COLOR


@contextmanager
def input_mode() -> Iterator[None]:
    if os.name != "posix":
        yield
        return
    import termios
    import tty

    if not sys.stdin.isatty():
        raise UsageError("error.tty")
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        attributes = termios.tcgetattr(descriptor)
        attributes[3] &= ~termios.ISIG
        termios.tcsetattr(descriptor, termios.TCSADRAIN, attributes)
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def read_key(timeout: float) -> str | None:
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                return msvcrt.getwch()
            time.sleep(min(0.05, timeout))
        return None
    readable, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if readable else None


def dimmed(text: str, *, color: bool) -> str:
    return f"\x1b[2m{text}\x1b[0m" if color else text


def notice_lines(
    notices: tuple[str, ...],
    *,
    width: int,
    color: bool,
    ascii: bool,
    translator: Translator,
    color_scheme: str = "classic",
) -> tuple[str, ...]:
    context = RenderContext(
        width,
        1,
        translator,
        color=color,
        ascii=ascii,
        color_scheme=color_scheme,
    )
    glyph = "!" if ascii else "⚠"
    notice_color = 255 if color_scheme == "mono" else WARNING_COLOR
    return tuple(
        clip_width(styled_text(f"{glyph} {notice}", notice_color, context, bold=True), width)
        for notice in notices
    )


def controls_line(controls: str, *, width: int, color: bool) -> str:
    return clip_width(dimmed(controls, color=color), width)
