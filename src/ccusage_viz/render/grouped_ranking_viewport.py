"""Group-aware physical-line viewport for partitioned Custom Rankings."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Literal, cast

from ccusage_viz.formatting import (
    center_text,
    clip_width,
    display_width,
    pad_width,
    strip_ansi,
)
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
from ccusage_viz.render.ranking_viewport import RankingColumns
from ccusage_viz.render.summary import format_custom_value
from ccusage_viz.scrollbar import Scrollbar

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


@dataclass(slots=True)
class GroupedRankingViewport:
    offset: int = 0
    total_rows: int = 0
    visible_rows: int = 0
    reserved_rows: int = 0
    sticky_rows: int = 0
    body_top: int = 0
    scrollbar: Scrollbar | None = None
    copy_all_hit: tuple[int, int] | None = None
    active: bool = False
    source: object | None = None
    data_key: object = None
    geometry_key: object = None
    reset_key: object = None
    rows: tuple[GroupedRankingRow, ...] = ()
    lines: tuple[str, ...] = ()
    groups: tuple[GroupedRankingPresentationGroup, ...] = ()
    visible_groups: tuple[
        tuple[GroupedRankingPresentationGroup, tuple[RankingPresentationEntry, ...]], ...
    ] = ()
    by_id: dict[GroupedIdentity, object] = field(default_factory=dict)
    hits: dict[int, tuple[GroupedIdentity, int, int | None]] = field(default_factory=dict)

    def _sticky_required(self, offset: int) -> bool:
        if self.visible_rows < 2 or not self.rows or offset >= len(self.rows):
            return False
        top = self.rows[offset]
        heading = next(
            (
                index
                for index, row in enumerate(self.rows)
                if row.kind == "group" and row.group_id == top.group_id
            ),
            offset,
        )
        window = self.rows[offset : offset + self.visible_rows]
        return (
            heading < offset
            and not any(row.kind == "group" for row in window)
            and any(row.kind == "series" and row.group_id == top.group_id for row in self.rows)
        )

    def effective_capacity(self, offset: int | None = None) -> int:
        """Physical source rows visible after reserving a sticky-heading row."""
        position = self.offset if offset is None else offset
        return max(0, self.visible_rows - int(self._sticky_required(position)))

    def maximum_offset(self) -> int:
        base = max(0, self.total_rows - self.visible_rows)
        # At the ordinary end position a sticky heading consumes one body line;
        # account for it before clamping so the final physical row is reachable.
        return max(0, self.total_rows - self.effective_capacity(base))

    def clamp(self) -> None:
        self.offset = min(max(0, self.offset), self.maximum_offset())

    def scroll(self, delta: int) -> bool:
        if self.visible_rows <= 0:
            return False
        before = self.offset
        self.offset += delta
        self.clamp()
        return before != self.offset

    def clear(self) -> None:
        self.offset = self.total_rows = self.visible_rows = self.reserved_rows = self.sticky_rows = 0
        self.body_top = 0
        self.scrollbar = self.copy_all_hit = None
        self.active = False
        self.source = self.data_key = self.geometry_key = self.reset_key = None
        self.rows = ()
        self.lines = ()
        self.groups = self.visible_groups = ()
        self.by_id.clear()
        self.hits.clear()

    def clipboard_text(self, identity: GroupedIdentity) -> str:
        if identity[0] == "group":
            pair = next((pair for pair in self.visible_groups if pair[0].id == identity[1]), None)
            if pair is None:
                return ""
            group, entries = pair
            return _grouped_ranking_group_clipboard_text(group, entries)
        group = next((group for group in self.groups if group.id == identity[1]), None)
        entry = cast(RankingPresentationEntry | None, self.by_id.get(identity))
        if group is None or entry is None:
            return ""
        return _grouped_ranking_series_clipboard_text(group.label, entry)

    def clipboard_all_text(self) -> str:
        return _grouped_ranking_clipboard_all_text(self.visible_groups)


def _entry_text(entry: RankingPresentationEntry) -> str:
    return "\n".join(
        part
        for part in (
            entry.label,
            copyable_description_text(entry.description or ""),
            entry.project_link,
        )
        if part
    )


def _grouped_ranking_series_clipboard_text(
    group_label: str, entry: RankingPresentationEntry
) -> str:
    return f"{group_label}\n{_entry_text(entry)}"


def _grouped_ranking_group_clipboard_text(
    group: GroupedRankingPresentationGroup, entries: tuple[RankingPresentationEntry, ...]
) -> str:
    heading = "\n".join(
        part
        for part in (group.label, copyable_description_text(group.description or ""), group.link)
        if part
    )
    bodies = tuple(_entry_text(entry) for entry in entries if not entry.is_other)
    return "\n\n".join((heading, *bodies))


def _grouped_ranking_clipboard_all_text(
    groups: tuple[
        tuple[GroupedRankingPresentationGroup, tuple[RankingPresentationEntry, ...]], ...
    ],
) -> str:
    # Preserve declared Dataset order and genuine empty headings. A group
    # whose projection contains only synthetic Other is not genuinely empty,
    # but Other itself must never become a clipboard entry.
    return "\n\n".join(
        _grouped_ranking_group_clipboard_text(group, entries)
        for group, entries in groups
        if not entries or any(not entry.is_other for entry in entries)
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
    copy_all_action: bool = False,
    copied_all: bool = False,
) -> str:
    """Render matched groups from immutable full facts into explicit physical rows."""
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
    data_key = (context.translator.language, projection.unit, search_query)
    source_changed = viewport.source is not projection.groups or viewport.data_key != data_key
    geometry_key = (
        context.width,
        context.height,
        context.density,
        context.period,
        context.pending,
        descriptions_visible,
        item_spacing,
        projection.comparison_available,
        projection.show_percentage,
        config.ranking_comparison if config else "full",
    )
    geometry_changed = viewport.geometry_key != geometry_key
    restore_identity = not reset_changed and (source_changed or geometry_changed)

    old_rows, old_offset = viewport.rows, viewport.offset
    anchor: tuple[str, str | None] | None = None
    if old_rows and restore_identity:
        # Every physical row carries the identity it visually belongs to.
        # Separators consistently belong to the following group/series, so a
        # geometry/source refresh preserves what was actually at the top.
        row = old_rows[min(old_offset, len(old_rows) - 1)]
        anchor = (row.group_id, row.series_id)

    global_total = sum((group.total for group in projection.groups or ()), start=Decimal())
    prepared = tuple(
        _prepare_group(group, projection, context, global_total=global_total)
        for group in projection.groups or ()
    )
    visible = tuple(
        (group, filter_ranking_entries(group.entries, search_query))
        for group in prepared
        if (matches := filter_ranking_entries(group.entries, search_query)) or (not search_query)
        for _ in (matches,)
    )
    viewport.groups = prepared
    viewport.visible_groups = visible
    viewport.source = projection.groups
    viewport.data_key = data_key
    viewport.geometry_key = geometry_key
    viewport.by_id = {("group", group.id): group for group, _ in visible} | {
        ("series", group.id, str(entry.key)): entry
        for group, entries in visible
        for entry in entries
        if not entry.is_other
    }

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
    if show_visible_count and context.density != "minimal":
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
    viewport.body_top = len(chrome)

    comparison = config.ranking_comparison if config else "full"
    comparison_visible = _comparison_visible(projection, context, comparison)
    columns = RankingColumns()
    total_entry_count = max((len(group.entries) for group in prepared), default=0)
    if context.width >= 58 and context.density in {"full", "detailed"}:
        # Exactly like the non-viewport renderer, finish measurement for every
        # matched group and heading before rendering the first physical row.
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
                columns.widths[name] = max(columns.widths.get(name, 0), width)
            columns.description_width = max(columns.description_width, measured.description_width)
        if comparison_visible:
            columns.widths["current"] = max(
                columns.widths.get("current", 0),
                *(display_width(group.display) + 2 for group, _ in visible),
            )
            if comparison == "full":
                columns.widths["delta"] = max(
                    columns.widths.get("delta", 0),
                    *(display_width(group.comparison_display) for group, _ in visible),
                )
            if projection.show_percentage:
                columns.widths["share"] = max(
                    columns.widths.get("share", 0),
                    *(
                        display_width(f"{group.share:>5.1%}") if group.share is not None else 0
                        for group, _ in visible
                    ),
                )
        else:
            columns.widths["right"] = max(
                columns.widths.get("right", 1),
                *(
                    display_width(group.display)
                    + (
                        display_width(f"{group.share:>5.1%}")
                        if projection.show_percentage and group.share is not None
                        else 0
                    )
                    + 3
                    for group, _ in visible
                ),
            )
    lines: list[str] = []
    records: list[GroupedRankingRow] = []

    def append(
        kind: GroupedRowKind, group_id: str, series_id: str | None, line: str
    ) -> None:
        records.append(GroupedRankingRow(kind, group_id, series_id, len(lines)))
        lines.append(line)

    separator = (
        " "
        if item_spacing == "space"
        else ("-" if context.ascii else "─") * context.width
        if item_spacing == "line"
        else ("- " * max(1, context.width // 2)).rstrip()
    )

    def value(number: int | Decimal) -> str:
        return format_custom_value(
            Decimal(number), projection.unit, language=context.translator.language
        )

    for group_index, (group, entries) in enumerate(visible):
        if group_index:
            append("separator", group.id, None, "")
        group_marker = "✓" if copied_entry_id == ("group", group.id) else "⊞"
        heading_lines = render_ranking_heading_row(
            label=f"{group.label} | {group_marker}",
            value=group.display,
            delta=group.comparison_display,
            share=f"{group.share:>5.1%}"
            if projection.show_percentage and group.share is not None
            else "",
            description=group.description,
            context=context,
            link=group.link,
            descriptions_visible=descriptions_visible,
            comparison_visible=comparison_visible,
            comparison_mode=comparison,
            show_percentage=projection.show_percentage,
            total_entry_count=total_entry_count,
            columns=columns,
        )
        append("group", group.id, None, heading_lines[0])
        for line in heading_lines[1:]:
            append("description", group.id, None, line)
        if not entries:
            append(
                "empty", group.id, None, context.translator.text("message.grouped_ranking_no_data")
            )
            continue
        marked = tuple(
            replace(
                entry,
                copy_marker=(
                    None
                    if entry.is_other
                    else "✓"
                    if copied_entry_id == ("series", group.id, str(entry.key))
                    else "⊞"
                ),
            )
            for entry in entries
        )
        for entry_index, entry in enumerate(marked):
            # Render entry-by-entry so classification follows the rendering
            # structure rather than inferring row kind from copy-marker text.
            # In particular, Other is still a primary series row.
            rendered = render_historical_ranking(
                (entry,),
                heading="",
                value_formatter=value,
                delta_formatter=lambda number: f"{'+' if number > 0 else '-'}{value(abs(number))}",
                context=context,
                total=group.total,
                maximum=group.maximum,
                descriptions_visible=descriptions_visible,
                search_query=search_query,
                comparison_mode=comparison,
                comparison_available=projection.comparison_available,
                show_new_entries=True,
                compact_labels=False,
                label_max_width=48,
                total_entry_count=len(group.entries),
                show_percentage=projection.show_percentage,
                columns=columns,
                entries_matched=True,
            ).splitlines()
            if entry_index and item_spacing != "compact":
                append("separator", group.id, str(entry.key), separator)
            append("series", group.id, str(entry.key), rendered[0])
            for line in rendered[1:]:
                append("series_description", group.id, str(entry.key), line)

    viewport.lines = tuple(lines)
    viewport.rows = tuple(records)
    viewport.total_rows = len(lines)
    viewport.visible_rows = max(0, context.height - len(chrome))
    if anchor is not None and records:
        new_identity_rows = {
            (row.group_id, row.series_id): index
            for index, row in enumerate(records)
            if row.kind in {"group", "series"}
        }
        chosen = new_identity_rows.get(anchor)
        old_series = [(row.group_id, row.series_id) for row in old_rows if row.kind == "series"]
        if chosen is None and anchor[1] is not None and anchor in old_series:
            origin = old_series.index(anchor)
            # Search outward by old identity order; equal-distance ties prefer
            # the later (forward) series, then the earlier series.
            for distance in range(1, len(old_series)):
                for candidate_index in (origin + distance, origin - distance):
                    if 0 <= candidate_index < len(old_series):
                        chosen = new_identity_rows.get(old_series[candidate_index])
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
                    for candidate_index in (
                        (origin,) if distance == 0 else (origin + distance, origin - distance)
                    ):
                        if 0 <= candidate_index < len(old_groups):
                            chosen = new_identity_rows.get((old_groups[candidate_index], None))
                            if chosen is not None:
                                break
                    if chosen is not None:
                        break
        if chosen is not None:
            viewport.offset = chosen
    viewport.clamp()

    sticky: str | None = None
    content_rows = viewport.effective_capacity()
    if viewport._sticky_required(viewport.offset) and records and viewport.offset < len(records):
        top = records[viewport.offset]
        group_heading = next(
            (
                index
                for index, row in enumerate(records)
                if row.kind == "group" and row.group_id == top.group_id
            ),
            viewport.offset,
        )
        window = records[viewport.offset : viewport.offset + content_rows]
        if group_heading < viewport.offset and not any(row.kind == "group" for row in window):
            group = next((item for item, _ in visible if item.id == top.group_id), None)
            if group is not None and group.entries:
                sticky = styled_text(
                    clip_width(group.label, context.width),
                    get_color_scheme(context.color_scheme).muted,
                    context,
                    dim=True,
                )
    body = list(lines[viewport.offset : viewport.offset + content_rows])
    if sticky is not None:
        body.insert(0, sticky)

    viewport.sticky_rows = int(sticky is not None)
    screen_shift = viewport.sticky_rows
    for source_index in range(viewport.offset, min(len(records), viewport.offset + content_rows)):
        row = records[source_index]
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
        visible_line = strip_ansi(lines[source_index])
        marker = max(visible_line.rfind("⊞"), visible_line.rfind("✓"))
        if marker < 0:
            continue
        screen_row = len(chrome) + screen_shift + source_index - viewport.offset
        copy_column = display_width(visible_line[:marker])
        link_column = display_width(visible_line.rsplit("→", 1)[0]) if "→" in visible_line else None
        if copy_column < context.width:
            viewport.hits[screen_row] = (identity, copy_column, link_column)

    rendered = "\n".join((*chrome, *body))
    if copy_all_action and matched_count and viewport.body_top:
        rows_out = rendered.splitlines()
        count_row = len(chrome) - 1
        if count_row >= 0:
            marker = "✓" if copied_all else "⊞"
            prefix = clip_width(rows_out[count_row].rstrip(), max(0, context.width - 4))
            rows_out[count_row] = f"{prefix} | {marker}"
            viewport.copy_all_hit = (count_row, display_width(prefix) + 3)
            rendered = "\n".join(rows_out)
    effective_rows = viewport.effective_capacity()
    if gutter and effective_rows > 0 and viewport.total_rows > effective_rows:
        bar = Scrollbar(
            context.width,
            viewport.body_top,
            viewport.visible_rows,
            viewport.total_rows,
            effective_rows,
            viewport.offset,
        )
        viewport.scrollbar = bar
        scheme = get_color_scheme(context.color_scheme)
        rows_out = rendered.splitlines()
        rows_out.extend("" for _ in range(context.height - len(rows_out)))
        for row in range(bar.top, bar.top + bar.height):
            thumb = bar.on_thumb(row)
            mark = ("#" if context.ascii else "█") if thumb else ("|" if context.ascii else "│")
            rows_out[row] = pad_width(
                clip_width(rows_out[row], context.width), context.width
            ) + styled_text(mark, scheme.highlight if thumb else scheme.muted, context, bold=thumb)
        rendered = "\n".join(rows_out)
    return rendered
