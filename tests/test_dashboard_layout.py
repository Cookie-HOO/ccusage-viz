from __future__ import annotations

import inspect

import pytest

from ccusage_viz.dashboard_layout import (
    adjust_weight,
    layout_bands,
    layout_for_pane_count,
    normalize_weights,
    pane_at,
    parse_layout,
    reconcile_weights,
    resolve_pane_layout,
)


@pytest.mark.parametrize(
    ("value", "count", "expected"),
    [
        ("AUTO", 3, "auto"),
        ("SPOTLIGHT-WIDE", 3, "spotlight-wide"),
        ("Spotlight-Wide2", 3, "spotlight-wide2"),
        ("spotlight-TALL", 3, "spotlight-tall"),
        ("2X2", 4, "2x2"),
    ],
)
def test_parse_layout_normalizes_valid_values(value: str, count: int, expected: str) -> None:
    assert parse_layout(value, count) == expected


@pytest.mark.parametrize(
    ("value", "count"),
    [
        ("", 1),
        ("zero", 1),
        ("2", 1),
        ("2x", 1),
        ("2x2x2", 1),
        ("0x2", 1),
        ("-1x2", 1),
        ("1x1", 2),
        ("auto", 0),
        ("wide", 4),
        ("narrow", 4),
        ("all", 4),
    ],
)
def test_parse_layout_rejects_invalid_or_insufficient_values(value: str, count: int) -> None:
    assert parse_layout(value, count) is None


@pytest.mark.parametrize(
    ("layout", "count", "expected"),
    [
        ("3x1", 2, "2x1"),
        ("2x2", 3, "2x2"),
        ("3x2", 4, "2x2"),
        ("2x2", 5, "3x2"),
        ("1x4", 3, "1x4"),
        ("auto", 5, "auto"),
        ("spotlight-wide", 5, "spotlight-wide"),
        ("spotlight-wide2", 5, "spotlight-wide2"),
        ("spotlight-tall", 5, "spotlight-tall"),
    ],
)
def test_layout_for_pane_count_reconciles_only_fixed_rows(
    layout: str, count: int, expected: str
) -> None:
    assert layout_for_pane_count(layout, count) == expected


def test_weights_are_positive_canonical_and_reconciled_by_trailing_band() -> None:
    assert normalize_weights((2, 4, 6)) == (1, 2, 3)
    assert reconcile_weights((2, 4), 3) == (1, 2, 1)
    assert reconcile_weights((2, 4, 6), 2) == (1, 2)
    assert adjust_weight((2, 2), 0, 2) == (3, 1)
    assert adjust_weight((1, 3), 0, -4) == (1, 3)
    with pytest.raises(ValueError):
        normalize_weights((1, 0))


def test_fixed_grid_geometry_preserves_empty_cell_and_dividers() -> None:
    layout = resolve_pane_layout(
        layout="2x2", pane_count=3, width=11, height=9, divider_style="line"
    )

    assert layout.column_sizes == (5, 5)
    assert layout.row_sizes == (4, 4)
    assert layout.panes == (
        layout.pane(0),
        layout.pane(1),
        layout.pane(2),
    )
    assert pane_at(layout, 0, 0) == 0
    assert pane_at(layout, 6, 0) == 1
    assert pane_at(layout, 0, 5) == 2
    assert pane_at(layout, 5, 0) is None
    assert pane_at(layout, 6, 5) is None


@pytest.mark.parametrize(
    ("count", "rows", "columns"),
    [(1, 1, 1), (2, 1, 2), (3, 2, 2), (5, 3, 2)],
)
def test_auto_retains_current_two_column_shape(count: int, rows: int, columns: int) -> None:
    layout = resolve_pane_layout(layout="auto", pane_count=count, width=81, height=31)
    assert (layout.topology.rows, layout.topology.columns) == (rows, columns)


def test_spotlight_wide_features_first_pane_over_fresh_auxiliary_grid() -> None:
    layout = resolve_pane_layout(layout="spotlight-wide", pane_count=5, width=81, height=31)

    featured = layout.pane(0)
    assert layout.rendered == "spotlight-wide"
    assert featured.left == 0
    assert featured.width == 81
    assert all(rect.top > featured.top for rect in layout.panes[1:])
    assert layout.topology.slot(0).column_span == 2


@pytest.mark.parametrize(
    ("count", "rows", "columns"),
    [(1, 1, 1), (2, 2, 1), (3, 3, 2), (4, 3, 2), (5, 4, 2), (7, 5, 2)],
)
def test_spotlight_wide2_has_two_full_width_leading_panes(
    count: int, rows: int, columns: int
) -> None:
    layout = resolve_pane_layout(layout="spotlight-wide2", pane_count=count, width=81, height=31)

    assert layout.rendered == "spotlight-wide2"
    assert (layout.topology.rows, layout.topology.columns) == (rows, columns)
    if count > 1:
        assert layout.pane(0).width == layout.pane(1).width == 81
        assert layout.pane(0).top < layout.pane(1).top
    if count > 2:
        assert layout.topology.slot(0).column_span == layout.topology.slot(1).column_span == 2
        assert layout.topology.slot(2).row == 2
        assert layout.topology.slot(2).column == 0


def test_spotlight_tall_features_first_pane_beside_auxiliary_grid() -> None:
    layout = resolve_pane_layout(layout="spotlight-tall", pane_count=5, width=81, height=31)

    featured = layout.pane(0)
    assert layout.rendered == "spotlight-tall"
    assert featured.top == 0
    assert featured.height == 31
    assert all(rect.left > featured.left for rect in layout.panes[1:])
    assert layout.topology.slot(0).row_span == 2


def test_narrow_tall_falls_back_without_mutating_configured_layout() -> None:
    narrow = resolve_pane_layout(layout="spotlight-tall", pane_count=5, width=12, height=31)
    wide = resolve_pane_layout(layout="spotlight-tall", pane_count=5, width=81, height=31)

    assert narrow.configured == wide.configured == "spotlight-tall"
    assert narrow.rendered == "spotlight-wide"
    assert wide.rendered == "spotlight-tall"
    assert tuple(rect.index for rect in narrow.panes) == tuple(rect.index for rect in wide.panes)


def test_one_spotlight_pane_occupies_entire_body() -> None:
    for configured in ("spotlight-wide", "spotlight-tall"):
        layout = resolve_pane_layout(layout=configured, pane_count=1, width=79, height=23)
        assert layout.pane(0) == type(layout.pane(0))(0, 0, 0, 79, 23)


def test_weighted_geometry_allocates_shared_logical_bands() -> None:
    layout = resolve_pane_layout(
        layout="2x2",
        pane_count=4,
        width=13,
        height=13,
        column_weights=(1, 2),
        row_weights=(2, 1),
    )

    assert layout.column_sizes == (4, 8)
    assert layout.row_sizes == (8, 4)
    assert layout.pane(1).width == layout.pane(3).width == 8
    assert layout.pane(0).height == layout.pane(1).height == 8


def test_layout_bands_describe_configured_spotlight_topology() -> None:
    assert layout_bands("spotlight-wide", 5) == type(layout_bands("auto", 1))(3, 2)
    assert layout_bands("spotlight-tall", 5) == type(layout_bands("auto", 1))(2, 3)


def test_resolver_has_no_focus_input() -> None:
    assert "focused" not in inspect.signature(resolve_pane_layout).parameters


@pytest.mark.parametrize(
    ("configured", "count", "width", "height"),
    [
        ("auto", 5, 81, 31),
        ("3x2", 5, 80, 30),
        ("spotlight-wide", 6, 79, 29),
        ("spotlight-tall", 6, 79, 29),
        ("spotlight-tall", 6, 12, 29),
    ],
)
def test_resolved_rectangles_are_complete_bounded_and_non_overlapping(
    configured: str, count: int, width: int, height: int
) -> None:
    layout = resolve_pane_layout(layout=configured, pane_count=count, width=width, height=height)
    assert tuple(rect.index for rect in layout.panes) == tuple(range(count))
    for rect in layout.panes:
        assert rect.width > 0 and rect.height > 0
        assert 0 <= rect.left < rect.left + rect.width <= width
        assert 0 <= rect.top < rect.top + rect.height <= height
    for index, left in enumerate(layout.panes):
        for right in layout.panes[index + 1 :]:
            assert (
                left.left + left.width <= right.left
                or right.left + right.width <= left.left
                or left.top + left.height <= right.top
                or right.top + right.height <= left.top
            )
