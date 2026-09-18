from dataclasses import replace
from datetime import date

import pytest

import ccusage_viz.tui as tui_module
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.command_copy import format_dashboard_pane_command, format_full_dashboard_command
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.deltas import RefreshRanks
from ccusage_viz.domain import Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor import ObservedTPM
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui import (
    DashboardHeader,
    TuiPane,
    _adjustment_controls,
    _adjustment_footer,
    _adjustment_key_supported,
    _adjustment_target,
    _dashboard_adjustment_status,
    _dashboard_title_line,
    _finish_clicked,
    _grid_shape,
    _header_lines,
    _header_options,
    _header_refresh_interval,
    _next_header_summary,
    _pane_render,
    _panel_fragment,
    _panel_options,
    _query_affecting_adjustment,
    _refresh_deltas,
    _refresh_ranks,
    _replace_header_interval,
    _unique_notices,
    compose_panels,
    pane_at,
    pane_rects,
    parse_grid,
    resolve_panel_layout,
)
from ccusage_viz.tui_input import InputDecoder, KeyEvent, MouseEvent
from ccusage_viz.watch import UsageSnapshot


def test_dashboard_defaults_to_a_filled_four_pane_dashboard() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard"]))
    assert options.command == "dashboard"
    assert options.panes == ("timeline", "stack", "ranking", "monitor --by model")
    assert options.grid == "2x2"
    assert options.header_style == "panel"
    assert options.header_summary == "day"
    assert options.header_interval == 60.0
    assert options.dashboard_style == "split"


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
                "--panel",
                "timeline --project /private/project",
            ]
        )
    )
    panels = tuple(_panel_options(fragment, dashboard) for fragment in dashboard.panes)

    full = format_full_dashboard_command(
        dashboard,
        panels,
        grid="auto",
        header_style="compact",
        header_summary="week",
        dashboard_style="split",
    )

    assert "/private/project" in full
    assert "--ccusage-bin /opt/ccusage" in full
    assert "--query-timeout 42" in full


def test_dashboard_pane_copy_materializes_canonical_standalone_interval() -> None:
    parser = build_parser(load_translator("en"))
    base = _to_options(parser.parse_args(["dashboard"]))
    timeline = _panel_options("timeline --period 7d", base)
    stack = _panel_options("stack", base)
    monitor = _panel_options("monitor --by model", base)

    assert format_dashboard_pane_command(timeline, refresh_interval=30) == (
        "ccuv timeline --period 7d --interval 30"
    )
    assert format_dashboard_pane_command(stack, refresh_interval=30) == (
        "ccuv stack --period 14d --interval 30"
    )
    assert format_dashboard_pane_command(monitor, refresh_interval=monitor.interval) == (
        "ccuv monitor --window 1h --interval 15 --by model --top 3 --style line"
    )


def test_dashboard_monitor_default_does_not_change_explicit_or_standalone_total() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--panel", "monitor"]))
    panel = _panel_options("monitor", dashboard)
    standalone = _to_options(parser.parse_args(["monitor"]))

    assert _panel_fragment("monitor") == "monitor --by model"
    assert panel.by is None
    assert standalone.by is None


def test_tui_adjustment_target_exists_only_during_adjustment() -> None:
    assert _adjustment_target(None, "\t", 4) is None
    assert _adjustment_target(None, "s", 4) == 0
    assert _adjustment_target(0, "\t", 4) == 1
    assert _adjustment_target(3, "\t", 4) == 0
    assert _adjustment_target(2, "l", 4) == 2
    assert _adjustment_target(2, "q", 4) == 2
    assert _adjustment_target(2, "Q", 4) == 2
    assert _adjustment_target(2, "\x1b", 4) is None


def test_dashboard_adjustment_status_only_advertises_navigation_when_available() -> None:
    english = load_translator("en")
    chinese = load_translator("zh")

    assert (
        _dashboard_adjustment_status(
            adjusting=False, focused=None, pane_count=4, translator=english
        )
        is None
    )
    assert (
        _dashboard_adjustment_status(adjusting=True, focused=0, pane_count=1, translator=english)
        == "Adjustment mode · Esc finish"
    )
    assert (
        _dashboard_adjustment_status(adjusting=True, focused=0, pane_count=2, translator=english)
        == "Adjustment mode · Tab next pane · Esc finish"
    )
    assert (
        _dashboard_adjustment_status(adjusting=True, focused=0, pane_count=1, translator=chinese)
        == "调整模式 · Esc 完成"
    )
    assert (
        _dashboard_adjustment_status(adjusting=True, focused=0, pane_count=2, translator=chinese)
        == "调整模式 · Tab 下一子图 · Esc 完成"
    )


def test_dashboard_panes_have_no_details_state() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = TuiPane(_panel_options("timeline", options), QueryRunner())

    assert not hasattr(pane, "show_details")


def test_dashboard_pane_render_retains_chart_notices_and_deduplicates_them() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    ranking = _panel_options("ranking --by project", options)
    snapshot = UsageSnapshot(
        (
            UsageRecord(
                ranking.date_range.until,
                "claude",
                TokenUsage(10, 10, 0, 0, 0),
                SourceKind.CLAUDE_DAILY_PROJECTS,
            ),
        ),
        (),
        0.1,
        coverage=DateCoverage((DateInterval(ranking.date_range.until, ranking.date_range.until),)),
        summary_notices=(Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),),
    )
    panes = [
        TuiPane(ranking, QueryRunner(), snapshot=snapshot),
        TuiPane(ranking, QueryRunner(), snapshot=snapshot),
    ]

    rendered = [
        _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True)) for pane in panes
    ]

    assert rendered[0].notices == (
        "Summary excludes Codex project-session usage; ccusage has no per-day values",
    )
    assert rendered[0].notices[0] not in rendered[0].chart
    assert _unique_notices(rendered) == rendered[0].notices


def test_dashboard_monitor_forwards_value_and_rank_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = TuiPane(_panel_options("monitor --by model --style ranking", options), QueryRunner())
    monitor.observer = ObservedTPM(window_seconds=3600, by="model", top=3)
    monitor.deltas = {"sonnet": 4.0}
    monitor.rank_deltas = {"sonnet": 1}
    captured: dict[str, object] = {}

    def fake_render(*args: object, **kwargs: object) -> str:
        captured.update(kwargs)
        return "monitor"

    monkeypatch.setattr(tui_module, "render_monitor_snapshot", fake_render)

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "monitor"
    assert captured["deltas"] == {"sonnet": 4.0}
    assert captured["rank_deltas"] == {"sonnet": 1}


def test_dashboard_monitor_and_error_panes_do_not_contribute_chart_notices() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    monitor = TuiPane(_panel_options("monitor", options), QueryRunner(), error="pane failed")

    rendered = _pane_render(monitor, load_translator("en"), Terminal(58, 16, False, True))

    assert rendered.chart == "pane failed"
    assert rendered.notices == ()


def test_dashboard_pane_retains_last_render_for_localized_renderer_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo"]))
    pane = TuiPane(
        _panel_options("stack", options),
        QueryRunner(),
        snapshot=UsageSnapshot((), (), 0.25),
    )
    monkeypatch.setattr(
        tui_module,
        "render_snapshot",
        lambda *args, **kwargs: tui_module.PaneRender("previous chart"),
    )
    first = _pane_render(pane, load_translator("en"), Terminal(58, 16, False, True))
    monkeypatch.setattr(
        tui_module,
        "render_snapshot",
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
    assert not _query_affecting_adjustment("timeline", "g")
    assert _query_affecting_adjustment("ranking", "b")
    assert _query_affecting_adjustment("monitor", "B")
    assert not _query_affecting_adjustment("stack", "c")
    assert not _query_affecting_adjustment("monitor", "+")
    assert not _query_affecting_adjustment("timeline", "t")


def test_tui_adjustment_footer_has_quick_advanced_and_three_rows() -> None:
    translator = load_translator("en")
    timeline_quick = _adjustment_controls("timeline", "quick", translator)
    timeline_advanced = _adjustment_controls("timeline", "advanced", translator)
    stack_advanced = _adjustment_controls("stack", "advanced", translator)

    assert "p period" in timeline_quick
    assert "g granularity" in timeline_quick
    assert "a Advanced" in timeline_quick
    assert "k weekdays" in timeline_advanced
    assert "l legend" in timeline_advanced
    assert "a Quick" in timeline_advanced
    assert "c cache mode" in stack_advanced
    assert not _adjustment_key_supported("timeline", "quick", "k")
    assert _adjustment_key_supported("timeline", "advanced", "k")
    assert _adjustment_key_supported("timeline", "quick", "b")
    assert not _adjustment_key_supported("timeline", "advanced", "b")

    rows, target = _adjustment_footer("timeline", "quick", translator, 80)
    assert len(rows) == 3
    assert all(len(row) == 80 for row in rows)
    assert rows[-1].rstrip().endswith("[Finish]")
    assert _finish_clicked(
        MouseEvent(0, target[0], 24, True, 0),
        adjusting=True,
        width=80,
        height=24,
        hit_target=target,
    )
    assert not _finish_clicked(
        MouseEvent(0, target[0] - 1, 24, True, 0),
        adjusting=True,
        width=80,
        height=24,
        hit_target=target,
    )


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


def test_tui_header_query_is_unfiltered_and_independent() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--demo", "--header-style", "panel"]))
    header = _header_options(options)
    assert header.command == "timeline"
    assert header.agents == header.models == header.projects == ()
    assert header.by is None
    assert header.top is None
    assert header.date_range.days == 8


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
    header = DashboardHeader(_header_options(options), QueryRunner())
    today = date(2026, 3, 15)

    cold = _header_refresh_interval(header, today=today)
    assert cold == DateInterval(date(2025, 3, 1), today)

    header.coverage = DateCoverage((cold,))
    header.records = (UsageRecord(today, "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY),)
    assert _header_refresh_interval(header, today=today) == DateInterval(today, today)
    assert _header_refresh_interval(header, aggressive=True, today=today) == cold

    header.records = ()
    assert _header_refresh_interval(header, today=today) == DateInterval(today, today)

    header.options = replace(header.options, header_summary="none")
    assert _header_refresh_interval(header, today=today) is None


def test_header_date_rollover_requests_new_current_day() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "day"]))
    header = DashboardHeader(_header_options(options), QueryRunner())
    previous = date(2026, 3, 15)
    header.coverage = DateCoverage((DateInterval(previous.replace(day=8), previous),))
    header.records = (UsageRecord(previous, "claude", TokenUsage.zero(), SourceKind.UNIFIED_DAILY),)

    assert _header_refresh_interval(header, today=date(2026, 3, 16)) == DateInterval(
        date(2026, 3, 16), date(2026, 3, 16)
    )


def test_header_none_keeps_title_without_unknown_detail() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "none"]))
    header = DashboardHeader(_header_options(options), QueryRunner())

    compact = _header_lines(header, "compact", load_translator("en"), Terminal(60, 4, False, True))
    banner = _header_lines(header, "banner", load_translator("en"), Terminal(60, 4, False, True))

    assert len(compact) == 1
    assert "Dashboard" in compact[0]
    assert "?" not in compact[0]
    assert len(banner) == 1


def test_header_cold_period_keeps_structure_with_unknown_detail() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(parser.parse_args(["dashboard", "--header-summary", "quarter"]))
    header = DashboardHeader(_header_options(options), QueryRunner())

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


def test_tui_accepts_repeatable_panel_fragments_and_grid() -> None:
    parser = build_parser(load_translator("en"))
    options = _to_options(
        parser.parse_args(
            ["dashboard", "--panel", "timeline --period 7d", "--panel", "ranking", "--grid", "1x2"]
        )
    )
    assert options.panes == ("timeline --period 7d", "ranking")
    assert options.grid == "1x2"


def test_tui_grid_auto_and_compositor() -> None:
    assert _grid_shape("auto", 3) == (2, 2)
    output = compose_panels(["a\nb", "c\nd"], 12, 4, 1, 2, focused=0)
    lines = output.splitlines()
    assert len(lines) == 4
    assert "a" in lines[1]
    assert "c" in lines[1]
    assert lines[1].startswith("║a")
    assert "│c" in lines[1]


def test_tui_default_frame_has_no_browse_outline_and_adjustment_outline_is_external() -> None:
    browsing = compose_panels(
        ["Title\nvalue"], 12, 4, 1, 1, focused=-1, frame_style="none", ascii=True
    )
    adjusting = compose_panels(
        ["Title\nvalue"], 12, 4, 1, 1, focused=0, frame_style="none", ascii=True
    )

    assert browsing.splitlines()[0].startswith("Title")
    assert adjusting.splitlines()[0] == "+----------+"
    assert adjusting.splitlines()[1].startswith("|Title")


def test_tui_persistent_frame_does_not_depend_on_focus() -> None:
    unfocused = compose_panels(["Title"], 12, 4, 1, 1, focused=-1, frame_style="subtle", ascii=True)
    focused = compose_panels(["Title"], 12, 4, 1, 1, focused=0, frame_style="subtle", ascii=True)

    assert unfocused == focused
    assert unfocused.splitlines()[1].startswith("|Title")


def test_tui_refresh_deltas_mark_new_keys_after_the_baseline() -> None:
    pane = TuiPane.__new__(TuiPane)
    pane.previous_values = {}
    pane.deltas = {}
    pane.values_initialized = False

    _refresh_deltas(pane, {"a": 10, "new": 20})
    assert pane.deltas == {}
    _refresh_deltas(pane, {"a": 15, "new": 17, "later": 30})
    assert pane.deltas == {"a": 5, "new": -3, "later": 30}


def test_refresh_ranks_tracks_movement_and_clear() -> None:
    ranks = RefreshRanks()

    ranks.accept(("a", "b", "c"))
    assert ranks.current == {}
    ranks.accept(("b", "a", "new"))
    assert ranks.current == {"b": 1, "a": -1}
    ranks.clear()
    assert ranks.previous == ranks.current == {}


def test_tui_refresh_ranks_require_an_existing_stable_key() -> None:
    pane = TuiPane.__new__(TuiPane)
    pane.previous_ranks = {}
    pane.rank_deltas = {}

    _refresh_ranks(pane, ("a", "b"))
    assert pane.rank_deltas == {}
    _refresh_ranks(pane, ("b", "new", "a"))
    assert pane.rank_deltas == {"b": 1, "a": -2}


def test_tui_input_decodes_keys_and_fragmented_mouse_press() -> None:
    decoder = InputDecoder()
    decoder.feed("r")
    assert decoder.next() == KeyEvent("r")
    decoder.feed("\x1b[<0;20")
    assert decoder.next() is None
    decoder.feed(";5M")
    assert decoder.next() == MouseEvent(0, 20, 5, True, 0)


def test_tui_parses_runtime_grid_with_capacity() -> None:
    assert parse_grid("AUTO", 3) == "auto"
    assert parse_grid("2X2", 3) == "2x2"
    assert parse_grid("1x2", 3) is None
    assert parse_grid("zero", 1) is None


def test_tui_panel_layout_allocates_remainders_and_compositor_height() -> None:
    layout = resolve_panel_layout(width=11, height=9, rows=2, columns=2, divider_style="line")
    assert layout.widths == (5, 5)
    assert layout.heights == (4, 4)
    assert (layout.width, layout.height) == (11, 9)
    assert len(compose_panels(["a", "b", "c"], 11, 9, 2, 2, divider_style="line").splitlines()) == 9


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
