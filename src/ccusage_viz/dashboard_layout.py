from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Literal

NAMED_LAYOUTS = frozenset(("auto", "spotlight-wide", "spotlight-wide2"))
MIN_WEIGHT_SHARES = 24
MIN_PANE_HEIGHT = 3

RenderedLayout = Literal["grid", "spotlight-wide", "spotlight-wide2"]


@dataclass(frozen=True, slots=True)
class PaneSlot:
    """A Pane's position in logical row and column bands."""

    index: int
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1


@dataclass(frozen=True, slots=True)
class PaneTopology:
    """Terminal-independent Pane placement within shared logical bands."""

    rows: int
    columns: int
    slots: tuple[PaneSlot, ...]

    def slot(self, index: int) -> PaneSlot:
        return self.slots[index]


@dataclass(frozen=True, slots=True)
class PaneRect:
    index: int
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class PaneLayout:
    """The exact geometry shared by rendering and pointer hit testing."""

    configured: str
    rendered: RenderedLayout
    width: int
    height: int
    gutter: int
    topology: PaneTopology
    column_sizes: tuple[int, ...]
    row_sizes: tuple[int, ...]
    panes: tuple[PaneRect, ...]

    def pane(self, index: int) -> PaneRect:
        return self.panes[index]


@dataclass(frozen=True, slots=True)
class LayoutBands:
    rows: int
    columns: int


def parse_grid(value: str, pane_count: int) -> str | None:
    """Normalize a rectangular grid only when it can display every Pane."""
    if pane_count < 1:
        return None
    try:
        rows_text, columns_text = value.casefold().split("x")
        rows, columns = int(rows_text), int(columns_text)
    except (AttributeError, TypeError, ValueError):
        return None
    if rows < 1 or columns < 1 or rows * columns < pane_count:
        return None
    return f"{rows}x{columns}"


def parse_layout(value: str, pane_count: int) -> str | None:
    """Normalize a named topology or rectangular grid when it fits every Pane."""
    if pane_count < 1:
        return None
    normalized = value.casefold()
    if normalized in NAMED_LAYOUTS:
        return normalized
    return parse_grid(normalized, pane_count)


def fixed_shape(layout: str) -> tuple[int, int]:
    """Return a validated fixed-grid shape."""
    try:
        rows_text, columns_text = layout.casefold().split("x")
        rows, columns = int(rows_text), int(columns_text)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"not a fixed Dashboard layout: {layout!r}") from error
    if rows < 1 or columns < 1:
        raise ValueError(f"not a fixed Dashboard layout: {layout!r}")
    return rows, columns


def layout_for_pane_count(layout: str, pane_count: int) -> str:
    """Reconcile fixed rows while preserving columns; named layouts are dynamic."""
    if pane_count < 1:
        raise ValueError("a Dashboard requires at least one Pane")
    normalized = layout.casefold()
    if normalized in NAMED_LAYOUTS:
        return normalized
    _, columns = fixed_shape(normalized)
    return f"{max(1, ceil(pane_count / columns))}x{columns}"


def normalize_weights(weights: tuple[int, ...]) -> tuple[int, ...]:
    """Validate positive integer shares without discarding their resolution."""
    if not weights or any(weight < 1 for weight in weights):
        raise ValueError("layout weights must be positive integers")
    return weights


def reconcile_weights(weights: tuple[int, ...] | None, count: int) -> tuple[int, ...]:
    """Preserve bands while maintaining the minimum logical share pool."""
    if count < 1:
        raise ValueError("a layout requires at least one band")
    current = normalize_weights(weights) if weights else ()
    reconciled = normalize_weights((*current[:count], *(1 for _ in range(count - len(current)))))
    return _expand_weight_pool(reconciled)


def _expand_weight_pool(weights: tuple[int, ...]) -> tuple[int, ...]:
    multiplier = ceil(MIN_WEIGHT_SHARES / sum(weights))
    if multiplier == 1:
        return weights
    return tuple(weight * multiplier for weight in weights)


def adjust_weight(weights: tuple[int, ...], index: int, delta: int) -> tuple[int, ...]:
    """Transfer shares between a selected band and its deterministic neighbor."""
    current = normalize_weights(weights)
    if not 0 <= index < len(current):
        raise IndexError(index)
    if len(current) == 1 or delta == 0:
        return current
    neighbor = index + 1 if index + 1 < len(current) else index - 1
    adjusted = _expand_weight_pool(current)
    for _ in range(abs(delta)):
        source, target = (neighbor, index) if delta > 0 else (index, neighbor)
        if adjusted[source] == 1:
            break
        working = list(adjusted)
        working[source] -= 1
        working[target] += 1
        adjusted = tuple(working)
    return adjusted


def layout_bands(layout: str, pane_count: int) -> LayoutBands:
    """Return the configured topology's logical band counts."""
    normalized = parse_layout(layout, pane_count)
    if normalized is None:
        raise ValueError(f"invalid Dashboard layout: {layout!r}")
    topology, _ = _build_topology(normalized, pane_count)
    return LayoutBands(topology.rows, topology.columns)


def pane_at(layout: PaneLayout, x: int, y: int) -> int | None:
    for rect in layout.panes:
        if rect.left <= x < rect.left + rect.width and rect.top <= y < rect.top + rect.height:
            return rect.index
    return None


def resolve_pane_layout(
    *,
    layout: str,
    pane_count: int,
    width: int,
    height: int,
    divider_style: str = "line",
    column_weights: tuple[int, ...] | None = None,
    row_weights: tuple[int, ...] | None = None,
) -> PaneLayout:
    """Resolve configured topology, weights, and viewport into exact Pane rectangles."""
    configured = parse_layout(layout, pane_count)
    if configured is None:
        raise ValueError(f"invalid Dashboard layout: {layout!r}")
    if width < 1 or height < 1:
        raise ValueError("layout dimensions must be positive")

    gutter = 0 if divider_style == "none" else 1
    topology, rendered = _build_topology(configured, pane_count)
    resolved_columns = _resolve_weights(column_weights, topology.columns)
    resolved_rows = _resolve_weights(row_weights, topology.rows)
    column_sizes = _allocate_axis(width, resolved_columns, gutter)
    row_sizes = _allocate_axis(height, resolved_rows, gutter)
    panes = _pane_rectangles(topology, column_sizes, row_sizes, gutter)
    return PaneLayout(
        configured=configured,
        rendered=rendered,
        width=width,
        height=height,
        gutter=gutter,
        topology=topology,
        column_sizes=column_sizes,
        row_sizes=row_sizes,
        panes=panes,
    )


def _resolve_weights(weights: tuple[int, ...] | None, count: int) -> tuple[int, ...]:
    if weights is None:
        return (1,) * count
    normalized = normalize_weights(weights)
    if len(normalized) != count:
        raise ValueError(f"expected {count} layout weights, got {len(normalized)}")
    return normalized


def _auto_shape(count: int) -> tuple[int, int]:
    columns = 1 if count == 1 else 2
    return ceil(count / columns), columns


def _build_topology(configured: str, pane_count: int) -> tuple[PaneTopology, RenderedLayout]:
    if pane_count == 1:
        return PaneTopology(1, 1, (PaneSlot(0, 0, 0),)), _rendered_name(configured)
    if configured == "spotlight-wide":
        aux_rows, columns = _auto_shape(pane_count - 1)
        slots = [PaneSlot(0, 0, 0, column_span=columns)]
        slots.extend(
            PaneSlot(index, 1 + (index - 1) // columns, (index - 1) % columns)
            for index in range(1, pane_count)
        )
        return PaneTopology(1 + aux_rows, columns, tuple(slots)), "spotlight-wide"
    if configured == "spotlight-wide2":
        if pane_count == 2:
            return PaneTopology(2, 1, (PaneSlot(0, 0, 0), PaneSlot(1, 1, 0))), "spotlight-wide2"
        slots = [
            PaneSlot(0, 0, 0, column_span=2),
            PaneSlot(1, 1, 0, column_span=2),
        ]
        slots.extend(
            PaneSlot(index, 2 + (index - 2) // 2, (index - 2) % 2) for index in range(2, pane_count)
        )
        return PaneTopology(2 + ceil((pane_count - 2) / 2), 2, tuple(slots)), "spotlight-wide2"
    if configured == "auto":
        rows, columns = _auto_shape(pane_count)
    else:
        rows, columns = fixed_shape(configured)
    slots = tuple(PaneSlot(index, index // columns, index % columns) for index in range(pane_count))
    return PaneTopology(rows, columns, slots), "grid"


def _rendered_name(configured: str) -> RenderedLayout:
    if configured == "spotlight-wide":
        return "spotlight-wide"
    if configured == "spotlight-wide2":
        return "spotlight-wide2"
    return "grid"


def _allocate_axis(total: int, weights: tuple[int, ...], gutter: int) -> tuple[int, ...]:
    available = total - gutter * (len(weights) - 1)
    if available < len(weights):
        raise ValueError("viewport is too small for the configured Dashboard layout")
    distributable = available - len(weights)
    weight_total = sum(weights)
    products = [distributable * weight for weight in weights]
    sizes = [1 + product // weight_total for product in products]
    remainder = available - sum(sizes)
    priorities = sorted(
        range(len(weights)),
        key=lambda index: (products[index] % weight_total, -index),
        reverse=True,
    )
    for index in priorities[:remainder]:
        sizes[index] += 1
    return tuple(sizes)


def _pane_rectangles(
    topology: PaneTopology,
    column_sizes: tuple[int, ...],
    row_sizes: tuple[int, ...],
    gutter: int,
) -> tuple[PaneRect, ...]:
    lefts: list[int] = []
    position = 0
    for size in column_sizes:
        lefts.append(position)
        position += size + gutter
    tops: list[int] = []
    position = 0
    for size in row_sizes:
        tops.append(position)
        position += size + gutter

    panes = []
    for slot in topology.slots:
        pane_width = sum(column_sizes[slot.column : slot.column + slot.column_span])
        pane_width += gutter * (slot.column_span - 1)
        pane_height = sum(row_sizes[slot.row : slot.row + slot.row_span])
        pane_height += gutter * (slot.row_span - 1)
        panes.append(
            PaneRect(slot.index, lefts[slot.column], tops[slot.row], pane_width, pane_height)
        )
    return tuple(panes)
