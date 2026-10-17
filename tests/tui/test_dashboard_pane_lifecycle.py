



from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta

import pytest

import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.rendering as tui_rendering
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.panes import parse_pane_fragment as parse_dashboard_pane
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import default_custom_pane, standalone_from_chart_pane
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import RenderedChart
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import AnimationPaneConfig, CustomCommandSource
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.custom_adjustments import _finish_ranking_search_editing
from ccusage_viz.tui.layout import _frame
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import _local_pane_content, _pane_render
from ccusage_viz.tui_input import KeyEvent


def test_dashboard_ranking_search_timeout_finishes_editing_without_clearing_query() -> None:
    options = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--pane", "ranking"])
    )
    pane = _new_pane(options, options.panes[0])
    assert isinstance(pane, tui_module.TuiChartPane)
    pane.ranking_search.query = "claude"
    pane.ranking_search.editing = True

    _finish_ranking_search_editing(pane)

    assert pane.ranking_search.query == "claude"
    assert pane.ranking_search.editing is False

def test_dashboard_rejects_conflicting_custom_source_on_add_and_save() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    source = CustomCommandSource("reading", ("reader", "ccuv"))
    panes = [
        _new_pane(
            dashboard,
            default_custom_pane("timeline", source=source, dashboard=dashboard),
            f"dashboard:pane:{index}",
            build_query_runtime(),
        )
        for index in range(2)
    ]
    conflicting = CustomCommandSource("reading", ("other-reader", "ccuv"))

    assert tui_module._custom_source_conflict(panes, source) is None
    assert tui_module._custom_source_conflict(panes, conflicting) == (source, conflicting)
    assert (
        tui_module._custom_source_conflict(panes[:1], conflicting, replacing_index=0) is None
    )
    assert tui_module._dashboard_custom_source_conflict(panes) is None

    message = tui_module._custom_source_conflict_message(
        (source, conflicting), load_translator("zh")
    )
    assert "数据集 reading" in message
    assert "现有来源：[本地命令] reader ccuv" in message
    assert "本次来源：[本地命令] other-reader ccuv" in message

    panes[1].component.configure(
        replace(panes[1].component.candidate, source=conflicting), data_affecting=True
    )

    assert tui_module._dashboard_custom_source_conflict(panes) == (source, conflicting)

@pytest.mark.parametrize("density", ("minimal", "compact", "full", "detailed"))
def test_native_dashboard_timeline_keeps_audit_adjacent_to_x_axis(
    density: str,
) -> None:
    translator = load_translator("zh")
    dashboard = _to_options(build_parser(translator).parse_args(["dashboard", "--empty"]))
    pane_options = standalone_from_chart_pane(
        dashboard,
        parse_dashboard_pane("timeline --period 14d", host=dashboard),
    )
    pane = _new_pane(pane_options, "dashboard:timeline", build_query_runtime())
    assert isinstance(pane, tui_module.TuiChartPane)
    assert isinstance(pane.component, HistoricalChartComponent)

    chart = pane.component.candidate.chart
    days = tuple(chart.date_range.since + timedelta(days=index) for index in range(14))
    snapshot = UsageSnapshot(
        tuple(
            UsageRecord(
                day,
                "claude",
                TokenUsage(100 + index, 0, 0, 0, 0),
                SourceKind.UNIFIED_DAILY,
            )
            for index, day in enumerate(days)
        ),
        (),
        0.1,
        coverage=DateCoverage.from_interval(days[0], days[-1]),
    )
    configured = replace(
        pane.component.candidate,
        chart=replace(
            chart,
            presentation=replace(chart.presentation, density=density, style="points"),
        ),
    )
    pane.component.configure(configured, data_affecting=False)
    pane.component.seed(configured, snapshot)
    terminal = Terminal(90, 20, color=False, ascii=True)

    rendered = _pane_render(pane, translator, terminal)
    content = _local_pane_content(
        rendered.chart,
        rendered.notices,
        height=terminal.height,
        return_metadata=True,
    )
    assert isinstance(content, tuple)
    pane_content, _, _, _ = content
    frame = _frame(
        pane_content.splitlines(),
        terminal.width + 2,
        terminal.height + 2,
        selected=False,
        ascii=True,
        frame_style="auto",
    )

    assert len(frame) == terminal.height + 2
    tick_row = next(
        index
        for index, row in enumerate(frame)
        if any(day.strftime("%m-%d") in row for day in days)
    )
    if density == "detailed":
        assert "更新于" in frame[tick_row + 1]
        assert frame[tick_row + 2].startswith("+")
    else:
        assert frame[tick_row + 1].startswith("+")

def test_dashboard_defaults_to_a_filled_four_pane_dashboard() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard"]))
    assert "dashboard" == "dashboard"
    assert isinstance(options.panes[0], AnimationPaneConfig)
    assert options.panes[0].animation.style == "digital-clock"
    assert tuple(pane.chart.kind for pane in options.panes[1:]) == (
        "timeline",
        "stack",
        "ranking",
        "monitor",
    )
    assert options.panes[-1].chart.by == "model"
    assert options.host.refresh_interval == 60.0
    assert options.host.sampling_interval == 15.0
    assert options.host.grid == "2x2"
    assert options.host.header_style == "panel"
    assert options.host.header_summary == "day"
    assert options.host.header_interval == 60.0
    assert options.host.style == "framed"
    assert all(pane.chart.presentation.density == "compact" for pane in options.panes[1:])

def test_dashboard_pane_density_defaults_to_compact_except_for_ranking_and_preserves_explicit_values() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["dashboard"]))

    assert parse_dashboard_pane("timeline", host=base).chart.presentation.density == "compact"
    assert parse_dashboard_pane("ranking", host=base).chart.presentation.density == "full"
    assert (
        parse_dashboard_pane("timeline --density full", host=base).chart.presentation.density
        == "full"
    )
    assert (
        parse_dashboard_pane("timeline --density minimal", host=base).chart.presentation.density
        == "minimal"
    )

def test_dashboard_panes_have_no_details_state() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:test",
    )

    assert not hasattr(pane, "show_details")

def test_dashboard_resize_saturates_at_dashboard_minimum(
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

    events = iter((KeyEvent("m"), *(KeyEvent("}") for _ in range(8)), KeyEvent("\x03")))
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((9, 8))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args, **_kwargs: tui_models.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert frames[-2].rows == frames[-1].rows

def test_dashboard_panes_host_chart_components_without_legacy_runners() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))

    historical = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:historical",
    )
    monitor = _new_pane(
        standalone_from_chart_pane(options, parse_dashboard_pane("monitor", host=options)),
        "pane:monitor",
    )

    assert isinstance(historical.component, HistoricalChartComponent)
    assert isinstance(monitor.component, MonitorComponent)
    assert monitor.component.monitor_started_at is None
    assert isinstance(historical.scheduler, FixedIntervalScheduler)
    assert isinstance(monitor.scheduler, FixedIntervalScheduler)
    assert isinstance(historical.lifecycle, LifecycleOperation)
    assert isinstance(monitor.lifecycle, LifecycleOperation)
    assert historical.lifecycle.coordinator.owner_id == "pane:historical"
    assert monitor.lifecycle.coordinator.owner_id == "pane:monitor"
    assert not hasattr(historical, "monitor_runner")
    assert not hasattr(monitor, "monitor_runner")

def test_error_only_custom_pane_keeps_scrolling_and_replace_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    custom = default_custom_pane(
        "timeline",
        source=CustomCommandSource("reading", ("reader", "ccuv")),
        dashboard=dashboard,
    )
    options = replace(dashboard, panes=(custom,))
    frames: list[object] = []

    class FailedHandle:
        def result(self) -> object:
            raise QueryError("error.custom_command_protocol", detail="broken response")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, _intent: object) -> FailedHandle:
            return FailedHandle()

        def cancel(self) -> None:
            pass

    service_status_calls: list[None] = []
    modal_actions: list[str] = []

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            service_status_calls.append(None)
            return ()

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    offsets: list[str] = []
    original_next_text_offset = tui_module.next_text_offset

    def record_error_scroll(key: str, **kwargs: object) -> int | None:
        offsets.append(key)
        return original_next_text_offset(key, **kwargs)

    events = iter(
        (KeyEvent("m"), KeyEvent("\x1b[B"), KeyEvent("r"), *(KeyEvent("j") for _ in range(5)), KeyEvent("\r"), KeyEvent("\x03"))
    )
    original_modal = tui_module.DashboardDatasetModalState

    def record_modal(*args: object, **kwargs: object) -> object:
        modal_actions.append(str(args[0]))
        return original_modal(*args, **kwargs)

    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "next_text_offset", record_error_scroll)
    monkeypatch.setattr(tui_module, "DashboardDatasetModalState", record_modal)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)

    assert tui_module.run_tui(options, load_translator("en")) == 0

    rendered = "\n".join("\n".join(frame.rows) for frame in frames)
    assert offsets == ["\x1b[B"]
    assert modal_actions == ["replace"]
    assert service_status_calls == [None]
    assert "Dataset Pane Management" not in rendered
    assert "No datasets installed" in rendered
    assert "Timeline · 14d" in rendered
    assert "broken response" in rendered
    assert "reading · Timeline" not in rendered

def test_dashboard_pane_preserves_accepted_chart_for_transient_unified_daily_error(
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
    pane.component.fail(
        QueryError(
            "error.ccusage_failed",
            query="unified_daily",
            code=1,
            stderr="SQLITE_BUSY: database is locked at /private/example.db",
        ),
        generation=pane.component.generation,
    )
    monkeypatch.setattr(
        tui_rendering,
        "render_historical_component",
        lambda *_args, **_kwargs: RenderedChart("accepted chart", ()),
    )

    rendered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "accepted chart"
    assert rendered.notices == ("The next refresh may recover; press r to try now.",)
