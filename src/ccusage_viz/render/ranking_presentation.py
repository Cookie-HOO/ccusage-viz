"""Domain-neutral historical Ranking presentation body."""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
    pad_width,
    strip_ansi,
    truncate_middle_width,
    truncate_width,
    wrap_width,
)
from ccusage_viz.render.base import RenderContext, colored_mark, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_viewport import RankingColumns
from ccusage_viz.trends import trend_glyph

RankingNumber = int | Decimal
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
    # Preserve Dataset-authored line breaks. Automatic wrapping is applied only
    # within each source line by the terminal layout below.
    sanitized = strip_ansi(value).replace("\x1b", "").strip()
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


@dataclass(frozen=True, slots=True)
class RankingPresentationEntry:
    """Raw, presentation-neutral facts for one historical ranking row."""

    key: Hashable
    label: str
    current: RankingNumber
    previous: RankingNumber | None = None
    comparison_ready: bool = False
    is_other: bool = False
    previous_rank: int | None = None
    description: str | None = None
    display: str | None = None
    is_fallback: bool = False
    comparison_display: str | None = None
    copy_marker: str | None = None
    project_link: str | None = None
    # Stable, unstyled scalar facts prepared with the entry data.  Viewport
    # geometry may inspect every entry, so it must never need its formatter.
    display_width: int | None = None
    comparison_display_width: int | None = None
    # Absolute position in the complete current ranking. Search and viewport
    # windows may hide rows but must not renumber the survivors.
    rank: int | None = None


def _refresh_markers(
    entry: RankingPresentationEntry,
    *,
    context: RenderContext,
    deltas: Mapping[Hashable, float],
    rank_deltas: Mapping[Hashable, int],
) -> tuple[str, str, str]:
    """Return rank, activity, and value-change markers from the latest refresh."""
    if entry.is_other or context.pending:
        return " ", " ", " "

    scheme = get_color_scheme(context.color_scheme)
    rank_marker = " "
    rank_change = rank_deltas.get(entry.key, 0)
    if rank_change:
        rank_color = scheme.trend_increase if rank_change > 0 else scheme.trend_decrease
        rank_marker = styled_text(
            trend_glyph(rank_change, ascii=context.ascii), rank_color, context, bold=True
        )

    activity = " "
    value_marker = " "
    if entry.key in deltas:
        value_change = deltas[entry.key]
        value_color = (
            scheme.trend_increase
            if value_change > 0
            else scheme.trend_decrease
            if value_change < 0
            else scheme.trend_neutral
        )
        value_marker = styled_text(
            trend_glyph(value_change, ascii=context.ascii),
            value_color,
            context,
            bold=value_change != 0,
        )
        if value_change:
            activity = styled_text(
                "*" if context.ascii else "●", scheme.highlight, context, bold=True
            )
    return rank_marker, activity, value_marker


def _compact_labels(labels: Sequence[str], width: int) -> list[str]:
    """Compact a shared prefix when doing so leaves unique display labels."""
    if len(labels) < 2:
        return list(labels)
    candidates: set[str] = set()
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1 :]:
            common = left
            while common and not right.startswith(common):
                common = common[:-1]
            boundaries = [index for index, character in enumerate(common) if character in "-/\\"]
            meaningful = [index for index in boundaries if len(common) - index >= 4]
            boundary = max(meaningful, default=max(boundaries, default=-1))
            if boundary >= 3:
                candidates.add(common[: boundary + 1])

    best: tuple[int, str, list[int]] | None = None
    for prefix in candidates:
        indexes = [index for index, label in enumerate(labels) if label.startswith(prefix)]
        remainders = [labels[index][len(prefix) :] for index in indexes]
        if len(indexes) < 2 or any(not remainder for remainder in remainders):
            continue
        compact = [f"…{remainder}" for remainder in remainders]
        if len(set(compact)) != len(compact):
            continue
        saving = sum(
            display_width(labels[index]) - display_width(label)
            for index, label in zip(indexes, compact, strict=True)
        )
        candidate = (saving, prefix, indexes)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None or best[0] <= 0:
        return list(labels)

    _, prefix, indexes = best
    result = list(labels)
    for index in indexes:
        result[index] = truncate_middle_width(f"…{labels[index][len(prefix) :]}", width)
    return result


def _matches_search(entry: RankingPresentationEntry, query: str) -> bool:
    """Return whether a literal case-insensitive query occurs in a searchable field."""
    needle = query.casefold()
    return (
        not needle
        or needle in entry.label.casefold()
        or (
            entry.description is not None
            and needle in _description_search_text(entry.description).casefold()
        )
        or (entry.project_link is not None and needle in entry.project_link.casefold())
    )


def filter_ranking_entries(
    entries: Sequence[RankingPresentationEntry], query: str
) -> tuple[RankingPresentationEntry, ...]:
    """Keep ranking entries whose label or description contains ``query``."""
    return tuple(entry for entry in entries if _matches_search(entry, query))


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


def _comparison_heading(context: RenderContext) -> str:
    """Name the contiguous comparison window without mislabelling it as a rate."""
    period = context.period
    return (
        context.translator.text("label.ranking_previous_period", period=period)
        if period
        else context.translator.text("label.ranking_previous")
    )


def measure_ranking_columns(
    entries: Sequence[RankingPresentationEntry],
    *,
    context: RenderContext,
    total: RankingNumber | None,
    show_percentage: bool,
    comparison_mode: str,
    comparison_available: bool,
    show_new_entries: bool,
    total_entry_count: int,
    columns: RankingColumns,
) -> None:
    """Measure shared layout widths without formatting rows or refresh markers.

    This deliberately performs only scalar text and wrap-width facts so a
    presentation change can retain an exact scrollbar range without rendering
    the complete stable entry sequence.
    """
    rank_width = max(2, display_width(str(total_entry_count)))
    comparison_visible = (
        context.density in {"full", "detailed"}
        and context.width >= 58
        and context.period != "all"
        and comparison_mode != "none"
        and comparison_available
    )
    if not comparison_visible:
        desired_right_width = 1
        for entry in entries:
            value_width = entry.display_width
            if value_width is None:
                value_width = display_width(entry.display or "")
            desired_right_width = max(
                desired_right_width,
                value_width
                + (
                    display_width(f"{entry.current / total:>5.1%}")
                    if show_percentage and total
                    else 0
                )
                + 3,
            )
        columns.width("right", desired_right_width)
        columns.description_width = max(1, context.width - min(context.width, rank_width + 5))
        return

    growth_visible = comparison_mode == "full"
    rank_comparison_visible = context.density == "detailed" and context.width >= 75
    delta_heading = _comparison_heading(context)
    rank_change_heading = context.translator.text("label.ranking_column_rank_change")
    current_heading = context.translator.text("label.ranking_column_current")
    share_heading = context.translator.text("label.ranking_column_share") if show_percentage else ""
    previous_entries = tuple(
        item for item in entries if item.previous is not None and not item.is_other
    )
    prior_rank = {
        entry.key: rank
        for rank, entry in enumerate(
            sorted(
                previous_entries,
                key=lambda item: (-cast(RankingNumber, item.previous), str(item.key)),
            ),
            start=1,
        )
    }
    delta_width = display_width(delta_heading) if growth_visible else 0
    current_width = display_width(current_heading)
    share_width = display_width(share_heading) if show_percentage else 0
    rank_change_width = display_width(rank_change_heading) if rank_comparison_visible else 0
    for rank, entry in enumerate(entries, start=1):
        value_width = entry.display_width
        if value_width is None:
            value_width = display_width(entry.display or "")
        current_width = max(current_width, value_width + 2)
        if show_percentage and total:
            share_width = max(share_width, display_width(f"{entry.current / total:>5.1%}"))
        if not (entry.comparison_ready and entry.previous is not None and not entry.is_other):
            if growth_visible:
                delta = (
                    context.translator.text("label.ranking_new")
                    if show_new_entries and not entry.is_other
                    else "—"
                )
                delta_width = max(delta_width, display_width(delta))
            if rank_comparison_visible:
                rank_change_width = max(
                    rank_change_width,
                    display_width(
                        context.translator.text("label.ranking_new_rank")
                        if show_new_entries and not entry.is_other
                        else "—"
                    ),
                )
            continue
        value_delta = entry.current - entry.previous
        if growth_visible:
            delta = (
                "0"
                if value_delta == 0
                else entry.comparison_display
                if entry.comparison_display is not None
                else f"{value_delta:+}"
            )
            delta_width = max(
                delta_width,
                entry.comparison_display_width
                if entry.comparison_display_width is not None and value_delta != 0
                else display_width(delta),
            )
        if rank_comparison_visible:
            rank_delta = (entry.previous_rank or prior_rank.get(entry.key, rank)) - rank
            rank_change_width = max(
                rank_change_width,
                display_width(
                    "·" if rank_delta == 0 else trend_glyph(rank_delta, ascii=context.ascii)
                ),
            )
    columns.width("delta", delta_width)
    columns.width("current", current_width)
    columns.width("share", share_width)
    columns.width("rank_change", rank_change_width)
    rank_column_width = max(
        rank_width + 4, display_width(context.translator.text("label.ranking_column_rank"))
    )
    columns.description_width = max(1, context.width - min(context.width, rank_column_width + 1))


def render_ranking_heading_row(
    *,
    label: str,
    value: str,
    delta: str,
    share: str,
    description: str | None,
    context: RenderContext,
    link: str | None = None,
    descriptions_visible: bool = False,
    comparison_visible: bool = True,
) -> tuple[str, ...]:
    """Render a secondary Ranking heading without a rank or scale column."""
    scheme = get_color_scheme(context.color_scheme)
    marker = f" · {_terminal_link('→', link)}" if link is not None else ""
    right_fields = [value]
    if comparison_visible and delta:
        right_fields.append(delta)
    if share:
        right_fields.append(share)
    right = "  ".join(field for field in right_fields if field)
    right_width = min(display_width(right), max(1, context.width // 2))
    label_width = max(1, context.width - right_width - int(bool(right)))
    visible_label = truncate_width(f"{strip_ansi(label).replace(chr(27), '')}{marker}", label_width)
    row = pad_width(visible_label, label_width)
    if right:
        row = f"{row} {truncate_width(right, right_width)}"
    rows = [styled_text(row, scheme.muted, context, bold=True)]
    if descriptions_visible and context.density != "minimal" and description:
        visible = description_visible_text(description)
        wrapped = wrap_width(visible, max(1, context.width - 2))
        for index, text in enumerate(wrapped[:2]):
            if index == 1 and len(wrapped) > 2:
                text = clip_width(text, max(0, context.width - 3)) + "…"
            rows.append(
                "  "
                + _render_highlighted_description(
                    _description_row_markup(text, description), "", context
                )
            )
    return tuple(rows)


def render_historical_ranking(
    entries: Sequence[RankingPresentationEntry],
    *,
    heading: str,
    value_formatter: Callable[[RankingNumber], str],
    context: RenderContext,
    delta_formatter: Callable[[RankingNumber], str] | None = None,
    summary: str = "",
    pending: bool = False,
    total: RankingNumber | None = None,
    maximum: RankingNumber | None = None,
    show_percentage: bool = True,
    descriptions_visible: bool = False,
    search_query: str = "",
    search_editing: bool = False,
    show_visible_count: bool = False,
    comparison_mode: str = "full",
    comparison_available: bool = True,
    show_new_entries: bool = False,
    compact_labels: bool = True,
    label_max_width: int = 28,
    entry_offset: int = 0,
    entry_limit: int | None = None,
    total_entry_count: int | None = None,
    rank_offset: int = 0,
    item_spacing: str = "compact",
    columns: RankingColumns | None = None,
    measure_only: bool = False,
    entries_matched: bool = False,
    matched_entry_count: int | None = None,
) -> str:
    """Render rows and ccuv-owned comparison markers from raw values only."""
    total_entry_count = len(entries) if total_entry_count is None else total_entry_count
    ranked_entries = tuple(
        (
            entry.rank if entry.rank is not None else rank,
            entry,
        )
        for rank, entry in enumerate(entries, start=rank_offset + entry_offset + 1)
    )
    if not entries_matched:
        ranked_entries = tuple(
            (rank, entry) for rank, entry in ranked_entries if _matches_search(entry, search_query)
        )
    ranked_entries = (
        ranked_entries[entry_offset:]
        if entry_limit is None
        else ranked_entries[entry_offset : entry_offset + max(0, entry_limit)]
    )
    entries = tuple(entry for _, entry in ranked_entries)
    raw_labels = [
        context.translator.text("label.other") if entry.is_other else entry.label
        for entry in entries
    ]
    # Match native Ranking: reserve one stable label column so every track starts together.
    label_width = min(label_max_width, max(8, context.width // 3))
    # Do not hide a matching label segment behind shared-prefix compaction.
    labels = (
        raw_labels
        if search_query or not compact_labels
        else _compact_labels(raw_labels, label_width)
    )
    values = [
        "??"
        if pending
        else entry.display
        if entry.display is not None
        else value_formatter(entry.current)
        for entry in entries
    ]
    rank_width = max(2, display_width(str(total_entry_count)))
    maximum = (
        maximum if maximum is not None else max((entry.current for entry in entries), default=1)
    )
    # Callers that precompute extrema can legitimately supply Decimal(0) when
    # a growth window contains only unchanged projects. A zero scale still
    # needs a harmless denominator so rendering shows empty tracks instead of
    # raising decimal.DivisionUndefined.
    maximum = maximum or 1
    total = total if total is not None else sum((entry.current for entry in entries), start=0)
    full, empty = ("#", ".") if context.ascii else ("█", "░")
    dot, track = ("o", ".") if context.ascii else ("●", "·")
    scheme = get_color_scheme(context.color_scheme)

    def formatted_label(entry: RankingPresentationEntry, label: str, width: int) -> str:
        marker = f" | {entry.copy_marker}" if entry.copy_marker is not None else ""
        if entry.project_link is not None:
            link_marker = f" · {_terminal_link('→', entry.project_link)}"
            marker += link_marker
        marker_width = display_width(marker)
        text_width = max(1, width - marker_width)
        text = truncate_width(
            highlight_ranking_match(label, search_query, context=context), text_width
        )
        return pad_width(f"{text}{marker}", width)

    previous_entries = tuple(
        item for item in entries if item.previous is not None and not item.is_other
    )
    prior_rank = {
        entry.key: rank
        for rank, entry in enumerate(
            sorted(
                previous_entries,
                key=lambda item: (-cast(RankingNumber, item.previous), str(item.key)),
            ),
            start=1,
        )
    }
    deltas = context.deltas or {}
    rank_deltas = context.rank_deltas or {}
    # Summary facts remain a left-aligned preamble; the chart's title is centered
    # independently of it so both native and Custom Dataset rankings share chrome.
    lines = [line for line in (summary, center_text(heading, context.width)) if line]
    if search_query or search_editing:
        lines.append(
            context.translator.text(
                "label.ranking_search_editing" if search_editing else "label.ranking_search",
                query=search_query,
                cursor="▏",
            )
        )
    if show_visible_count and context.density != "minimal":
        lines.append(
            context.translator.text(
                "label.ranking_search_visible_items"
                if search_query
                else "label.ranking_visible_items",
                visible=len(entries) if matched_entry_count is None else matched_entry_count,
                total=total_entry_count,
                count=(total_entry_count if not search_query else len(entries))
                if matched_entry_count is None
                else matched_entry_count,
            )
        )
    if search_query and not entries:
        lines.append(context.translator.text("message.ranking_search_empty", query=search_query))
        return "\n".join(lines)
    # Keep narrow terminals readable: a comparison table is useful only after
    # there is room for a recognizable project label and a meaningful scale.
    comparison_visible = (
        context.density in {"full", "detailed"}
        and context.width >= 58
        and context.period != "all"
        and comparison_mode != "none"
        and comparison_available
    )
    growth_visible = comparison_visible and comparison_mode == "full"
    rank_comparison_visible = (
        comparison_visible and context.density == "detailed" and context.width >= 75
    )
    rows: list[tuple[int, RankingPresentationEntry, str, str, str, str, str, str, str, str]] = []
    for (rank, entry), label, value in zip(ranked_entries, labels, values, strict=True):
        rank_marker, activity, value_marker = (
            (" ", " ", " ")
            if measure_only
            else _refresh_markers(
                entry,
                context=context,
                deltas=deltas,
                rank_deltas=rank_deltas,
            )
        )
        value_delta = None
        rank_delta = None
        if (
            comparison_visible
            and not pending
            and entry.comparison_ready
            and entry.previous is not None
            and not entry.is_other
        ):
            value_delta = entry.current - entry.previous
            rank_delta = (entry.previous_rank or prior_rank.get(entry.key, rank)) - rank
        is_new_entry = (
            show_new_entries
            and comparison_visible
            and not pending
            and not entry.is_other
            and not entry.comparison_ready
        )
        if value_delta is None:
            delta = (
                context.translator.text("label.ranking_new")
                if growth_visible and is_new_entry
                else "—"
                if growth_visible and not pending
                else ""
            )
        elif not growth_visible:
            delta = ""
        elif value_delta == 0:
            delta = "0"
        else:
            delta = (
                entry.comparison_display
                if entry.comparison_display is not None
                else delta_formatter(value_delta)
                if delta_formatter is not None
                else f"{value_delta:+}"
            )
        if rank_delta is None or not rank_comparison_visible:
            rank_comparison = (
                context.translator.text("label.ranking_new_rank")
                if rank_comparison_visible and is_new_entry
                else "—"
                if rank_comparison_visible and not pending
                else ""
            )
        elif rank_delta == 0:
            rank_comparison = "·"
        else:
            rank_color = scheme.trend_increase if rank_delta > 0 else scheme.trend_decrease
            rank_comparison = (
                trend_glyph(rank_delta, ascii=context.ascii)
                if measure_only
                else styled_text(
                    trend_glyph(rank_delta, ascii=context.ascii), rank_color, context, bold=True
                )
            )
        share = (
            f"{entry.current / total:>5.1%}" if show_percentage and total and not pending else ""
        )
        rows.append(
            (
                rank,
                entry,
                label,
                value,
                rank_marker,
                activity,
                value_marker,
                delta,
                rank_comparison,
                share,
            )
        )

    if comparison_visible:
        rank_heading = context.translator.text("label.ranking_column_rank")
        project_heading = context.translator.text("label.ranking_column_project")
        scale_heading = context.translator.text("label.ranking_column_scale")
        current_heading = context.translator.text("label.ranking_column_current")
        delta_heading = _comparison_heading(context)
        share_heading = (
            context.translator.text("label.ranking_column_share") if show_percentage else ""
        )
        rank_change_heading = context.translator.text("label.ranking_column_rank_change")
        rank_column_width = max(rank_width + 4, display_width(rank_heading))
        delta_width = (
            max(display_width(delta_heading), *(display_width(row[7]) for row in rows))
            if growth_visible
            else 0
        )
        current_width = max(
            display_width(current_heading), *(display_width(row[3]) + 2 for row in rows)
        )
        share_width = (
            max(display_width(share_heading), *(display_width(row[9]) for row in rows))
            if show_percentage
            else 0
        )
        rank_change_width = (
            max(display_width(rank_change_heading), *(display_width(row[8]) for row in rows))
            if rank_comparison_visible
            else 0
        )
        if columns is not None:
            delta_width = columns.width("delta", delta_width)
            current_width = columns.width("current", current_width)
            share_width = columns.width("share", share_width)
            rank_change_width = columns.width("rank_change", rank_change_width)
        optional_width = delta_width + share_width + rank_change_width
        optional_count = sum((growth_visible, rank_comparison_visible, show_percentage))
        if context.style == "list":
            # List removes the graph column as a whole. Give its space to the
            # label and count only separators between fields that are rendered.
            fixed_width = rank_column_width + current_width + optional_width + 2 + optional_count
            label_width = min(label_width, max(1, context.width - fixed_width))
            bar_width = 0
            header_fields = [
                pad_width(rank_heading, rank_column_width, align="right"),
                pad_width(project_heading, label_width),
                pad_width(current_heading, current_width, align="right"),
            ]
        else:
            fixed_width = rank_column_width + current_width + optional_width + 4 + optional_count
            available = max(2, context.width - fixed_width)
            label_width = min(label_width, max(1, available - 2))
            bar_width = max(1, available - label_width - 1)
            header_fields = [
                pad_width(rank_heading, rank_column_width, align="right"),
                pad_width(project_heading, label_width),
                pad_width(scale_heading, bar_width),
                pad_width(current_heading, current_width, align="right"),
            ]
        if growth_visible:
            header_fields.append(pad_width(delta_heading, delta_width, align="right"))
        if rank_comparison_visible:
            header_fields.append(pad_width(rank_change_heading, rank_change_width, align="right"))
        if show_percentage:
            header_fields.append(pad_width(share_heading, share_width, align="right"))
        lines.append(" ".join(header_fields))
        if columns is not None:
            columns.description_width = max(
                1, context.width - min(context.width, rank_column_width + 1)
            )
        if measure_only:
            return "\n".join(lines)
        for (
            rank,
            entry,
            label,
            value,
            rank_marker,
            activity,
            value_marker,
            delta,
            rank_comparison,
            share,
        ) in rows:
            length = round(entry.current / maximum * bar_width)
            color = scheme.other if entry.is_other or entry.is_fallback else scheme.highlight
            if context.style == "dot":
                dot_length = max(1, length)
                mark = (
                    track * max(0, dot_length - 1)
                    + colored_mark(dot, color, context)
                    + track * (bar_width - dot_length)
                )
            elif context.style == "dots":
                mark = colored_mark(dot * length, color, context) + track * (bar_width - length)
            elif context.style == "list":
                mark = ""
            else:
                mark = colored_mark(full * length, color, context) + empty * (bar_width - length)
            label = formatted_label(entry, label, label_width)
            rank_value = f"{rank:>{rank_width}} {rank_marker} {activity}"
            current = f"{value} {value_marker}" if value_marker.strip() else value
            fields = [
                pad_width(rank_value, rank_column_width, align="right"),
                label,
                *(() if context.style == "list" else (mark,)),
                pad_width(current, current_width, align="right"),
            ]
            if growth_visible:
                fields.append(pad_width(delta, delta_width, align="right"))
            if rank_comparison_visible:
                fields.append(pad_width(rank_comparison, rank_change_width, align="right"))
            if show_percentage:
                fields.append(pad_width(share, share_width, align="right"))
            lines.append(" ".join(fields))
            if descriptions_visible and entry.description:
                indent = " " * min(context.width, rank_column_width + 1)
                available = max(1, context.width - display_width(indent))
                description = description_visible_text(entry.description)
                description_rows = wrap_width(
                    description,
                    available,
                )
                for index, row in enumerate(description_rows[:2]):
                    if index == 1 and len(description_rows) > 2:
                        row = clip_width(row, max(0, available - 1)) + "…"
                    lines.append(
                        f"{indent}{_render_highlighted_description(_description_row_markup(row, entry.description), search_query, context)}"
                    )
        return "\n".join(lines)

    desired_right_width = max(
        (
            display_width(row[3])
            + display_width(row[6])
            + (display_width(row[9]) if show_percentage else 0)
            + 2
            for row in rows
        ),
        default=1,
    )
    if columns is not None:
        desired_right_width = columns.width("right", desired_right_width)
        columns.description_width = max(1, context.width - min(context.width, rank_width + 5))
    if measure_only:
        return "\n".join(lines)
    # Keep all three columns within even a narrow viewport. At practical widths
    # this retains the usual eight-cell label and track minimums; when space is
    # scarce it contracts the columns together instead of letting a long
    # Dataset-owned display string push the row beyond the terminal edge.
    # The row has rank/status (``rank_width + 5``) plus two separators.
    content_width = max(3, context.width - rank_width - 7)
    right_width = min(desired_right_width, max(1, content_width - 2))
    label_width = min(label_width, max(1, content_width - right_width - 1))
    bar_width = max(1, content_width - label_width - right_width - 1)
    for (
        rank,
        entry,
        label,
        value,
        rank_marker,
        activity,
        value_marker,
        _delta,
        _rank_comparison,
        share,
    ) in rows:
        length = round(entry.current / maximum * bar_width)
        color = scheme.other if entry.is_other or entry.is_fallback else scheme.highlight
        if context.style == "dot":
            # A scaled value can round to zero in a one-cell narrow track;
            # retain exactly one endpoint cell instead of emitting dot + track.
            dot_length = max(1, length)
            mark = (
                track * max(0, dot_length - 1)
                + colored_mark(dot, color, context)
                + track * (bar_width - dot_length)
            )
        elif context.style == "dots":
            mark = colored_mark(dot * length, color, context) + track * (bar_width - length)
        elif context.style == "list":
            mark = ""
        else:
            mark = colored_mark(full * length, color, context) + empty * (bar_width - length)
        label = formatted_label(entry, label, label_width)
        right = truncate_width(
            f"{value} {value_marker}{share if show_percentage else ''}", right_width
        )
        if context.style == "list":
            # Center the fixed-width row as a column grid, rather than each
            # row's visible content, so labels and values retain one vertical
            # alignment across the list.
            list_width = rank_width + 5 + label_width + 1 + right_width
            list_row = (
                f"{rank:>{rank_width}} {rank_marker} {activity} {label} "
                f"{pad_width(right, right_width, align='right')}"
            )
            lines.append(" " * max(0, (context.width - list_width) // 2) + list_row)
        else:
            lines.append(
                pad_width(
                    f"{rank:>{rank_width}} {rank_marker} {activity} {label} {mark} "
                    f"{pad_width(right, right_width, align='right')}",
                    context.width,
                )
            )
        if descriptions_visible and context.density != "minimal" and entry.description:
            # Keep explanations aligned with the label column, not the chart track.
            indent = " " * min(context.width, rank_width + 5)
            available = max(1, context.width - display_width(indent))
            description = description_visible_text(entry.description)
            description_rows = wrap_width(description, available)
            for index, row in enumerate(description_rows[:2]):
                if index == 1 and len(description_rows) > 2:
                    row = clip_width(row, max(0, available - 1)) + "…"
                lines.append(
                    f"{indent}{_render_highlighted_description(_description_row_markup(row, entry.description), search_query, context)}"
                )
    return "\n".join(lines)
