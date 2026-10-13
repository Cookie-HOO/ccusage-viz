"""Session-local display-line windows for Dashboard Custom historical Rankings.

Preparation retains scalar layout facts, not a full styled chart. Warm rendering
uses binary search and formats only entries intersecting the visible window.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from ccusage_viz.formatting import display_width, strip_ansi, wrap_width
from ccusage_viz.render.base import styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.scrollbar import Scrollbar

if TYPE_CHECKING:
    from ccusage_viz.render.base import RenderContext
    from ccusage_viz.render.ranking_presentation import RankingPresentationEntry


def ranking_separator(spacing: str, context: RenderContext) -> str:
    """Render one presentation-only ranking separator for every viewport."""
    if spacing == "space":
        return " "
    if spacing == "line":
        return ("-" if context.ascii else "─") * context.width
    raw = ("- " * max(1, context.width // 2)).rstrip()
    if spacing == "dashed":
        return styled_text(
            raw,
            get_color_scheme(context.color_scheme).muted,
            context,
            dim=True,
        )
    return ""


@dataclass(frozen=True, slots=True)
class _RankingGeometry:
    """Immutable scalar facts for one prepared ranking layout."""

    widths: tuple[tuple[str, int], ...]
    description_width: int
    starts: tuple[int, ...]
    heights: tuple[int, ...]
    total_rows: int


@dataclass(slots=True)
class RankingColumns:
    """Widths measured once across the complete matching sequence."""

    widths: dict[str, int] = field(default_factory=dict)
    description_width: int = 1

    def width(self, name: str, measured: int) -> int:
        return self.widths.setdefault(name, measured)


@dataclass(slots=True)
class RankingViewport:
    offset: int = 0
    total_rows: int = 0
    visible_rows: int = 0
    reserved_rows: int = 0
    body_top: int = 0
    scrollbar: Scrollbar | None = None
    copy_all_hit: tuple[int, int] | None = None
    active: bool = False
    source: object | None = None
    data_key: object = None
    geometry_key: object = None
    reset_key: object = None
    full_entries: tuple[RankingPresentationEntry, ...] = ()
    entries: tuple[RankingPresentationEntry, ...] = ()
    by_id: dict[str, RankingPresentationEntry] = field(default_factory=dict)
    columns: RankingColumns = field(default_factory=RankingColumns)
    starts: tuple[int, ...] = (0,)
    # Heights omit the separator preceding each entry.
    heights: tuple[int, ...] = ()
    hits: dict[int, tuple[str, int, int | None]] = field(default_factory=dict)
    full_total: int | Decimal = 0
    full_maximum: int | Decimal = 1
    _geometry_cache: dict[object, _RankingGeometry] = field(
        default_factory=dict, init=False, repr=False
    )

    def restore_geometry(self, key: object) -> bool:
        """Restore and mark recent a defensively copied geometry snapshot."""
        snapshot = self._geometry_cache.pop(key, None)
        if snapshot is None:
            return False
        self._geometry_cache[key] = snapshot
        self.columns = RankingColumns(dict(snapshot.widths), snapshot.description_width)
        self.starts = snapshot.starts
        self.heights = snapshot.heights
        self.total_rows = snapshot.total_rows
        return True

    def remember_geometry(self, key: object) -> None:
        """Snapshot active geometry and retain only the two most recent layouts."""
        snapshot = _RankingGeometry(
            tuple(self.columns.widths.items()),
            self.columns.description_width,
            self.starts,
            self.heights,
            self.total_rows,
        )
        self._geometry_cache.pop(key, None)
        self._geometry_cache[key] = snapshot
        while len(self._geometry_cache) > 2:
            del self._geometry_cache[next(iter(self._geometry_cache))]

    def invalidate_geometry(self) -> None:
        """Discard snapshots without changing the current scroll position."""
        self._geometry_cache.clear()

    def clamp(self) -> None:
        self.offset = min(max(0, self.offset), max(0, self.total_rows - self.visible_rows))

    def scroll(self, delta: int) -> bool:
        """Move one display line per wheel report, independent of pane height."""
        if self.visible_rows <= 0:
            return False
        before = self.offset
        self.offset += delta
        self.clamp()
        return self.offset != before

    def clear(self) -> None:
        self.invalidate_geometry()
        self.offset = self.total_rows = self.visible_rows = self.reserved_rows = 0
        self.full_total, self.full_maximum = 0, 1
        self.body_top = 0
        self.scrollbar = None
        self.copy_all_hit = None
        self.active = False
        self.source = self.data_key = self.geometry_key = self.reset_key = None
        self.full_entries = self.entries = ()
        self.by_id.clear()
        self.hits.clear()
        self.starts = (0,)
        self.heights = ()
        self.columns = RankingColumns()

    def prepare_lines(self, *, descriptions: bool, spacing: str) -> None:
        from ccusage_viz.render.ranking_presentation import description_visible_text

        heights = []
        starts = [0]
        for entry in self.entries:
            height = 1
            if descriptions and entry.description:
                height += min(
                    2,
                    len(
                        wrap_width(
                            description_visible_text(entry.description),
                            self.columns.description_width,
                        )
                    ),
                )
            heights.append(height)
            starts.append(starts[-1] + height + int(spacing != "compact"))
        self.heights = tuple(heights)
        self.starts = tuple(starts)
        self.total_rows = starts[-1]

    def render(
        self,
        render_entries: Callable[[tuple[RankingPresentationEntry, ...], int], str],
        *,
        render_chrome: Callable[[], str],
        context: RenderContext,
        spacing: str,
    ) -> str:
        """Render chrome plus the window; collect hits only on visible primary rows."""
        self.hits.clear()
        self.body_top = 0
        self.active = True
        if not self.entries:
            self.offset = self.total_rows = self.visible_rows = 0
            return "\n".join(render_entries((), 0).splitlines()[: max(0, context.height)])
        chrome = render_chrome().splitlines()
        self.body_top = len(chrome)
        self.visible_rows = max(0, context.height - len(chrome))
        self.clamp()
        if not self.visible_rows:
            return "\n".join(chrome[: context.height])
        first = max(0, bisect_right(self.starts, self.offset) - 1)
        stop = bisect_left(self.starts, self.offset + self.visible_rows)
        entries = self.entries[first:stop]
        rendered = render_entries(entries, first).splitlines()[len(chrome) :]
        separator = ranking_separator(spacing, context)
        rows: list[str] = []
        primary: list[tuple[int, RankingPresentationEntry]] = []
        position = 0
        for index, entry in enumerate(entries, first):
            if spacing != "compact":
                rows.append(separator)
            primary.append((len(rows), entry))
            height = self.heights[index]
            rows.extend(rendered[position : position + height])
            position += height
        leading = self.offset - self.starts[first]
        body = rows[leading : leading + self.visible_rows]
        for row, entry in primary:
            screen_row = row - leading
            if entry.is_other or not 0 <= screen_row < len(body):
                continue
            line = strip_ansi(body[screen_row])
            marker_index = max(line.rfind("✓"), line.rfind("⊞"))
            if marker_index < 0:
                continue
            copy_column = display_width(line[:marker_index])
            if copy_column >= context.width:
                continue
            link_column = (
                display_width(line.rsplit("→", 1)[0])
                if entry.project_link and "→" in line
                else None
            )
            if link_column is not None and link_column >= context.width:
                link_column = None
            self.hits[len(chrome) + screen_row] = (str(entry.key), copy_column, link_column)
        return "\n".join((*chrome, *body))
