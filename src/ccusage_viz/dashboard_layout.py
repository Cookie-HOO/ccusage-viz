from __future__ import annotations

from dataclasses import dataclass
from math import ceil

MIN_WEIGHT_SHARES = 24
MIN_PANE_WIDTH = 4
MIN_PANE_HEIGHT = 3


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

    width: int
    height: int
    column_gutter: int
    row_gutter: int
    topology: PaneTopology
    column_sizes: tuple[int, ...]
    row_sizes: tuple[int, ...]
    panes: tuple[PaneRect, ...]

    @property
    def gutter(self) -> int:
        return min(self.column_gutter, self.row_gutter)

    def pane(self, index: int) -> PaneRect:
        return self.panes[index]


@dataclass(frozen=True, slots=True)
class LayoutBands:
    rows: int
    columns: int


def _validate_topology(columns: int, spotlight: int, pane_count: int) -> None:
    if pane_count < 1:
        raise ValueError("a Dashboard requires at least one Pane")
    if columns < 1:
        raise ValueError("Dashboard columns must be positive")
    if not 0 <= spotlight <= pane_count:
        raise ValueError("Dashboard spotlight must be between zero and the Pane count")


def build_topology(*, columns: int, spotlight: int, pane_count: int) -> PaneTopology:
    """Place leading spotlight Panes above a fixed-column ordinary grid."""
    _validate_topology(columns, spotlight, pane_count)
    ordinary_count = pane_count - spotlight
    rows = spotlight + (ceil(ordinary_count / columns) if ordinary_count else 0)
    slots = [PaneSlot(index, index, 0, column_span=columns) for index in range(spotlight)]
    slots.extend(
        PaneSlot(index, spotlight + (index - spotlight) // columns, (index - spotlight) % columns)
        for index in range(spotlight, pane_count)
    )
    return PaneTopology(rows, columns, tuple(slots))


def normalize_weights(weights: tuple[int, ...]) -> tuple[int, ...]:
    if not weights or any(weight < 1 for weight in weights):
        raise ValueError("layout weights must be positive integers")
    return weights


def reconcile_weights(weights: tuple[int, ...] | None, count: int) -> tuple[int, ...]:
    if count < 1:
        raise ValueError("a layout requires at least one band")
    current = normalize_weights(weights) if weights else ()
    reconciled = normalize_weights((*current[:count], *(1 for _ in range(count - len(current)))))
    return _expand_weight_pool(reconciled)


def _expand_weight_pool(weights: tuple[int, ...]) -> tuple[int, ...]:
    multiplier = ceil(MIN_WEIGHT_SHARES / sum(weights))
    return weights if multiplier == 1 else tuple(weight * multiplier for weight in weights)


def adjust_weight(weights: tuple[int, ...], index: int, delta: int) -> tuple[int, ...]:
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


def layout_bands(*, columns: int, spotlight: int, pane_count: int) -> LayoutBands:
    topology = build_topology(columns=columns, spotlight=spotlight, pane_count=pane_count)
    return LayoutBands(topology.rows, topology.columns)


def pane_at(layout: PaneLayout, x: int, y: int) -> int | None:
    for rect in layout.panes:
        if rect.left <= x < rect.left + rect.width and rect.top <= y < rect.top + rect.height:
            return rect.index
    return None


def pane_in_direction(layout: PaneLayout, current: int, key: str) -> int:
    if key == "\x1b[D":
        return (current - 1) % len(layout.panes)
    if key == "\x1b[C":
        return (current + 1) % len(layout.panes)
    directions = {"\x1b[A": (0, -1), "\x1b[B": (0, 1)}
    if key not in directions:
        return current
    source = layout.pane(current)
    source_x = source.left + source.width / 2
    source_y = source.top + source.height / 2
    dx, dy = directions[key]
    candidates: list[tuple[float, float, int]] = []
    for target in layout.panes:
        if target.index == current:
            continue
        target_x = target.left + target.width / 2
        target_y = target.top + target.height / 2
        primary = (target_x - source_x) * dx + (target_y - source_y) * dy
        if primary <= 0:
            continue
        secondary = abs((target_y - source_y) if dx else (target_x - source_x))
        candidates.append((secondary, primary, target.index))
    return min(candidates)[2] if candidates else current


def resolve_pane_layout(
    *,
    columns: int,
    spotlight: int,
    pane_count: int,
    width: int,
    height: int,
    divider_style: str = "line",
    column_weights: tuple[int, ...] | None = None,
    row_weights: tuple[int, ...] | None = None,
) -> PaneLayout:
    if width < 1 or height < 1:
        raise ValueError("layout dimensions must be positive")
    topology = build_topology(columns=columns, spotlight=spotlight, pane_count=pane_count)
    requested_gutter = 0 if divider_style == "none" else 1
    column_gutter = _resolve_gutter(requested_gutter, width, topology.columns)
    row_gutter = _resolve_gutter(requested_gutter, height, topology.rows)
    resolved_columns = _resolve_weights(column_weights, topology.columns)
    resolved_rows = _resolve_weights(row_weights, topology.rows)
    column_sizes = _allocate_axis(width, resolved_columns, column_gutter, minimum=MIN_PANE_WIDTH)
    row_sizes = _allocate_axis(height, resolved_rows, row_gutter, minimum=MIN_PANE_HEIGHT)
    panes = _pane_rectangles(topology, column_sizes, row_sizes, column_gutter, row_gutter)
    return PaneLayout(
        width, height, column_gutter, row_gutter, topology, column_sizes, row_sizes, panes
    )


def _resolve_gutter(requested: int, length: int, bands: int) -> int:
    return 0 if requested and length - (bands - 1) < bands else requested


def _resolve_weights(weights: tuple[int, ...] | None, count: int) -> tuple[int, ...]:
    if weights is None:
        return (1,) * count
    normalized = normalize_weights(weights)
    if len(normalized) != count:
        raise ValueError(f"expected {count} layout weights, got {len(normalized)}")
    return normalized


def _allocate_axis(
    total: int, weights: tuple[int, ...], gutter: int, *, minimum: int
) -> tuple[int, ...]:
    available = total - gutter * (len(weights) - 1)
    if available >= minimum * len(weights):
        base = minimum
    elif available >= len(weights):
        base = 1
    else:
        return tuple(0 for _ in weights)
    distributable = available - base * len(weights)
    weight_total = sum(weights)
    products = [distributable * weight for weight in weights]
    sizes = [base + product // weight_total for product in products]
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
    column_gutter: int,
    row_gutter: int,
) -> tuple[PaneRect, ...]:
    lefts: list[int] = []
    position = 0
    for size in column_sizes:
        lefts.append(position)
        position += size + column_gutter
    tops: list[int] = []
    position = 0
    for size in row_sizes:
        tops.append(position)
        position += size + row_gutter
    panes = []
    for slot in topology.slots:
        pane_width = sum(column_sizes[slot.column : slot.column + slot.column_span])
        pane_width += column_gutter * (slot.column_span - 1)
        pane_height = sum(row_sizes[slot.row : slot.row + slot.row_span])
        pane_height += row_gutter * (slot.row_span - 1)
        panes.append(
            PaneRect(slot.index, lefts[slot.column], tops[slot.row], pane_width, pane_height)
        )
    return tuple(panes)
