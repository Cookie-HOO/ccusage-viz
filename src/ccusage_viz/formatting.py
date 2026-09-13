from __future__ import annotations

import re
import unicodedata

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def format_tokens(value: int) -> str:
    """Format token counts with decimal K/M/B suffixes."""
    absolute = abs(value)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= threshold:
            scaled = value / threshold
            precision = 0 if abs(scaled) >= 100 else 1
            text = f"{scaled:.{precision}f}"
            if precision:
                text = text.rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return str(value)


def format_summary_tokens(value: int) -> str:
    """Format summary token counts with fixed four-decimal compact precision."""
    absolute = abs(value)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= threshold:
            return f"{value / threshold:.4f}{suffix}"
    return str(value)


def format_percent(part: int, whole: int) -> str:
    return "0%" if whole <= 0 else f"{part / whole:.1%}"


def strip_ansi(value: str) -> str:
    return _ANSI.sub("", value)


def char_width(char: str) -> int:
    if not char or unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def display_width(value: str) -> int:
    return sum(char_width(char) for char in strip_ansi(value))


def center_text(value: str, width: int) -> str:
    """Clip and center text by terminal display width."""
    clipped = clip_width(value, width)
    return " " * max(0, (width - display_width(clipped)) // 2) + clipped


def clip_width(value: str, width: int) -> str:
    """Clip text without splitting wide characters or ANSI sequences."""
    output: list[str] = []
    used = 0
    position = 0
    styled = False
    while position < len(value):
        match = _ANSI.match(value, position)
        if match:
            sequence = match.group()
            output.append(sequence)
            styled = sequence != "\x1b[0m"
            position = match.end()
            continue
        char = value[position]
        size = char_width(char)
        if used + size > width:
            break
        output.append(char)
        used += size
        position += 1
    if position < len(value) and styled:
        output.append("\x1b[0m")
    return "".join(output)


def truncate_width(value: str, width: int, *, ellipsis: str = "…") -> str:
    if width <= 0:
        return ""
    if display_width(value) <= width:
        return value
    marker = ellipsis if display_width(ellipsis) <= width else ""
    remaining = width - display_width(marker)
    return clip_width(value, remaining) + marker


def truncate_middle_width(value: str, width: int, *, ellipsis: str = "…") -> str:
    if width <= 0:
        return ""
    if display_width(value) <= width:
        return value
    marker_width = display_width(ellipsis)
    if marker_width > width:
        return ""
    remaining = width - marker_width
    left_width = remaining // 2
    right_width = remaining - left_width
    left = clip_width(value, left_width)
    right = ""
    used = 0
    for char in reversed(value):
        size = char_width(char)
        if used + size > right_width:
            break
        right = char + right
        used += size
    return left + ellipsis + right


def pad_width(value: str, width: int, *, align: str = "left") -> str:
    padding = max(0, width - display_width(value))
    return (" " * padding + value) if align == "right" else (value + " " * padding)
