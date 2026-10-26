from __future__ import annotations

import pytest

from ccusage_viz.dashboard_layout import (
    MIN_PANE_WIDTH,
    PaneRect,
    adjust_weight,
    build_topology,
    layout_bands,
    normalize_weights,
    pane_at,
    reconcile_weights,
    resolve_pane_layout,
)


@pytest.mark.parametrize(
    ("pane_count", "columns", "spotlight", "rows", "expected"),
    [
        (1, 1, 0, 1, ((0, 0, 1),)),
        (5, 3, 0, 2, ((0, 0, 1), (0, 1, 1), (0, 2, 1), (1, 0, 1), (1, 1, 1))),
        (5, 3, 2, 3, ((0, 0, 3), (1, 0, 3), (2, 0, 1), (2, 1, 1), (2, 2, 1))),
        (3, 4, 3, 3, ((0, 0, 4), (1, 0, 4), (2, 0, 4))),
    ],
)
def test_parameterized_topology(
    pane_count: int,
    columns: int,
    spotlight: int,
    rows: int,
    expected: tuple[tuple[int, int, int], ...],
) -> None:
    topology = build_topology(columns=columns, spotlight=spotlight, pane_count=pane_count)
    assert (topology.rows, topology.columns) == (rows, columns)
    assert tuple((slot.row, slot.column, slot.column_span) for slot in topology.slots) == expected


@pytest.mark.parametrize(
    ("columns", "spotlight", "pane_count"), [(0, 0, 1), (1, -1, 1), (1, 2, 1), (1, 0, 0)]
)
def test_invalid_topology_is_rejected(columns: int, spotlight: int, pane_count: int) -> None:
    with pytest.raises(ValueError):
        build_topology(columns=columns, spotlight=spotlight, pane_count=pane_count)


def test_layout_bands_resolve_spotlight_and_ordinary_rows() -> None:
    assert layout_bands(columns=3, spotlight=2, pane_count=7) == type(
        layout_bands(columns=3, spotlight=2, pane_count=7)
    )(4, 3)


def test_weights_preserve_resolution_and_adjust() -> None:
    assert normalize_weights((12, 24, 36)) == (12, 24, 36)
    assert reconcile_weights((2, 4), 3) == (8, 16, 4)
    assert adjust_weight((1, 1), 0, 1) == (13, 11)
    assert adjust_weight((12, 24, 36), 1, 2) == (12, 26, 34)
    with pytest.raises(ValueError):
        normalize_weights((1, 0))


def test_spotlight_geometry_spans_all_columns_and_keeps_empty_last_cell() -> None:
    layout = resolve_pane_layout(
        columns=3,
        spotlight=2,
        pane_count=7,
        width=17,
        height=14,
        divider_style="line",
    )
    assert layout.pane(0).width == layout.pane(1).width == 17
    assert layout.topology.slot(0).column_span == 3
    assert layout.topology.slot(2).row == 2
    assert layout.topology.slot(6).row == 3
    assert layout.topology.slot(6).column == 1
    assert pane_at(layout, 16, 0) == 0
    assert pane_at(layout, 16, layout.pane(6).top) is None


def test_exact_spotlight_rectangles_include_internal_gutters() -> None:
    layout = resolve_pane_layout(
        columns=2, spotlight=2, pane_count=4, width=13, height=10, divider_style="line"
    )
    assert layout.panes == (
        PaneRect(0, 0, 0, 13, 3),
        PaneRect(1, 0, 4, 13, 3),
        PaneRect(2, 0, 8, 6, 2),
        PaneRect(3, 7, 8, 6, 2),
    )


def test_weighted_geometry_allocates_shared_bands() -> None:
    layout = resolve_pane_layout(
        columns=2,
        spotlight=0,
        pane_count=4,
        width=13,
        height=13,
        column_weights=(1, 2),
        row_weights=(2, 1),
    )
    assert layout.column_sizes == (5, 7)
    assert layout.row_sizes == (7, 5)


def test_weighted_layout_keeps_feasible_minimum() -> None:
    layout = resolve_pane_layout(
        columns=2,
        spotlight=0,
        pane_count=2,
        width=80,
        height=3,
        column_weights=(1, 1000),
        row_weights=(1,),
    )
    assert layout.column_sizes == (MIN_PANE_WIDTH, 75)


@pytest.mark.parametrize(("width", "expected"), [(3, (1, 1, 1)), (1, (0, 0, 0))])
def test_impossible_axes_degrade_safely(width: int, expected: tuple[int, int, int]) -> None:
    layout = resolve_pane_layout(
        columns=3, spotlight=0, pane_count=3, width=width, height=7, divider_style="line"
    )
    assert layout.column_sizes == expected
