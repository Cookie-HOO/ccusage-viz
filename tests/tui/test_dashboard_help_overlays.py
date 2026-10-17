import threading
from contextlib import nullcontext

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.completion as tui_completion
import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.dashboard_events as tui_dashboard_events
import ccusage_viz.tui.datasets.blocking as tui_datasets_blocking
import ccusage_viz.tui.datasets.catalog as tui_datasets_catalog
import ccusage_viz.tui.datasets.chooser as tui_datasets_chooser
import ccusage_viz.tui.datasets.modal as tui_datasets_modal
import ccusage_viz.tui.events as tui_events
import ccusage_viz.tui.help as tui_help
import ccusage_viz.tui.history as tui_history
import ccusage_viz.tui.input as tui_input
import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.painting as tui_painting
import ccusage_viz.tui.pane_events as tui_pane_events
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.queries as tui_queries
import ccusage_viz.tui.rendering as tui_rendering
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.i18n import load_translator
from ccusage_viz.query.models import QueryTrigger
from ccusage_viz.tui_input import KeyEvent


def test_dashboard_preset_shortcuts_open_the_manager_and_do_not_adjust_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--demo", "--header-style", "hidden", "--pane", "timeline"]
        )
    )
    frames: list[object] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Submission:
        purpose = tui_models.HistoricalPurpose.PRIMARY
        handle: "Submission"

        def __init__(self, generation: int) -> None:
            self.generation = generation
            self.handle = self

        def cancel(self) -> None:
            pass

        def result(self) -> object:
            raise RuntimeError("not reached")

    class Component:
        def __init__(self, selected: object, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.error = None
            self.generation = 0
            self.snapshot = None

        def configure(self, selected: object, *, data_affecting: bool) -> None:
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

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    events = iter(
        (
            KeyEvent("p"),
            KeyEvent("s"),
            KeyEvent("\x10"),
            KeyEvent("\x1b"),
            KeyEvent("\x13"),
            KeyEvent("\x1b"),
            KeyEvent("\x03"),
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_models, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_rendering, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_completion, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_custom_adjustments, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_models, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_rendering, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_completion, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_custom_adjustments, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_queries, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_events, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_history, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_queries, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_history, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_input, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_catalog, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_chooser, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((120, 35)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((120, 35)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(
        tui_rendering, "_pane_render", lambda *_args: tui_models.PaneRender("chart")
    )
    monkeypatch.setattr(tui_painting, "_pane_render", lambda *_args: tui_models.PaneRender("chart"))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0

    text = "\n".join("\n".join(frame.rows) for frame in frames)
    assert "Dashboard presets" in text
    assert "Save current Dashboard as:" in text


@pytest.mark.parametrize(
    (
        "events_before_help",
        "expected_current",
        "expected_operation",
        "expected_page",
        "expects_text_navigation",
        "ascii_mode",
    ),
    (
        ((), "Browse mode", "Browse controls", None, False, False),
        (("v",), "Browse mode", "Browse controls", None, True, False),
        (("m",), "Pane adjustment", "Pane adjustment", "Quick", False, False),
        (("m", "v"), "Pane adjustment", "Pane adjustment", "Quick", True, False),
        (("m", "a"), "Pane adjustment", "Pane adjustment", "Advanced", False, False),
        (("d",), "Dashboard adjustment", "Dashboard adjustment", None, False, False),
        (("m",), "Pane adjustment", "Pane adjustment", "Quick", False, True),
    ),
)
def test_dashboard_help_explains_each_mode_without_repeating_footer(
    monkeypatch: pytest.MonkeyPatch,
    events_before_help: tuple[str, ...],
    expected_current: str,
    expected_operation: str,
    expected_page: str | None,
    expects_text_navigation: bool,
    ascii_mode: bool,
) -> None:
    parser = build_parser(load_translator("en"))
    args = [
        "dashboard",
        "--demo",
        "--header-style",
        "hidden",
        "--header-summary",
        "none",
        "--pane",
        "timeline",
    ]
    if ascii_mode:
        args.append("--ascii")
    options = _to_options(parser.parse_args(args))
    frames: list[object] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Submission:
        purpose = tui_models.HistoricalPurpose.PRIMARY
        handle: "Submission"

        def __init__(self, generation: int) -> None:
            self.generation = generation
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

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    keys = iter((*map(KeyEvent, events_before_help), KeyEvent("h"), KeyEvent("\x03")))
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_models, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_rendering, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_completion, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_custom_adjustments, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_models, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_rendering, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_completion, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_custom_adjustments, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_queries, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_events, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_history, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_queries, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_history, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_input, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_datasets_catalog, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_datasets_chooser, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((160, 55)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((160, 55)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(
        tui_rendering, "_pane_render", lambda *_args: tui_models.PaneRender("chart")
    )
    monkeypatch.setattr(tui_painting, "_pane_render", lambda *_args: tui_models.PaneRender("chart"))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0

    help_text = "\n".join(
        "\n".join(frame.rows) for frame in frames if "Dashboard help" in "\n".join(frame.rows)
    )
    assert expected_current in help_text
    active_marker = "* " if ascii_mode else "● "
    page_active_marker = "[x] " if ascii_mode else "● "
    page_inactive_marker = "[ ] " if ascii_mode else "○ "
    assert help_text.count(active_marker) >= 1
    assert "Current Pane adjustment" not in help_text
    assert expected_operation in help_text
    assert "Modes · current:" not in help_text
    assert "Global operations: u undo · U redo · h help" not in help_text
    assert "MODES" in help_text
    assert "CONTROLS" in help_text
    assert "LIMITS" not in help_text
    assert "STRATEGY" in help_text
    assert "💡" not in help_text
    assert "═" not in help_text
    assert "—" not in help_text
    assert "Dashboard undo/redo history is session-only" in help_text
    expects_summary_computation = events_before_help in {("m",), ("m", "a")}
    assert ("SUMMARY SCOPE [COMPUTATION LOGIC]" in help_text) is expects_summary_computation
    assert ("COMPARISON WINDOWS [COMPUTATION LOGIC]" in help_text) is expects_summary_computation
    if expects_summary_computation:
        assert "Fixed --since/--until" in help_text
        assert "Filters affect totals" in help_text
        assert "Day: today" in help_text
    if events_before_help == ():
        for interval in (
            "Historical refresh: 60s by default · --refresh-interval · not editable in Dashboard",
            "Monitor sampling: 15s by default · --sampling-interval · not editable in Dashboard",
            "Header refresh: 60s by default · --header-interval · not editable in Dashboard",
        ):
            assert interval in help_text
        assert "Historical refresh: 15s by default" not in help_text
        assert "Missed scheduled updates coalesce instead of replaying." in help_text
        assert "This Help closes automatically after 10 min idle." in help_text
        assert help_text.index(
            "Missed scheduled updates coalesce instead of replaying."
        ) < help_text.index("This Help closes automatically after 10 min idle.")
    if events_before_help in {(), ("v",)}:
        assert "Query subprocesses run up to 2 at a time" in help_text
        assert "coalesce" not in next(
            line for line in help_text.splitlines() if "Query subprocesses run up to 2" in line
        )
    branch = "|- " if ascii_mode else "├─ "
    assert branch in help_text
    assert "Enter adjustment: m Pane / d Dashboard" in help_text
    assert "Pane adjustment: selected Pane only" in help_text
    assert "Finish: Enter/Esc" in help_text
    assert "Dashboard adjustment: Dashboard-wide settings" in help_text
    assert "Enter: d" in help_text
    assert ("Text view" in help_text) is expects_text_navigation
    assert ("y copy: copy the current view" in help_text) is expects_text_navigation
    if expected_page is None:
        assert f"{page_inactive_marker}Quick" not in help_text
        assert f"{page_inactive_marker}Advanced" not in help_text
    elif expects_text_navigation:
        assert "Pane parameter adjustment" in help_text
        assert "Structure adjustment" in help_text
        assert "v/V view: change this Pane view" in help_text
    else:
        assert f"{page_active_marker}{expected_page}" in help_text
        assert "Pane parameter adjustment" in help_text
        assert "Structure adjustment" in help_text
        assert "Global common" in help_text
        assert "[Quick]" in help_text
        assert "[Advanced]" in help_text
        inactive_page = "Advanced" if expected_page == "Quick" else "Quick"
        assert f"{page_inactive_marker}{inactive_page}" in help_text
        for action in (
            "p/P period",
            "g/G granularity",
            "d/D density",
            "t/T theme",
            "s/S style",
            "o Other",
            "l legend",
            "k weekdays",
            "f edit filters",
        ):
            assert action in help_text
        assert "A project aggregation" not in help_text
        assert "P project labels" not in help_text
        assert "N / n insert: add a Pane before / after" in help_text
        assert "[ / ] order: move this Pane earlier / later" in help_text
        assert "x delete: remove this Pane" not in help_text
        if ascii_mode:
            assert "● " not in help_text
            assert "○ " not in help_text


def test_dashboard_overlay_editor_keeps_global_shortcuts_in_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--demo",
                "--header-style",
                "hidden",
                "--header-summary",
                "none",
                "--pane",
                "animate rain",
            ]
        )
    )
    frames: list[object] = []
    applied: list[tuple[str, str]] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    original_apply_draft = tui_models.AnimationOverlayRuntime.apply_draft

    def capture_draft(self: object, mode: str, draft: str) -> None:
        applied.append((mode, draft))
        original_apply_draft(self, mode, draft)

    keys = iter(
        (
            KeyEvent("m"),
            KeyEvent("h"),
            KeyEvent("\x1b"),
            KeyEvent("a"),
            KeyEvent("e"),
            KeyEvent("\x08"),
            KeyEvent("h"),
            KeyEvent("d"),
            KeyEvent("\x7f"),
            KeyEvent("{"),
            KeyEvent("}"),
            KeyEvent("\n"),
            KeyEvent("\x0b"),
            *map(KeyEvent, "hHuU"),
            KeyEvent("\t"),
            *map(KeyEvent, "hHuU"),
            KeyEvent("\x15"),
            KeyEvent("{"),
            KeyEvent("}"),
            KeyEvent("x"),
            KeyEvent("\x01"),
            KeyEvent("\x17"),
            KeyEvent("Y"),
            KeyEvent("\x02"),
            KeyEvent("\x02"),
            KeyEvent("Z"),
            KeyEvent("\r"),
            KeyEvent("\x03"),
        )
    )
    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_input, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_datasets_catalog, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_datasets_chooser, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((200, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((200, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((200, 30))
    )
    monkeypatch.setattr(tui_models.AnimationOverlayRuntime, "apply_draft", capture_draft)

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert applied == [("command", "Z{}Yx")]
    painted = "\n".join("\n".join(frame.rows) for frame in frames)
    assert "Draft cleared" in painted
    assert "DRAFT ·" in painted
    assert "NAV ·" in painted
    assert "OVERALL ·" in painted
    assert "Ctrl-J / Ctrl-K pane height" in painted
    assert "COMPLETE ·" not in painted
    assert "Overlay editor help" in painted
    assert "Dashboard help" in painted
    assert "[Advanced] e edit: edit text or command source" in painted
    assert "TEXT MODE: edit literal content displayed directly" in painted
    assert "COMMAND MODE: edit the shell command whose stdout is displayed" in painted
    assert "NAVIGATION" in painted
    assert "DRAFT" in painted
    assert "COMPLETE" in painted
    assert "DASHBOARD PANE" in painted
    assert "Ctrl-J/Ctrl-K: decrease / increase pane height" in painted
    assert "STRATEGY" not in painted
    assert "Dashboard undo/redo history is session-only" not in painted
    assert "Animation overlay commands time out after 30 seconds." not in painted
