




from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.animation import animation_spec, animation_style_choices
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.panes import parse_pane_fragment as parse_dashboard_pane
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.core.time import DateRange
from ccusage_viz.i18n import load_translator
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import MonitorConfig
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.adjustments import (
    _adjustment_target_page,
    _animation_adjustment_target_page,
    _pane_adjustment_state,
)
from ccusage_viz.tui.pane_lifecycle import _new_pane, _new_pane_options
from ccusage_viz.tui.rendering import (
    _append_monitor_attachment,
    _pane_render,
    _update_monitor_attachment_activity,
)


def test_dashboard_monitor_default_does_not_change_explicit_or_standalone_total() -> None:
    parser = build_parser(load_translator("en"))
    dashboard = _to_options(parser.parse_args(["dashboard", "--pane", "monitor"]))
    panel = dashboard.panes[0]
    standalone = _to_options(parser.parse_args(["chart", "monitor"]))

    assert _new_pane_options("monitor", dashboard).chart.by == "model"
    assert panel.chart.by is None
    assert standalone.chart.by is None

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

    attachment = tui_pane_lifecycle.new_animation_session(animation_spec("rain"), theme="classic")
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
