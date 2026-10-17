
import threading
from contextlib import nullcontext

import pytest

import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.historical_component import UsageSnapshot
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import Filters
from ccusage_viz.query.models import QueryTrigger
from ccusage_viz.tui_input import KeyEvent, MouseEvent


def test_dashboard_layout_editor_is_visible_transactional_and_returns_to_global(
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
            ]
        )
    )
    frames: list[object] = []

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
            self.cancelled.wait(10)
            raise RuntimeError("cancelled query must stay hidden")

    class Component:
        def __init__(self, selected: object, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_options = None
            self.error = None
            self.generation = 0
            self.snapshot = None
            self.accepted_generation = None

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

    keys = iter(
        (
            KeyEvent("d"),
            KeyEvent("Z"),
            *(KeyEvent(char) for char in "1x1"),
            KeyEvent("\r"),
            *(KeyEvent("\x7f") for _ in range(3)),
            *(KeyEvent(char) for char in "axbhuU"),
            KeyEvent("\r"),
            *(KeyEvent("\x7f") for _ in range(6)),
            *(KeyEvent(char) for char in "3x2"),
            KeyEvent("\r"),
            KeyEvent("Z"),
            KeyEvent("\x1b"),
            KeyEvent("z"),
            KeyEvent("\x1b"),
            KeyEvent("\x03"),
        )
    )
    runtime = Runtime()
    monkeypatch.setattr(tui_module, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "MonitorComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "MonitorComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_models.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    painted = ["\n".join(frame.rows) for frame in frames]
    assert any("Set grid (ROWSxCOLUMNS): " in frame for frame in painted)
    assert any(
        "Set grid (ROWSxCOLUMNS): 1x1" in frame
        and "Grid '1x1' cannot display all 5 panes." in frame
        for frame in painted
    )
    assert any(
        "Set grid (ROWSxCOLUMNS): axbhuU" in frame
        and "Grid 'axbhuU' cannot display all 5 panes." in frame
        for frame in painted
    )
    assert not any("Dashboard help" in frame for frame in painted)
    assert any("Set grid (ROWSxCOLUMNS): 3x2" in frame for frame in painted)
    assert any("Current status: running · 3x2" in frame for frame in painted)

def test_empty_dashboard_pane_double_click_enters_management_before_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--empty",
                "--grid",
                "1x2",
                "--pane",
                "empty",
                "--pane",
                "animate rain",
                "--header-style",
                "hidden",
                "--header-summary",
                "none",
            ]
        )
    )
    frames: list[object] = []

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    events = iter(
        (
            MouseEvent(0, 1, 1, True, 0),
            MouseEvent(0, 1, 1, True, 0),
            KeyEvent("r"),
            KeyEvent("\x1b"),
            MouseEvent(0, 70, 1, True, 0),
            MouseEvent(0, 70, 1, True, 0),
            KeyEvent("\x03"),
        )
    )
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_module,
        "layout_pane_at",
        lambda _layout, x, _y: 0 if x < 50 else 1,
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0

    painted = ["\n".join(frame.rows) for frame in frames]
    chooser_index = next(index for index, frame in enumerate(painted) if "Replace pane" in frame)
    management_index = next(
        index
        for index, frame in enumerate(painted)
        if "Dashboard Pane Management" in frame and "r replace" in frame
    )
    assert management_index < chooser_index
    assert "v switch view" not in painted[management_index]
    assert any(
        index > chooser_index and "p/P overlay position" in frame
        for index, frame in enumerate(painted)
    )

@pytest.mark.parametrize(
    ("edited", "expected_configures", "expected_submits"),
    (
        (
            Filters(agents=("Claude Code",)),
            [("configure", True, 1)],
            [
                ("submit", QueryTrigger.STARTUP, 0),
                ("submit", QueryTrigger.REFRESH, 1),
            ],
        ),
        (None, [], [("submit", QueryTrigger.STARTUP, 0)]),
    ),
)
def test_dashboard_pane_filter_editor_commits_once_or_discards_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
    edited: Filters | None,
    expected_configures: list[tuple[object, ...]],
    expected_submits: list[tuple[object, ...]],
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
                "timeline",
            ]
        )
    )
    events: list[tuple[object, ...]] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Submission:
        def __init__(self, generation: int) -> None:
            self.generation = generation
            self.purpose = tui_module.HistoricalPurpose.PRIMARY

        def cancel(self) -> None:
            events.append(("submission-cancel", self.generation))

        def result(self) -> object:
            return object()

    class Component:
        def __init__(self, selected: object, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_generation = None
            self.accepted_options = None
            self.accepted_at = None
            self.snapshot = None
            self.error = None
            self.generation = 0

        def configure(self, selected: object, *, data_affecting: bool) -> None:
            if selected == self.candidate:
                return
            self.candidate = selected
            if data_affecting:
                self.generation += 1
            events.append(("configure", data_affecting, self.generation))

        def missing_comparison_coverage(self) -> DateCoverage:
            return DateCoverage()

        def submit(self, trigger: QueryTrigger, **_kwargs: object) -> Submission:
            events.append(("submit", trigger, self.generation))
            return Submission(self.generation)

        def accept(self, _completion: object) -> bool:
            chart = self.candidate.chart
            self.snapshot = UsageSnapshot(
                (),
                (),
                0.1,
                coverage=DateCoverage.from_interval(
                    chart.date_range.since,
                    chart.date_range.until,
                ),
            )
            self.accepted_options = self.candidate
            self.accepted_generation = self.generation
            self.accepted_at = tui_module.datetime.now().astimezone()
            return True

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            events.append(("finish",))

    keys = iter((KeyEvent("m"), KeyEvent("a"), KeyEvent("f"), KeyEvent("\x03")))
    runtime = Runtime()
    monkeypatch.setattr(tui_module, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_module, "run_filter_editor", lambda *_args, **_kwargs: edited)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_models.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert [event for event in events if event[0] == "configure"] == expected_configures
    assert [event for event in events if event[0] == "submit"] == expected_submits
    assert events[-2:] == [("runtime-cancel",), ("finish",)]
