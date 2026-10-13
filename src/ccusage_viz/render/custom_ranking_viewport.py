"""Prepare and window Custom Ranking facts without touching query lifecycles."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from decimal import Decimal

from ccusage_viz.formatting import center_text, clip_width, display_width, pad_width
from ccusage_viz.processing.custom_historical import CustomChartProjection
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.custom_ranking_preparation import prepare_custom_ranking
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    measure_ranking_columns,
    render_historical_ranking,
)
from ccusage_viz.render.ranking_viewport import RankingColumns, RankingViewport
from ccusage_viz.render.summary import format_custom_value
from ccusage_viz.scrollbar import Scrollbar


def render_custom_ranking_viewport(
    projection: CustomChartProjection,
    context: RenderContext,
    viewport: RankingViewport,
    *,
    heading: str,
    descriptions_visible: bool,
    search_query: str,
    search_editing: bool,
    show_visible_count: bool,
    copied_entry_id: str | None,
    item_spacing: str,
    scrollbar: bool = False,
    scrollbar_hovered: bool = False,
    copy_all_action: bool = False,
    copied_all: bool = False,
) -> str:
    viewport.scrollbar = None
    viewport.copy_all_hit = None
    gutter = scrollbar and context.width > 1
    if gutter:
        context = replace(context, width=context.width - 1)
    config = projection.config
    reset_key = (
        (config.source, config.metric_id, config.group_by, config.filters, config.date_range)
        if config
        else None,
        search_query,
    )
    reset_changed = reset_key != viewport.reset_key
    if reset_changed:
        viewport.offset = 0
        viewport.reset_key = reset_key
    comparison = config.ranking_comparison if config else "full"
    viewport.comparison_visible = (
        context.style != "list"
        and context.density in {"full", "detailed"}
        and context.width >= 58
        and context.period != "all"
        and projection.comparison_available
        and comparison == "full"
    )
    viewport.percentage_visible = (
        projection.show_percentage and context.style != "list" and not context.pending
    )
    # Entry facts are stable across presentation changes. The source identity
    # plus locale and query define the localized, filtered entry projection.
    data_key = (context.translator.language, projection.unit, search_query)
    rebuild_data = viewport.source is not projection.series or viewport.data_key != data_key
    # These facts can alter column widths, chrome height, wrapping, or row
    # spacing. List style has its own label-prioritized row layout; themes only
    # change marks.
    geometry_key = (
        context.width,
        context.style,
        context.density,
        context.period,
        context.pending,
        projection.unit,
        comparison,
        projection.comparison_available,
        projection.show_percentage,
        descriptions_visible,
        search_editing,
        item_spacing,
    )
    rebuild_geometry = rebuild_data or viewport.geometry_key != geometry_key
    anchor_id: str | None = None
    old_anchor_index: int | None = None
    old_entries = viewport.entries
    if rebuild_geometry and not reset_changed and viewport.entries:
        anchor_index = max(
            0,
            min(
                len(viewport.entries) - 1,
                bisect_right(viewport.starts, viewport.offset) - 1,
            ),
        )
        anchor_id = str(viewport.entries[anchor_index].key)
        old_anchor_index = anchor_index

    def value(number: int | Decimal) -> str:
        return format_custom_value(
            Decimal(number), projection.unit, language=context.translator.language
        )

    def render(
        entries: tuple[RankingPresentationEntry, ...], offset: int, *, measure: bool = False
    ) -> str:
        if copied_entry_id is not None and not measure:
            entries = tuple(
                replace(entry, copy_marker="✓") if entry.key == copied_entry_id else entry
                for entry in entries
            )
        return render_historical_ranking(
            entries,
            heading=heading,
            context=context,
            pending=context.pending,
            value_formatter=value,
            delta_formatter=lambda number: f"{'+' if number > 0 else '-'}{value(abs(number))}",
            total=viewport.full_total,
            maximum=viewport.full_maximum,
            descriptions_visible=descriptions_visible,
            search_query=search_query,
            search_editing=search_editing,
            show_visible_count=show_visible_count,
            comparison_mode=comparison,
            comparison_available=projection.comparison_available and bool(viewport.entries),
            show_new_entries=True,
            compact_labels=False,
            label_max_width=48,
            total_entry_count=len(viewport.full_entries),
            matched_entry_count=len(viewport.entries),
            rank_offset=offset,
            show_percentage=projection.show_percentage,
            columns=viewport.columns,
            measure_only=measure,
            entries_matched=True,
        )

    if rebuild_data:
        viewport.invalidate_geometry()
        prepared = prepare_custom_ranking(
            projection,
            context,
            search_query=search_query,
            copy_marker=lambda entry: None if entry.is_other else "⊞",
        )
        viewport.full_entries = prepared.full_entries
        viewport.entries = prepared.matched_entries
        viewport.by_id = prepared.by_id
        viewport.full_total = prepared.full_total
        viewport.full_maximum = prepared.full_maximum
        viewport.source = projection.series
        viewport.data_key = data_key
    if rebuild_geometry:
        if not viewport.restore_geometry(geometry_key):
            viewport.columns = RankingColumns()
            if viewport.entries:
                measure_ranking_columns(
                    viewport.entries,
                    context=context,
                    total=viewport.full_total,
                    show_percentage=projection.show_percentage,
                    comparison_mode=comparison,
                    comparison_available=projection.comparison_available,
                    show_new_entries=True,
                    total_entry_count=len(viewport.entries),
                    columns=viewport.columns,
                )
            viewport.prepare_lines(descriptions=descriptions_visible, spacing=item_spacing)
            viewport.remember_geometry(geometry_key)
        if anchor_id is not None and old_anchor_index is not None:
            surviving_id = anchor_id if anchor_id in viewport.by_id else None
            for distance in range(1, len(old_entries)):
                if surviving_id is not None:
                    break
                for index in (old_anchor_index + distance, old_anchor_index - distance):
                    if 0 <= index < len(old_entries):
                        candidate = str(old_entries[index].key)
                        if candidate in viewport.by_id:
                            surviving_id = candidate
                            break
            if surviving_id is not None:
                new_index = next(
                    index
                    for index, entry in enumerate(viewport.entries)
                    if str(entry.key) == surviving_id
                )
                viewport.offset = viewport.starts[new_index]
        # render() clamps only after deriving visible_rows from the current
        # chrome and context height; the previous viewport size may be stale.
        viewport.geometry_key = geometry_key
    if not projection.series:
        viewport.active = True
        viewport.offset = viewport.total_rows = viewport.visible_rows = 0
        viewport.hits.clear()
        return "\n".join(
            (
                center_text(heading, context.width),
                context.translator.text("message.custom_no_data"),
            )[: max(0, context.height)]
        )
    rendered = viewport.render(
        render,
        render_chrome=lambda: render(viewport.entries[:1], 0, measure=True),
        context=context,
        spacing=item_spacing,
    )
    if (
        context.style != "list"
        and copy_all_action
        and context.density != "minimal"
        and any(not entry.is_other for entry in viewport.entries)
        and viewport.body_top > 0
    ):
        rows = rendered.splitlines()
        marker = "✓" if copied_all else "⊞"
        # Historical Ranking chrome is heading, optional search prompt, then
        # the visible-count row. Keep copy-all attached to that count rather
        # than to the heading or the scrollable table.
        row = 1 + int(bool(search_query or search_editing))
        if row < viewport.body_top and row < len(rows):
            prefix = clip_width(rows[row].rstrip(), max(0, context.width - 4))
            column = display_width(prefix) + 3
            rows[row] = f"{prefix} | {marker}"
            viewport.copy_all_hit = (row, column)
            rendered = "\n".join(rows)
    if gutter and viewport.visible_rows > 0 and viewport.total_rows > viewport.visible_rows:
        bar = Scrollbar(
            context.width,
            viewport.body_top,
            viewport.visible_rows,
            viewport.total_rows,
            viewport.visible_rows,
            viewport.offset,
        )
        viewport.scrollbar = bar
        scheme = get_color_scheme(context.color_scheme)
        rows = rendered.splitlines()
        rows.extend("" for _ in range(context.height - len(rows)))
        for row in range(bar.top, bar.top + bar.height):
            mark, color, bold = bar.mark_at(
                row,
                ascii=context.ascii,
                hovered=scrollbar_hovered,
                highlight=scheme.highlight,
                muted=scheme.muted,
            )
            rows[row] = pad_width(
                clip_width(rows[row], context.width), context.width
            ) + styled_text(mark, color, context, bold=bold)
        rendered = "\n".join(rows)
    return rendered
