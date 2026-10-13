import shlex
import threading
import time
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui as tui_module
from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer
from ccusage_viz.animation import animation_spec, animation_style_choices
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.cli import parse_pane_fragment as parse_dashboard_pane
from ccusage_viz.command_copy import (
    format_command,
    format_dashboard_pane_command,
    format_full_command,
    format_full_dashboard_command,
)
from ccusage_viz.configuration import default_custom_pane, standalone_from_chart_pane
from ccusage_viz.core.time import DateRange
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
from ccusage_viz.custom_protocol import CustomChartResponse, CustomProbeResponse
from ccusage_viz.domain import Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError, SchemaError, UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import RenderedChart
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import (
    AnimationPaneConfig,
    CustomCommandSource,
    EmptyPaneConfig,
    Filters,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
)
from ccusage_viz.processing.projection import build_ranking
from ccusage_viz.query.models import DataResolution, ProviderResult, QueryTrigger
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui import (
    _adjustment_controls,
    _adjustment_footer,
    _adjustment_key_supported,
    _adjustment_target,
    _adjustment_target_page,
    _animation_adjustment_target_page,
    _append_monitor_attachment,
    _choose_pane_type,
    _custom_dashboard_sources,
    _finish_ranking_search_editing,
    _frame,
    _header_options,
    _local_pane_content,
    _new_pane,
    _new_pane_options,
    _official_catalog_rows,
    _official_catalog_viewport,
    _pane_adjustment_state,
    _pane_content_actions,
    _pane_copy_payload,
    _pane_render,
    _query_affecting_adjustment,
    _update_monitor_attachment_activity,
)
from ccusage_viz.tui_input import KeyEvent, MouseEvent, PasteEvent


def test_dashboard_adjustment_paste_resets_idle_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    timers: list[AdjustmentIdleTimer] = []

    def new_timer(*_args: object, **_kwargs: object) -> AdjustmentIdleTimer:
        timer = AdjustmentIdleTimer(clock=lambda: now)
        timers.append(timer)
        return timer

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), PasteEvent("pasted text"), KeyEvent("\x03")))

    def read_input(_decoder: object, _timeout: float) -> object:
        nonlocal now
        event = next(events)
        if isinstance(event, PasteEvent):
            now = 100.0
        return event

    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    monkeypatch.setattr(tui_module, "AdjustmentIdleTimer", new_timer)
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", read_input)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert len(timers) == 1
    assert timers[0].remaining() == 180.0


def test_empty_dashboard_pane_renders_localized_placeholder() -> None:
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    pane = _new_pane(options, EmptyPaneConfig())

    assert _pane_render(pane, load_translator("en"), Terminal(40, 8, False, True)).chart == (
        "Empty pane\nDouble-click to select, then press r to choose a type"
    )
    assert _pane_render(pane, load_translator("zh"), Terminal(40, 8, False, True)).chart == (
        "空白子图\n双击选中，然后按 r 选择类型"
    )


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
        purpose = tui_module.HistoricalPurpose.PRIMARY
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
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((120, 35))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0

    text = "\n".join("\n".join(frame.rows) for frame in frames)
    assert "Dashboard presets" in text
    assert "Save current Dashboard as:" in text


def _catalog_entries(count: int = 1) -> tuple[object, ...]:
    return tuple(
        SimpleNamespace(
            id=f"dataset-{index}",
            title=LocalizedText(f"Dataset {index}", f"数据集 {index}"),
            summary=LocalizedText(
                "This deliberately long summary explains what the Dataset measures over a useful period.",
                "这是一个用于验证官方数据集简介在表格中最多显示两行并在超出时省略的较长说明。",
            ),
        )
        for index in range(count)
    )


def test_official_catalog_table_limits_each_summary_to_two_lines() -> None:
    rows = _official_catalog_rows(
        _catalog_entries(), load_translator("en"), index=0, width=48
    )

    assert rows[0].startswith("  Name")
    assert rows[2].startswith("› Dataset 0")
    assert rows[3].endswith("...")
    assert len(rows) == 4


def test_official_catalog_table_keeps_headers_visible_while_scrolling() -> None:
    choices, offset = _official_catalog_viewport(
        _catalog_entries(5),
        load_translator("en"),
        index=4,
        offset=0,
        width=72,
        height=5,
    )

    assert choices.splitlines()[0].startswith("  Name")
    assert choices.splitlines()[1] == "─" * 72
    assert "Dataset 4" in choices
    assert offset > 0


def test_pane_chooser_groups_token_usage_and_other_datasets() -> None:
    frames: list[object] = []

    class Screen:
        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

    events = iter((KeyEvent("\x1b"),))
    assert _choose_pane_type(
        Screen(),  # type: ignore[arg-type]
        load_translator("en"),
        object(),  # type: ignore[arg-type]
        height=24,
        read_input=lambda: next(events),
    ) is None

    output = "\n".join(frames[0].rows)  # type: ignore[union-attr]
    assert "Built-in token usage" in output
    assert "Other datasets" in output
    assert "Datasets" in output


def test_dashboard_custom_sources_choose_first_pane_for_each_dataset_id() -> None:
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

    assert _custom_dashboard_sources(panes) == (tui_module.CustomDashboardSource(source),)

    panes[1].component.configure(
        replace(panes[1].component.candidate, source=CustomCommandSource("reading", ("other",))),
        data_affecting=True,
    )

    assert _custom_dashboard_sources(panes) == (tui_module.CustomDashboardSource(source),)


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


def test_dashboard_command_copy_preserves_custom_legend() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                "custom timeline --dataset reading --command 'reader ccuv' --legend inside",
            ]
        )
    )

    command = format_full_dashboard_command(dashboard)
    copied = _to_options(parser.parse_args(shlex.split(command)[1:]))

    assert "--legend inside" in command
    pane = copied.panes[0]
    assert isinstance(pane, tui_module.CustomChartPaneConfig)
    assert pane.chart.presentation.legend == "inside"


def test_dashboard_defaults_to_a_filled_four_pane_dashboard() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard"]))
    assert "dashboard" == "dashboard"
    assert isinstance(options.panes[0], AnimationPaneConfig)
    assert options.panes[0].animation.style == "analog-clock"
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


def test_dashboard_commands_preserve_local_date_context_and_timezone() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard"]))

    full = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert shlex.split(full)[:2] == ["ccuv", "dashboard"]
    assert "--timezone Asia/Shanghai" in full
    assert (
        _header_options(reparsed).chart.date_range.since
        <= _header_options(reparsed).chart.date_range.until
    )
    explicit = _to_options(parser.parse_args(["dashboard", "--timezone", "UTC"]))
    assert explicit.host.timezone == "UTC"


def test_full_dashboard_command_preserves_local_launcher_for_clock_overlay() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard"]), launcher="ccuv-local")

    command = format_full_dashboard_command(dashboard)
    tokens = shlex.split(command)
    reparsed = _to_options(parser.parse_args(tokens[1:]), launcher=tokens[0])

    assert tokens[:2] == ["ccuv-local", "dashboard"]
    assert "--overlay-command" in tokens[tokens.index("--pane") + 1]
    assert reparsed.launcher == "ccuv-local"
    assert isinstance(reparsed.panes[0], AnimationPaneConfig)
    assert reparsed.panes[0].overlay.command == "ccuv-local text time-state --run"


def test_full_dashboard_command_preserves_animation_pane_style() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(
        parser.parse_args(["dashboard", "--pane", "timeline", "--pane", "animate rain"])
    )

    command = format_full_dashboard_command(dashboard)
    reparsed = _to_options(parser.parse_args(shlex.split(command)[1:]))

    assert "animate rain" in command
    assert reparsed.panes[1] == dashboard.panes[1]


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
        row_weights=(3, 1, 1),
    )
    reparsed = _to_options(parser.parse_args(shlex.split(full)[1:]))

    assert reparsed.host.column_weights == (16, 8)
    assert reparsed.host.row_weights == (15, 5, 5)


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
        standalone_from_chart_pane(base, timeline), refresh_interval=30
    ) == (
        "ccuv chart timeline --period 7d --timezone Asia/Shanghai --interval 30 --density compact"
    )
    assert format_dashboard_pane_command(
        standalone_from_chart_pane(base, stack), refresh_interval=30
    ) == ("ccuv chart stack --timezone Asia/Shanghai --interval 30 --density compact")
    assert format_dashboard_pane_command(
        standalone_from_chart_pane(base, monitor), refresh_interval=30, sampling_interval=15
    ) == ("ccuv chart monitor --by model --timezone Asia/Shanghai --density compact")


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
    pane = _new_pane(standalone_from_chart_pane(dashboard, dashboard.panes[0]), "pane:command")
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


def test_dashboard_monitor_default_does_not_change_explicit_or_standalone_total() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--pane", "monitor"]))
    panel = dashboard.panes[0]
    standalone = _to_options(parser.parse_args(["chart", "monitor"]))

    assert _new_pane_options("monitor", dashboard).chart.by == "model"
    assert panel.chart.by is None
    assert standalone.chart.by is None


def test_tui_adjustment_target_exists_only_during_adjustment() -> None:
    assert _adjustment_target(None, "\t", 4) is None
    assert _adjustment_target(None, "m", 4) == 0
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
        standalone_from_chart_pane(options, parse_dashboard_pane("timeline", host=options)),
        "pane:test",
    )

    assert not hasattr(pane, "show_details")


def test_dashboard_animation_pane_is_render_only() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "animate rain"]))

    pane = _new_pane(options, AnimationPaneConfig(animation_spec("rain")))

    assert isinstance(pane, tui_module.TuiAnimationPane)
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


def test_dashboard_animation_panes_keep_independent_session_state() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(["dashboard", "--pane", "animate rain", "--pane", "animate rain"])
    )

    first = _new_pane(options, options.panes[0])
    second = _new_pane(options, options.panes[1])
    assert isinstance(first, tui_module.TuiAnimationPane)
    assert isinstance(second, tui_module.TuiAnimationPane)

    first.session.set_theme("vivid", 1.0)
    first.session.set_playback_requested(False, 1.0)

    assert second.session.theme == "classic"
    assert second.session.playback_requested


def test_dashboard_monitor_attachment_starts_disabled() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "monitor --by model"]))
    pane = _new_pane(options, options.panes[0], "dashboard:pane:0", build_query_runtime())

    assert pane.attachment is not None
    assert pane.attachment.spec.style == animation_style_choices("monitor")[0]
    assert pane.attachment.theme == "classic"
    assert not pane.attachment_enabled
    assert not pane.attachment.visible


def test_dashboard_monitor_attachment_tracks_only_accepted_activity() -> None:
    class Component:
        accepted_total_token_delta = 4

    attachment = tui_module.new_animation_session(animation_spec("rain"), theme="classic")
    attachment.set_visible(True, 0.0)
    attachment.set_viable(True, 0.0)

    _update_monitor_attachment_activity(
        Component(),
        attachment,
        now=1.0,
        wall=datetime(2026, 9, 28, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert attachment.playback_requested

    Component.accepted_total_token_delta = None
    _update_monitor_attachment_activity(
        Component(),
        attachment,
        now=2.0,
        wall=datetime(2026, 9, 28, 6, 42, 10, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert not attachment.playback_requested
    assert attachment.activity_label == "last activity detected: 00:00:00"

    _update_monitor_attachment_activity(
        Component(),
        attachment,
        now=3.0,
        wall=datetime(2026, 9, 28, 6, 43, 0, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert attachment.activity_label == "last activity detected: 00:00:00"


def test_dashboard_monitor_attachment_hides_outside_ranking_and_list() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "monitor --style ranking"]))
    pane = _new_pane(options, options.panes[0], "pane:monitor")
    assert isinstance(pane, tui_module.TuiChartPane)
    assert pane.attachment is not None

    body = _append_monitor_attachment(
        pane,
        "chart",
        terminal=Terminal(80, 24, False, True),
        reserved_rows=0,
        now=1.0,
        translator=load_translator("en"),
    )
    assert body == "chart"
    assert not pane.attachment.visible

    pane.component.observer.current_interval = type("Interval", (), {"total": 0})()
    body = _append_monitor_attachment(
        pane,
        "chart",
        terminal=Terminal(80, 24, False, True),
        reserved_rows=0,
        now=2.0,
        translator=load_translator("en"),
    )
    assert body == "chart"
    assert not pane.attachment.visible

    pane.attachment_enabled = True
    body = _append_monitor_attachment(
        pane,
        "chart",
        terminal=Terminal(80, 24, False, True),
        reserved_rows=0,
        now=3.0,
        translator=load_translator("en"),
    )
    assert body != "chart"
    assert pane.attachment.visible

    candidate = pane.component.candidate
    pane.component.candidate = replace(
        candidate,
        chart=replace(
            candidate.chart, presentation=replace(candidate.chart.presentation, style="bars")
        ),
    )
    assert (
        _append_monitor_attachment(
            pane,
            "chart",
            terminal=Terminal(80, 24, False, True),
            reserved_rows=0,
            now=2.0,
            translator=load_translator("en"),
        )
        == "chart"
    )
    assert not pane.attachment.visible


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

    keys = iter(
        (KeyEvent("v"), KeyEvent("r"), KeyEvent(" "), KeyEvent("\x03"))
        if text_view
        else (KeyEvent(" "), KeyEvent("r"), KeyEvent("\x03"))
    )
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
        purpose = tui_module.HistoricalPurpose.PRIMARY
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
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "build_chart_registry", lambda: object())
    monkeypatch.setattr(tui_module, "HistoricalChartComponent", Component)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((160, 55))
    )
    monkeypatch.setattr(tui_module, "_pane_render", lambda *_args: tui_module.PaneRender("chart"))

    assert tui_module.run_tui(options, load_translator("en")) == 0

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
            KeyEvent("m"),
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
    pane_ref: list[tui_module.TuiChartPane] = []
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
    original_pane_render = tui_module._pane_render

    def record_summary(self: HistoricalChartComponent, summary: object) -> None:
        summary_set_calls.append(summary)
        original_set_summary(self, summary)  # type: ignore[arg-type]

    def capture_pane_render(pane: object, *args: object, **kwargs: object) -> tui_module.PaneRender:
        if isinstance(pane, tui_module.TuiChartPane):
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

    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(HistoricalChartComponent, "set_summary", record_summary)
    monkeypatch.setattr(tui_module, "_pane_render", capture_pane_render)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", read_event)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert summary_submissions == 3
    assert any(event == "cancel:summary:2" for event in events)
    assert stale_finished.is_set()
    assert len(summary_set_calls) == 1
    assert pane_ref[0].summary is baseline_summary[0]
    assert pane_ref[0].component.summary is baseline_component_summary[0]
    assert isinstance(pane_ref[0].summary_error, QueryError)


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
        standalone_from_chart_pane(
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

    monkeypatch.setattr(tui_module, "render_historical_component", fake_render)

    rendered = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "timeline"
    assert captured["normalize_titles"] is True


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

    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", read_until_chart)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert [intent.payload.request_kind for intent in submitted[:2]] == ["probe", "chart"]
    assert chart_submitted.is_set()


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
            raise QueryError("error.custom_command_protocol")

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

    events = iter((KeyEvent("m"), KeyEvent("\x1b[B"), KeyEvent("r"), KeyEvent("\x03")))
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
    assert _query_affecting_adjustment("monitor", "B")
    assert not _query_affecting_adjustment("stack", "c")
    assert not _query_affecting_adjustment("monitor", "+")
    assert not _query_affecting_adjustment("timeline", "t")


def test_dashboard_pane_adjustment_state_changes_with_page() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = _new_pane(standalone_from_chart_pane(options, options.panes[1]), "pane:test")
    translator = load_translator("en")

    quick = _pane_adjustment_state(pane, "quick", translator)
    advanced = _pane_adjustment_state(pane, "advanced", translator)

    assert "timeline · compact · nord · line-points" in quick
    assert "Legend" in advanced
    assert "Weekdays" in advanced
    assert quick != advanced


@pytest.mark.parametrize("command", ("timeline", "ranking"))
def test_historical_project_adjustments_are_not_exposed_in_dashboard(command: str) -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--pane", f"{command} --by project"]))
    project_pane = _new_pane(
        standalone_from_chart_pane(dashboard, dashboard.panes[0]), f"pane:{command}:project"
    )
    chart = project_pane.component.candidate.chart
    translator = load_translator("en")

    controls = _adjustment_controls(command, "advanced", translator, chart=chart)
    assert "project aggregation" not in controls
    assert "project labels" not in controls
    assert not _adjustment_key_supported(command, "advanced", "A", chart=chart)
    assert not _adjustment_key_supported(command, "advanced", "P", chart=chart)
    state = _pane_adjustment_state(project_pane, "advanced", translator)
    assert "Project aggregation" not in state
    assert "Project labels" not in state


def test_dashboard_pane_adjustment_page_resolves_unambiguous_shortcuts() -> None:
    chart = TimelineConfig("timeline", DateRange(date(2026, 1, 1), date(2026, 1, 14)))
    project_chart = replace(chart, by="project")
    ranking_chart = RankingConfig("ranking", DateRange(date(2026, 1, 1), date(2026, 1, 14)))

    assert _adjustment_target_page("timeline", "quick", "k", chart=chart) == "advanced"
    assert _adjustment_target_page("timeline", "advanced", "g", chart=chart) == "quick"
    assert _adjustment_target_page("timeline", "quick", "f", chart=chart) == "advanced"
    assert _adjustment_target_page("timeline", "quick", "?", chart=chart) is None
    assert _adjustment_target_page("timeline", "quick", "P", chart=project_chart) == "quick"
    assert _adjustment_target_page("timeline", "advanced", "P", chart=project_chart) == "quick"
    assert _adjustment_target_page("timeline", "advanced", "P", chart=chart) == "quick"
    assert _adjustment_target_page("ranking", "quick", "+", chart=ranking_chart) == "quick"
    assert _adjustment_target_page("ranking", "advanced", "-", chart=ranking_chart) == "quick"
    assert _adjustment_key_supported("ranking", "quick", "+", chart=ranking_chart)
    assert _adjustment_key_supported("ranking", "quick", "-", chart=ranking_chart)


def test_dashboard_ranking_top_adjustments_change_the_display_count() -> None:
    chart = RankingConfig(
        "ranking", DateRange(date(2026, 1, 1), date(2026, 1, 14)), top=10
    )
    options = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)

    increased = adjust_standalone(options, "+")
    decreased = adjust_standalone(increased, "-")

    assert increased.chart.top == 11
    assert decreased.chart.top == 10


def test_dashboard_ranking_state_shows_the_current_grouping_and_top() -> None:
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--pane", "ranking --by project --top 11"]
        )
    )
    pane = _new_pane(
        standalone_from_chart_pane(options, options.panes[0]), "pane:ranking:top"
    )

    assert "Group project · Top 11" in _pane_adjustment_state(
        pane, "quick", load_translator("en")
    )


def test_ranking_top_above_available_projects_keeps_all_available_projects() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))
    records = tuple(
        UsageRecord(
            period.since,
            f"agent-{index}",
            TokenUsage.from_parts(total=index, input=index),
            SourceKind.UNIFIED_DAILY,
        )
        for index in range(1, 10)
    )

    model = build_ranking(records, period, by="agent", top=11, show_other=True)

    assert len(model.entries) == 9
    assert all(not entry.is_other for entry in model.entries)


def test_dashboard_monitor_page_resolution_keeps_attachment_shortcuts_current() -> None:
    chart = replace(
        MonitorConfig("monitor", DateRange(date(2026, 1, 1), date(2026, 1, 14))),
        presentation=replace(
            MonitorConfig("monitor", DateRange(date(2026, 1, 1), date(2026, 1, 14))).presentation,
            style="ranking",
        ),
    )

    for key in ("t", "T", "s", "S"):
        assert (
            _adjustment_target_page("monitor", "quick", key, chart=chart, attachment_available=True)
            == "quick"
        )
        assert (
            _adjustment_target_page(
                "monitor", "advanced", key, chart=chart, attachment_available=True
            )
            == "advanced"
        )
    assert _adjustment_target_page("monitor", "advanced", "t", chart=chart) == "quick"


def test_dashboard_animation_pane_resolves_unambiguous_shortcuts() -> None:
    assert _animation_adjustment_target_page("quick", "e") == "advanced"
    assert _animation_adjustment_target_page("advanced", "t") == "quick"
    assert _animation_adjustment_target_page("quick", "p") == "quick"
    assert _animation_adjustment_target_page("advanced", "\x1b[A") == "advanced"
    assert _animation_adjustment_target_page("quick", "?") is None


def test_calendar_advanced_adjustment_uses_the_shared_filter_control() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "calendar"]))
    pane = _new_pane(standalone_from_chart_pane(options, options.panes[0]), "pane:calendar")
    translator = load_translator("en")

    assert _pane_adjustment_state(pane, "advanced", translator) == "running"
    assert _adjustment_controls("calendar", "advanced", translator) == "f edit filters"


def test_dashboard_monitor_advanced_state_shows_attachment_settings() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "monitor --style ranking"]))
    pane = _new_pane(standalone_from_chart_pane(options, options.panes[0]), "pane:monitor")
    assert pane.attachment is not None
    pane.attachment.set_theme("dracula", 0.0)

    assert "ANIMATION none · THEME dracula" in _pane_adjustment_state(
        pane, "advanced", load_translator("en")
    )
    pane.attachment_enabled = True
    english = _pane_adjustment_state(pane, "advanced", load_translator("en"))
    chinese = _pane_adjustment_state(pane, "advanced", load_translator("zh"))

    style = animation_style_choices("monitor")[0]
    display_name = animation_spec(style, target="monitor").display_name
    assert f"ANIMATION {display_name} · THEME dracula" in english
    assert f"动画 {display_name} · 主题 dracula" in chinese
    pane.attachment_enabled = False
    assert "ANIMATION none · THEME dracula" in _pane_adjustment_state(
        pane, "advanced", load_translator("en")
    )
    assert "ANIMATION" not in _pane_adjustment_state(pane, "quick", load_translator("en"))


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

    original_apply_draft = tui_module.AnimationOverlayRuntime.apply_draft

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
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(keys))
    monkeypatch.setattr(
        tui_module,
        "get_terminal_size",
        lambda: __import__("os").terminal_size((200, 30)),
    )
    monkeypatch.setattr(tui_module.AnimationOverlayRuntime, "apply_draft", capture_draft)

    assert tui_module.run_tui(options, load_translator("en")) == 0
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


def test_animation_pane_footer_exposes_dashboard_management_without_view() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "animate rain"]))
    pane = _new_pane(options, options.panes[0])
    assert isinstance(pane, tui_module.TuiAnimationPane)

    quick = tui_module._animation_adjustment_footer(pane, "quick", load_translator("en"), 120)
    advanced = tui_module._animation_adjustment_footer(pane, "advanced", load_translator("en"), 120)
    chinese = tui_module._animation_adjustment_footer(pane, "quick", load_translator("zh"), 120)

    assert "Space" not in quick[1]
    assert "p/P overlay position" in quick[1]
    assert "r replace" in quick[3]
    assert "N insert before" in quick[3]
    assert "n insert after" in quick[3]
    assert "x delete" in quick[3]
    assert "v switch view" not in quick[3]
    assert "y copy" not in quick[3]
    assert "Tab select next" in quick[4]
    assert "{ / } width" in quick[4]
    assert "J / K height" in quick[4]
    assert quick[2:] == advanced[2:]
    assert "r 替换" in chinese[3]
    assert "v 切换视图" not in chinese[3]
    assert quick[2] == "━━ Dashboard Pane Management ━━"
    assert chinese[2] == "━━ Dashboard 子图管理 ━━"
    assert tui_module._pane_management_divider(load_translator("en"), 120, color=True) == (
        "\x1b[1m━━ Dashboard Pane Management ━━\x1b[0m"
    )
    assert tui_module._pane_management_divider(load_translator("en"), 120, color=False) == (
        "━━ Dashboard Pane Management ━━"
    )
    for language in ("en", "zh"):
        assert all(
            display_width(row) <= 24
            for row in tui_module._animation_adjustment_footer(
                pane, "quick", load_translator(language), 24, color=True
            )
        )


def test_empty_pane_footer_exposes_dashboard_management_without_local_actions() -> None:
    translator = load_translator("en")
    footer = tui_module._empty_pane_adjustment_footer(translator, 120)
    chinese = tui_module._empty_pane_adjustment_footer(load_translator("zh"), 120)

    assert footer[0] == "━━ Dashboard Pane Management ━━"
    assert "r replace" in footer[1]
    assert "N insert before" in footer[1]
    assert "n insert after" in footer[1]
    assert "x delete" in footer[1]
    assert "v switch view" not in footer[1]
    assert "y copy" not in footer[1]
    assert "Tab select next" in footer[2]
    assert "{ / } width" in footer[2]
    assert "J / K height" in footer[2]
    assert "Quick settings" not in "\n".join(footer)
    assert "p/P period" not in "\n".join(footer)
    assert "r 替换" in chinese[1]
    assert "v 切换视图" not in chinese[1]
    for language in ("en", "zh"):
        assert all(
            display_width(row) <= 24
            for row in tui_module._empty_pane_adjustment_footer(
                load_translator(language), 24, color=True
            )
        )


def test_tui_adjustment_footer_separates_dashboard_management() -> None:
    translator = load_translator("en")
    timeline_chart = TimelineConfig(
        "timeline", DateRange(date(2026, 1, 1), date(2026, 1, 14)), by="project"
    )
    timeline_quick = _adjustment_controls("timeline", "quick", translator, chart=timeline_chart)
    timeline_advanced = _adjustment_controls(
        "timeline", "advanced", translator, chart=timeline_chart
    )
    stack_advanced = _adjustment_controls("stack", "advanced", translator)

    assert "p/P period" in timeline_quick
    assert "g/G granularity" in timeline_quick
    assert "v view" not in timeline_quick
    assert "k weekdays" in timeline_advanced
    assert "l legend" in timeline_advanced
    assert "f edit filters" in timeline_advanced
    assert "project aggregation" not in timeline_advanced
    assert "project labels" not in timeline_advanced
    assert "c cache mode" in stack_advanced
    assert not _adjustment_key_supported("timeline", "quick", "k")
    assert _adjustment_key_supported("timeline", "advanced", "k")
    assert not _adjustment_key_supported("timeline", "advanced", "A", chart=timeline_chart)
    assert not _adjustment_key_supported("timeline", "advanced", "P", chart=timeline_chart)
    assert _adjustment_key_supported("timeline", "quick", "b")
    assert _adjustment_key_supported("timeline", "quick", "d")
    assert _adjustment_key_supported("monitor", "quick", "d")
    assert not _adjustment_key_supported("timeline", "advanced", "b")
    assert not _adjustment_key_supported("monitor", "quick", "i")
    assert _adjustment_key_supported("monitor", "quick", "B")
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
    assert "Dashboard Pane Management" in quick_rows[2]
    assert "v switch view" in quick_rows[3]
    assert "N insert before" in quick_rows[3]
    assert "Tab select next" in quick_rows[4]
    assert quick_rows[2:] == advanced_rows[2:]
    assert "[Finish]" not in "\n".join(quick_rows)
    chinese_advanced = _adjustment_footer(
        "当前状态：运行中", "timeline", "advanced", "chart", load_translator("zh"), 80
    )
    assert "a 快捷" in chinese_advanced[1]


def test_monitor_attachment_adjustment_actions_are_localized() -> None:
    ranking = MonitorConfig("monitor", DateRange(date(2026, 1, 1), date(2026, 1, 14)), by="model")
    ranking = replace(ranking, presentation=replace(ranking.presentation, style="ranking"))

    for language, expected in (
        ("en", ("t/T animation theme", "s/S animation style")),
        ("zh", ("t/T 动画主题", "s/S 动画样式")),
    ):
        actions = tui_module._pane_adjustment_actions(
            "monitor",
            "advanced",
            load_translator(language),
            chart=ranking,
            attachment_available=True,
        )
        assert tuple(action.text for action in actions[-2:]) == expected

    assert not any(
        "animation" in action.text
        for action in tui_module._pane_adjustment_actions(
            "monitor", "quick", load_translator("en"), chart=ranking, attachment_available=True
        )
    )
