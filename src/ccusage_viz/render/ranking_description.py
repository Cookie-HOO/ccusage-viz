from __future__ import annotations

import re
from dataclasses import dataclass

from ccusage_viz.formatting import sanitize_terminal_text
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme

_DESCRIPTION_LINK = re.compile(r"\[([^\]]+)\]\((https://[A-Za-z0-9][^\s)]*)\)")


@dataclass(frozen=True, slots=True)
class _DescriptionPart:
    text: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class _DescriptionEmphasis:
    text: str
    style: str | None = None


def _description_emphasis(value: str) -> tuple[_DescriptionEmphasis, ...]:
    """Parse the intentionally small, non-nesting star-emphasis subset."""
    parts: list[_DescriptionEmphasis] = []
    plain_start = 0
    position = 0
    while position < len(value):
        marker = "**" if value.startswith("**", position) else "*" if value[position] == "*" else ""
        before_is_star = position > 0 and value[position - 1] == "*"
        after = position + len(marker)
        after_is_star = after < len(value) and value[after] == "*"
        if not marker or before_is_star or after_is_star:
            position += 1
            continue
        end = value.find(marker, after)
        while end >= 0 and (
            value[end - 1] == "*"
            or (end + len(marker) < len(value) and value[end + len(marker)] == "*")
        ):
            end = value.find(marker, end + 1)
        content = value[after:end] if end >= 0 else ""
        if end < 0 or not content.strip() or "*" in content:
            position += 1
            continue
        if plain_start < position:
            parts.append(_DescriptionEmphasis(value[plain_start:position]))
        parts.append(_DescriptionEmphasis(content, "bold" if marker == "**" else "italic"))
        position = end + len(marker)
        plain_start = position
    if plain_start < len(value):
        parts.append(_DescriptionEmphasis(value[plain_start:]))
    return tuple(parts)


def _description_visible_text_part(value: str) -> str:
    return "".join(part.text for part in _description_emphasis(value))


def _description_parts(value: str) -> tuple[_DescriptionPart, ...]:
    """Parse the one safe inline description construct without executing source controls."""
    sanitized = sanitize_terminal_text(value, preserve_newlines=True).strip()
    parts: list[_DescriptionPart] = []
    position = 0
    for match in _DESCRIPTION_LINK.finditer(sanitized):
        if match.start() > position:
            parts.append(_DescriptionPart(sanitized[position : match.start()]))
        parts.append(_DescriptionPart(match.group(1), match.group(2)))
        position = match.end()
    if position < len(sanitized):
        parts.append(_DescriptionPart(sanitized[position:]))
    return tuple(parts)


def _terminal_link(value: str, url: str) -> str:
    """Attach a trusted https target with an OSC 8 link that has no visible URL."""
    return f"\x1b]8;;{url}\x1b\\{value}\x1b]8;;\x1b\\"


def _link_emphasis(value: str, context: RenderContext, *, color: int) -> str:
    """Keep links muted while making their interaction affordance legible."""
    if not context.color:
        return value
    return f"\x1b[38;5;{color}m\x1b[2;4m{value}\x1b[0m"


def _description_search_text(value: str) -> str:
    """Expose both visible labels and hidden link targets to local search."""
    return " ".join(
        _description_visible_text_part(part.text)
        if part.url is None
        else f"{_description_visible_text_part(part.text)} {part.url}"
        for part in _description_parts(value)
    )


def copyable_description_text(value: str) -> str:
    """Flatten a safe description into clipboard text without terminal controls."""
    return "".join(
        _description_visible_text_part(part.text)
        if part.url is None
        else f"{_description_visible_text_part(part.text)} {part.url}"
        for part in _description_parts(value)
    ).strip()


def description_visible_text(value: str) -> str:
    """Return only the text rendered for a description, excluding link targets."""
    return "".join(_description_visible_text_part(part.text) for part in _description_parts(value))


def _description_row_markup(row: str, source: str) -> str:
    """Restore intact safe links after plain-text description wrapping."""
    for part in _description_parts(source):
        visible_text = _description_visible_text_part(part.text)
        if visible_text not in row:
            continue
        markup = f"[{part.text}]({part.url})" if part.url is not None else part.text
        row = row.replace(visible_text, markup)
    return row


def _highlight_parts(value: str, query: str) -> tuple[tuple[str, bool], ...]:
    """Split plain text into unmatched/matched literal case-insensitive spans."""
    if not query:
        return ((value, False),)
    needle = query.casefold()
    folded = value.casefold()
    parts: list[tuple[str, bool]] = []
    position = 0
    while (match := folded.find(needle, position)) >= 0:
        if match > position:
            parts.append((value[position:match], False))
        end = match + len(query)
        parts.append((value[match:end], True))
        position = end
    if position < len(value):
        parts.append((value[position:], False))
    return tuple(parts)


def highlight_ranking_match(value: str, query: str, *, context: RenderContext) -> str:
    """Highlight every literal case-insensitive match without changing text width."""
    scheme = get_color_scheme(context.color_scheme)
    return "".join(
        styled_text(part, scheme.highlight, context, bold=True) if matched else part
        for part, matched in _highlight_parts(value, query)
    )


def render_ranking_description(value: str, context: RenderContext) -> str:
    """Render description text with the same muted treatment as Custom Ranking."""

    return _render_highlighted_description(value, "", context)


def _render_highlighted_description(value: str, query: str, context: RenderContext) -> str:
    """Render safe links, metadata tags, and star emphasis."""
    scheme = get_color_scheme(context.color_scheme)
    tag_parts = re.split(r"(`[^`]+`)", value)
    if len(tag_parts) > 1:
        return "".join(
            styled_text(f"[ {part[1:-1]} ]", scheme.muted, context)
            if part.startswith("`") and part.endswith("`")
            else _render_highlighted_description(part, query, context)
            for part in tag_parts
            if part
        )
    rendered: list[str] = []
    for description_part in _description_parts(value):
        emphasis = _description_emphasis(description_part.text)

        def render_emphasis(part: _DescriptionEmphasis, *, link: bool) -> str:
            if context.color and part.style is None and link:
                return _link_emphasis(part.text, context, color=scheme.muted)
            pieces: list[str] = []
            for text, matched in _highlight_parts(part.text, query):
                if not context.color:
                    pieces.append(text)
                    continue
                color = scheme.highlight if matched else scheme.muted
                styles = ["4"] if link else []
                if not matched:
                    styles.append("2")
                if matched or part.style == "bold":
                    styles.append("1")
                if part.style == "italic":
                    styles.append("3")
                pieces.append(f"\x1b[38;5;{color}m\x1b[{';'.join(styles)}m{text}\x1b[0m")
            return "".join(pieces)

        text = "".join(
            render_emphasis(part, link=description_part.url is not None) for part in emphasis
        )
        if description_part.url is None:
            rendered.append(text)
            continue
        rendered.append(_terminal_link(text, description_part.url))
        marker = _link_emphasis(" ↗", context, color=scheme.muted)
        rendered.append(_terminal_link(marker, description_part.url))
    return "".join(rendered)
