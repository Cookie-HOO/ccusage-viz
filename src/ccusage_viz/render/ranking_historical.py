from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
    pad_width,
    truncate_width,
    wrap_width,
)
from ccusage_viz.render.base import RenderContext, colored_mark, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_columns import _comparison_heading, _fit_comparison_widths
from ccusage_viz.render.ranking_description import (
    _description_row_markup,
    _render_highlighted_description,
    _terminal_link,
    description_visible_text,
    highlight_ranking_match,
)
from ccusage_viz.render.ranking_entries import (
    RankingNumber,
    RankingPresentationEntry,
    _compact_labels,
    _matches_search,
    _refresh_markers,
)
from ccusage_viz.render.ranking_viewport import RankingColumns
from ccusage_viz.trends import trend_glyph


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
        if context.style == "list" or search_query or not compact_labels
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

    list_style = context.style == "list"

    def formatted_label(entry: RankingPresentationEntry, label: str, width: int) -> str:
        marker = "" if list_style else f" | {entry.copy_marker}" if entry.copy_marker is not None else ""
        if entry.project_link is not None and not list_style:
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
        not list_style
        and context.density in {"full", "detailed"}
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
            if measure_only or list_style
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
            f"{entry.current / total:>5.1%}"
            if show_percentage and total and not pending and not list_style
            else ""
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

    if list_style:
        rank_heading = context.translator.text("label.ranking_column_rank")
        project_heading = context.translator.text("label.ranking_column_project")
        current_heading = context.translator.text("label.ranking_column_current")
        rank_column_width = rank_width
        desired_current_width = max(
            display_width(current_heading), *(display_width(row[3]) for row in rows)
        )
        if columns is not None:
            desired_current_width = columns.width("current", desired_current_width)
        # Keep a readable label available even when a Dataset supplies an
        # oversized value display. The rank and two separators are fixed list
        # geometry.
        label_minimum = min(8, max(1, context.width - rank_column_width - 3))
        current_width = min(
            desired_current_width,
            max(1, context.width - rank_column_width - label_minimum - 2),
        )
        if columns is not None:
            columns.width("current", current_width)
            columns.width("right", current_width)
        label_width = max(1, context.width - rank_column_width - current_width - 2)
        header = (
            f"{pad_width(truncate_width(rank_heading, rank_width), rank_width, align='right')} "
            f"{pad_width(truncate_width(project_heading, label_width), label_width)} "
            f"{pad_width(truncate_width(current_heading, current_width), current_width, align='right')}"
        )
        lines.append(clip_width(header, context.width))
        if columns is not None:
            columns.description_width = max(1, label_width)
        if measure_only:
            return "\n".join(lines)
        for rank, entry, label, value, *_rest in rows:
            rank_prefix = f"{rank:>{rank_width}} "
            # A description belongs beneath the label, not beneath the rank.
            # Derive its indent from the rendered rank prefix's display width
            # so ANSI styling in the description cannot affect its column.
            label_indent = " " * display_width(rank_prefix)
            row = (
                f"{rank_prefix}{formatted_label(entry, label, label_width)} "
                f"{pad_width(truncate_width(value, current_width), current_width, align='right')}"
            )
            lines.append(clip_width(row, context.width))
            if descriptions_visible and context.density != "minimal" and entry.description:
                description = description_visible_text(entry.description)
                for index, description_row in enumerate(wrap_width(description, label_width)[:2]):
                    if index == 1 and len(wrap_width(description, label_width)) > 2:
                        description_row = clip_width(description_row, max(0, label_width - 1)) + "…"
                    lines.append(
                        f"{label_indent}{_render_highlighted_description(_description_row_markup(description_row, entry.description), search_query, context)}"
                    )
        return "\n".join(lines)

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
        current_width, delta_width, rank_change_width, share_width = _fit_comparison_widths(
            context=context,
            rank_column_width=rank_column_width,
            current_width=current_width,
            delta_width=delta_width,
            share_width=share_width,
            rank_change_width=rank_change_width,
            growth_visible=growth_visible,
            rank_comparison_visible=rank_comparison_visible,
            show_percentage=show_percentage,
        )
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
                pad_width(truncate_width(project_heading, label_width), label_width),
                pad_width(
                    truncate_width(current_heading, current_width), current_width, align="right"
                ),
            ]
        else:
            fixed_width = rank_column_width + current_width + optional_width + 4 + optional_count
            available = max(2, context.width - fixed_width)
            label_width = min(label_width, max(1, available - 2))
            bar_width = max(1, available - label_width - 1)
            header_fields = [
                pad_width(rank_heading, rank_column_width, align="right"),
                pad_width(truncate_width(project_heading, label_width), label_width),
                pad_width(truncate_width(scale_heading, bar_width), bar_width),
                pad_width(
                    truncate_width(current_heading, current_width), current_width, align="right"
                ),
            ]
        if growth_visible:
            header_fields.append(
                pad_width(truncate_width(delta_heading, delta_width), delta_width, align="right")
            )
        if rank_comparison_visible:
            header_fields.append(
                pad_width(
                    truncate_width(rank_change_heading, rank_change_width),
                    rank_change_width,
                    align="right",
                )
            )
        if show_percentage:
            header_fields.append(
                pad_width(truncate_width(share_heading, share_width), share_width, align="right")
            )
        lines.append(clip_width(" ".join(header_fields), context.width))
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
            length = min(bar_width, max(0, round(entry.current / maximum * bar_width)))
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
                pad_width(truncate_width(current, current_width), current_width, align="right"),
            ]
            if growth_visible:
                fields.append(
                    pad_width(truncate_width(delta, delta_width), delta_width, align="right")
                )
            if rank_comparison_visible:
                fields.append(
                    pad_width(
                        truncate_width(rank_comparison, rank_change_width),
                        rank_change_width,
                        align="right",
                    )
                )
            if show_percentage:
                fields.append(
                    pad_width(truncate_width(share, share_width), share_width, align="right")
                )
            lines.append(clip_width(" ".join(fields), context.width))
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
        length = min(bar_width, max(0, round(entry.current / maximum * bar_width)))
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
