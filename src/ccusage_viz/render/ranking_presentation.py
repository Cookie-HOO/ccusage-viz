"""Domain-neutral historical Ranking presentation body."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from ccusage_viz.formatting import (
    center_text,
    display_width,
    pad_width,
    truncate_middle_width,
    truncate_width,
)
from ccusage_viz.render.base import RenderContext, colored_mark, styled_text
from ccusage_viz.render.palette import get_color_scheme
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
) -> str:
    """Render rows and ccuv-owned comparison markers from raw values only."""
    label_width = min(28, max(8, context.width // 3))
    labels = _compact_labels(
        [
            context.translator.text("label.other") if entry.is_other else entry.label
            for entry in entries
        ],
        label_width,
    )
    values = ["??" if pending else value_formatter(entry.current) for entry in entries]
    value_width = max(map(display_width, values), default=1)
    bar_width = max(8, context.width - label_width - value_width - 22)
    maximum = max((entry.current for entry in entries), default=1) or 1
    total = total if total is not None else sum((entry.current for entry in entries), start=0)
    full, empty = ("#", ".") if context.ascii else ("█", "░")
    dot, track = ("o", ".") if context.ascii else ("●", "·")
    scheme = get_color_scheme(context.color_scheme)
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
    lines = [line for line in (summary, center_text(heading, context.width)) if line]
    for rank, (entry, label, value) in enumerate(
        zip(entries, labels, values, strict=True), start=1
    ):
        length = round(entry.current / maximum * bar_width)
        color = scheme.other if entry.is_other else scheme.highlight
        if context.style == "dot":
            mark = (
                track * max(0, length - 1)
                + colored_mark(dot, color, context)
                + track * (bar_width - length)
            )
        elif context.style == "dots":
            mark = colored_mark(dot * length, color, context) + track * (bar_width - length)
        elif context.style == "list":
            mark = ""
        else:
            mark = colored_mark(full * length, color, context) + empty * (bar_width - length)
        rank_marker, activity, value_marker = _refresh_markers(
            entry,
            context=context,
            deltas=deltas,
            rank_deltas=rank_deltas,
        )
        comparison = " "
        if (
            not pending
            and entry.comparison_ready
            and entry.previous is not None
            and not entry.is_other
        ):
            value_delta = entry.current - entry.previous
            rank_delta = (entry.previous_rank or prior_rank.get(entry.key, rank)) - rank
            glyph = trend_glyph(float(value_delta), ascii=context.ascii)
            trend_color = (
                scheme.trend_increase
                if value_delta > 0
                else scheme.trend_decrease
                if value_delta < 0
                else scheme.trend_neutral
            )
            comparison = styled_text(glyph, trend_color, context, bold=value_delta != 0)
            if value_delta:
                formatted_delta = (
                    delta_formatter(value_delta)
                    if delta_formatter is not None
                    else f"{value_delta:+}"
                )
                comparison += f" {formatted_delta}"
            if rank_delta:
                rank_color = scheme.trend_increase if rank_delta > 0 else scheme.trend_decrease
                comparison += " · " + styled_text(
                    trend_glyph(rank_delta, ascii=context.ascii), rank_color, context, bold=True
                )
        share = f" {entry.current / total:>5.1%}" if total and not pending else ""
        label = pad_width(truncate_width(label, label_width), label_width)
        if context.style == "list":
            lines.append(
                center_text(
                    f"{rank:>2} {rank_marker} {activity} {label} {value} "
                    f"{value_marker}{comparison}{share}",
                    context.width,
                )
            )
        else:
            lines.append(
                f"{rank:>2} {rank_marker} {activity} {label} {mark} "
                f"{pad_width(value, value_width, align='right')} {value_marker}{comparison}{share}"
            )
    return "\n".join(lines)
