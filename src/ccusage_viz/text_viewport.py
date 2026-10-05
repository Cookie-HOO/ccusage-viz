from __future__ import annotations

from dataclasses import dataclass

from ccusage_viz.formatting import wrap_width


def wrap_text_rows(text: str, *, width: int) -> tuple[str, ...]:
    """Wrap text into display-width rows while preserving explicit newlines."""

    if width <= 0:
        return ()
    if not text:
        return ()
    rows: list[str] = []
    for line in text.splitlines():
        rows.extend(wrap_width(line, width))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class TextViewport:
    """A clamped vertical window over complete rendered text."""

    body: str
    offset: int
    line_count: int
    visible_rows: int


def render_text_viewport(
    text: str | tuple[str, ...], *, offset: int, visible_rows: int
) -> TextViewport:
    """Return the visible rows of text and its valid scrolling position."""
    lines = (
        list(text)
        if isinstance(text, tuple)
        else text.rstrip("\r\n").splitlines()
        if text
        else []
    )
    visible_rows = max(0, visible_rows)
    maximum = max(0, len(lines) - visible_rows)
    offset = min(max(0, offset), maximum)
    body = "\n".join(lines[offset : offset + visible_rows]) if visible_rows else ""
    return TextViewport(body, offset, len(lines), visible_rows)


def text_viewport_overflows(*, line_count: int, visible_rows: int) -> bool:
    """Return whether a text viewport has content below its visible rows."""
    return line_count > max(0, visible_rows)


def next_text_offset(
    key: str,
    *,
    offset: int,
    line_count: int,
    visible_rows: int,
) -> int | None:
    """Return the next viewport offset for a scrolling key, if any."""
    maximum = max(0, line_count - max(0, visible_rows))
    offset = min(max(0, offset), maximum)
    if key == "\x1b[A":
        return max(0, offset - 1)
    if key == "\x1b[B":
        return min(maximum, offset + 1)
    if key in {"h", "\x1b[H"}:
        return 0
    if key == "e":
        return maximum
    return None
