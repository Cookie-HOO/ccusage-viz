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
from ccusage_viz.historical_component import UsageSnapshot
from ccusage_viz.i18n import load_translator
from ccusage_viz.query.models import QueryTrigger
from ccusage_viz.tui_input import KeyEvent


@pytest.mark.parametrize("text_view", (False, True))
def test_dashboard_space_is_ignored_and_manual_refresh_remains_allowed(
    monkeypatch: pytest.MonkeyPatch,
    text_view: bool,
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
    submissions: list[object] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Submission:
        def __init__(self, generation: int) -> None:
            self.generation = generation
            self.purpose = tui_models.HistoricalPurpose.PRIMARY
            self.handle = self
            self.cancelled = threading.Event()

        def cancel(self) -> None:
            self.cancelled.set()
            events.append(("submission-cancel", self.generation))

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

        def configure(self, selected: object, *, data_affecting: bool) -> None:
            if selected != self.candidate:
                self.candidate = selected
                if data_affecting:
                    self.generation += 1

        def missing_comparison_coverage(self) -> DateCoverage:
            return DateCoverage()

        def submit(self, trigger: QueryTrigger, **_kwargs: object) -> Submission:
            events.append(("submit", trigger, self.generation))
            submission = Submission(self.generation)
            submissions.append(submission)
            return submission

        def fail(
            self,
            error: BaseException,
            *,
            generation: int,
            **_kwargs: object,
        ) -> bool:
            events.append(("fail", str(error), generation))
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            events.append(("paint", frame))

        def finish(self) -> None:
            events.append(("finish",))

    keys = iter(
        (KeyEvent("v"), KeyEvent("r"), KeyEvent(" "), KeyEvent("\x03"))
        if text_view
        else (KeyEvent(" "), KeyEvent("r"), KeyEvent("\x03"))
    )
    runtime = Runtime()
    monkeypatch.setattr(tui_session, "build_query_runtime", lambda: runtime)
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
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((100, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((100, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_rendering, "_pane_render", lambda *_args: tui_models.PaneRender("chart")
    )
    monkeypatch.setattr(tui_painting, "_pane_render", lambda *_args: tui_models.PaneRender("chart"))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    expected_submissions = [(QueryTrigger.STARTUP, 0)]
    if not text_view:
        expected_submissions.append((QueryTrigger.REFRESH, 0))
    assert [
        (event[1], event[2]) for event in events if event[0] == "submit"
    ] == expected_submissions
    painted_text = "\n".join("\n".join(event[1].rows) for event in events if event[0] == "paint")
    assert (not text_view) == ("refresh requested" in painted_text)
    assert "paused" not in painted_text
    assert len(submissions) == len(expected_submissions)
    assert submissions[0].cancelled.is_set()
    assert not any(event[0] == "fail" for event in events)
    assert events[-3:] == [
        ("submission-cancel", 0),
        ("runtime-cancel",),
        ("finish",),
    ]


def test_dashboard_manual_refresh_notice_clears_after_its_final_completion(
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
                "timeline",
            ]
        )
    )
    frames: list[object] = []
    release_manual = threading.Event()

    class Runtime:
        def cancel(self) -> None:
            pass

    class Submission:
        def __init__(self, generation: int, *, manual: bool) -> None:
            self.generation = generation
            self.purpose = tui_models.HistoricalPurpose.PRIMARY
            self.handle = self
            self.manual = manual
            self.cancelled = threading.Event()

        def cancel(self) -> None:
            self.cancelled.set()

        def result(self) -> object:
            if self.manual:
                assert release_manual.wait(1)
                return object()
            assert self.cancelled.wait(1)
            raise RuntimeError("cancelled startup query")

    class Component:
        def __init__(self, selected: object, **_kwargs: object) -> None:
            self.candidate = selected
            self.accepted_generation = None
            self.accepted_options = None
            self.accepted_at = None
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

        def submit(self, trigger: QueryTrigger, **_kwargs: object) -> Submission:
            return Submission(self.generation, manual=trigger is QueryTrigger.REFRESH)

        def accept(self, _completion: object) -> bool:
            chart = self.candidate.chart
            self.snapshot = UsageSnapshot(
                (),
                (),
                0.1,
                coverage=DateCoverage.from_interval(chart.date_range.since, chart.date_range.until),
            )
            self.accepted_generation = self.generation
            self.accepted_options = self.candidate
            self.accepted_at = tui_models.datetime.now().astimezone()
            return True

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    keys = iter((KeyEvent(" "), KeyEvent("r")))
    saw_notice = False

    def read_events(_decoder: object, _timeout: float) -> KeyEvent | None:
        nonlocal saw_notice
        try:
            return next(keys)
        except StopIteration:
            pass
        rendered = [frame.rows for frame in frames]
        if any("refresh requested · in progress" in rows for rows in rendered):
            saw_notice = True
            release_manual.set()
        if saw_notice and rendered and "refresh requested · in progress" not in rendered[-1]:
            return KeyEvent("\x03")
        threading.Event().wait(0.01)
        return None

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
    monkeypatch.setattr(tui_adjustments, "read_event", read_events)
    monkeypatch.setattr(tui_input, "read_event", read_events)
    monkeypatch.setattr(tui_datasets_catalog, "read_event", read_events)
    monkeypatch.setattr(tui_datasets_chooser, "read_event", read_events)
    monkeypatch.setattr(
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((100, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_datasets_blocking,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((100, 30)),
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(
        tui_rendering, "_pane_render", lambda *_args: tui_models.PaneRender("chart")
    )
    monkeypatch.setattr(tui_painting, "_pane_render", lambda *_args: tui_models.PaneRender("chart"))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0

    refreshing = [frame.rows for frame in frames if "refresh requested · in progress" in frame.rows]
    assert refreshing
    notice_row = refreshing[-1].index("refresh requested · in progress")
    assert "r refresh all" in refreshing[-1][notice_row + 1]
    assert "refresh requested · in progress" not in frames[-1].rows
