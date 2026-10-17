"""Display-cell differential output, with conservative control-sequence fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ccusage_viz.formatting import char_width

_SGR = re.compile(r"\x1b\[[0-9;:]*m")
_LINK = re.compile(r"\x1b]8;[^;\x1b\x07]*;([^\x1b\x07]*)(?:\x1b\\|\x07)")
_RESET = "\x1b[0m"
_CLOSE_LINK = "\x1b]8;;\x1b\\"


@dataclass(frozen=True, slots=True)
class _Glyph:
    text: str
    style: str
    link: str
    start: int
    width: int


def _cells(text: str) -> list[_Glyph] | None:
    glyphs: list[_Glyph] = []
    style = link = ""
    position = column = 0
    while position < len(text):
        sgr = _SGR.match(text, position)
        if sgr:
            sequence = sgr.group()
            style = "" if sequence in {"\x1b[m", _RESET} else style + sequence
            position = sgr.end()
            continue
        hyperlink = _LINK.match(text, position)
        if hyperlink:
            link = hyperlink.group() if hyperlink.group(1) else ""
            position = hyperlink.end()
            continue
        char = text[position]
        # Unsupported controls and complex graphemes retain the safe row path.
        if ord(char) < 32 or char == "\x7f" or char in {"\u200d", "\ufe0e", "\ufe0f"}:
            return None
        width = char_width(char)
        if width == 0:
            if not glyphs:
                return None
            glyphs[-1] = replace(glyphs[-1], text=glyphs[-1].text + char)
        else:
            glyphs.append(_Glyph(char, style, link, column, width))
            column += width
        position += 1
    return [glyph for glyph in glyphs for _ in range(glyph.width)]


def row_updates(previous: str, current: str, row: int) -> str:
    """Address only changed spans (row is one-based), never split wide glyphs."""
    old, new = _cells(previous), _cells(current)
    if old is None or new is None:
        return f"\x1b[{row};1H\x1b[2K{current}"
    width = max(len(old), len(new))
    old.extend(_Glyph(" ", "", "", i, 1) for i in range(len(old), width))
    new.extend(_Glyph(" ", "", "", i, 1) for i in range(len(new), width))
    changed = [left != right for left, right in zip(old, new, strict=True)]
    # A changed continuation must include both the old and new glyph in full.
    for index in range(width):
        if changed[index]:
            start = min(old[index].start, new[index].start)
            end = max(old[index].start + old[index].width, new[index].start + new[index].width)
            while start > 0 and (old[start].start < start or new[start].start < start):
                start = min(old[start].start, new[start].start)
            while end < width and (old[end].start < end or new[end].start < end):
                end = max(old[end].start + old[end].width, new[end].start + new[end].width)
            changed[start:end] = [True] * (end - start)
    output: list[str] = []
    index = 0
    while index < width:
        if not changed[index]:
            index += 1
            continue
        output.append(f"\x1b[{row};{index + 1}H")
        style = link = ""
        while index < width and changed[index]:
            glyph = new[index]
            if glyph.link != link:
                if link:
                    output.append(_CLOSE_LINK)
                if glyph.link:
                    output.append(glyph.link)
                link = glyph.link
            if glyph.style != style:
                if style:
                    output.append(_RESET)
                output.append(glyph.style)
                style = glyph.style
            output.append(glyph.text)
            index += glyph.width
        if link:
            output.append(_CLOSE_LINK)
        if style:
            output.append(_RESET)
    return "".join(output)
