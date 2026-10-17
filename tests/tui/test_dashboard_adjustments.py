



from contextlib import nullcontext
from dataclasses import replace
from datetime import date

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.controls as tui_controls
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
)
from ccusage_viz.processing.projection import build_ranking
from ccusage_viz.tui.adjustments import (
    _adjustment_controls,
    _adjustment_footer,
    _adjustment_key_supported,
    _adjustment_target,
    _adjustment_target_page,
    _pane_adjustment_state,
    _query_affecting_adjustment,
)
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui_input import KeyEvent, PasteEvent


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

def test_tui_adjustment_target_exists_only_during_adjustment() -> None:
    assert _adjustment_target(None, "\t", 4) is None
    assert _adjustment_target(None, "m", 4) == 0
    assert _adjustment_target(0, "\t", 4) == 1
    assert _adjustment_target(3, "\t", 4) == 0
    assert _adjustment_target(2, "l", 4) == 2
    assert _adjustment_target(2, "q", 4) == 2
    assert _adjustment_target(2, "Q", 4) == 2
    assert _adjustment_target(2, "\x1b", 4) is None

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
            TokenUsage.from_parts(
                total=index, input=index, output=0, cache_read=0, cache_creation=0
            ),
            SourceKind.UNIFIED_DAILY,
        )
        for index in range(1, 10)
    )

    model = build_ranking(records, period, by="agent", top=11, show_other=True)

    assert len(model.entries) == 9
    assert all(not entry.is_other for entry in model.entries)

def test_calendar_advanced_adjustment_uses_the_shared_filter_control() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--pane", "calendar"]))
    pane = _new_pane(standalone_from_chart_pane(options, options.panes[0]), "pane:calendar")
    translator = load_translator("en")

    assert _pane_adjustment_state(pane, "advanced", translator) == "running"
    assert _adjustment_controls("calendar", "advanced", translator) == "f edit filters"

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
    assert tui_controls._pane_management_divider(load_translator("en"), 120, color=True) == (
        "\x1b[1m━━ Dashboard Pane Management ━━\x1b[0m"
    )
    assert tui_controls._pane_management_divider(load_translator("en"), 120, color=False) == (
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
        actions = tui_adjustments._pane_adjustment_actions(
            "monitor",
            "advanced",
            load_translator(language),
            chart=ranking,
            attachment_available=True,
        )
        assert tuple(action.text for action in actions[-2:]) == expected

    assert not any(
        "animation" in action.text
        for action in tui_adjustments._pane_adjustment_actions(
            "monitor", "quick", load_translator("en"), chart=ranking, attachment_available=True
        )
    )

    for style in ("ranking", "ranking-dot", "list"):
        chart = replace(ranking, presentation=replace(ranking.presentation, style=style))
        actions = tui_adjustments._pane_adjustment_actions(
            "monitor", "quick", load_translator("en"), chart=chart
        )
        assert not any(action.text.startswith("w window") for action in actions)

    line = replace(ranking, presentation=replace(ranking.presentation, style="line"))
    line_actions = tui_adjustments._pane_adjustment_actions(
        "monitor", "quick", load_translator("en"), chart=line
    )
    assert any(action.text.startswith("w window") for action in line_actions)
