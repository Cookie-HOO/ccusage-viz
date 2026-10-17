from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from ccusage_viz.formatting import (
    clip_width,
    display_width,
    pad_width,
    strip_ansi,
    truncate_width,
    wrap_width,
)
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_description import (
    _description_row_markup,
    _render_highlighted_description,
    _terminal_link,
    description_visible_text,
)
from ccusage_viz.render.ranking_entries import RankingNumber, RankingPresentationEntry
from ccusage_viz.render.ranking_viewport import RankingColumns
from ccusage_viz.trends import trend_glyph


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
    if context.style == "list":
        desired_value_width = max(
            1,
            display_width(context.translator.text("label.ranking_column_current")),
            *(
                entry.display_width
                if entry.display_width is not None
                else display_width(entry.display or "")
                for entry in entries
            ),
        )
        # Reserve a readable label and both separators before assigning the
        # value column. Dataset-owned display strings must not consume label
        # space.
        label_minimum = min(8, max(1, context.width - rank_width - 3))
        value_width = min(
            desired_value_width, max(1, context.width - rank_width - label_minimum - 2)
        )
        columns.width("current", value_width)
        columns.width("right", value_width)
        columns.description_width = max(1, context.width - rank_width - value_width - 2)
        return
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

def _fit_comparison_widths(
    *,
    context: RenderContext,
    rank_column_width: int,
    current_width: int,
    delta_width: int,
    share_width: int,
    rank_change_width: int,
    growth_visible: bool,
    rank_comparison_visible: bool,
    show_percentage: bool,
) -> tuple[int, int, int, int]:
    """Contract shared scalar columns to the terminal's finite cell budget."""
    widths = [
        max(1, current_width),
        max(1, delta_width) if growth_visible else 0,
        max(1, rank_change_width) if rank_comparison_visible else 0,
        max(1, share_width) if show_percentage else 0,
    ]
    field_count = 3 + sum((growth_visible, rank_comparison_visible, show_percentage))
    content_minimum = 1 if context.style == "list" else 2
    scalar_budget = max(
        len([width for width in widths if width]),
        context.width - rank_column_width - (field_count - 1) - content_minimum,
    )
    overflow = max(0, sum(widths) - scalar_budget)
    # Preserve the current value first; optional columns contract in stable
    # lowest-priority order before the mandatory current column does.
    for index in (2, 3, 1, 0):
        reducible = max(0, widths[index] - 1)
        reduction = min(overflow, reducible)
        widths[index] -= reduction
        overflow -= reduction
    return widths[0], widths[1], widths[2], widths[3]

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
    comparison_mode: str = "full",
    show_percentage: bool = True,
    total_entry_count: int = 0,
    columns: RankingColumns | None = None,
) -> tuple[str, ...]:
    """Render a secondary Ranking heading on the shared Ranking column grid."""
    scheme = get_color_scheme(context.color_scheme)
    plain_label = strip_ansi(label).replace(chr(27), "")
    if context.style == "list":
        desired_value_width = max(
            1,
            columns.widths.get("current", columns.widths.get("right", display_width(value)))
            if columns
            else display_width(value),
        )
        # Fit the scalar while retaining a readable supplied label.
        label_minimum = min(8, max(1, context.width - 2))
        value_width = min(desired_value_width, max(1, context.width - label_minimum - 1))
        label_width = max(1, context.width - value_width - 1)
        row = (
            f"{pad_width(truncate_width(plain_label, label_width), label_width)} "
            f"{pad_width(truncate_width(value, value_width), value_width, align='right')}"
        )
        rows = [styled_text(clip_width(row, context.width), scheme.muted, context, bold=True)]
        if descriptions_visible and context.density != "minimal" and description:
            visible = description_visible_text(description)
            wrapped = wrap_width(visible, max(1, context.width))
            for index, text in enumerate(wrapped[:2]):
                if index == 1 and len(wrapped) > 2:
                    text = clip_width(text, max(0, context.width - 1)) + "…"
                rows.append(
                    _render_highlighted_description(
                        _description_row_markup(text, description), "", context
                    )
                )
        return tuple(rows)
    marker = f" · {_terminal_link('→', link)}" if link is not None else ""
    heading_label = f"{plain_label}{marker}"
    growth_visible = comparison_visible and comparison_mode == "full"
    rank_comparison_visible = (
        comparison_visible and context.density == "detailed" and context.width >= 75
    )
    if comparison_visible and columns is not None:
        rank_width = max(2, display_width(str(total_entry_count)))
        rank_column_width = max(
            rank_width + 4,
            display_width(context.translator.text("label.ranking_column_rank")),
        )
        current_width = columns.widths.get("current", max(1, display_width(value)))
        delta_width = columns.widths.get("delta", 0) if growth_visible else 0
        share_width = columns.widths.get("share", 0) if show_percentage else 0
        rank_change_width = columns.widths.get("rank_change", 0) if rank_comparison_visible else 0
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
            fixed_width = rank_column_width + current_width + optional_width + 2 + optional_count
            label_width = min(48, max(1, context.width - fixed_width))
            prefix_width = rank_column_width + 1 + label_width
        else:
            fixed_width = rank_column_width + current_width + optional_width + 4 + optional_count
            available = max(2, context.width - fixed_width)
            label_width = min(48, max(1, available - 2))
            bar_width = max(1, available - label_width - 1)
            prefix_width = rank_column_width + 1 + label_width + 1 + bar_width
        fields = [
            pad_width(truncate_width(heading_label, prefix_width), prefix_width),
            pad_width(truncate_width(value, current_width), current_width, align="right"),
        ]
        if growth_visible:
            fields.append(
                pad_width(truncate_width(delta, delta_width), delta_width, align="right")
            )
        if rank_comparison_visible:
            fields.append(" " * rank_change_width)
        if show_percentage:
            fields.append(
                pad_width(truncate_width(share, share_width), share_width, align="right")
            )
        row = clip_width(" ".join(fields), context.width)
    else:
        right_fields = [value]
        if growth_visible and delta:
            right_fields.append(delta)
        if show_percentage and share:
            right_fields.append(share)
        right = "  ".join(field for field in right_fields if field)
        measured_right = (
            columns.widths.get("right", display_width(right)) if columns else display_width(right)
        )
        right_width = min(measured_right, max(1, context.width // 2))
        label_width = max(1, context.width - right_width - int(bool(right)))
        visible_label = truncate_width(heading_label, label_width)
        row = pad_width(visible_label, label_width)
        if right:
            row = (
                f"{row} {pad_width(truncate_width(right, right_width), right_width, align='right')}"
            )
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
