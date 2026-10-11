from dataclasses import replace

import pytest

from ccusage_viz.scrollbar import Scrollbar


def test_proportional_thumb_endpoints_and_paging():
    bar = Scrollbar(79, 3, 20, 100, 20, 0)
    assert bar.thumb_size == 4
    assert bar.thumb_top == 3
    assert bar.travel == 16
    assert bar.maximum_offset == 80
    assert bar.contains(79, 3)
    assert not bar.contains(78, 3)
    assert not bar.contains(79, 23)
    assert bar.page_offset(10) == 20
    assert bar.page_offset(4) == 0
    middle = replace(bar, offset=40)
    assert middle.thumb_top == 11
    assert middle.page_offset(3) == 20
    assert middle.page_offset(22) == 60
    assert replace(bar, offset=80).thumb_top == 19


@pytest.mark.parametrize("height", (0, 1, 2, 3, 20))
def test_small_tracks_near_fit_and_very_large_lists(height):
    for total in (height + 1, 100_000):
        bar = Scrollbar(1, 0, height, total, height, 0)
        assert 0 <= bar.thumb_size <= height
        if height > 1:
            assert 1 <= bar.thumb_size < height
            assert replace(bar, offset=bar.maximum_offset).thumb_top + bar.thumb_size == height
        else:
            assert bar.travel == 0


def test_drag_capture_grab_and_offset_mapping():
    bar = Scrollbar(79, 3, 20, 100, 20, 0)
    # Pressing inside the thumb records the row distance from its top edge.
    assert bar.grab_at(5) == 2
    # Dragging the captured cell down moves the offset proportionally.
    assert bar.offset_at(5, grab=2) == 0
    assert bar.offset_at(bar.top + bar.travel, grab=0) == bar.maximum_offset
    # Beyond the track the offset clamps to the valid range.
    assert bar.offset_at(1000, grab=0) == bar.maximum_offset
    assert bar.offset_at(-1000, grab=0) == 0
    # A track click centering the thumb lands under the pressed cell.
    middle = replace(bar, offset=bar.offset_at(11, grab=bar.thumb_size // 2))
    assert middle.on_thumb(11)


def test_offset_mapping_is_inert_without_travel():
    bar = Scrollbar(1, 0, 1, 100, 1, 0)
    assert bar.travel == 0
    assert bar.offset_at(50, grab=0) == 0
