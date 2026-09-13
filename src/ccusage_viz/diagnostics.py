from __future__ import annotations

import os
from typing import TextIO

from ccusage_viz.errors import VizError
from ccusage_viz.i18n import Translator
from ccusage_viz.render.palette import get_color_scheme

_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"


def color_enabled(stream: TextIO, *, no_color: bool = False) -> bool:
    return (
        stream.isatty()
        and not no_color
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )


def _casefold_map(text: str) -> tuple[str, list[int]]:
    folded: list[str] = []
    indexes: list[int] = []
    for index, character in enumerate(text):
        value = character.casefold()
        folded.append(value)
        indexes.extend([index] * len(value))
    return "".join(folded), indexes


def highlight_matches(text: str, needle: str, color: int) -> str:
    folded_text, indexes = _casefold_map(text)
    folded_needle = needle.casefold()
    if not folded_needle:
        return text

    spans: list[tuple[int, int]] = []
    offset = 0
    while (found := folded_text.find(folded_needle, offset)) >= 0:
        start = indexes[found]
        end = indexes[found + len(folded_needle) - 1] + 1
        if not spans or start >= spans[-1][1]:
            spans.append((start, end))
        offset = found + len(folded_needle)

    if not spans:
        return text
    parts: list[str] = []
    previous = 0
    prefix = f"\x1b[38;5;{color}m{_BOLD}"
    for start, end in spans:
        parts.extend((text[previous:start], prefix, text[start:end], _RESET))
        previous = end
    parts.append(text[previous:])
    return "".join(parts)


def format_error(
    error: BaseException,
    translator: Translator,
    *,
    color: bool = False,
    color_scheme: str = "classic",
) -> str:
    if not isinstance(error, VizError):
        return str(error)
    values = dict(error.values)
    if color and error.key in {"error.selector_ambiguous", "error.selector_ambiguous_more"}:
        selector = values.get("selector")
        candidates = values.get("candidates")
        if isinstance(selector, str) and isinstance(candidates, str):
            values["candidates"] = highlight_matches(
                candidates, selector, get_color_scheme(color_scheme).highlight
            )
    try:
        return translator.text(error.key, **values)
    except (KeyError, IndexError, ValueError):
        return error.key
