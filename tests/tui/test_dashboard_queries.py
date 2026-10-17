import threading
import time
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from decimal import Decimal

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
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomData,
    CustomDataset,
    CustomDimension,
    CustomPoint,
    CustomProbeDescriptor,
    CustomSeries,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.custom_protocol.responses import CustomChartResponse, CustomProbeResponse
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.query.models import DataResolution, ProviderResult, QueryTrigger
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
    monkeypatch.setattr(tui_session, 'build_query_runtime', lambda: runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_models, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_rendering, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_completion, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_custom_adjustments, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_models, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_rendering, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_completion, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_custom_adjustments, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_queries, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_events, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_history, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_queries, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_history, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_input, 'read_event', lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_rendering, '_pane_render', lambda *_args: tui_models.PaneRender('chart'))
    monkeypatch.setattr(tui_painting, '_pane_render', lambda *_args: tui_models.PaneRender('chart'))

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

    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_models, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_rendering, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_completion, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_custom_adjustments, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_models, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_rendering, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_completion, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_custom_adjustments, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_queries, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_events, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_history, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_queries, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_history, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', read_events)
    monkeypatch.setattr(tui_input, 'read_event', read_events)
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', read_events)
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', read_events)
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_rendering, '_pane_render', lambda *_args: tui_models.PaneRender('chart'))
    monkeypatch.setattr(tui_painting, '_pane_render', lambda *_args: tui_models.PaneRender('chart'))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0

    refreshing = [frame.rows for frame in frames if "refresh requested · in progress" in frame.rows]
    assert refreshing
    notice_row = refreshing[-1].index("refresh requested · in progress")
    assert "r refresh all" in refreshing[-1][notice_row + 1]
    assert "refresh requested · in progress" not in frames[-1].rows

def test_dashboard_primary_completion_queues_pane_supplement(
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
                "timeline --density full",
            ]
        )
    )
    comparison = DateCoverage((DateInterval(date(2025, 12, 31), date(2025, 12, 31)),))
    events: list[tuple[object, ...]] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Submission:
        def __init__(self, generation: int, purpose: tui_models.HistoricalPurpose) -> None:
            self.generation = generation
            self.purpose = purpose

        def cancel(self) -> None:
            events.append(("submission-cancel", self.purpose))

        def result(self) -> object:
            events.append(("result", self.purpose))
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
            self._missing = DateCoverage()

        def configure(self, selected: object, *, data_affecting: bool) -> None:
            if selected != self.candidate:
                self.candidate = selected
                if data_affecting:
                    self.generation += 1

        def missing_comparison_coverage(self) -> DateCoverage:
            return self._missing

        def submit(self, trigger: QueryTrigger, **kwargs: object) -> Submission:
            purpose = kwargs["purpose"]
            assert isinstance(purpose, tui_models.HistoricalPurpose)
            events.append(
                (
                    "submit",
                    trigger,
                    purpose,
                    kwargs.get("coverage"),
                    self.generation,
                )
            )
            return Submission(self.generation, purpose)

        def accept(self, _completion: object) -> bool:
            chart = self.candidate.chart
            display = DateCoverage.from_interval(chart.date_range.since, chart.date_range.until)
            if self.snapshot is None:
                self.snapshot = UsageSnapshot((), (), 0.1, coverage=display)
                self.accepted_generation = self.generation
                self._missing = comparison
            else:
                self.snapshot = UsageSnapshot(
                    (),
                    (),
                    0.1,
                    coverage=self.snapshot.coverage.merge(comparison),
                )
                self._missing = DateCoverage()
            self.accepted_options = self.candidate
            self.accepted_at = tui_models.datetime.now().astimezone()
            return True

        def fail(self, *_args: object, **_kwargs: object) -> bool:
            events.append(("fail",))
            return True

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            events.append(("finish",))

    runtime = Runtime()

    def read_when_ready(_decoder: object, _timeout: float) -> KeyEvent | None:
        results = [event for event in events if event[0] == "result"]
        if len(results) < 2:
            threading.Event().wait(0.01)
            return None
        return KeyEvent("\x03")

    monkeypatch.setattr(tui_session, 'build_query_runtime', lambda: runtime)
    monkeypatch.setattr(tui_pane_lifecycle, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_models, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_rendering, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_completion, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_custom_adjustments, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_models, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_rendering, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_completion, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_custom_adjustments, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_queries, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_events, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_history, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_queries, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_history, 'HistoricalChartComponent', Component)
    monkeypatch.setattr(tui_pane_lifecycle, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', read_when_ready)
    monkeypatch.setattr(tui_input, 'read_event', read_when_ready)
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', read_when_ready)
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', read_when_ready)
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_rendering, '_pane_render', lambda *_args: tui_models.PaneRender('chart'))
    monkeypatch.setattr(tui_painting, '_pane_render', lambda *_args: tui_models.PaneRender('chart'))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    submissions = [event for event in events if event[0] == "submit"]
    assert submissions == [
        ("submit", QueryTrigger.STARTUP, tui_models.HistoricalPurpose.PRIMARY, None, 0),
        (
            "submit",
            QueryTrigger.REFRESH,
            tui_models.HistoricalPurpose.SUPPLEMENTAL,
            DateCoverage.from_interval(
                options.panes[0].chart.date_range.since,
                options.panes[0].chart.date_range.until,
            ),
            0,
        ),
    ]
    assert not any(event[0] == "fail" for event in events)

def test_dashboard_builtin_summary_retains_last_accepted_value_across_replacement_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelled, stale, or failed replacements cannot displace an accepted summary."""
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
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
    provider_runtime = build_query_runtime()
    summary_submissions = 0
    summary_set_calls: list[object] = []
    events: list[str] = []
    stale_release = threading.Event()
    stale_finished = threading.Event()
    pane_ref: list[tui_models.TuiChartPane] = []
    baseline_summary: list[object] = []
    baseline_component_summary: list[object] = []
    first_replacement_requested = False
    second_replacement_requested = False

    def result_for(value: int) -> ProviderResult:
        today = date.today()
        return ProviderResult(
            (
                UsageRecord(
                    today,
                    "claude",
                    TokenUsage(value, 0, 0, 0, 0),
                    SourceKind.UNIFIED_DAILY,
                ),
            ),
            (),
            DataResolution.DATE,
            DateCoverage.from_interval(today, today),
        )

    class Handle:
        def __init__(self, kind: str, ordinal: int = 0) -> None:
            self.kind = kind
            self.ordinal = ordinal

        def result(self) -> ProviderResult:
            if self.kind == "chart":
                return result_for(1)
            if self.ordinal == 1:
                return result_for(10)
            if self.ordinal == 2:
                assert stale_release.wait(1)
                stale_finished.set()
                return result_for(20)
            raise QueryError("error.ccusage_failed", query="summary")

        def cancel(self) -> None:
            events.append(f"cancel:{self.kind}:{self.ordinal}")

    class Runtime:
        def definition(self, provider_id: object) -> object:
            return provider_runtime.definition(provider_id)  # type: ignore[arg-type]

        def submit(self, intent: object) -> Handle:
            nonlocal summary_submissions
            owner_id = intent.owner_id  # type: ignore[union-attr]
            if owner_id.endswith(":summary"):
                summary_submissions += 1
                return Handle("summary", summary_submissions)
            return Handle("chart")

        def cancel(self) -> None:
            events.append("runtime-cancel")

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            events.append("finish")

    original_set_summary = HistoricalChartComponent.set_summary
    original_pane_render = tui_painting._pane_render

    def record_summary(self: HistoricalChartComponent, summary: object) -> None:
        summary_set_calls.append(summary)
        original_set_summary(self, summary)  # type: ignore[arg-type]

    def capture_pane_render(pane: object, *args: object, **kwargs: object) -> tui_models.PaneRender:
        if isinstance(pane, tui_models.TuiChartPane):
            pane_ref[:] = [pane]
        return original_pane_render(pane, *args, **kwargs)  # type: ignore[arg-type]

    def read_event(_decoder: object, _timeout: float) -> KeyEvent | None:
        nonlocal first_replacement_requested, second_replacement_requested
        if len(summary_set_calls) == 1 and not baseline_summary:
            baseline_summary[:] = [pane_ref[0].summary]
            baseline_component_summary[:] = [summary_set_calls[0]]
        if baseline_summary and not first_replacement_requested:
            first_replacement_requested = True
            return KeyEvent("r")
        if summary_submissions >= 2 and not second_replacement_requested:
            assert pane_ref[0].summary is baseline_summary[0]
            assert pane_ref[0].component.summary is baseline_component_summary[0]
            second_replacement_requested = True
            return KeyEvent("r")
        if second_replacement_requested and summary_submissions >= 3:
            stale_release.set()
            if stale_finished.is_set() and pane_ref[0].summary_error is not None:
                return KeyEvent("\x03")
        time.sleep(0.005)
        return None

    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(HistoricalChartComponent, "set_summary", record_summary)
    monkeypatch.setattr(tui_rendering, '_pane_render', capture_pane_render)
    monkeypatch.setattr(tui_painting, '_pane_render', capture_pane_render)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', read_event)
    monkeypatch.setattr(tui_input, 'read_event', read_event)
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', read_event)
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', read_event)
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert summary_submissions == 3
    assert any(event == "cancel:summary:2" for event in events)
    assert stale_finished.is_set()
    assert len(summary_set_calls) == 1
    assert pane_ref[0].summary is baseline_summary[0]
    assert pane_ref[0].component.summary is baseline_component_summary[0]
    assert isinstance(pane_ref[0].summary_error, QueryError)

def test_dashboard_submits_chart_immediately_after_custom_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(
            [
                "dashboard",
                "--empty",
                "--refresh-interval",
                "3600",
                "--header-style",
                "hidden",
            ]
        )
    )
    source = CustomCommandSource("reading", ("reader", "ccuv"))
    options = replace(
        dashboard, panes=(default_custom_pane("ranking", source=source, dashboard=dashboard),)
    )
    submitted: list[object] = []
    chart_submitted = threading.Event()
    point = CustomPoint(date(2026, 1, 1), Decimal("1"))
    text = LocalizedText("Reading", "阅读")
    dataset = CustomDataset("Reading", text, CustomUnit("minute", text, "suffix", 0))
    capabilities = CustomCapabilities(
        (CustomDimension("book", text),),
        (),
        {"ranking": CustomChartCapability(("day",), ("book",), ())},
    )
    probe = CustomProbeResponse(
        "reading",
        CustomProbeDescriptor(
            "reading-1",
            "0.1.0",
            dataset,
            capabilities,
            {"ranking": CustomChartDefaults("1y", "book", 10)},
            (),
        )
    )
    chart = CustomChartResponse(
        dataset,
        capabilities,
        CustomData((CustomSeries("book-1", text, (point,)),)),
    )

    class Handle:
        def __init__(self, response: object, *, wait: threading.Event | None = None) -> None:
            self.response = response
            self.wait = wait

        def result(self) -> object:
            if self.wait is not None and not self.wait.wait(1):
                raise TimeoutError("chart request was not submitted immediately after the probe")
            return ProviderResult(
                (), (), DataResolution.DATE, DateCoverage(), custom_response=self.response
            )

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, intent: object) -> Handle:
            submitted.append(intent)
            request = intent.payload  # type: ignore[union-attr]
            if request.request_kind == "probe":
                return Handle(probe)
            if request.request_kind == "chart":
                chart_submitted.set()
                return Handle(chart)
            return Handle(chart)

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            pass

    deadline = time.monotonic() + 1

    def read_until_chart(_decoder: object, _timeout: float) -> KeyEvent | None:
        if chart_submitted.is_set():
            return KeyEvent("\x03")
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"chart request was not submitted immediately after the probe: {submitted!r}"
            )
        time.sleep(0.01)
        return None

    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', read_until_chart)
    monkeypatch.setattr(tui_input, 'read_event', read_until_chart)
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', read_until_chart)
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', read_until_chart)
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((80, 24)))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert [intent.payload.request_kind for intent in submitted[:2]] == ["probe", "chart"]
    assert chart_submitted.is_set()
