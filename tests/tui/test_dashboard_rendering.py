import threading
from contextlib import nullcontext

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.completion as tui_completion
import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.custom_rendering as tui_custom_rendering
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
from ccusage_viz.animation import animation_spec
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.panes import parse_pane_fragment as parse_dashboard_pane
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError, SchemaError, UsageError
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import RenderedChart
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import AnimationPaneConfig, EmptyPaneConfig
from ccusage_viz.query.models import QueryTrigger
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import _pane_render
from ccusage_viz.tui_input import KeyEvent


def test_empty_dashboard_pane_renders_localized_placeholder() -> None:
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    pane = _new_pane(options, EmptyPaneConfig())

    assert _pane_render(pane, load_translator("en"), Terminal(40, 8, False, True)).chart == (
        "Empty pane\nDouble-click to select, then press r to choose a type"
    )
    assert _pane_render(pane, load_translator("zh"), Terminal(40, 8, False, True)).chart == (
        "空白子图\n双击选中，然后按 r 选择类型"
    )


def test_dashboard_animation_pane_is_render_only() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "animate rain"]))

    pane = _new_pane(options, AnimationPaneConfig(animation_spec("rain")))

    assert isinstance(pane, tui_models.TuiAnimationPane)
    assert pane.session.spec.style == "rain"
    assert not hasattr(pane, "component")
    assert not hasattr(pane, "scheduler")
    assert not hasattr(pane, "lifecycle")


def test_dashboard_animation_pane_renders_text_overlay() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "animate rain"]))
    pane = _new_pane(
        options,
        AnimationPaneConfig(animation_spec("rain"), OverlayConfig(text="OVERLAY")),
    )

    try:
        rendered = _pane_render(pane, load_translator("en"), Terminal(40, 8, False, True))
    finally:
        pane.overlay.close()

    assert "OVERLAY" in rendered.chart


def test_undersized_dashboard_panes_skip_normal_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            [
                "dashboard",
                "--header-style",
                "hidden",
                "--pane",
                "animate rain",
                "--pane",
                "animate rain",
            ]
        )
    )
    frames: list[object] = []

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

    monkeypatch.setattr(tui_session, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_session, "FramePainter", Screen)
    monkeypatch.setattr(tui_adjustments, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_catalog, "FramePainter", Screen)
    monkeypatch.setattr(tui_datasets_chooser, "FramePainter", Screen)
    monkeypatch.setattr(tui_runtime, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_adjustments, "read_event", lambda _decoder, _timeout: KeyEvent("\x03"))
    monkeypatch.setattr(tui_input, "read_event", lambda _decoder, _timeout: KeyEvent("\x03"))
    monkeypatch.setattr(
        tui_datasets_catalog, "read_event", lambda _decoder, _timeout: KeyEvent("\x03")
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "read_event", lambda _decoder, _timeout: KeyEvent("\x03")
    )
    monkeypatch.setattr(
        tui_events, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_runtime, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_dashboard_events, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_pane_events, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_blocking, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_painting, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_pointer, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_help, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_history, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_catalog, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_chooser, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_blocking, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_datasets_modal, "get_terminal_size", lambda: __import__("os").terminal_size((1, 1))
    )
    monkeypatch.setattr(
        tui_rendering,
        "_pane_render",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("undersized pane rendered")),
    )
    monkeypatch.setattr(
        tui_painting,
        "_pane_render",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("undersized pane rendered")),
    )

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    assert frames
    assert all(len(frame.rows) == 1 for frame in frames)


def test_dashboard_pane_insert_chooser_renders_inside_focused_pane(
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
            self.purpose = tui_models.HistoricalPurpose.PRIMARY
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
            self.accepted_options = selected
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
            KeyEvent("m"),
            KeyEvent("n"),
            KeyEvent("\x1b"),
            KeyEvent("N"),
            KeyEvent("\x1b"),
            KeyEvent("\x03"),
        )
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
    monkeypatch.setattr(tui_models, "MonitorComponent", Component)
    monkeypatch.setattr(tui_rendering, "MonitorComponent", Component)
    monkeypatch.setattr(tui_completion, "MonitorComponent", Component)
    monkeypatch.setattr(tui_custom_rendering, "MonitorComponent", Component)
    monkeypatch.setattr(tui_models, "MonitorComponent", Component)
    monkeypatch.setattr(tui_rendering, "MonitorComponent", Component)
    monkeypatch.setattr(tui_completion, "MonitorComponent", Component)
    monkeypatch.setattr(tui_custom_rendering, "MonitorComponent", Component)
    monkeypatch.setattr(tui_queries, "MonitorComponent", Component)
    monkeypatch.setattr(tui_pane_events, "MonitorComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "MonitorComponent", Component)
    monkeypatch.setattr(tui_queries, "MonitorComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "MonitorComponent", Component)
    monkeypatch.setattr(tui_pane_lifecycle, "MonitorComponent", Component)
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
    painted = ["\n".join(frame.rows) for frame in frames]
    assert any("Insert pane after" in frame for frame in painted), painted
    assert any("Insert pane before" in frame for frame in painted), painted


def test_dashboard_pane_render_retains_notices_for_each_source_pane() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    ranking = parse_dashboard_pane("ranking --by project", host=options)
    snapshot = UsageSnapshot(
        (
            UsageRecord(
                ranking.chart.date_range.until,
                "claude",
                TokenUsage(10, 10, 0, 0, 0),
                SourceKind.CLAUDE_DAILY_PROJECTS,
            ),
        ),
        (),
        0.1,
        coverage=DateCoverage(
            (DateInterval(ranking.chart.date_range.until, ranking.chart.date_range.until),)
        ),
        summary_notices=(Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),),
    )
    panes = [
        _new_pane(standalone_from_chart_pane(options, ranking), f"pane:{index}")
        for index in range(2)
    ]
    for pane in panes:
        assert pane.component is not None
        pane.component.seed(pane.component.candidate, snapshot)

    rendered = [
        _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True)) for pane in panes
    ]

    assert rendered[0].notices == (
        "Ranking includes Codex session usage; daily Summary excludes it",
    )
    assert rendered[0].notices[0] not in rendered[0].chart
    assert rendered[1].notices == rendered[0].notices


def test_dashboard_monitor_forwards_component_changes_to_chart_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = _new_pane(
        standalone_from_chart_pane(
            options,
            parse_dashboard_pane("monitor --by model --style ranking", host=options),
        ),
        "pane:monitor",
    )
    assert isinstance(monitor.component, MonitorComponent)
    monitor.component.deltas["sonnet"] = 4.0
    monitor.component.rank_deltas["sonnet"] = 1
    captured: dict[str, object] = {}

    def fake_render(self: MonitorComponent, context, **kwargs: object) -> str:
        captured["deltas"] = context.deltas
        captured["rank_deltas"] = context.rank_deltas
        captured["density"] = context.density
        captured["audit"] = context.audit
        return "monitor"

    monkeypatch.setattr(MonitorComponent, "render", fake_render)

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "monitor"
    assert captured["deltas"] == {"sonnet": 4.0}
    assert captured["rank_deltas"] == {"sonnet": 1}
    assert captured["density"] == "compact"
    assert captured["audit"].interval == monitor.scheduler.interval
    assert captured["audit"].cadence == "sample"


def test_dashboard_historical_pane_normalizes_titles_like_standalone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:timeline",
    )
    assert isinstance(pane.component, HistoricalChartComponent)
    pane.component.seed(pane.component.candidate, UsageSnapshot((), (), 0.1))
    captured: dict[str, object] = {}

    def fake_render(*_args: object, **kwargs: object) -> RenderedChart:
        captured.update(kwargs)
        return RenderedChart("timeline", ())

    monkeypatch.setattr(tui_rendering, "render_historical_component", fake_render)

    rendered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "timeline"
    assert captured["normalize_titles"] is True


def test_dashboard_monitor_and_error_panes_do_not_contribute_chart_notices() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("monitor", host=options)),
        "pane:monitor",
    )
    monitor.component.fail(RuntimeError("pane failed"), generation=monitor.component.generation)

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "pane failed"
    assert rendered.notices == ()


def test_dashboard_pane_uses_safe_placeholder_for_initial_transient_error() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:timeline",
    )
    assert isinstance(pane.component, HistoricalChartComponent)
    pane.component.fail(
        QueryError(
            "error.ccusage_failed",
            query="unified_daily",
            code=1,
            stderr="SQLITE_BUSY: database is locked at /private/example.db",
        ),
        generation=pane.component.generation,
    )

    rendered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == (
        "Usage data is temporarily unavailable.\nThe next refresh may recover; press r to try now."
    )
    assert "/private/example.db" not in rendered.chart


def test_dashboard_pane_localizes_schema_errors() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("monitor", host=options)),
        "pane:monitor",
    )
    monitor.component.fail(
        SchemaError("error.schema", path="$.projects", reason="expected object"),
        generation=monitor.component.generation,
    )

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart != "error.schema"
    assert "$.projects" in rendered.chart
    assert "expected object" in rendered.chart


def test_dashboard_pane_retains_last_render_for_localized_renderer_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("stack", host=options)),
        "pane:stack",
    )
    assert pane.component is not None
    pane.component.seed(pane.component.candidate, UsageSnapshot((), (), 0.25))
    monkeypatch.setattr(
        tui_rendering,
        "render_historical_component",
        lambda *args, **kwargs: tui_models.PaneRender("previous chart"),
    )
    first = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))
    monkeypatch.setattr(
        tui_rendering,
        "render_historical_component",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            UsageError("error.stack_stacked_width", width=58)
        ),
    )

    recovered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert first.chart == "previous chart"
    assert recovered.chart == "previous chart"
    assert recovered.notices == (
        "Terminal is too narrow (58 columns) to show every Stack period; widen it or use a "
        "coarser aggregation or shorter range.",
    )
