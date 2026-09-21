import shlex
import threading
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from io import StringIO

import pytest

import ccusage_viz.tui as tui_module
import ccusage_viz.tui_input as tui_input_module
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.cli import parse_pane_fragment as parse_dashboard_pane
from ccusage_viz.command_copy import (
    format_command,
    format_dashboard_pane_command,
    format_full_command,
    format_full_dashboard_command,
)
from ccusage_viz.configuration import standalone_from_pane
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.deltas import RefreshRanks
from ccusage_viz.domain import Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError, SchemaError, UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import RenderedChart
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import Filters, TimelineConfig
from ccusage_viz.query.models import QueryTrigger
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui import (
    _adjustment_controls,
    _adjustment_footer,
    _adjustment_key_supported,
    _adjustment_target,
    _choose_pane_type,
    _dashboard_title_line,
    _grid_for_pane_count,
    _grid_shape,
    _header_lines,
    _header_options,
    _header_refresh_interval,
    _insert_pane,
    _local_pane_content,
    _new_header,
    _new_pane,
    _new_pane_options,
    _next_header_summary,
    _pane_adjustment_state,
    _pane_content_actions,
    _pane_copy_payload,
    _pane_render,
    _practical_grid,
    _query_affecting_adjustment,
    _replace_header_interval,
    _replace_pane,
    _set_header_theme,
    compose_panes,
    pane_at,
    pane_rects,
    parse_grid,
    resolve_panel_layout,
)
from ccusage_viz.tui_input import InputDecoder, KeyEvent, MouseEvent


def test_dashboard_defaults_to_a_filled_four_pane_dashboard() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard"]))
    assert "dashboard" == "dashboard"
    assert tuple(pane.chart.kind for pane in options.panes) == (
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
    assert all(pane.chart.presentation.density == "compact" for pane in options.panes)


def test_dashboard_timezone_is_host_owned_and_round_trips() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--timezone", "UTC"]))

    full = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert dashboard.host.timezone == "UTC"
    assert reparsed.host.timezone == "UTC"
    assert all(
        pane.chart.date_range.timezone is None
        for pane in reparsed.panes
        if hasattr(pane.chart, "date_range")
    )
    assert _header_options(reparsed).chart.date_range.timezone == "UTC"


def test_dashboard_layout_weights_round_trip_through_full_command() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                "timeline",
                "--pane",
                "ranking",
                "--grid",
                "1x2",
                "--column-weight",
                "2",
                "--column-weight",
                "1",
                "--row-weight",
                "3",
            ]
        )
    )

    full = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert "--column-weight 16 --column-weight 8" in full
    assert "--row-weight 24" in full
    assert reparsed.host.grid == "1x2"
    assert reparsed.host.column_weights == (16, 8)
    assert reparsed.host.row_weights == (24,)


def test_full_dashboard_command_explicit_grid_overrides_source_named_layout() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "spotlight-wide"]))

    full = format_full_dashboard_command(dashboard, grid="2x2")
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert "--grid 2x2" in full
    assert "--layout" not in full
    assert reparsed.host.grid == "2x2"
    assert reparsed.host.layout is None


def test_full_dashboard_command_serializes_runtime_layout_weight_overrides() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard"]))

    full = format_full_dashboard_command(
        dashboard,
        column_weights=(2, 1),
        row_weights=(3, 1),
    )
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert reparsed.host.column_weights == (16, 8)
    assert reparsed.host.row_weights == (18, 6)


def test_full_dashboard_command_includes_private_and_runtime_configuration() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--ccusage-bin",
                "/opt/ccusage",
                "--query-timeout",
                "42",
                "--pane",
                "timeline --project /private/project --density minimal",
            ]
        )
    )
    full = format_full_dashboard_command(
        dashboard,
        dashboard.panes,
        layout="auto",
        header_style="compact",
        header_summary="month",
        dashboard_style="split",
    )

    tokens = shlex.split(full)
    assert "/private/project" in full
    assert "--ccusage-bin /opt/ccusage" in full
    assert "--query-timeout 42" in full
    assert "--pane" in tokens
    assert "--interval" not in tokens
    reparsed = _to_options(parser.parse_args(tokens[1:]))
    assert reparsed.panes[0].chart.filters.projects == ("/private/project",)
    assert reparsed.panes[0].chart.presentation.density == "minimal"
    assert "--density minimal" in tokens[tokens.index("--pane") + 1]


def test_dashboard_pane_copy_materializes_canonical_standalone_interval() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["dashboard"]))
    timeline = parse_dashboard_pane("timeline --period 7d", host=base)
    stack = parse_dashboard_pane("stack", host=base)
    monitor = parse_dashboard_pane("monitor --by model", host=base)

    assert format_dashboard_pane_command(
        standalone_from_pane(base, timeline), refresh_interval=30
    ) == ("ccuv timeline --period 7d --interval 30 --density compact")
    assert format_dashboard_pane_command(
        standalone_from_pane(base, stack), refresh_interval=30
    ) == ("ccuv stack --interval 30 --density compact")
    assert format_dashboard_pane_command(
        standalone_from_pane(base, monitor), refresh_interval=30, sampling_interval=15
    ) == ("ccuv monitor --by model --density compact")


def test_dashboard_pane_command_views_wrap_without_affecting_copy_payload() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--ccusage-bin",
                "/private/bin/ccusage",
                "--pane",
                "timeline --period 7d --by model --top 4 --agent claude --model sonnet --project project --density minimal",
            ]
        )
    )
    pane = _new_pane(standalone_from_pane(dashboard, dashboard.panes[0]), "pane:command")
    terminal = Terminal(24, 16, False, True)
    active = pane.component.candidate

    pane.body_view = "command"
    concise = _pane_render(pane, load_translator("en"), terminal).chart
    assert "\n" in concise
    assert all(display_width(line) <= terminal.width for line in concise.splitlines())
    assert " ".join(concise.splitlines()) == format_command(active)

    pane.body_view = "full-command"
    full = _pane_render(pane, load_translator("en"), terminal).chart
    assert "\n" in full
    assert all(display_width(line) <= terminal.width for line in full.splitlines())
    assert "--ccusage-bin" in full
    assert format_full_command(active).count("\n") == 0
    assert _pane_copy_payload(pane, load_translator("en"), terminal) == format_full_command(active)


def test_dashboard_pane_copy_actions_follow_body_view() -> None:
    assert (
        "y copy"
        not in _adjustment_footer(
            "Current status: running", "timeline", "quick", "chart", load_translator("en"), 120
        )[3]
    )
    for view in ("command", "full-command", "data-table", "data-json"):
        assert ("y", "copy") in _pane_content_actions(view)
        assert (
            "y copy"
            in _adjustment_footer(
                "Current status: running", "timeline", "quick", view, load_translator("en"), 120
            )[3]
        )


def test_dashboard_pane_density_defaults_to_compact_and_preserves_explicit_values() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["dashboard"]))

    assert parse_dashboard_pane("timeline", host=base).chart.presentation.density == "compact"
    assert (
        parse_dashboard_pane("timeline --density full", host=base).chart.presentation.density
        == "full"
    )
    assert (
        parse_dashboard_pane("timeline --density minimal", host=base).chart.presentation.density
        == "minimal"
    )


def test_dashboard_monitor_default_does_not_change_explicit_or_standalone_total() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--pane", "monitor"]))
    panel = dashboard.panes[0]
    standalone = _to_options(parser.parse_args(["monitor"]))

    assert _new_pane_options("monitor", dashboard).chart.by == "model"
    assert panel.chart.by is None
    assert standalone.chart.by is None


def test_tui_adjustment_target_exists_only_during_adjustment() -> None:
    assert _adjustment_target(None, "\t", 4) is None
    assert _adjustment_target(None, "s", 4) == 0
    assert _adjustment_target(0, "\t", 4) == 1
    assert _adjustment_target(3, "\t", 4) == 0
    assert _adjustment_target(2, "l", 4) == 2
    assert _adjustment_target(2, "q", 4) == 2
    assert _adjustment_target(2, "Q", 4) == 2
    assert _adjustment_target(2, "\x1b", 4) is None


def test_dashboard_panes_have_no_details_state() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:test",
    )

    assert not hasattr(pane, "show_details")


def test_dashboard_panes_host_chart_components_without_legacy_runners() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))

    historical = _new_pane(
        standalone_from_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:historical",
    )
    monitor = _new_pane(
        standalone_from_pane(options, parse_dashboard_pane("monitor", host=options)),
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


def test_dashboard_pause_cancels_automatic_panes_and_manual_refresh_remains_allowed(
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
    events: list[tuple[object, ...]] = []
    submissions: list[object] = []

    class Runtime:
        def cancel(self) -> None:
            events.append(("runtime-cancel",))

    class Submission:
        def __init__(self, generation: int) -> None:
            self.generation = generation
            self.purpose = tui_module.HistoricalPurpose.PRIMARY
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

    keys = iter((KeyEvent(" "), KeyEvent("r"), KeyEvent("\x03")))
    runtime = Runtime()
    monkeypatch.setattr(tui_module, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert [(event[1], event[2]) for event in events if event[0] == "submit"] == [
        (QueryTrigger.STARTUP, 0),
        (QueryTrigger.REFRESH, 0),
    ]
    painted_text = "\n".join("\n".join(event[1].rows) for event in events if event[0] == "paint")
    assert "refresh requested" in painted_text
    assert len(submissions) == 2
    assert submissions[0].cancelled.is_set()
    assert submissions[1].cancelled.is_set()
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
            self.purpose = tui_module.HistoricalPurpose.PRIMARY
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
            self.accepted_at = tui_module.datetime.now().astimezone()
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

    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", read_events)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0

    refreshing = [frame.rows for frame in frames if "refresh requested · in progress" in frame.rows]
    assert refreshing
    notice_row = refreshing[-1].index("refresh requested · in progress")
    assert "r refresh all" in refreshing[-1][notice_row + 1]
    assert "refresh requested · in progress" not in frames[-1].rows


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
            KeyEvent("g"),
            KeyEvent("Z"),
            *(KeyEvent("\x7f") for _ in range(3)),
            *(KeyEvent(char) for char in "1x1"),
            KeyEvent("\r"),
            *(KeyEvent("\x7f") for _ in range(3)),
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
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "MonitorComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    painted = ["\n".join(frame.rows) for frame in frames]
    assert any("Set grid (ROWSxCOLUMNS): 2x2" in frame for frame in painted)
    assert any(
        "Set grid (ROWSxCOLUMNS): 1x1" in frame
        and "Grid '1x1' cannot display all 4 panes." in frame
        for frame in painted
    )
    assert sum("Set grid (ROWSxCOLUMNS): 3x2" in frame for frame in painted) >= 2
    assert any("Current status: running · 3x2" in frame for frame in painted)


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
            KeyEvent("s"),
            KeyEvent("n"),
            KeyEvent("\x1b"),
            KeyEvent("N"),
            KeyEvent("\x1b"),
            KeyEvent("\x03"),
        )
    )
    runtime = Runtime()
    monkeypatch.setattr(tui_module, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "MonitorComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    painted = ["\n".join(frame.rows) for frame in frames]
    assert any("Insert pane after" in frame for frame in painted), painted
    assert any("Insert pane before" in frame for frame in painted), painted


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
        def __init__(self, generation: int, purpose: tui_module.HistoricalPurpose) -> None:
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
            assert isinstance(purpose, tui_module.HistoricalPurpose)
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
            self.accepted_at = tui_module.datetime.now().astimezone()
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

    monkeypatch.setattr(tui_module, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", read_when_ready)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    submissions = [event for event in events if event[0] == "submit"]
    assert submissions == [
        ("submit", QueryTrigger.STARTUP, tui_module.HistoricalPurpose.PRIMARY, None, 0),
        (
            "submit",
            QueryTrigger.REFRESH,
            tui_module.HistoricalPurpose.SUPPLEMENTAL,
            DateCoverage.from_interval(
                options.panes[0].chart.date_range.since,
                options.panes[0].chart.date_range.until,
            ),
            0,
        ),
    ]
    assert not any(event[0] == "fail" for event in events)


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

    keys = iter((KeyEvent("s"), KeyEvent("a"), KeyEvent("f"), KeyEvent("\x03")))
    runtime = Runtime()
    monkeypatch.setattr(tui_module, "build_query_runtime", lambda: runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(tui_module, "run_filter_editor", lambda *_args, **_kwargs: edited)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert [event for event in events if event[0] == "configure"] == expected_configures
    assert [event for event in events if event[0] == "submit"] == expected_submits
    assert events[-2:] == [("runtime-cancel",), ("finish",)]


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
        _new_pane(standalone_from_pane(options, ranking), f"pane:{index}") for index in range(2)
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


@pytest.mark.parametrize(
    ("change", "expected_querying"),
    (("by", True), ("window", False)),
)
def test_dashboard_monitor_marks_only_data_candidate_panes(
    change: str,
    expected_querying: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = _new_pane(
        standalone_from_pane(
            options,
            parse_dashboard_pane("monitor --by model --style ranking", host=options),
        ),
        "pane:monitor",
    )
    assert isinstance(monitor.component, MonitorComponent)
    component = monitor.component
    component.accepted_options = component.candidate
    chart = component.candidate.chart
    updated = replace(
        component.candidate,
        chart=replace(
            chart,
            by="agent" if change == "by" else chart.by,
            window_seconds=600 if change == "window" else chart.window_seconds,
        ),
    )
    component.configure(updated, data_affecting=change == "by")
    captured: dict[str, object] = {}

    def fake_render(self: MonitorComponent, context, **_kwargs: object) -> str:
        captured["pending"] = context.pending
        captured["querying"] = context.audit.querying if context.audit is not None else None
        return "monitor"

    monkeypatch.setattr(MonitorComponent, "render", fake_render)

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "monitor"
    assert captured == {"pending": expected_querying, "querying": expected_querying}


def test_dashboard_monitor_forwards_component_changes_to_chart_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = _new_pane(
        standalone_from_pane(
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
        standalone_from_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:timeline",
    )
    assert isinstance(pane.component, HistoricalChartComponent)
    pane.component.seed(pane.component.candidate, UsageSnapshot((), (), 0.1))
    captured: dict[str, object] = {}

    def fake_render(*_args: object, **kwargs: object) -> RenderedChart:
        captured.update(kwargs)
        return RenderedChart("timeline", ())

    monkeypatch.setattr(tui_module, "render_historical_component", fake_render)

    rendered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "timeline"
    assert captured["normalize_titles"] is True


def test_dashboard_monitor_and_error_panes_do_not_contribute_chart_notices() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = _new_pane(
        standalone_from_pane(options, parse_dashboard_pane("monitor", host=options)),
        "pane:monitor",
    )
    monitor.component.fail(RuntimeError("pane failed"), generation=monitor.component.generation)

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "pane failed"
    assert rendered.notices == ()


def test_dashboard_pane_preserves_accepted_chart_for_transient_unified_daily_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_pane(options, parse_dashboard_pane("timeline", host=options)),
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
        tui_module,
        "render_historical_component",
        lambda *_args, **_kwargs: RenderedChart("accepted chart", ()),
    )

    rendered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "accepted chart"
    assert rendered.notices == ("The next refresh may recover; press r to try now.",)


def test_dashboard_pane_uses_safe_placeholder_for_initial_transient_error() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(
        standalone_from_pane(options, parse_dashboard_pane("timeline", host=options)),
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
        standalone_from_pane(options, parse_dashboard_pane("monitor", host=options)),
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
        standalone_from_pane(options, parse_dashboard_pane("stack", host=options)),
        "pane:stack",
    )
    assert pane.component is not None
    pane.component.seed(pane.component.candidate, UsageSnapshot((), (), 0.25))
    monkeypatch.setattr(
        tui_module,
        "render_historical_component",
        lambda *args, **kwargs: tui_module.PaneRender("previous chart"),
    )
    first = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))
    monkeypatch.setattr(
        tui_module,
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


def test_query_affecting_adjustments_are_explicit() -> None:
    assert _query_affecting_adjustment("timeline", "p")
    assert not _query_affecting_adjustment("timeline", "d")
    assert not _query_affecting_adjustment("timeline", "A")
    assert not _query_affecting_adjustment("monitor", "d")
    assert not _query_affecting_adjustment("timeline", "g")
    assert _query_affecting_adjustment("ranking", "b")
    assert not _query_affecting_adjustment("monitor", "B")
    assert not _query_affecting_adjustment("stack", "c")
    assert not _query_affecting_adjustment("monitor", "+")
    assert not _query_affecting_adjustment("timeline", "t")


def test_dashboard_pane_adjustment_state_changes_with_page() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(standalone_from_pane(options, options.panes[0]), "pane:test")
    translator = load_translator("en")

    quick = _pane_adjustment_state(pane, "quick", translator)
    advanced = _pane_adjustment_state(pane, "advanced", translator)

    assert "timeline · compact · nord · line-points" in quick
    assert "Legend" in advanced
    assert "Weekdays" in advanced
    assert quick != advanced


@pytest.mark.parametrize("command", ("timeline", "ranking", "monitor"))
def test_project_aggregation_is_advanced_only_for_project_panes(command: str) -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--pane", f"{command} --by project"]))
    project_pane = _new_pane(
        standalone_from_pane(dashboard, dashboard.panes[0]), f"pane:{command}:project"
    )
    chart = project_pane.component.candidate.chart
    translator = load_translator("en")

    assert "A project aggregation" in _adjustment_controls(
        command, "advanced", translator, chart=chart
    )
    assert _adjustment_key_supported(command, "advanced", "A", chart=chart)
    assert "Project aggregation name" in _pane_adjustment_state(
        project_pane, "advanced", translator
    )

    nonproject_chart = replace(chart, by="agent")
    assert "project aggregation" not in _adjustment_controls(
        command, "advanced", translator, chart=nonproject_chart
    )
    assert not _adjustment_key_supported(command, "advanced", "A", chart=nonproject_chart)


def test_calendar_advanced_adjustment_uses_the_shared_filter_control() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "calendar"]))
    pane = _new_pane(standalone_from_pane(options, options.panes[0]), "pane:calendar")
    translator = load_translator("en")

    assert _pane_adjustment_state(pane, "advanced", translator) == "running"
    assert _adjustment_controls("calendar", "advanced", translator) == "f filters"


def test_tui_adjustment_footer_separates_dashboard_management() -> None:
    translator = load_translator("en")
    timeline_chart = TimelineConfig(
        "timeline", DateRange(date(2026, 1, 1), date(2026, 1, 14), None), by="project"
    )
    timeline_quick = _adjustment_controls("timeline", "quick", translator, chart=timeline_chart)
    timeline_advanced = _adjustment_controls(
        "timeline", "advanced", translator, chart=timeline_chart
    )
    stack_advanced = _adjustment_controls("stack", "advanced", translator)

    assert "p/P period" in timeline_quick
    assert "g granularity" in timeline_quick
    assert "v view" not in timeline_quick
    assert "k weekdays" in timeline_advanced
    assert "l legend" in timeline_advanced
    assert "f filters" in timeline_advanced
    assert "A project aggregation" in timeline_advanced
    assert "c cache mode" in stack_advanced
    assert not _adjustment_key_supported("timeline", "quick", "k")
    assert _adjustment_key_supported("timeline", "advanced", "k")
    assert not _adjustment_key_supported("timeline", "advanced", "A")
    assert _adjustment_key_supported("timeline", "advanced", "A", chart=timeline_chart)
    assert _adjustment_key_supported("timeline", "quick", "b")
    assert _adjustment_key_supported("timeline", "quick", "d")
    assert _adjustment_key_supported("monitor", "quick", "d")
    assert not _adjustment_key_supported("timeline", "advanced", "b")
    assert not _adjustment_key_supported("monitor", "quick", "i")
    assert not _adjustment_key_supported("monitor", "quick", "B")
    assert "project aggregation" not in _adjustment_controls("timeline", "advanced", translator)

    quick_rows = _adjustment_footer(
        "Current status: running", "timeline", "quick", "chart", translator, 80
    )
    advanced_rows = _adjustment_footer(
        "Current status: running", "timeline", "advanced", "chart", translator, 80
    )
    assert len(quick_rows) == 5
    assert "a Advanced" in quick_rows[1]
    assert "Enter/Esc finish" in quick_rows[1]
    assert "Dashboard Pane" in quick_rows[2]
    assert "v view" in quick_rows[3]
    assert "N insert before" in quick_rows[3]
    assert "Tab next pane" in quick_rows[4]
    assert quick_rows[2:] == advanced_rows[2:]
    assert "[Finish]" not in "\n".join(quick_rows)


def test_dashboard_title_centers_and_right_aligns_freshness() -> None:
    line = _dashboard_title_line("Dashboard", "updated 12:34:56", 50)
    assert len(line) == 50
    assert line.endswith("updated 12:34:56")
    assert line.index("Dashboard") == (50 - len("Dashboard")) // 2

    narrow = _dashboard_title_line("仪表盘", "更新于 12:34:56", 18)
    assert len(narrow.encode()) > 0
    assert narrow.rstrip().endswith("…")


def test_tui_is_not_a_dashboard_compatibility_alias() -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError):
        parser.parse_args(["tui"])


def test_dashboard_header_uses_host_summary_and_tracks_global_theme() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(["dashboard", "--header-summary", "quarter", "--theme", "nord"])
    )

    runtime = build_query_runtime()
    header = _new_header(options, runtime)
    assert header.runtime is runtime
    assert isinstance(header.scheduler, FixedIntervalScheduler)
    assert isinstance(header.lifecycle, LifecycleOperation)
    assert header.scheduler.interval == options.host.header_interval
    assert header.lifecycle.coordinator.owner_id == "dashboard:header"
    assert header.summary_period == "quarter"
    assert header.options.chart.presentation.theme == "nord"

    _set_header_theme(header, "dracula")
    assert header.options.chart.presentation.theme == "dracula"


def test_tui_header_query_is_unfiltered_and_independent() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo", "--header-style", "panel"]))
    header = _header_options(options)
    assert header.chart.kind == "timeline"
    assert (
        header.chart.filters.agents
        == header.chart.filters.models
        == header.chart.filters.projects
        == ()
    )
    assert header.chart.by is None
    assert header.chart.top is None
    assert header.chart.date_range.days == 8


def test_header_summary_cycle_includes_none_and_wraps() -> None:
    observed = []
    period = "day"
    for _ in range(5):
        period = _next_header_summary(period)
        observed.append(period)

    assert observed == ["month", "quarter", "year", "none", "day"]


def test_header_refresh_uses_missing_coverage_then_current_day() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "month"]))
    header = _new_header(options, build_query_runtime())
    today = date(2026, 3, 15)

    cold = _header_refresh_interval(header, today=today)
    assert cold == DateInterval(date(2025, 3, 1), today)

    header.coverage = DateCoverage((cold,))
    header.records = (UsageRecord(today, "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY),)
    assert _header_refresh_interval(header, today=today) == DateInterval(today, today)
    assert _header_refresh_interval(header, aggressive=True, today=today) == cold

    header.records = ()
    assert _header_refresh_interval(header, today=today) == DateInterval(today, today)

    header.summary_period = "none"
    assert _header_refresh_interval(header, today=today) is None


def test_header_date_rollover_requests_new_current_day() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "day"]))
    header = _new_header(options, build_query_runtime())
    previous = date(2026, 3, 15)
    header.coverage = DateCoverage((DateInterval(previous.replace(day=8), previous),))
    header.records = (UsageRecord(previous, "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY),)

    assert _header_refresh_interval(header, today=date(2026, 3, 16)) == DateInterval(
        date(2026, 3, 16), date(2026, 3, 16)
    )


def test_header_none_keeps_title_without_unknown_detail() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "none"]))
    header = _new_header(options, build_query_runtime())

    compact = _header_lines(header, "compact", load_translator("en"), Terminal(60, 4, False, True))
    banner = _header_lines(header, "banner", load_translator("en"), Terminal(60, 4, False, True))

    assert len(compact) == 1
    assert "Dashboard" in compact[0]
    assert "?" not in compact[0]
    assert len(banner) == 1


def test_header_cold_period_keeps_structure_with_unknown_detail() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "quarter"]))
    header = _new_header(options, build_query_runtime())

    lines = _header_lines(header, "banner", load_translator("en"), Terminal(60, 4, False, True))

    assert len(lines) == 2
    assert "Dashboard" in lines[0]
    assert "Quarter-to-date tokens ??" in lines[1]
    assert "prior quarter-to-" in lines[1]


def test_header_successful_interval_replaces_cached_rows_authoritatively() -> None:
    old = UsageRecord(date(2026, 1, 1), "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY)
    unaffected = UsageRecord(
        date(2025, 12, 31), "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY
    )
    fresh = UsageRecord(
        date(2026, 1, 1),
        "claude",
        TokenUsage(10, 10, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    snapshot = UsageSnapshot(
        (fresh,),
        (),
        0.1,
        coverage=DateCoverage((DateInterval(date(2026, 1, 1), date(2026, 1, 2)),)),
    )

    replaced = _replace_header_interval((unaffected, old), snapshot)

    assert replaced == (unaffected, fresh)


def test_header_successful_empty_interval_removes_stale_covered_rows() -> None:
    stale = UsageRecord(
        date(2026, 1, 1),
        "claude",
        TokenUsage(10, 10, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    snapshot = UsageSnapshot(
        (),
        (),
        0.1,
        coverage=DateCoverage((DateInterval(date(2026, 1, 1), date(2026, 1, 1)),)),
    )

    assert _replace_header_interval((stale,), snapshot) == ()


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
        == "calendar"
    )


def test_pane_chooser_wraps_backward_and_escape_cancels(
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
    assert _choose_pane_type(Screen(), load_translator("en"), decoder, height=20) == "monitor"

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
            paint_choices=lambda choices, title, controls: painted.append(
                (choices, title, controls)
            ),
        )
        is None
    )
    assert painted[0][1:] == (
        "Replace pane",
        "j/k select · Enter replace · Esc cancel",
    )


def test_tui_input_decodes_keys_and_fragmented_mouse_press() -> None:
    decoder = InputDecoder()
    decoder.feed("r")
    assert decoder.next() == KeyEvent("r")
    decoder.feed("\x1b[<0;20")
    assert decoder.next() is None
    decoder.feed(";5M")
    assert decoder.next() == MouseEvent(0, 20, 5, True, 0)


def test_tui_input_times_out_incomplete_mouse_report_and_recovers() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<0;20")

    assert decoder.next(now=1.0) is None
    assert decoder.next(now=1.11) is None

    decoder.feed("r")
    assert decoder.next(now=1.11) == KeyEvent("r")


@pytest.mark.parametrize("malformed", ("\x1b[<0;;3M", "\x1b[<0;7;3;M"))
def test_tui_input_recovers_after_malformed_mouse_report(malformed: str) -> None:
    decoder = InputDecoder()
    decoder.feed(malformed + "\x1b[<0;7;3M")

    assert decoder.next() is None
    assert decoder.next() == MouseEvent(0, 7, 3, True, 0)
    assert decoder.buffer == ""


def test_tui_input_keeps_ordinary_key_after_malformed_mouse_report() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<0;;3Mq")

    assert decoder.next() is None
    assert decoder.next() == KeyEvent("q")


def test_tui_input_mode_disables_mouse_and_restores_terminal_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios
    import tty

    class Stdin:
        def isatty(self) -> bool:
            return True

        def fileno(self) -> int:
            return 7

    previous = [0, 0, 0, termios.ISIG, 0, 0, 0]
    attributes = list(previous)
    output = StringIO()
    tcset_calls: list[tuple[object, ...]] = []
    setcbreak_fds: list[int] = []
    tcget_calls = 0

    def tcgetattr(_descriptor: int) -> list[int]:
        nonlocal tcget_calls
        tcget_calls += 1
        return previous if tcget_calls == 1 else attributes

    monkeypatch.setattr(tui_input_module.sys, "stdin", Stdin())
    monkeypatch.setattr(tui_input_module.sys, "stdout", output)
    monkeypatch.setattr(tui_input_module.os, "name", "posix")
    monkeypatch.setattr(termios, "tcgetattr", tcgetattr)
    monkeypatch.setattr(termios, "tcsetattr", lambda *args: tcset_calls.append(args))
    monkeypatch.setattr(tty, "setcbreak", lambda descriptor: setcbreak_fds.append(descriptor))

    with (
        pytest.raises(RuntimeError, match="body failure"),
        tui_input_module.tui_input_mode() as decoder,
    ):
        assert isinstance(decoder, InputDecoder)
        raise RuntimeError("body failure")

    assert output.getvalue() == tui_input_module._MOUSE_ENABLE + tui_input_module._MOUSE_DISABLE
    assert setcbreak_fds == [7]
    assert tcset_calls[0][0:2] == (7, termios.TCSADRAIN)
    assert tcset_calls[0][2][3] == previous[3] & ~termios.ISIG
    assert tcset_calls[-1] == (7, termios.TCSADRAIN, previous)


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
def test_dashboard_pane_height_keys_adjust_only_shared_row_weights(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    expected: tuple[int, int],
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
                "ranking",
                "--pane",
                "timeline",
            ]
        )
    )
    copied: list[str] = []

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
            KeyEvent("s"),
            KeyEvent(key),
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
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0

    assert copied
    assert f"--row-weight {expected[0]} --row-weight {expected[1]}" in copied[-1]
    assert "--top 10" in copied[-1]


def test_dashboard_pane_adjustment_preserves_chart_top_shortcuts() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["ranking"]))

    assert tui_module.adjust_standalone(base, "+").chart.top == base.chart.top + 1
    assert tui_module.adjust_standalone(base, "-").chart.top == base.chart.top - 1
    assert tui_module._adjustment_key_supported("ranking", "quick", "+")
    assert tui_module._adjustment_key_supported("ranking", "quick", "-")
    assert not tui_module._adjustment_key_supported("ranking", "quick", "J")
    assert not tui_module._adjustment_key_supported("ranking", "quick", "K")


def test_pane_advanced_actions_exclude_dashboard_management() -> None:
    controls = _adjustment_controls("timeline", "advanced", load_translator("en"))

    assert "f filters" in controls
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
