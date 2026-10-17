import threading
import time
from contextlib import nullcontext
from datetime import date

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
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
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.rendering as tui_rendering
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.historical_component import HistoricalChartComponent
from ccusage_viz.i18n import load_translator
from ccusage_viz.query.models import DataResolution, ProviderResult
from ccusage_viz.tui_input import KeyEvent


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

    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(HistoricalChartComponent, "set_summary", record_summary)
    monkeypatch.setattr(tui_rendering, "_pane_render", capture_pane_render)
    monkeypatch.setattr(tui_painting, "_pane_render", capture_pane_render)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", read_event)
    monkeypatch.setattr(tui_input, "read_event", read_event)
    monkeypatch.setattr(tui_datasets_catalog, "read_event", read_event)
    monkeypatch.setattr(tui_datasets_chooser, "read_event", read_event)
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

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert summary_submissions == 3
    assert any(event == "cancel:summary:2" for event in events)
    assert stale_finished.is_set()
    assert len(summary_set_calls) == 1
    assert pane_ref[0].summary is baseline_summary[0]
    assert pane_ref[0].component.summary is baseline_component_summary[0]
    assert isinstance(pane_ref[0].summary_error, QueryError)
