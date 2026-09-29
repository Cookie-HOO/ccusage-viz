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
    """Format summary token counts with up to two compact decimal places."""
    absolute = abs(value)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= threshold:
            text = f"{value / threshold:.2f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
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


def wrap_width(value: str, width: int) -> tuple[str, ...]:
    """Wrap plain text at whitespace without splitting wide characters."""
    if width <= 0:
        return ()
    words = value.split()
    if not words:
        return ("",)
    rows: list[str] = []
    row = ""
    for word in words:
        candidate = word if not row else f"{row} {word}"
        if row and display_width(candidate) > width:
            rows.append(row)
            row = ""
        while display_width(word) > width:
            part = ""
            for char in word:
                if display_width(part + char) > width:
                    break
                part += char
            rows.append(part)
            word = word[len(part) :]
        row = word if not row else f"{row} {word}"
    if row:
        rows.append(row)
    return tuple(rows)


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


def slice_width(value: str, start: int, width: int) -> str:
    """Return a display-cell slice without splitting ANSI sequences or wide glyphs."""

    if width <= 0:
        return ""
    start = max(0, start)
    end = start + width
    output: list[str] = []
    position = 0
    used = 0
    active_sgr = ""
    emitted = False
    while position < len(value):
        match = _ANSI.match(value, position)
        if match:
            sequence = match.group()
            active_sgr = "" if sequence == "\x1b[0m" else sequence
            if emitted and used < end:
                output.append(sequence)
            position = match.end()
            continue
        char = value[position]
        char_width_value = char_width(char)
        if used >= start and used + char_width_value <= end:
            if not emitted:
                if active_sgr:
                    output.append(active_sgr)
                emitted = True
            output.append(char)
        used += char_width_value
        position += 1
        if used >= end:
            break
    if emitted and active_sgr:
        output.append("\x1b[0m")
    return "".join(output)


def replace_width(value: str, start: int, replacement: str, *, width: int) -> str:
    """Replace a display-cell span while keeping ANSI sequences structurally intact."""

    start = max(0, start)
    end = min(width, start + display_width(replacement))
    output: list[str] = []
    position = 0
    used = 0
    active_sgr = ""
    suffix_sgr = ""
    inserted = False
    while position < len(value) and used < width:
        match = _ANSI.match(value, position)
        if match:
            sequence = match.group()
            active_sgr = "" if sequence == "\x1b[0m" else sequence
            if used < start or used >= end:
                output.append(sequence)
            if used >= end:
                suffix_sgr = active_sgr
            position = match.end()
            continue
        char = value[position]
        char_width_value = char_width(char)
        if used + char_width_value > width:
            break
        if used < start or used >= end:
            if not inserted and used >= end:
                output.extend(("\x1b[0m", replacement, "\x1b[0m"))
                if suffix_sgr:
                    output.append(suffix_sgr)
                inserted = True
            output.append(char)
        used += char_width_value
        position += 1
    if not inserted:
        output.extend(("\x1b[0m", replacement, "\x1b[0m"))
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
