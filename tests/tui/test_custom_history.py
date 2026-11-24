"""Custom pane history must respect the monitor/historical component boundary."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.history as history
import ccusage_viz.tui.queries as queries
import ccusage_viz.tui.session as sessions
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.dashboard_history import DashboardHistory
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomChartConfig, CustomChartPaneConfig, CustomCommandSource
from ccusage_viz.tui.models import TuiCustomPane
from ccusage_viz.tui.pane_lifecycle import _new_pane


@pytest.fixture
def session(monkeypatch):
    translator = load_translator("en")
    options = _to_options(
        build_parser(translator).parse_args(["dashboard", "--empty", "--header-style", "hidden"])
    )
    options = replace(options, host=replace(options.host, timezone="UTC"))
    monkeypatch.setattr(sessions, "build_query_runtime", lambda: SimpleNamespace())
    monkeypatch.setattr(queries, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(queries, "sync_custom_dashboard_summaries", lambda *a: None)
    session = sessions.TuiSession(options, translator)
    session.panes = []
    yield session
    for pane in session.panes:
        history._shutdown_pane(pane)


def add_pane(session, kind, pane_id):
    config = CustomChartPaneConfig(
        CustomChartConfig(
            kind=kind,
            source=CustomCommandSource("history", ("reader", "ccuv")),
            date_range=DateRange(date(2026, 10, 1), date(2026, 10, 8)),
            metric_id="tokens",
        )
    )
    pane = _new_pane(session.options, config, f"dashboard:pane:{pane_id}", session.runtime)
    assert isinstance(pane, TuiCustomPane)
    pane.pane_id = pane_id
    session.panes.append(pane)
    return pane


@pytest.mark.parametrize(
    ("initial_kind", "target_kind", "replaced"),
    [
        ("monitor", "ranking", True),
        ("monitor", "timeline", True),
        ("ranking", "monitor", True),
        ("ranking", "timeline", False),
        ("monitor", "monitor", False),
    ],
)
def test_custom_history_component_compatibility_and_undo_redo(
    session, monkeypatch, initial_kind, target_kind, replaced
):
    original = add_pane(session, initial_kind, 0)
    unaffected_monitor = add_pane(session, "monitor", 1)
    unaffected_historical = add_pane(session, "ranking", 2)
    unaffected_components = (unaffected_monitor.component, unaffected_historical.component)
    baseline = history.capture_dashboard_state(session)
    session.history = DashboardHistory(baseline)
    target = replace(
        baseline,
        panes=(
            replace(
                baseline.panes[0],
                config=replace(
                    baseline.panes[0].config,
                    chart=replace(original.component.candidate, kind=target_kind),
                ),
            ),
            *baseline.panes[1:],
        ),
    )
    shutdown = []
    real_shutdown = history._shutdown_pane

    def track_shutdown(pane):
        shutdown.append(pane)
        real_shutdown(pane)

    monkeypatch.setattr(history, "_shutdown_pane", track_shutdown)

    def assert_panes(kind):
        pane = session.panes[0]
        assert isinstance(pane, TuiCustomPane)
        assert pane.pane_id == original.pane_id
        assert pane.component.candidate.kind == kind
        expected = CustomMonitorComponent if kind == "monitor" else CustomHistoricalComponent
        assert isinstance(pane.component, expected)
        assert (pane.summary is None) == (kind == "monitor")
        assert (pane.attachment is not None) == (kind == "monitor")
        assert session.panes[1] is unaffected_monitor
        assert session.panes[2] is unaffected_historical
        assert unaffected_monitor.component is unaffected_components[0]
        assert unaffected_historical.component is unaffected_components[1]

    changed = history.record_mutation(
        session,
        ("preset", "load", "custom"),
        lambda: history.apply_dashboard_state(session, target),
    )
    assert changed == (initial_kind != target_kind)
    assert_panes(target_kind)
    assert (session.panes[0] is not original) == replaced
    assert shutdown == ([original] if replaced else [])
    if changed:
        session.history = session.history.undo()
        history.apply_dashboard_state(session, session.history.current)
        assert_panes(initial_kind)
        session.history = session.history.redo()
        history.apply_dashboard_state(session, session.history.current)
        assert_panes(target_kind)
        assert len(shutdown) == (3 if replaced else 0)
        assert all(pane.pane_id == 0 for pane in shutdown)
