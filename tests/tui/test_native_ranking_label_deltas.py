from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from ccusage_viz.coverage import DateCoverage
from ccusage_viz.deltas import RefreshDeltas
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_labels import label_change, ranking_label
from ccusage_viz.tui import completion, queries
from ccusage_viz.tui.models import HistoricalOutcome, HistoricalPurpose, TuiChartPane
from ccusage_viz.tui.pane_lifecycle import _clear_changes, _refresh_deltas


def pane_for(component):
    return TuiChartPane(
        component,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("ranking"),
    )


def label_context(pane):
    return RenderContext(
        80,
        24,
        load_translator("en"),
        deltas=pane.deltas,
        label_deltas=pane.label_deltas,
        label_color_mode="direction",
    )


def test_new_native_entry_has_no_label_increase_but_keeps_arrow_delta():
    pane = pane_for(None)
    _refresh_deltas(pane, {"old": 10})
    _refresh_deltas(pane, {"old": 12, "new": 7})
    assert pane.deltas == {"old": 2, "new": 7}
    assert pane.label_deltas == {"old": 2}
    entry = RankingPresentationEntry("new", "New", 7)
    assert label_change(entry, label_context(pane)) is None
    assert ranking_label("New", entry, label_context(pane)) == "New"
    _refresh_deltas(pane, {"old": 12, "new": 8})
    assert pane.label_deltas == {"old": 0, "new": 1}
    _clear_changes(pane)
    assert pane.label_deltas == pane.previous_label_values == {}


def test_monitor_refresh_tracker_keeps_new_keys_out_of_label_channel():
    tracker = RefreshDeltas()
    tracker.accept({"old": 10})
    tracker.accept({"old": 9, "new": 5})
    assert tracker.current == {"old": -1, "new": 5}
    assert tracker.label_current == {"old": -1}
    tracker.clear()
    assert tracker.label_current == {}


def test_supplemental_completion_preserves_primary_label_direction(monkeypatch: pytest.MonkeyPatch):
    class Component:
        candidate = SimpleNamespace(chart=SimpleNamespace(kind="ranking"))
        accepted_at = None

        def accept(self, accepted):
            self.values = accepted
            return True

        def ranking_values(self):
            return self.values

        def ranking_keys(self):
            return tuple(self.values)

        def missing_comparison_coverage(self):
            return DateCoverage()

    monkeypatch.setattr(completion, "HistoricalChartComponent", Component)
    monkeypatch.setattr(queries, "start_pane", lambda *args, **kwargs: None)
    component = Component()
    pane = pane_for(component)
    session = SimpleNamespace(
        panes=[pane],
        header=SimpleNamespace(lifecycle=LifecycleOperation("header"), custom_summaries={}),
        manual_refresh_operations=set(),
        last_successful_update=None,
    )

    def collect(values, purpose=HistoricalPurpose.PRIMARY):
        future = Future()
        future.set_result(HistoricalOutcome(0, purpose, values))
        pane.lifecycle.request(
            LifecycleTrigger.MANUAL,
            generation=0,
            now=0,
            start=lambda operation: (future, lambda: None),
        )
        assert completion.collect(session)

    collect({"a": 10})
    collect({"a": 8})
    before = ranking_label("Alpha", RankingPresentationEntry("a", "Alpha", 8), label_context(pane))
    assert "\x1b[" in before
    collect({"a": 8}, HistoricalPurpose.SUPPLEMENTAL)
    assert pane.deltas == {"a": 0}  # Existing arrow behavior is intentionally unchanged.
    assert pane.label_deltas == {"a": -2}
    assert pane.previous_label_values == {"a": 8}
    assert (
        ranking_label("Alpha", RankingPresentationEntry("a", "Alpha", 8), label_context(pane))
        == before
    )
    # Supplemental values cannot advance the primary LABEL baseline either.
    collect({"a": 100}, HistoricalPurpose.SUPPLEMENTAL)
    collect({"a": 9})
    assert pane.label_deltas == {"a": 1}
