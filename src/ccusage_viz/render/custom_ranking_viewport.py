"""Prepare and window Custom Ranking facts without touching query lifecycles."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from decimal import Decimal
from typing import cast

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.formatting import center_text, clip_width, display_width, pad_width
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    filter_ranking_entries,
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
    # Entry facts are stable across presentation changes. The source identity
    # plus locale and query define the localized, filtered entry projection.
    data_key = (context.translator.language, projection.unit, search_query)
    rebuild_data = viewport.source is not projection.series or viewport.data_key != data_key
    # These facts can alter column widths, chrome height, wrapping, or row
    # spacing. Styles and themes intentionally do not: they only change marks.
    geometry_key = (
        context.width,
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
            value_formatter=value,
            delta_formatter=lambda number: f"{'+' if number > 0 else '-'}{value(abs(number))}",
            total=viewport.total,
            maximum=viewport.maximum,
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

        def localized(text: LocalizedText) -> str:
            return text.zh_cn if context.translator.language == "zh" else text.en

        def prepare_entry(entry: CustomProjectedSeries) -> RankingPresentationEntry:
            display = (
                localized(entry.display)
                if entry.display and not entry.is_other
                else value(entry.total)
            )
            comparison_display = (
                localized(entry.comparison_display)
                if entry.comparison_display and not entry.is_other
                else (
                    f"{'+' if entry.total > entry.previous_total else '-'}"
                    f"{value(abs(entry.total - entry.previous_total))}"
                    if entry.previous_total is not None and entry.total != entry.previous_total
                    else None
                )
            )
            return RankingPresentationEntry(
                entry.id,
                context.translator.text("label.other")
                if entry.is_other
                else localized(entry.label).replace("\n", "\\n"),
                entry.total,
                entry.previous_total,
                entry.comparison_ready,
                entry.is_other,
                entry.previous_rank,
                description=localized(entry.description)
                if entry.description and not entry.is_other
                else None,
                display=display,
                comparison_display=comparison_display,
                copy_marker=None if entry.is_other else "⊞",
                project_link=None if entry.is_other else entry.link,
                display_width=display_width(display),
                comparison_display_width=(
                    display_width(comparison_display) if comparison_display is not None else None
                ),
            )

        anchor_id: str | None = None
        if not reset_changed and viewport.entries:
            anchor_index = max(
                0,
                min(
                    len(viewport.entries) - 1,
                    bisect_right(viewport.starts, viewport.offset) - 1,
                ),
            )
            anchor_id = str(viewport.entries[anchor_index].key)

        full_entries = tuple(
            replace(prepare_entry(entry), rank=entry.rank or rank)
            for rank, entry in enumerate(projection.series, 1)
        )
        prior = {
            entry.key: rank
            for rank, entry in enumerate(
                sorted(
                    (
                        entry
                        for entry in full_entries
                        if entry.previous is not None and not entry.is_other
                    ),
                    key=lambda entry: (-cast(Decimal, entry.previous), str(entry.key)),
                ),
                1,
            )
        }
        viewport.full_entries = tuple(
            replace(entry, previous_rank=entry.previous_rank or prior.get(entry.key))
            for entry in full_entries
        )
        viewport.entries = filter_ranking_entries(viewport.full_entries, search_query)
        viewport.by_id = {str(entry.key): entry for entry in viewport.entries}
        viewport.total = sum((entry.current for entry in viewport.full_entries), Decimal())
        viewport.maximum = (
            max((entry.current for entry in viewport.full_entries), default=Decimal()) or 1
        )
        viewport.source = projection.series
        viewport.data_key = data_key
    if rebuild_geometry:
        if not viewport.restore_geometry(geometry_key):
            viewport.columns = RankingColumns()
            if viewport.entries:
                measure_ranking_columns(
                    viewport.entries,
                    context=context,
                    total=viewport.total,
                    show_percentage=projection.show_percentage,
                    comparison_mode=comparison,
                    comparison_available=projection.comparison_available,
                    show_new_entries=True,
                    total_entry_count=len(viewport.entries),
                    columns=viewport.columns,
                )
            viewport.prepare_lines(descriptions=descriptions_visible, spacing=item_spacing)
            if rebuild_data and anchor_id is not None:
                anchor_index = next(
                    (
                        index
                        for index, entry in enumerate(viewport.entries)
                        if str(entry.key) == anchor_id
                    ),
                    None,
                )
                if anchor_index is not None:
                    viewport.offset = viewport.starts[anchor_index]
            viewport.remember_geometry(geometry_key)
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
        copy_all_action
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
            thumb = bar.on_thumb(row)
            mark = ("#" if context.ascii else "█") if thumb else ("|" if context.ascii else "│")
            rows[row] = pad_width(
                clip_width(rows[row], context.width), context.width
            ) + styled_text(
                mark,
                scheme.highlight if thumb else scheme.muted,
                context,
                bold=thumb,
            )
        rendered = "\n".join(rows)
    return rendered
