from dataclasses import replace

from ccusage_viz.formatting import strip_ansi
from ccusage_viz.tui_input import KeyEvent, MouseEvent, WheelEvent
from tests.ranking_scroll.helpers import grouped_projection


def test_dashboard_scrollbar_hover_expands_and_collapses_thumb(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    del decoder, copied, opened
    size[:] = [160, 12]
    captured: dict[str, object] = {}

    def hover_thumb():
        bar = panes[0].ranking_viewport.scrollbar
        assert bar is not None
        rect = layouts[-1].pane(0)
        captured["bar"] = bar
        captured["rect"] = rect
        captured["offset"] = panes[0].ranking_viewport.offset
        captured["focuses"] = len(focuses)
        return MouseEvent(
            3,
            rect.left + bar.column + 1,
            rect.top + bar.thumb_top + 1,
            False,
            0b100000,
        )

    def verify_hovered():
        bar = captured["bar"]
        rect = captured["rect"]
        assert panes[0].ranking_viewport.offset == captured["offset"]
        assert len(focuses) == captured["focuses"] + 1
        row = rect.top + bar.thumb_top
        assert strip_ansi(frames[-1].rows[row])[rect.left + bar.column] == "█"
        return MouseEvent(
            0,
            rect.left + bar.column + 1,
            rect.top + bar.thumb_top + 1,
            True,
            0,
        )

    def drag_thumb():
        bar = captured["bar"]
        rect = captured["rect"]
        return MouseEvent(
            0,
            rect.left + bar.column + 1,
            rect.top + bar.top + bar.travel + 1,
            True,
            0b100000,
        )

    def verify_dragged():
        bar = panes[0].ranking_viewport.scrollbar
        assert bar is not None
        rect = captured["rect"]
        assert panes[0].ranking_viewport.offset > captured["offset"]
        assert strip_ansi(frames[-1].rows[rect.top + bar.thumb_top])[rect.left + bar.column] == "█"
        return MouseEvent(0, 1, 1, False, 0)

    def verify_compact():
        bar = captured["bar"]
        rect = captured["rect"]
        row = rect.top + bar.thumb_top
        assert strip_ansi(frames[-1].rows[row])[rect.left + bar.column] == "│"
        assert panes[0].ranking_viewport.offset > captured["offset"]
        return KeyEvent("\x03")

    run([hover_thumb, verify_hovered, drag_thumb, verify_dragged, verify_compact])


def test_grouped_dashboard_scrollbar_drag_uses_active_viewport(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    del frames, decoder, copied, opened
    size[:] = [160, 12]
    for pane in panes:
        model = grouped_projection()
        coding = (model.groups or ())[0]
        seed = coding.series[0]
        series = tuple(
            replace(
                seed,
                id=f"item-{index}",
                label=replace(seed.label, en=f"Item {index}", zh_cn=f"Item {index}"),
                link=f"https://example.com/item-{index}",
            )
            for index in range(20)
        )
        groups = (replace(coding, series=series),)
        config = replace(model.config, date_range=replace(model.date_range, fixed_bounds=True))
        pane.component.candidate = pane.component.accepted_config = config
        pane.component.model = replace(model, config=config, groups=groups)

    captured: dict[str, object] = {}

    def grab_grouped_thumb():
        pane = panes[0]
        viewport = pane.grouped_ranking_viewport
        assert viewport.active and not pane.ranking_viewport.active
        bar = viewport.scrollbar
        assert bar is not None
        assert bar.maximum_offset == viewport.maximum_offset()
        rect = layouts[-1].pane(0)
        captured["bar"] = bar
        captured["rect"] = rect
        return MouseEvent(
            0,
            rect.left + bar.column + 1,
            rect.top + bar.thumb_top + 1,
            True,
            0,
        )

    def drag_to_bottom():
        bar = captured["bar"]
        rect = captured["rect"]
        return MouseEvent(
            0,
            rect.left + bar.column + 1,
            rect.top + bar.top + bar.travel + 1,
            True,
            0b100000,
        )

    def verify_grouped_bottom():
        viewport = panes[0].grouped_ranking_viewport
        assert viewport.offset == viewport.maximum_offset()
        assert viewport.scrollbar is not None
        assert viewport.scrollbar.maximum_offset == viewport.maximum_offset()
        assert panes[1].grouped_ranking_viewport.offset == 0
        return MouseEvent(0, 1, 1, False, 0)

    run([grab_grouped_thumb, drag_to_bottom, verify_grouped_bottom, KeyEvent("\x03")])


def test_scrollbar_drag_moves_body_and_releases_capture(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    captured: dict[str, object] = {}

    def prime():
        # One wheel step forces the scrollbar to materialize for hit testing.
        return WheelEvent(1, 2, 3)

    def grab_thumb():
        pane = panes[0]
        bar = pane.ranking_viewport.scrollbar
        assert bar is not None
        rect = layouts[-1].pane(0)
        framed = 0  # Unfocused dashboard panes render without a frame.
        captured["bar"] = bar
        captured["rect"] = rect
        captured["framed"] = framed
        captured["start"] = pane.ranking_viewport.offset
        x = rect.left + framed + bar.column + 1
        y = rect.top + framed + bar.thumb_top + 1
        return MouseEvent(0, x, y, True, 0)

    def drag_down():
        bar = captured["bar"]
        rect = captured["rect"]
        framed = captured["framed"]
        # A held-button motion report (motion modifier bit set) rides to the
        # bottom of the track.
        x = rect.left + framed + bar.column + 1
        y = rect.top + framed + (bar.top + bar.travel) + 1
        return MouseEvent(0, x, y, True, 0b100000)

    def check_dragged():
        pane = panes[0]
        assert pane.ranking_viewport.offset > captured["start"]
        assert pane.ranking_viewport.offset == pane.ranking_viewport.scrollbar.maximum_offset
        # The second pane never moves from a drag over the first.
        assert panes[1].ranking_viewport.offset == 0
        return MouseEvent(0, 1, 1, False, 0)

    def check_released():
        # After release a stray motion no longer scrolls the body.
        bar = captured["bar"]
        rect = captured["rect"]
        framed = captured["framed"]
        return MouseEvent(
            0,
            rect.left + framed + bar.column + 1,
            rect.top + framed + bar.top + 1,
            True,
            0b100000,
        )

    def check_inert():
        assert (
            panes[0].ranking_viewport.offset == panes[0].ranking_viewport.scrollbar.maximum_offset
        )
        return KeyEvent("\x03")

    run([prime, grab_thumb, drag_down, check_dragged, check_released, check_inert])


def test_scrollbar_track_click_pages_without_starting_drag(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    captured: dict[str, object] = {}

    def prime():
        return WheelEvent(1, 2, 3)

    def click_below_thumb():
        pane = panes[0]
        bar = pane.ranking_viewport.scrollbar
        assert bar is not None
        rect = layouts[-1].pane(0)
        captured["before"] = pane.ranking_viewport.offset
        captured["bar"] = bar
        captured["rect"] = rect
        # Click one row past the thumb bottom, inside the track.
        y = rect.top + (bar.thumb_top + bar.thumb_size) + 1
        return MouseEvent(0, rect.left + bar.column + 1, y, True, 0)

    def check_paged():
        pane = panes[0]
        assert (
            pane.ranking_viewport.offset == captured["before"] + pane.ranking_viewport.visible_rows
        )
        # A page click starts no drag: a later stray motion is inert.
        bar = captured["bar"]
        rect = captured["rect"]
        return MouseEvent(0, rect.left + bar.column + 1, rect.top + bar.top + 1, True, 0b100000)

    def check_no_drag():
        pane = panes[0]
        assert (
            pane.ranking_viewport.offset == captured["before"] + pane.ranking_viewport.visible_rows
        )
        return KeyEvent("\x03")

    run([prime, click_below_thumb, check_paged, check_no_drag])


def test_scrollbar_stationary_grab_and_release_cancel_do_not_move(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    captured: dict[str, object] = {}

    def prime():
        return WheelEvent(1, 2, 3)

    def grab_thumb():
        pane = panes[0]
        bar = pane.ranking_viewport.scrollbar
        rect = layouts[-1].pane(0)
        captured["bar"] = bar
        captured["rect"] = rect
        row = bar.thumb_top
        # The offset the implementation settles on for a stationary grab.
        captured["settled"] = bar.offset_at(row, bar.grab_at(row))
        return MouseEvent(0, rect.left + bar.column + 1, rect.top + row + 1, True, 0)

    def stationary_motion():
        # A motion to the same row keeps the settled offset unchanged (no jump).
        bar = captured["bar"]
        rect = captured["rect"]
        return MouseEvent(
            0, rect.left + bar.column + 1, rect.top + bar.thumb_top + 1, True, 0b100000
        )

    def cancel_with_release():
        assert panes[0].ranking_viewport.offset == captured["settled"]
        return MouseEvent(0, 1, 1, False, 0)

    def check_cancelled():
        # After release ends capture, a stray motion no longer scrolls.
        bar = captured["bar"]
        rect = captured["rect"]
        return MouseEvent(
            0,
            rect.left + bar.column + 1,
            rect.top + bar.top + bar.travel + 1,
            True,
            0b100000,
        )

    def check_inert():
        assert panes[0].ranking_viewport.offset == captured["settled"]
        return KeyEvent("\x03")

    run([prime, grab_thumb, stationary_motion, cancel_with_release, check_cancelled, check_inert])
