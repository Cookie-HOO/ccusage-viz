from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from ccusage_viz.formatting import display_width, truncate_middle_width
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_description import _description_search_text
from ccusage_viz.trends import trend_glyph

RankingNumber = int | Decimal

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
