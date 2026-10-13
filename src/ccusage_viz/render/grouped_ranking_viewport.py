"""Cached group-aware physical-line viewport for partitioned Custom Rankings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, cast

from ccusage_viz.formatting import center_text, clip_width, display_width, pad_width, strip_ansi
from ccusage_viz.processing.custom_historical import CustomChartProjection
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.grouped_ranking import GroupedRankingPresentationGroup, _prepare_group
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_presentation import (
    RankingPresentationEntry,
    copyable_description_text,
    filter_ranking_entries,
    measure_ranking_columns,
    render_historical_ranking,
    render_ranking_heading_row,
)
from ccusage_viz.render.ranking_viewport import RankingColumns, ranking_separator
from ccusage_viz.render.summary import format_custom_value
from ccusage_viz.scrollbar import Scrollbar
from ccusage_viz.trends import trend_glyph

GroupedIdentity = tuple[Literal["group"], str] | tuple[Literal["series"], str, str]
GroupedRowKind = Literal[
    "group", "description", "separator", "series", "series_description", "empty"
]


@dataclass(frozen=True, slots=True)
class GroupedRankingRow:
    kind: GroupedRowKind
    group_id: str
    series_id: str | None
    source_line: int


@dataclass(frozen=True, slots=True)
class _GroupedRankingGeometry:
    widths: tuple[tuple[str, int], ...]
    description_width: int
    rows: tuple[GroupedRankingRow, ...]
    group_headings: tuple[int, ...]


@dataclass(slots=True)
class GroupedRankingViewport:
    offset: int = 0
    total_rows: int = 0
    visible_rows: int = 0
    reserved_rows: int = 0
    body_top: int = 0
    scrollbar: Scrollbar | None = None
    copy_all_hit: tuple[int, int] | None = None
    active: bool = False
    source: object | None = None
    preparation_key: object = None
    data_key: object = None
    geometry_key: object = None
    reset_key: object = None
    rows: tuple[GroupedRankingRow, ...] = ()
    group_headings: tuple[int, ...] = ()
    # Kept for compatibility with viewport inspection. Warm rendering no longer
    # materializes the complete styled result.
    lines: tuple[str, ...] = ()
    groups: tuple[GroupedRankingPresentationGroup, ...] = ()
    visible_groups: tuple[
        tuple[GroupedRankingPresentationGroup, tuple[RankingPresentationEntry, ...]], ...
    ] = ()
    by_id: dict[GroupedIdentity, object] = field(default_factory=dict)
    hits: dict[int, tuple[GroupedIdentity, int, int | None]] = field(default_factory=dict)
    columns: RankingColumns = field(default_factory=RankingColumns)
    comparison_visible: bool = False
    percentage_visible: bool = False
    entry_percentage_visible: bool = False
    entry_pending: bool = False
    rank_comparison_visible: bool = False
    _geometry_cache: dict[object, _GroupedRankingGeometry] = field(
        default_factory=dict, init=False, repr=False
    )
    _groups_by_id: Mapping[str, GroupedRankingPresentationGroup] = field(
        default_factory=lambda: MappingProxyType({}), init=False, repr=False
    )
    _entries_by_id: Mapping[tuple[str, str], RankingPresentationEntry] = field(
        default_factory=lambda: MappingProxyType({}), init=False, repr=False
    )

    def maximum_offset(self) -> int:
        return max(0, self.total_rows - self.visible_rows)

    def clamp(self) -> None:
        self.offset = min(max(0, self.offset), self.maximum_offset())

    def scroll(self, delta: int) -> bool:
        if self.visible_rows <= 0:
            return False
        before = self.offset
        self.offset += delta
        self.clamp()
        return before != self.offset

    def restore_geometry(self, key: object) -> bool:
        snapshot = self._geometry_cache.pop(key, None)
        if snapshot is None:
            return False
        self._geometry_cache[key] = snapshot
        self.columns = RankingColumns(dict(snapshot.widths), snapshot.description_width)
        self.rows = snapshot.rows
        self.group_headings = snapshot.group_headings
        self.total_rows = len(snapshot.rows)
        return True

    def remember_geometry(self, key: object) -> None:
        self._geometry_cache.pop(key, None)
        self._geometry_cache[key] = _GroupedRankingGeometry(
            tuple(self.columns.widths.items()),
            self.columns.description_width,
            self.rows,
            self.group_headings,
        )
        while len(self._geometry_cache) > 2:
            del self._geometry_cache[next(iter(self._geometry_cache))]

    def invalidate_geometry(self) -> None:
        self._geometry_cache.clear()

    def clear(self) -> None:
        self.invalidate_geometry()
        self.offset = self.total_rows = self.visible_rows = self.reserved_rows = 0
        self.body_top = 0
        self.scrollbar = self.copy_all_hit = None
        self.active = False
        self.source = self.preparation_key = self.data_key = self.geometry_key = self.reset_key = (
            None
        )
        self.rows = self.lines = ()
        self.group_headings = ()
        self.groups = self.visible_groups = ()
        self.columns = RankingColumns()
        self.comparison_visible = self.percentage_visible = self.entry_percentage_visible = (
            self.entry_pending
        ) = self.rank_comparison_visible = False
        self.by_id.clear()
        self.hits.clear()
        self._groups_by_id = MappingProxyType({})
        self._entries_by_id = MappingProxyType({})

    def clipboard_text(self, identity: GroupedIdentity) -> str:
        if identity[0] == "group":
            pair = next((pair for pair in self.visible_groups if pair[0].id == identity[1]), None)
            if pair is None:
                return ""
            return _grouped_ranking_group_clipboard_text(
                *pair,
                comparison_visible=self.comparison_visible,
                rank_comparison_visible=self.rank_comparison_visible,
                percentage_visible=self.percentage_visible,
                entry_percentage_visible=self.entry_percentage_visible,
                entry_pending=self.entry_pending,
            )
        group = next((group for group in self.groups if group.id == identity[1]), None)
        entry = cast(RankingPresentationEntry | None, self.by_id.get(identity))
        if group is None or entry is None:
            return ""
        return _grouped_ranking_series_clipboard_text(
            group.label,
            entry,
            comparison_visible=self.comparison_visible,
            rank_comparison_visible=self.rank_comparison_visible,
            percentage_visible=self.entry_percentage_visible,
            pending=self.entry_pending,
            total=group.total,
        )

    def clipboard_all_text(self) -> str:
        return _grouped_ranking_clipboard_all_text(
            self.visible_groups,
            comparison_visible=self.comparison_visible,
            rank_comparison_visible=self.rank_comparison_visible,
            percentage_visible=self.percentage_visible,
            entry_percentage_visible=self.entry_percentage_visible,
            entry_pending=self.entry_pending,
        )


def _share_text(share: Decimal | None) -> str:
    """Return a display-equivalent percentage without terminal column padding."""
    return f"{share:.1%}" if share is not None else ""


def _entry_text(
    entry: RankingPresentationEntry,
    *,
    comparison_visible: bool,
    rank_comparison_visible: bool,
    percentage_visible: bool,
    pending: bool,
    total: Decimal,
) -> str:
    parts = [entry.label, "??" if pending else entry.display or ""]
    if comparison_visible:
        parts.append(entry.comparison_display or "")
    if rank_comparison_visible and entry.comparison_ready and entry.previous is not None:
        rank_delta = (entry.previous_rank or 1) - (entry.rank or 1)
        parts.append("·" if rank_delta == 0 else trend_glyph(rank_delta, ascii=False))
    if percentage_visible and total:
        parts.append(_share_text(Decimal(entry.current) / total))
    parts.extend((copyable_description_text(entry.description or ""), entry.project_link or ""))
    return "\n".join(part for part in parts if part)


def _grouped_ranking_series_clipboard_text(
    group_label: str,
    entry: RankingPresentationEntry,
    *,
    comparison_visible: bool,
    rank_comparison_visible: bool,
    percentage_visible: bool,
    pending: bool,
    total: Decimal,
) -> str:
    return "\n".join(
        (
            group_label,
            _entry_text(
                entry,
                comparison_visible=comparison_visible,
                rank_comparison_visible=rank_comparison_visible,
                percentage_visible=percentage_visible,
                pending=pending,
                total=total,
            ),
        )
    )


def _grouped_ranking_group_clipboard_text(
    group: GroupedRankingPresentationGroup,
    entries: tuple[RankingPresentationEntry, ...],
    *,
    comparison_visible: bool,
    rank_comparison_visible: bool,
    percentage_visible: bool,
    entry_percentage_visible: bool,
    entry_pending: bool,
) -> str:
    heading_parts = [group.label, group.display]
    if comparison_visible:
        heading_parts.append(group.comparison_display)
    if percentage_visible:
        heading_parts.append(_share_text(group.share))
    heading_parts.extend((copyable_description_text(group.description or ""), group.link or ""))
    heading = "\n".join(part for part in heading_parts if part)
    return "\n\n".join(
        (
            heading,
            *(
                _entry_text(
                    entry,
                    comparison_visible=comparison_visible,
                    rank_comparison_visible=rank_comparison_visible,
                    percentage_visible=entry_percentage_visible,
                    pending=entry_pending,
                    total=group.total,
                )
                for entry in entries
            ),
        )
    )


def _grouped_ranking_clipboard_all_text(
    groups: tuple[
        tuple[GroupedRankingPresentationGroup, tuple[RankingPresentationEntry, ...]], ...
    ],
    *,
    comparison_visible: bool,
    rank_comparison_visible: bool,
    percentage_visible: bool,
    entry_percentage_visible: bool,
    entry_pending: bool,
) -> str:
    return "\n\n".join(
        _grouped_ranking_group_clipboard_text(
            group,
            entries,
            comparison_visible=comparison_visible,
            rank_comparison_visible=rank_comparison_visible,
            percentage_visible=percentage_visible,
            entry_percentage_visible=entry_percentage_visible,
            entry_pending=entry_pending,
        )
        for group, entries in groups
    )


def _comparison_visible(
    projection: CustomChartProjection, context: RenderContext, mode: str
) -> bool:
    return (
        context.density in {"full", "detailed"}
        and context.width >= 58
        and context.period != "all"
        and projection.comparison_available
        and mode != "none"
    )


def render_grouped_custom_ranking_viewport(
    projection: CustomChartProjection,
    context: RenderContext,
    viewport: GroupedRankingViewport,
    *,
    heading: str,
    descriptions_visible: bool,
    search_query: str,
    search_editing: bool,
    show_visible_count: bool,
    copied_entry_id: object | None,
    item_spacing: str,
    scrollbar: bool = False,
    scrollbar_hovered: bool = False,
    copy_all_action: bool = False,
    copied_all: bool = False,
) -> str:
    """Render only physical units intersecting the current grouped window."""
    viewport.active = True
    viewport.scrollbar = None
    viewport.copy_all_hit = None
    viewport.hits.clear()
    gutter = scrollbar and context.width > 1
    if gutter:
        context = replace(context, width=context.width - 1)
    config = projection.config
    reset_key = (
        (
            config.source,
            config.metric_id,
            config.partition_by,
            config.group_by,
            config.filters,
            config.date_range,
        )
        if config
        else None,
        search_query,
    )
    reset_changed = reset_key != viewport.reset_key
    if reset_changed:
        viewport.offset = 0
        viewport.reset_key = reset_key

    preparation_key = (
        context.translator.language,
        projection.unit,
        context.period,
        context.pending,
        projection.comparison_available,
    )
    data_key = search_query
    rebuild_prepared = (
        viewport.source is not projection.groups or viewport.preparation_key != preparation_key
    )
    rebuild_data = rebuild_prepared or viewport.data_key != data_key
    comparison = config.ranking_comparison if config else "full"
    geometry_key = (
        context.width,
        context.style,
        context.density,
        context.period,
        context.pending,
        descriptions_visible,
        item_spacing,
        projection.comparison_available,
        projection.show_percentage,
        comparison,
    )
    rebuild_geometry = rebuild_data or viewport.geometry_key != geometry_key
    old_rows, old_offset = viewport.rows, viewport.offset
    anchor: tuple[str, str | None] | None = None
    if old_rows and rebuild_geometry and not reset_changed:
        row = old_rows[min(old_offset, len(old_rows) - 1)]
        anchor = (row.group_id, row.series_id)

    if rebuild_data:
        viewport.invalidate_geometry()
        if rebuild_prepared:
            global_total = sum((group.total for group in projection.groups or ()), start=Decimal())
            viewport.groups = tuple(
                _prepare_group(group, projection, context, global_total=global_total)
                for group in projection.groups or ()
            )
            viewport.source = projection.groups
            viewport.preparation_key = preparation_key
        prepared = viewport.groups
        matched = tuple(
            (
                group,
                tuple(
                    entry
                    for entry in filter_ranking_entries(group.entries, search_query)
                    if not search_query or not entry.is_other
                ),
            )
            for group in prepared
        )
        visible = tuple(
            (group, entries) for group, entries in matched if entries or not search_query
        )
        viewport.visible_groups = visible
        groups_by_id = {group.id: group for group, _ in visible}
        entries_by_id = {
            (group.id, str(entry.key)): entry for group, entries in visible for entry in entries
        }
        viewport._groups_by_id = MappingProxyType(groups_by_id)
        viewport._entries_by_id = MappingProxyType(entries_by_id)
        viewport.by_id = {
            ("group", group_id): group for group_id, group in groups_by_id.items()
        } | {
            ("series", group_id, series_id): entry
            for (group_id, series_id), entry in entries_by_id.items()
            if not entry.is_other
        }
        viewport.data_key = data_key

    visible = viewport.visible_groups
    prepared = viewport.groups
    comparison_visible = _comparison_visible(projection, context, comparison)
    # The item renderer emits a value delta only in full comparison mode. List
    # rows have neither comparison nor share columns, regardless of width.
    viewport.comparison_visible = (
        comparison_visible and comparison == "full" and context.style != "list"
    )
    viewport.rank_comparison_visible = (
        comparison_visible
        and comparison == "rank"
        and context.style != "list"
        and context.density == "detailed"
        and context.width >= 75
    )
    viewport.percentage_visible = projection.show_percentage and context.style != "list"
    viewport.entry_percentage_visible = viewport.percentage_visible and not context.pending
    viewport.entry_pending = context.pending
    total_entry_count = max((len(group.entries) for group in prepared), default=0)

    def value(number: int | Decimal) -> str:
        return format_custom_value(
            Decimal(number), projection.unit, language=context.translator.language
        )

    def heading_lines(
        group: GroupedRankingPresentationGroup, *, measure: bool = False
    ) -> list[str]:
        marker = "⊞" if measure or copied_entry_id != ("group", group.id) else "✓"
        return list(
            render_ranking_heading_row(
                label=group.label if context.style == "list" else f"{group.label} | {marker}",
                value=group.display,
                delta=group.comparison_display,
                share=(
                    f"{group.share:>5.1%}"
                    if projection.show_percentage and group.share is not None
                    else ""
                ),
                description=group.description,
                context=context,
                link=None if context.style == "list" else group.link,
                descriptions_visible=descriptions_visible,
                comparison_visible=comparison_visible,
                comparison_mode=comparison,
                show_percentage=projection.show_percentage,
                total_entry_count=total_entry_count,
                columns=viewport.columns,
            )
        )

    def entry_lines(
        group: GroupedRankingPresentationGroup,
        entry: RankingPresentationEntry,
        *,
        measure: bool = False,
    ) -> list[str]:
        marked = replace(
            entry,
            copy_marker=(
                None
                if context.style == "list" or entry.is_other
                else "⊞"
                if measure or copied_entry_id != ("series", group.id, str(entry.key))
                else "✓"
            ),
        )
        rendered = render_historical_ranking(
            (marked,),
            heading="",
            value_formatter=value,
            delta_formatter=lambda number: f"{'+' if number > 0 else '-'}{value(abs(number))}",
            context=context,
            pending=context.pending,
            total=group.total,
            maximum=group.maximum,
            descriptions_visible=descriptions_visible,
            search_query=search_query,
            search_editing=search_editing,
            comparison_mode=comparison,
            comparison_available=projection.comparison_available,
            show_new_entries=True,
            compact_labels=False,
            label_max_width=48,
            total_entry_count=len(group.entries),
            show_percentage=projection.show_percentage,
            columns=viewport.columns,
            entries_matched=True,
            measure_only=measure,
        ).splitlines()
        # The grouped viewport owns heading/search/table chrome. Keep only the
        # single entry's primary row and any following wrapped description.
        primary = next(
            (
                index
                for index, line in enumerate(rendered)
                if strip_ansi(line).lstrip().startswith(f"{marked.rank} ")
            ),
            len(rendered),
        )
        return rendered[primary:]

    if rebuild_geometry:
        if not viewport.restore_geometry(geometry_key):
            viewport.columns = RankingColumns()
            if context.width >= 58 and context.density in {"full", "detailed"}:
                for group, entries in visible:
                    measured = RankingColumns()
                    measure_ranking_columns(
                        entries,
                        context=context,
                        total=group.total,
                        show_percentage=projection.show_percentage,
                        comparison_mode=comparison,
                        comparison_available=projection.comparison_available,
                        show_new_entries=True,
                        total_entry_count=total_entry_count,
                        columns=measured,
                    )
                    for name, width in measured.widths.items():
                        viewport.columns.widths[name] = max(
                            viewport.columns.widths.get(name, 0), width
                        )
                    viewport.columns.description_width = max(
                        viewport.columns.description_width, measured.description_width
                    )
                if comparison_visible:
                    viewport.columns.widths["current"] = max(
                        (display_width(group.display) + 2 for group, _ in visible),
                        default=viewport.columns.widths.get("current", 0),
                    )
                    if comparison == "full":
                        viewport.columns.widths["delta"] = max(
                            (display_width(group.comparison_display) for group, _ in visible),
                            default=viewport.columns.widths.get("delta", 0),
                        )
                    if projection.show_percentage:
                        viewport.columns.widths["share"] = max(
                            (
                                display_width(f"{group.share:>5.1%}")
                                if group.share is not None
                                else 0
                                for group, _ in visible
                            ),
                            default=viewport.columns.widths.get("share", 0),
                        )
                else:
                    viewport.columns.widths["right"] = max(
                        (
                            display_width(group.display)
                            + (
                                display_width(f"{group.share:>5.1%}")
                                if projection.show_percentage and group.share is not None
                                else 0
                            )
                            + 3
                            for group, _ in visible
                        ),
                        default=viewport.columns.widths.get("right", 1),
                    )
            records: list[GroupedRankingRow] = []
            for group_index, (group, entries) in enumerate(visible):
                if group_index:
                    records.append(GroupedRankingRow("separator", group.id, None, 0))
                for line_index, _ in enumerate(heading_lines(group, measure=True)):
                    records.append(
                        GroupedRankingRow(
                            "group" if line_index == 0 else "description",
                            group.id,
                            None,
                            line_index,
                        )
                    )
                if not entries:
                    records.append(GroupedRankingRow("empty", group.id, None, 0))
                    continue
                for entry_index, entry in enumerate(entries):
                    if entry_index and item_spacing != "compact":
                        records.append(GroupedRankingRow("separator", group.id, str(entry.key), 0))
                    for line_index, _ in enumerate(entry_lines(group, entry)):
                        records.append(
                            GroupedRankingRow(
                                "series" if line_index == 0 else "series_description",
                                group.id,
                                str(entry.key),
                                line_index,
                            )
                        )
            viewport.rows = tuple(records)
            viewport.group_headings = tuple(
                index for index, row in enumerate(records) if row.kind == "group"
            )
            viewport.total_rows = len(records)
            viewport.remember_geometry(geometry_key)
        viewport.geometry_key = geometry_key

    if anchor is not None and viewport.rows:
        identity_rows = {
            (row.group_id, row.series_id): index
            for index, row in enumerate(viewport.rows)
            if row.kind in {"group", "series"}
        }
        chosen = identity_rows.get(anchor)
        old_series = [(row.group_id, row.series_id) for row in old_rows if row.kind == "series"]
        if chosen is None and anchor[1] is not None and anchor in old_series:
            origin = old_series.index(anchor)
            for distance in range(1, len(old_series)):
                for candidate in (origin + distance, origin - distance):
                    if 0 <= candidate < len(old_series):
                        chosen = identity_rows.get(old_series[candidate])
                        if chosen is not None:
                            break
                if chosen is not None:
                    break
        if chosen is None:
            old_groups = list(
                dict.fromkeys(row.group_id for row in old_rows if row.kind == "group")
            )
            if anchor[0] in old_groups:
                origin = old_groups.index(anchor[0])
                for distance in range(len(old_groups)):
                    candidates = (
                        (origin,) if distance == 0 else (origin + distance, origin - distance)
                    )
                    for candidate in candidates:
                        if 0 <= candidate < len(old_groups):
                            chosen = identity_rows.get((old_groups[candidate], None))
                            if chosen is not None:
                                break
                    if chosen is not None:
                        break
        if chosen is not None:
            viewport.offset = chosen

    chrome = [center_text(heading, context.width)]
    if search_query or search_editing:
        chrome.append(
            context.translator.text(
                "label.ranking_search_editing" if search_editing else "label.ranking_search",
                query=search_query,
                cursor="▏",
            )
        )
    matched_count = sum(not entry.is_other for _, entries in visible for entry in entries)
    full_count = sum(not entry.is_other for group in prepared for entry in group.entries)
    count_row: int | None = None
    if show_visible_count and context.density != "minimal":
        count_row = len(chrome)
        chrome.append(
            context.translator.text(
                "label.ranking_search_visible_items"
                if search_query
                else "label.ranking_visible_items",
                visible=matched_count,
                total=full_count,
                count=matched_count if search_query else full_count,
            )
        )
    chrome = chrome[: max(0, context.height)]
    viewport.body_top = len(chrome)
    viewport.visible_rows = max(0, context.height - viewport.body_top)
    viewport.clamp()

    source_indexes = range(
        viewport.offset, min(len(viewport.rows), viewport.offset + viewport.visible_rows)
    )
    group_by_id = viewport._groups_by_id
    rendered_units: dict[tuple[str, str, str | None], list[str]] = {}
    separator = ranking_separator(item_spacing, context)

    def source_line(row: GroupedRankingRow) -> str:
        if row.kind == "separator":
            return "" if row.series_id is None else separator
        if row.kind == "empty":
            return context.translator.text("message.grouped_ranking_no_data")
        group = group_by_id[row.group_id]
        if row.series_id is None:
            key = ("group", row.group_id, None)
            lines = rendered_units.get(key)
            if lines is None:
                lines = heading_lines(group)
                rendered_units[key] = lines
        else:
            key = ("series", row.group_id, row.series_id)
            lines = rendered_units.get(key)
            if lines is None:
                entry = viewport._entries_by_id[row.group_id, row.series_id]
                lines = entry_lines(group, entry)
                rendered_units[key] = lines
        return lines[row.source_line]

    body = [source_line(viewport.rows[index]) for index in source_indexes]
    viewport.lines = tuple(body)

    if context.style != "list":
        for screen_index, source_index in enumerate(source_indexes):
            row = viewport.rows[source_index]
            if row.kind not in {"group", "series"}:
                continue
            identity: GroupedIdentity = (
                ("group", row.group_id)
                if row.kind == "group"
                else ("series", row.group_id, cast(str, row.series_id))
            )
            entry = viewport.by_id.get(identity)
            if isinstance(entry, RankingPresentationEntry) and entry.is_other:
                continue
            visible_line = strip_ansi(body[screen_index])
            marker = max(visible_line.rfind("⊞"), visible_line.rfind("✓"))
            if marker < 0:
                continue
            copy_column = display_width(visible_line[:marker])
            link_column = (
                display_width(visible_line.rsplit("→", 1)[0]) if "→" in visible_line else None
            )
            if link_column is not None and link_column >= context.width:
                link_column = None
            screen_row = viewport.body_top + screen_index
            if screen_row < context.height and copy_column < context.width:
                viewport.hits[screen_row] = (identity, copy_column, link_column)

    rendered = "\n".join((*chrome, *body))
    if (
        context.style != "list"
        and copy_all_action
        and count_row is not None
        and count_row < len(chrome)
        and count_row < context.height
        and viewport.clipboard_all_text()
    ):
        rows_out = rendered.splitlines()
        marker = "✓" if copied_all else "⊞"
        prefix = clip_width(rows_out[count_row].rstrip(), max(0, context.width - 4))
        rows_out[count_row] = f"{prefix} | {marker}"
        viewport.copy_all_hit = (count_row, display_width(prefix) + 3)
        rendered = "\n".join(rows_out)

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
        rows_out = rendered.splitlines()[: context.height]
        rows_out.extend("" for _ in range(context.height - len(rows_out)))
        for row in range(bar.top, min(context.height, bar.top + bar.height)):
            mark, color, bold = bar.mark_at(
                row,
                ascii=context.ascii,
                hovered=scrollbar_hovered,
                highlight=scheme.highlight,
                muted=scheme.muted,
            )
            rows_out[row] = pad_width(
                clip_width(rows_out[row], context.width), context.width
            ) + styled_text(mark, color, context, bold=bold)
        rendered = "\n".join(rows_out)
    return "\n".join(rendered.splitlines()[: max(0, context.height)])
