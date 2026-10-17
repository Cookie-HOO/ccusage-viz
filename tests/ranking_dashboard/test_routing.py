from dataclasses import replace
from time import monotonic

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.datasets.blocking as tui_datasets_blocking
import ccusage_viz.tui.datasets.modal as tui_datasets_modal
import ccusage_viz.tui.header as tui_header
import ccusage_viz.tui.layout as tui_layout
import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.painting as tui_painting
import ccusage_viz.tui.pointer as tui_pointer
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.render.ranking_viewport import RankingViewport
from ccusage_viz.tui_input import KeyEvent, MouseEvent, WheelEvent
from tests.ranking_scroll.helpers import grouped_projection


def test_grouped_dashboard_dispatch_wheel_and_hit_translation(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    del frames, decoder, opened
    size[:] = [160, 12]
    for pane in panes:
        model = grouped_projection()
        config = replace(model.config, date_range=replace(model.date_range, fixed_bounds=True))
        pane.component.candidate = pane.component.accepted_config = config
        pane.component.model = replace(model, config=config)

    target = []

    def click_visible():
        pane = panes[0]
        assert pane.grouped_ranking_viewport.active
        assert not pane.ranking_viewport.active
        row, (identity, column, _) = next(
            (row, hit) for row, hit in pane.ranking_copy_rows.items() if hit[0][0] == "group"
        )
        target.append(identity)
        rect = layouts[-1].pane(0)
        framed = focuses[-1] == 0
        return MouseEvent(
            0,
            rect.left + column + 1 + framed,
            rect.top + row + 1 + framed,
            True,
            0,
        )

    def verify():
        assert panes[0].grouped_ranking_viewport.offset == 1
        assert target[0][0] == "group"
        assert copied == [panes[0].grouped_ranking_viewport.clipboard_text(target[0])]
        return KeyEvent("\x03")

    run([WheelEvent(1, 2, 3), click_visible, verify])


def test_grouped_dashboard_incremental_numeric_search_survives_zero_matches(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    del frames, layouts, decoder, copied, opened
    size[:] = [160, 14]
    for pane in panes:
        model = grouped_projection()
        config = replace(model.config, date_range=replace(model.date_range, fixed_bounds=True))
        pane.component.candidate = pane.component.accepted_config = config
        pane.component.model = replace(model, config=config)

    def verify():
        pane = panes[0]
        assert pane.ranking_search.query == "gpt4"
        assert pane.grouped_ranking_viewport.visible_groups == ()
        assert pane.ranking_copy_rows == {}
        return KeyEvent("\x03")

    run(
        [
            MouseEvent(0, 1, 1, True, 0),
            MouseEvent(0, 1, 1, True, 0),
            KeyEvent("/"),
            *map(KeyEvent, "gpt4"),
            verify,
        ]
    )


def test_pointed_unfocused_pane_batches_wheel_without_queries_or_focus_change(dashboard):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def burst():
        assert focuses[-1] == 1
        decoder.feed("\x1b[<65;2;3M" * 10 + "\x1b[<64;2;3M")
        before[0] = len(frames)
        return WheelEvent(1, 2, 3)

    before = [0]

    def check():
        assert panes[0].ranking_viewport.offset == 10
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
        assert [p.ranking_viewport.offset for p in panes] == [1, 1]
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
        assert viewport.offset == viewport.total_rows - viewport.visible_rows - 1
        before[0] = viewport.offset
        return KeyEvent("h")

    def check_help():
        assert panes[0].ranking_viewport.offset == before[0]
        return KeyEvent("\x1b")

    before = [0]
    run([bottom, check_bottom, WheelEvent(-1, 2, 3), check_help, KeyEvent("\x03")])


def test_presentation_adjustments_retain_scrolled_ranking_interactions_without_work(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, _ = dashboard
    del frames, decoder
    pane = panes[0]
    # Start from a valid non-detailed density.  The native `d` adjustment must
    # establish detailed mode rather than a fixture assignment doing so.
    initial_config = replace(
        pane.component.candidate,
        presentation=replace(pane.component.candidate.presentation, density="full"),
    )
    pane.component.candidate = pane.component.accepted_config = initial_config
    pane.component.model = replace(pane.component.model, config=initial_config)
    initial_offset = 10
    states: list[
        tuple[object, tuple[int, tuple[float, float, float, bool], int, tuple[object | None, ...]]]
    ] = []

    def state() -> tuple[int, tuple[float, float, float, bool], int, tuple[object | None, ...]]:
        scheduler = pane.scheduler
        return (
            pane.component.generation,
            (
                scheduler.baseline,
                scheduler.interval,
                scheduler.next_opportunity,
                scheduler.stopping,
            ),
            len(requests),
            tuple(current.lifecycle.active for current in panes),
        )

    # The fixture's startup-only request assertion ensures that a presentation
    # adjustment cannot silently submit query work.
    requests = []
    original_request = LifecycleOperation.request

    def record_request(self, trigger, **kwargs):
        requests.append(trigger)
        return original_request(self, trigger, **kwargs)

    run.monkeypatch.setattr(LifecycleOperation, "request", record_request)

    def enter_adjustment():
        assert pane.ranking_viewport.offset == initial_offset
        return KeyEvent("m")

    def adjust(key: str, field: str, expected: str):
        def event():
            presentation = pane.component.candidate.presentation
            states.append((presentation, state()))
            assert getattr(presentation, field) != expected
            return KeyEvent(key)

        return event

    def check_adjustment(field: str, expected: str):
        presentation, (generation, scheduler, request_count, active) = states[-1]
        viewport = pane.ranking_viewport
        assert getattr(pane.component.candidate.presentation, field) == expected
        assert pane.component.candidate.presentation == replace(presentation, **{field: expected})
        assert pane.component.generation == generation
        assert (
            pane.scheduler.baseline,
            pane.scheduler.interval,
            pane.scheduler.next_opportunity,
            pane.scheduler.stopping,
        ) == scheduler
        assert len(requests) == request_count
        assert active == (None,) * len(panes)
        assert tuple(current.lifecycle.active for current in panes) == active
        expected_offset = min(initial_offset, max(0, viewport.total_rows - viewport.visible_rows))
        assert expected_offset > 0
        assert viewport.offset == expected_offset
        assert viewport.scrollbar is not None
        assert viewport.hits

    def after_density():
        check_adjustment("density", "detailed")
        return adjust("t", "theme", tui_adjustments.COLOR_SCHEMES[1])()

    def after_theme():
        check_adjustment("theme", tui_adjustments.COLOR_SCHEMES[1])
        return adjust("s", "style", "bar")()

    def click_visible(*, link: bool = False):
        # This hit map is freshly captured from the current rendered viewport.
        assert pane.ranking_copy_rows == pane.ranking_viewport.hits
        row, (entry_id, column, link_column) = next(
            (row, hit) for row, hit in pane.ranking_copy_rows.items() if hit[2] is not None
        )
        target.append(entry_id)
        rect = layouts[-1].pane(0)
        framed = focuses[-1] == 0
        return MouseEvent(
            0,
            rect.left + (link_column if link else column) + 1 + framed,
            rect.top + row + 1 + framed,
            True,
            0,
        )

    target: list[str] = []

    def after_style():
        check_adjustment("style", "bar")
        return click_visible()

    def check_copy():
        assert copied == [pane.ranking_viewport.clipboard_text(target[0])]
        assert target[0] in {entry_id for entry_id, *_ in pane.ranking_copy_rows.values()}
        return click_visible(link=True)

    def check_link():
        entry = pane.ranking_viewport.by_id[target[-1]]
        assert opened == [entry.project_link]
        return KeyEvent("\x03")

    run(
        [
            *(WheelEvent(1, 2, 3) for _ in range(initial_offset)),
            enter_adjustment,
            adjust("d", "density", "detailed"),
            after_density,
            after_theme,
            after_style,
            check_copy,
            check_link,
        ]
    )


def test_frameless_focus_reuses_two_committed_ranking_geometries(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, _ = dashboard
    del decoder, copied, opened
    pane = panes[0]
    viewport = pane.ranking_viewport
    initial_offset = 10
    prepared_widths: list[int] = []
    snapshots: dict[str, object] = {}
    original_prepare = RankingViewport.prepare_lines

    def geometry_key_parts(key: object) -> tuple[int, tuple[object, ...]]:
        # The renderer's geometry key starts with its effective context width.
        assert isinstance(key, tuple)
        width, *remaining = key
        assert isinstance(width, int)
        return width, tuple(remaining)

    def geometry_snapshot():
        return (
            viewport.columns.widths.copy(),
            viewport.columns.description_width,
            viewport.starts,
            viewport.heights,
            viewport.total_rows,
        )

    def runtime_state():
        return tuple(
            (
                current.component.generation,
                current.component.pending_generation,
                current.scheduler.baseline,
                current.scheduler.interval,
                current.scheduler.next_opportunity,
                current.scheduler.stopping,
                current.lifecycle.active,
            )
            for current in panes
        ), len(requests)

    def assert_usable():
        maximum_offset = max(0, viewport.total_rows - viewport.visible_rows)
        expected_offset = min(initial_offset, maximum_offset)
        assert expected_offset > 0
        assert viewport.offset == expected_offset
        assert viewport.scrollbar is not None
        assert viewport.scrollbar.offset == viewport.offset
        assert viewport.scrollbar.maximum_offset == maximum_offset
        assert viewport.hits
        assert pane.ranking_copy_rows == viewport.hits
        rect = layouts[-1].pane(0)
        framed = focuses[-1] == 0
        for row, (entry_id, _, _) in viewport.hits.items():
            assert viewport.body_top <= row < viewport.body_top + viewport.visible_rows
            assert entry_id in viewport.by_id
            frame_row = rect.top + row + int(framed)
            assert 0 <= frame_row < len(frames[-1].rows)
            assert any(marker in frames[-1].rows[frame_row] for marker in ("⊞", "✓"))
        assert runtime_state() == snapshots["runtime"]

    requests = []
    original_request = LifecycleOperation.request

    def record_request(self, trigger, **kwargs):
        requests.append((self, trigger))
        return original_request(self, trigger, **kwargs)

    run.monkeypatch.setattr(LifecycleOperation, "request", record_request)

    def after_initial_render():
        assert focuses[-1] == -1
        assert viewport.scrollbar is not None
        assert viewport.hits
        viewport.offset = initial_offset
        snapshots["unfocused_key"] = viewport.geometry_key
        snapshots["unfocused"] = geometry_snapshot()
        snapshots["runtime"] = runtime_state()

        def count_prepare(self, **kwargs):
            original_prepare(self, **kwargs)
            if self is viewport:
                prepared_widths.append(self.columns.description_width)

        run.monkeypatch.setattr(RankingViewport, "prepare_lines", count_prepare)
        return KeyEvent("m")

    def after_first_focus():
        assert focuses[-1] == 0
        assert viewport.geometry_key != snapshots["unfocused_key"]
        snapshots["focused_key"] = viewport.geometry_key
        snapshots["focused"] = geometry_snapshot()
        unfocused_width, unfocused_remaining = geometry_key_parts(snapshots["unfocused_key"])
        focused_width, focused_remaining = geometry_key_parts(snapshots["focused_key"])
        assert unfocused_width - focused_width == 2
        assert focused_remaining == unfocused_remaining
        assert viewport.columns.description_width != snapshots["unfocused"][1]
        assert prepared_widths == [viewport.columns.description_width]
        assert_usable()
        return KeyEvent("\x1b")

    def after_first_exit():
        assert focuses[-1] == -1
        assert viewport.geometry_key == snapshots["unfocused_key"]
        assert geometry_snapshot() == snapshots["unfocused"]
        assert prepared_widths == [snapshots["focused"][1]]
        assert_usable()
        return KeyEvent("m")

    def after_second_focus():
        assert focuses[-1] == 0
        assert viewport.geometry_key == snapshots["focused_key"]
        assert geometry_snapshot() == snapshots["focused"]
        assert prepared_widths == [snapshots["focused"][1]]
        assert_usable()
        return KeyEvent("\x1b")

    def after_second_exit():
        assert focuses[-1] == -1
        assert viewport.geometry_key == snapshots["unfocused_key"]
        assert geometry_snapshot() == snapshots["unfocused"]
        assert prepared_widths == [snapshots["focused"][1]]
        assert len(viewport._geometry_cache) == 2
        assert set(viewport._geometry_cache) == {
            snapshots["unfocused_key"],
            snapshots["focused_key"],
        }
        assert_usable()
        return KeyEvent("\x03")

    run(
        [
            after_initial_render,
            after_first_focus,
            after_first_exit,
            after_second_focus,
            after_second_exit,
        ]
    )


def test_text_view_and_nonranking_panes_do_not_scroll_while_pending_ranking_clears_viewport(
    dashboard,
):
    run, panes, frames, focuses, layouts, decoder, *_ = dashboard

    def hide_chart():
        assert panes[0].ranking_viewport.offset == 1
        panes[0].body_view = "command"
        return WheelEvent(1, 2, 3)

    def pending():
        assert panes[0].ranking_viewport.offset == 1
        panes[0].body_view = "chart"
        panes[0].component.configure(
            replace(panes[0].component.candidate, kind="timeline"), data_affecting=True
        )
        # Resize forces an actual pending paint on the next loop.
        dashboard[-1][0] = 162
        return None

    def check():
        assert not panes[0].ranking_viewport.active
        assert not panes[0].ranking_copy_rows
        assert panes[0].ranking_viewport.offset == 1
        return KeyEvent("\x03")

    run([WheelEvent(1, 2, 3), hide_chart, pending, WheelEvent(1, 2, 3), check])


def test_scrolling_uses_displayed_header_and_resized_geometry(dashboard):
    run, panes, frames, focuses, layouts, decoder, copied, opened, size = dashboard
    run.options = replace(run.options, host=replace(run.options.host, header_style="full"))
    run.monkeypatch.setattr(
        tui_header, "_header_lines", lambda *args: ["header", "summary", "divider"]
    )
    run.monkeypatch.setattr(
        tui_painting, "_header_lines", lambda *args: ["header", "summary", "divider"]
    )
    run.monkeypatch.setattr(
        tui_pointer, "_header_lines", lambda *args: ["header", "summary", "divider"]
    )
    run.monkeypatch.setattr(
        tui_datasets_blocking, "_header_lines", lambda *args: ["header", "summary", "divider"]
    )
    run.monkeypatch.setattr(
        tui_datasets_modal, "_header_lines", lambda *args: ["header", "summary", "divider"]
    )

    def resize():
        assert panes[0].ranking_viewport.offset == 1
        size[:] = [100, 16]
        return None

    def check():
        assert panes[0].ranking_viewport.offset == 1
        assert panes[1].ranking_viewport.offset == 1
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
    from ccusage_viz.errors import QueryError
    from tests.tui.custom_helpers import custom_summary_response

    run, panes, frames, focuses, layouts, decoder, *_ = dashboard
    pane = panes[0]
    pane.component.candidate = replace(
        pane.component.candidate,
        presentation=replace(pane.component.candidate.presentation, density="detailed"),
    )
    pane.component.accepted_config = pane.component.candidate
    pane.component.error = QueryError("error.query", detail="temporary failure")
    pane.summary = tui_models.CustomDashboardSummary(
        pane.component.candidate.source,
        FixedIntervalScheduler(3600, now=monotonic()),
        LifecycleOperation("test-summary"),
        response=custom_summary_response(display="68 pages"),
        accepted_period="day",
        accepted_as_of_date=pane.component.candidate.date_range.until,
    )
    snapshots = []
    original = tui_painting._compose_resolved_panes

    def compose(contents, layout, **kwargs):
        snapshots.append(contents[0].splitlines())
        return original(contents, layout, **kwargs)

    run.monkeypatch.setattr(tui_layout, "_compose_resolved_panes", compose)
    run.monkeypatch.setattr(tui_painting, "_compose_resolved_panes", compose)
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
