import threading
from contextlib import nullcontext

import pytest

import ccusage_viz.tui as tui_module
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.deltas import RefreshRanks
from ccusage_viz.i18n import load_translator
from ccusage_viz.query.models import QueryTrigger
from ccusage_viz.tui import (
    _adjustment_controls,
    _choose_layout_shortcut,
    _choose_pane_type,
    _grid_for_pane_count,
    _grid_shape,
    _insert_pane,
    _local_pane_content,
    _practical_grid,
    _replace_pane,
    compose_panes,
    pane_at,
    pane_rects,
    parse_grid,
    resolve_panel_layout,
)
from ccusage_viz.tui_input import InputDecoder, KeyEvent


def test_tui_accepts_repeatable_pane_fragments_and_grid() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            ["dashboard", "--pane", "timeline --period 7d", "--pane", "ranking", "--grid", "1x2"]
        )
    )
    assert tuple(pane.chart.kind for pane in options.panes) == ("timeline", "ranking")
    assert options.panes[0].chart.date_range.period == "7d"
    assert options.host.grid == "1x2"


def test_dashboard_pane_notices_are_local_and_bounded() -> None:
    left = _local_pane_content("Left title\nleft chart", ("! left warning",), height=4)
    right = _local_pane_content("Right title\nright chart", (), height=4)
    output = compose_panes([left, right], 25, 4, 1, 2, frame_style="none", ascii=True)
    lines = output.splitlines()

    assert len(lines) == 4
    assert "Left title" in lines[0]
    assert "Right title" in lines[0]
    assert "! left" in lines[-1]
    assert lines[-1].count("! left") == 1
    assert lines[1].index("right chart") == lines[0].index("Right title")


def test_dashboard_identical_notices_remain_in_each_source_pane() -> None:
    notice = ("! same warning",)
    panes = [
        _local_pane_content("First", notice, height=4),
        _local_pane_content("Second", notice, height=4),
    ]

    output = compose_panes(panes, 25, 4, 1, 2, frame_style="none", ascii=True)

    assert output.count("! same") == 2


def test_dashboard_constrained_pane_preserves_identity_before_local_notices() -> None:
    pane = _local_pane_content("Identity\nbody\nstatus", ("notice one", "notice two"), height=3)

    assert pane.splitlines() == ["Identity", "body", "status"]


def test_tui_grid_auto_and_compositor() -> None:
    assert _grid_shape("auto", 3) == (2, 2)
    output = compose_panes(["a\nb", "c\nd"], 12, 4, 1, 2, focused=0)
    lines = output.splitlines()
    assert len(lines) == 4
    assert "a" in lines[1]
    assert "c" in lines[1]
    assert lines[1].startswith("║a")
    assert "│c" in lines[1]


def test_tui_default_frame_has_no_browse_outline_and_adjustment_outline_is_external() -> None:
    browsing = compose_panes(
        ["Title\nvalue"], 12, 4, 1, 1, focused=-1, frame_style="none", ascii=True
    )
    adjusting = compose_panes(
        ["Title\nvalue"], 12, 4, 1, 1, focused=0, frame_style="none", ascii=True
    )

    assert browsing.splitlines()[0].startswith("Title")
    assert adjusting.splitlines()[0] == "+----------+"
    assert adjusting.splitlines()[1].startswith("|Title")


def test_tui_persistent_frame_does_not_depend_on_focus() -> None:
    unfocused = compose_panes(["Title"], 12, 4, 1, 1, focused=-1, frame_style="subtle", ascii=True)
    focused = compose_panes(["Title"], 12, 4, 1, 1, focused=0, frame_style="subtle", ascii=True)

    assert unfocused == focused
    assert unfocused.splitlines()[1].startswith("|Title")


def test_refresh_ranks_tracks_movement_and_clear() -> None:
    ranks = RefreshRanks()

    ranks.accept(("a", "b", "c"))
    assert ranks.current == {}
    ranks.accept(("b", "a", "new"))
    assert ranks.current == {"b": 1, "a": -1}
    ranks.clear()
    assert ranks.previous == ranks.current == {}


def test_layout_chooser_shows_unavailable_layouts_and_skips_them() -> None:
    frames: list[object] = []

    class Screen:
        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

    events = iter((KeyEvent("j"), KeyEvent("\r")))

    assert (
        _choose_layout_shortcut(
            Screen(),
            load_translator("en"),
            InputDecoder(),
            height=20,
            current="wide",
            pane_count=4,
            read_input=lambda: next(events),
        )
        == "all"
    )

    initial = "\n".join(frames[0].rows)
    selected = "\n".join(frames[1].rows)
    assert "› wide" in initial
    assert "narrow · unavailable: 3 cells for 4 panes" in initial
    assert "› all" in selected


def test_layout_chooser_preserves_current_fixed_grid_value() -> None:
    class Screen:
        def paint(self, _frame: object, **_kwargs: object) -> None:
            pass

    events = iter((KeyEvent("\r"),))

    assert (
        _choose_layout_shortcut(
            Screen(),
            load_translator("en"),
            InputDecoder(),
            height=20,
            current="3x1",
            pane_count=3,
            read_input=lambda: next(events),
        )
        == "narrow"
    )


def test_pane_chooser_reuses_dashboard_decoder_and_ignores_mouse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args: object, **kwargs: object) -> None:
            pass

    decoder = InputDecoder()
    decoder.feed("\x1b[<0;20;5M\x1b[B\r")
    monkeypatch.setattr(
        tui_module,
        "read_event",
        lambda active, timeout: active.next(now=1.0),
    )

    assert (
        _choose_pane_type(
            Screen(),
            load_translator("en"),
            decoder,
            height=20,
        )
        == "timeline"
    )


def test_pane_chooser_opens_help_without_losing_selection() -> None:
    class Screen:
        def paint(self, *args: object, **kwargs: object) -> None:
            pass

    selected: list[str] = []
    events = iter((KeyEvent("h"), KeyEvent("\x1b[B"), KeyEvent("\r")))

    assert (
        _choose_pane_type(
            Screen(),
            load_translator("en"),
            InputDecoder(),
            height=20,
            read_input=lambda: next(events),
            on_help=selected.append,
        )
        == "timeline"
    )
    assert selected == ["empty"]


def test_pane_chooser_wraps_backward_to_datasets_and_escape_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args: object, **kwargs: object) -> None:
            pass

    decoder = InputDecoder()
    decoder.feed("k\r")
    monkeypatch.setattr(
        tui_module,
        "read_event",
        lambda active, timeout: active.next(now=1.0),
    )
    assert _choose_pane_type(Screen(), load_translator("en"), decoder, height=20) == "datasets"

    cancelled = InputDecoder()
    cancelled.feed("\x1b")
    moments = iter((1.0, 1.04))
    monkeypatch.setattr(
        tui_module,
        "read_event",
        lambda active, timeout: active.next(now=next(moments)),
    )
    assert _choose_pane_type(Screen(), load_translator("en"), cancelled, height=20) is None


def test_pane_chooser_uses_operation_specific_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    painted: list[tuple[str, str, str]] = []
    decoder = InputDecoder()
    decoder.feed("\x1b")
    moments = iter((1.0, 1.04))
    monkeypatch.setattr(
        tui_module,
        "read_event",
        lambda active, timeout: active.next(now=next(moments)),
    )

    assert (
        _choose_pane_type(
            object(),
            load_translator("en"),
            decoder,
            height=20,
            action="replace",
            paint_choices=lambda choices, title, controls, notices: painted.append(
                (choices, title, controls)
            ),
        )
        is None
    )
    assert painted[0][1:] == (
        "Replace pane",
        "j/k select · Enter replace · Esc cancel",
    )


def test_pane_chooser_localizes_names_and_includes_animation() -> None:
    painted: list[tuple[str, str, str]] = []

    assert (
        _choose_pane_type(
            object(),
            load_translator("zh"),
            InputDecoder(),
            height=20,
            paint_choices=lambda choices, title, controls, notices: painted.append(
                (choices, title, controls)
            ),
            read_input=lambda: KeyEvent("\x1b"),
        )
        is None
    )

    assert "空白 (Empty)" in painted[0][0]
    assert "时间趋势 (Timeline)" in painted[0][0]
    assert "监控 (Monitor)" in painted[0][0]
    assert "动画 (Animation)" in painted[0][0]
    assert "数据集…" in painted[0][0]


def test_tui_parses_runtime_numeric_grid_with_capacity() -> None:
    assert parse_grid("2X2", 3) == "2x2"
    assert parse_grid("auto", 3) is None
    assert parse_grid("spotlight-wide2", 3) is None
    assert parse_grid("wide", 3) is None
    assert parse_grid("1x2", 3) is None


@pytest.mark.parametrize(
    ("pane_count", "expected"),
    ((1, "1x1"), (2, "1x2"), (3, "2x2"), (4, "2x2"), (5, "3x2")),
)
def test_runtime_numeric_grid_draft_uses_practical_two_column_shape(
    pane_count: int, expected: str
) -> None:
    assert _practical_grid(pane_count) == expected


@pytest.mark.parametrize(
    ("grid", "pane_count", "expected"),
    (
        ("auto", 5, "auto"),
        ("spotlight-wide2", 5, "spotlight-wide2"),
        ("2x2", 4, "2x2"),
        ("2x2", 5, "3x2"),
        ("3x1", 4, "4x1"),
    ),
)
def test_pane_insertion_expands_rows_while_preserving_columns(
    grid: str, pane_count: int, expected: str
) -> None:
    assert _grid_for_pane_count(grid, pane_count) == expected


def test_replace_pane_is_atomic_and_shuts_down_displaced_lifecycle() -> None:
    events: list[tuple[str, int | str]] = []

    class Scheduler:
        def shutdown(self) -> None:
            events.append(("scheduler", "old"))

    class Lifecycle:
        def shutdown(self) -> None:
            events.append(("lifecycle", "old"))

    displaced = type("Pane", (), {"scheduler": Scheduler(), "lifecycle": Lifecycle()})()
    replacement = object()
    other = object()
    panes = [other, displaced]

    _replace_pane(
        panes,
        1,
        replacement,
        start=lambda index: events.append(("start", index)),
    )

    assert panes == [other, replacement]
    assert events == [("start", 1), ("scheduler", "old"), ("lifecycle", "old")]


def test_insert_pane_uses_list_index_and_starts_only_new_pane() -> None:
    before = object()
    focused = object()
    after = object()
    inserted = object()
    panes = [before, focused, after]
    started: list[int] = []

    _insert_pane(panes, 1, inserted, start=started.append)

    assert panes == [before, inserted, focused, after]
    assert started == [1]


@pytest.mark.parametrize(
    ("key", "expected"),
    (("J", (11, 13)), ("K", (13, 11))),
)
@pytest.mark.parametrize("first_pane", ("ranking", "animate rain"))
def test_dashboard_pane_height_keys_adjust_only_shared_row_weights(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    expected: tuple[int, int],
    first_pane: str,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--demo",
                "--grid",
                "2x1",
                "--header-style",
                "hidden",
                "--header-summary",
                "none",
                "--pane",
                first_pane,
                "--pane",
                "timeline",
            ]
        )
    )
    copied: list[str] = []
    rendered_views: list[str] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Submission:
        def __init__(self, generation: int) -> None:
            self.generation = generation
            self.purpose = tui_module.HistoricalPurpose.PRIMARY
            self.handle = self
            self.cancelled = threading.Event()

        def cancel(self) -> None:
            self.cancelled.set()

        def result(self) -> object:
            self.cancelled.wait(1)
            raise RuntimeError("cancelled startup query")

    class Component:
        def __init__(self, selected: object, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.error = None
            self.generation = 0
            self.snapshot = None

        def configure(self, selected: object, *, data_affecting: bool) -> None:
            if selected != self.candidate:
                self.candidate = selected
                if data_affecting:
                    self.generation += 1

        def missing_comparison_coverage(self) -> DateCoverage:
            return DateCoverage()

        def submit(self, _trigger: QueryTrigger, **_kwargs: object) -> Submission:
            return Submission(self.generation)

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            pass

    keys = iter(
        (
            KeyEvent("m"),
            KeyEvent(key),
            KeyEvent("v"),
            KeyEvent("\x1b"),
            KeyEvent("v"),
            KeyEvent("y"),
            KeyEvent("\x03"),
        )
    )
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_module, "copy_command", lambda command: copied.append(command) or True)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )

    def render(pane: object, *_args: object) -> tui_module.PaneRender:
        rendered_views.append(pane.body_view)
        return tui_module.PaneRender("chart")

    monkeypatch.setattr(tui_module, "_pane_render", render)

    assert tui_module.run_tui(options, load_translator("en")) == 0

    assert copied
    assert f"--row-weight {expected[0]} --row-weight {expected[1]}" in copied[-1]
    if first_pane == "ranking":
        assert "--top 10" in copied[-1]
    else:
        assert "--pane 'animate rain'" in copied[-1]
    if first_pane == "ranking":
        assert "command" in rendered_views
        assert rendered_views[-1:] == ["chart"]
    else:
        assert rendered_views
        assert all(view == "chart" for view in rendered_views)


def test_dashboard_pane_adjustment_preserves_chart_top_shortcuts() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["chart", "ranking"]))

    assert tui_module.adjust_standalone(base, "+").chart.top == base.chart.top + 1
    assert tui_module.adjust_standalone(base, "-").chart.top == base.chart.top - 1
    assert tui_module._adjustment_key_supported("ranking", "quick", "+")
    assert tui_module._adjustment_key_supported("ranking", "quick", "-")
    assert not tui_module._adjustment_key_supported("ranking", "quick", "J")
    assert not tui_module._adjustment_key_supported("ranking", "quick", "K")


def test_pane_advanced_actions_exclude_dashboard_management() -> None:
    controls = _adjustment_controls("timeline", "advanced", load_translator("en"))

    assert "f edit filters" in controls
    assert "r replace" not in controls
    assert "N insert before" not in controls
    assert "n insert after" not in controls
    assert parse_grid("zero", 1) is None


def test_tui_panel_layout_allocates_remainders_and_compositor_height() -> None:
    layout = resolve_panel_layout(width=11, height=9, rows=2, columns=2, divider_style="line")
    assert layout.widths == (5, 5)
    assert layout.heights == (4, 4)
    assert (layout.width, layout.height) == (11, 9)
    assert len(compose_panes(["a", "b", "c"], 11, 9, 2, 2, divider_style="line").splitlines()) == 9


def test_tui_pane_rects_hit_test_grid_without_empty_cells() -> None:
    rects = pane_rects(pane_count=3, width=80, height=26, rows=2, columns=2)
    assert pane_at(rects, 1, 2) == 0
    assert pane_at(rects, 42, 2) == 1
    assert pane_at(rects, 1, 16) == 2
    assert pane_at(rects, 41, 16) is None
    assert pane_at(rects, 1, 1) is None


def test_tui_pane_rects_share_line_divider_geometry() -> None:
    rects = pane_rects(pane_count=3, width=11, height=9, rows=2, columns=2, divider_style="line")
    assert pane_at(rects, 1, 2) == 0
    assert pane_at(rects, 7, 2) == 1
    assert pane_at(rects, 6, 2) is None
    assert pane_at(rects, 1, 7) == 2
