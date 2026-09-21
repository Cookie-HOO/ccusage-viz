from __future__ import annotations

import os
from typing import TextIO

from ccusage_viz.errors import QueryError, VizError
from ccusage_viz.i18n import Translator
from ccusage_viz.render.palette import get_color_scheme

_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"

_TRANSIENT_UNIFIED_DAILY_DATABASE_MARKERS = (
    "sqlite_busy",
    "sqlite_locked",
    "database is locked",
    "unable to open database file",
    "failed to inspect antigravity database",
)


def color_enabled(stream: TextIO, *, no_color: bool = False) -> bool:
    return stream.isatty() and not no_color and os.environ.get("TERM") != "dumb"


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


def is_transient_unified_daily_database_error(error: BaseException) -> bool:
    """Whether ``ccusage unified_daily`` hit a known transient local-db failure."""
    if not isinstance(error, QueryError) or error.key != "error.ccusage_failed":
        return False
    if error.values.get("query") != "unified_daily":
        return False
    stderr = error.values.get("stderr")
    if not isinstance(stderr, str):
        return False
    normalized = stderr.casefold()
    return any(marker in normalized for marker in _TRANSIENT_UNIFIED_DAILY_DATABASE_MARKERS)


def is_ccusage_query_error(error: BaseException) -> bool:
    """Whether an error was raised while running the ccusage provider."""
    return isinstance(error, QueryError) and error.key.startswith("error.ccusage_")


def ccusage_error_notice_lines(
    error: BaseException, translator: Translator
) -> tuple[str, ...] | None:
    """Return the compact follow-up shown after a ccusage query error."""
    if not is_ccusage_query_error(error):
        return None
    return (translator.text("notice.next_refresh_may_recover"),)


def transient_query_recovery_lines(
    error: BaseException,
    translator: Translator,
    *,
    initial: bool,
) -> tuple[str, ...] | None:
    """Return safe UI copy for a known transient local-db failure."""
    if not is_transient_unified_daily_database_error(error):
        return None
    recovery = translator.text("notice.next_refresh_may_recover")
    if initial:
        return (translator.text("status.data_temporarily_unavailable"), recovery)
    return (recovery,)


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
