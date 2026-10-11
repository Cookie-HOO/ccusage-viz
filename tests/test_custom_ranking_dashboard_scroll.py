"""Exercise real Dashboard routing/composition with accepted local Dataset facts."""

from contextlib import nullcontext
from dataclasses import replace
from os import terminal_size
from time import monotonic

import pytest
from test_custom_ranking_scroll import projection

import ccusage_viz.tui as tui
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.options import ProcessConfig
from ccusage_viz.tui_input import InputDecoder, KeyEvent, MouseEvent, WheelEvent


@pytest.fixture
def dashboard(monkeypatch):
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            [
                "dashboard",
                "--empty",
                "--grid",
                "1x2",
                "--pane",
                "empty",
                "--pane",
                "empty",
                "--header-style",
                "hidden",
                "--header-summary",
                "none",
            ]
        )
    )
    panes = []
    for index in range(2):
        model = projection(100)
        config = replace(model.config, date_range=replace(model.date_range, fixed_bounds=True))
        component = CustomHistoricalComponent(config)
        component.model = replace(model, config=config)
        component.accepted_config = config
        component.pending_generation = None
        pane = tui.TuiCustomPane(
            component,
            FixedIntervalScheduler(3600, now=monotonic()),
            LifecycleOperation(f"scroll-test-{index}"),
            ProcessConfig(),
            probe_complete=True,
        )
        panes.append(pane)
    frames = []
    focuses = []
    geometries = []
    requests = []
    copied = []
    opened = []
    decoder = InputDecoder()
    size = [160, 30]

    class Screen:
        def __init__(self, stream):
            pass

        def paint(self, frame, **kwargs):
            frames.append(frame)

        def finish(self):
            pass

    def request(self, trigger, **kwargs):
        requests.append((self, trigger))
        # Accept data before entering the loop; only startup is stubbed.
        assert trigger == LifecycleTrigger.STARTUP, "wheel input must not request work"
        return False

    original_compose = tui._compose_resolved_panes

    def compose(contents, layout, **kwargs):
        focuses.append(kwargs["focused"])
        geometries.append(layout)
        return original_compose(contents, layout, **kwargs)

    original_new_pane = tui._new_pane
    supplied = iter(panes)
    monkeypatch.setattr(tui, "_new_pane", lambda *args, **kwargs: next(supplied))
    monkeypatch.setattr(tui, "FramePainter", Screen)
    monkeypatch.setattr(tui, "_compose_resolved_panes", compose)
    monkeypatch.setattr(tui, "tui_input_mode", lambda: nullcontext(decoder))
    monkeypatch.setattr(tui, "get_terminal_size", lambda: terminal_size(size))
    monkeypatch.setattr(LifecycleOperation, "request", request)
    monkeypatch.setattr(tui, "copy_command", lambda text: copied.append(text) or True)
    monkeypatch.setattr(tui.webbrowser, "open", lambda url: opened.append(url) or True)

    def run(events):
        turns = iter(events)

        def read(decoder, timeout):
            event = next(turns)
            return event() if callable(event) else event

        monkeypatch.setattr(tui, "read_event", read)
        assert tui.run_tui(run.options, load_translator("en")) == 0
        assert len(requests) == run.expected_requests

    run.options = options
    run.expected_requests = 2
    run.monkeypatch = monkeypatch
    run.new_pane = original_new_pane
    return run, panes, frames, focuses, geometries, decoder, copied, opened, size


def test_pointed_unfocused_pane_batches_wheel_without_queries_or_focus_change(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def burst():
        assert focuses[-1] == 1
        decoder.feed("\x1b[<65;2;3M" * 10 + "\x1b[<64;2;3M")
        before[0] = len(frames)
        return WheelEvent(1, 2, 3)

    before = [0]

    def check():
        assert panes[0].ranking_viewport.offset == 30
        assert panes[1].ranking_viewport.offset == 0
        assert len(frames) == before[0] + 1
        assert focuses[-1] == 1
        assert decoder.buffer == ""
        return KeyEvent("\x03")

    run([MouseEvent(0, 100, 1, True, 0), MouseEvent(0, 100, 1, True, 0), burst, check])


def test_two_panes_edges_outside_coordinates_and_no_idle_motion(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def right_border():
        rect = layouts[-1].pane(1)
        return WheelEvent(1, rect.left + rect.width, rect.top + 1)

    def after_idle():
        assert [p.ranking_viewport.offset for p in panes] == [3, 3]
        assert focuses[-1] == -1
        return KeyEvent("\x03")

    run(
        [
            WheelEvent(-1, 1, 1),  # Top clamp.
            WheelEvent(1, 1, 1),
            right_border,
            WheelEvent(1, 0, 3),
            WheelEvent(1, 161, 3),
            WheelEvent(1, 2, 30),
            None,
            None,
            after_idle,
        ]
    )
    # Startup and exactly two visible wheel moves.
    assert len(frames) == 3


def test_help_owns_wheel_and_reverse_leaves_bottom_immediately(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def bottom():
        decoder.feed("\x1b[<65;2;3M" * 100 + "\x1b[<64;2;3M")
        return WheelEvent(1, 2, 3)

    def check_bottom():
        viewport = panes[0].ranking_viewport
        assert viewport.offset == viewport.total_rows - viewport.visible_rows - 3
        before[0] = viewport.offset
        return KeyEvent("h")

    def check_help():
        assert panes[0].ranking_viewport.offset == before[0]
        return KeyEvent("\x1b")

    before = [0]
    run([bottom, check_bottom, WheelEvent(-1, 2, 3), check_help, KeyEvent("\x03")])


def test_scroll_copy_link_and_search_use_visible_stable_id(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, _ = dashboard
    target_id = []
    run.monkeypatch.setattr(
        tui, "_custom_ranking_copyable_entries", lambda *args: pytest.fail("full-list copy lookup")
    )

    def click_visible(*, link=False):
        pane = panes[0]
        row, (entry_id, column, link_column) = next(iter(pane.ranking_copy_rows.items()))
        target_id.append(entry_id)
        rect = layouts[-1].pane(0)
        # The default Dashboard is frameless until its pane owns focus.
        framed = focuses[-1] == 0
        return MouseEvent(
            0,
            rect.left + (link_column if link else column) + 1 + framed,
            rect.top + row + 1 + framed,
            True,
            0,
        )

    def check_copy():
        assert target_id[0] == "3"
        assert copied == ["Project 3\nhttps://example.com/3"]
        assert panes[0].copied_ranking_entry_id == "3"
        return click_visible(link=True)

    def check_link():
        assert opened == ["https://example.com/3"]
        return KeyEvent("\x03")

    run([WheelEvent(1, 2, 3), click_visible, check_copy, check_link])


def test_text_view_pending_and_nonranking_panes_do_not_scroll(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def hide_chart():
        assert panes[0].ranking_viewport.offset == 3
        panes[0].body_view = "command"
        return WheelEvent(1, 2, 3)

    def pending():
        assert panes[0].ranking_viewport.offset == 3
        panes[0].body_view = "chart"
        panes[0].component.pending_generation = panes[0].component.generation
        # Resize forces an actual pending paint on the next loop.
        dashboard[-1][0] = 162
        return None

    def check():
        assert not panes[0].ranking_viewport.active
        assert not panes[0].ranking_copy_rows
        assert panes[0].ranking_viewport.offset == 3
        return KeyEvent("\x03")

    run([WheelEvent(1, 2, 3), hide_chart, pending, WheelEvent(1, 2, 3), check])


def test_scrolling_uses_displayed_header_and_resized_geometry(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    run.options = replace(run.options, host=replace(run.options.host, header_style="full"))
    run.monkeypatch.setattr(tui, "_header_lines", lambda *args: ["header", "summary", "divider"])

    def resize():
        assert panes[0].ranking_viewport.offset == 3
        size[:] = [100, 16]
        return None

    def check():
        assert panes[0].ranking_viewport.offset == 3
        assert panes[1].ranking_viewport.offset == 3
        assert layouts[-1].width == 100
        return KeyEvent("\x03")

    run(
        [
            WheelEvent(1, 1, 1),
            WheelEvent(1, 1, 3),
            WheelEvent(1, 1, 4),
            resize,
            WheelEvent(1, 80, 4),
            check,
        ]
    )


def test_wheel_search_editing_resets_scroll_without_data_work(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def check_search():
        assert panes[0].ranking_viewport.offset == 0
        assert panes[0].ranking_search.query == "Project 9"
        assert next(iter(panes[0].ranking_copy_rows.values()))[0] == "9"
        return KeyEvent("\x03")

    run(
        [
            MouseEvent(0, 1, 1, True, 0),
            MouseEvent(0, 1, 1, True, 0),
            WheelEvent(1, 1, 1),
            KeyEvent("/"),
            *map(KeyEvent, "Project 9"),
            KeyEvent("\r"),
            check_search,
        ]
    )


def test_notices_audit_and_summary_stay_fixed(dashboard):
    from test_tui_custom import custom_summary_response

    from ccusage_viz.errors import QueryError

    run, panes, frames, focuses, layouts, decoder, *_ = dashboard
    pane = panes[0]
    pane.component.candidate = replace(
        pane.component.candidate,
        presentation=replace(pane.component.candidate.presentation, density="detailed"),
    )
    pane.component.accepted_config = pane.component.candidate
    pane.component.error = QueryError("error.query", detail="temporary failure")
    pane.summary = tui.CustomDashboardSummary(
        pane.component.candidate.source,
        FixedIntervalScheduler(3600, now=monotonic()),
        LifecycleOperation("test-summary"),
        response=custom_summary_response(display="68 pages"),
        accepted_period="day",
        accepted_as_of_date=pane.component.candidate.date_range.until,
    )
    snapshots = []
    original = tui._compose_resolved_panes

    def compose(contents, layout, **kwargs):
        snapshots.append(contents[0].splitlines())
        return original(contents, layout, **kwargs)

    run.monkeypatch.setattr(tui, "_compose_resolved_panes", compose)
    run([WheelEvent(1, 1, 1), KeyEvent("\x03")])
    before, after = snapshots[:2]
    assert before != after
    assert "68 pages" in "\n".join(before)
    assert before[0] == after[0]
    assert before[-1] == after[-1]
    assert pane.ranking_viewport.reserved_rows > 0
    assert len(before) == len(after)


def test_nonranking_custom_chart_does_not_gain_a_viewport(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard
    pane = panes[0]
    pane.component.candidate = replace(pane.component.candidate, kind="calendar")
    pane.component.accepted_config = pane.component.candidate
    pane.component.model = replace(
        pane.component.model, kind="calendar", config=pane.component.candidate
    )
    run([WheelEvent(1, 1, 1), KeyEvent("\x03")])
    assert pane.ranking_viewport.offset == 0
    assert not pane.ranking_viewport.active


@pytest.mark.parametrize("kind", ("ranking", "monitor"))
def test_native_ranking_and_monitor_ignore_wheels(dashboard, kind):
    from ccusage_viz.configuration import standalone_from_chart_pane

    run, panes, frames, focuses, layouts, decoder, *_ = dashboard
    native_options = _to_options(
        build_parser(load_translator("en")).parse_args(
            [
                "dashboard",
                "--pane",
                kind,
            ]
        )
    )
    panes[0] = run.new_pane(
        standalone_from_chart_pane(native_options, native_options.panes[0]), "native-test"
    )
    run.expected_requests = 3 if kind == "ranking" else 2
    run([WheelEvent(1, 1, 1), KeyEvent("\x03")])
    assert len(frames) == 1
    assert not hasattr(panes[0], "ranking_viewport")


def test_custom_monitor_ranking_ignores_wheels(dashboard):
    from ccusage_viz.custom_monitor_component import CustomMonitorComponent

    run, panes, frames, focuses, layouts, decoder, *_ = dashboard
    config = replace(
        panes[0].component.candidate,
        kind="monitor",
        presentation=replace(panes[0].component.candidate.presentation, style="ranking"),
    )
    panes[0].component = CustomMonitorComponent(config)
    run([WheelEvent(1, 1, 1), KeyEvent("\x03")])
    assert len(frames) == 1
    assert not panes[0].ranking_viewport.active


def test_opposite_wheels_with_unchanged_final_offset_do_not_paint(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def batch():
        decoder.feed("\x1b[<64;1;1M")
        return WheelEvent(1, 1, 1)

    run([batch, KeyEvent("\x03")])
    assert panes[0].ranking_viewport.offset == 0
    assert len(frames) == 1
