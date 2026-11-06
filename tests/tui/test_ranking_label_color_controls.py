"""Keyboard edits and history must not query or advance accepted baselines."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Protocol, cast

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomRankingBand, LocalizedText
from ccusage_viz.dashboard_history import DashboardHistory
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import LifecycleTrigger
from ccusage_viz.options import ChartPaneConfig, RankingConfig, adjust_custom_chart
from ccusage_viz.render.surfaces import dashboard_pane_surface
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui import history
from ccusage_viz.tui.adjustments import _pane_adjustment_state
from ccusage_viz.tui.custom_adjustments import _custom_pane_adjustment_state
from ccusage_viz.tui.custom_rendering import _render_custom_projection
from ccusage_viz.tui.models import TuiChartPane
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import _pane_render

from . import test_custom_interaction_audit as audit_helpers


class _WrappedAuditFixture(Protocol):
    def __wrapped__(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[Callable[..., SimpleNamespace]]: ...


@pytest.fixture
def audit(monkeypatch):
    yield from cast(_WrappedAuditFixture, audit_helpers.audit).__wrapped__(monkeypatch)


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
@pytest.mark.parametrize("bands", (False, True))
def test_custom_label_cycle_accepted_bands_and_no_query_history(audit, kind, bands):
    a = audit(kind)
    if bands:
        response = a.component.accepted_response
        a.component.accepted_response = replace(
            response,
            data=replace(
                response.data,
                bands=(CustomRankingBand("qualified", LocalizedText("Qualified", "晋级")),),
            ),
        )
    response = a.component.accepted_response
    baseline = a.component.accepted_config
    generation = a.component.generation
    modes = (
        ("increase", "decrease", "direction", "band", "none", "change")
        if bands
        else ("increase", "decrease", "direction", "none", "change")
    )
    for mode in modes:
        a.press("C")
        assert a.session.adjustment_page == "advanced"
        assert a.component.candidate.presentation.label_color_mode == mode
        assert load_translator("en").text(
            f"label.label_color_{mode}"
        ) in _custom_pane_adjustment_state(a.pane, "advanced", load_translator("en"))
    a.press("l")
    assert a.component.candidate.presentation.legend == "below-title"
    assert "Legend" not in _custom_pane_adjustment_state(a.pane, "advanced", load_translator("en"))
    assert a.component.accepted_response is response
    assert a.component.accepted_config.presentation.label_color_mode == "change"
    assert a.component.accepted_config.date_range == baseline.date_range
    assert a.component.generation == generation
    assert not a.submitted


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
@pytest.mark.parametrize("pending", ("refresh", "switch"))
def test_pending_custom_label_and_legend_edits_render_without_query_mismatch(
    audit, monkeypatch, kind, pending
):
    import ccusage_viz.tui.rendering as rendering

    a = audit(kind)
    response = a.component.accepted_response
    data = response.data
    if kind == "ranking":
        data = replace(data, series=tuple(replace(e, band_id="qualified") for e in data.series))
    else:
        data = replace(
            data,
            groups=tuple(
                replace(g, series=tuple(replace(e, band_id="qualified") for e in g.series))
                for g in data.groups
            ),
        )
    a.component.accepted_response = replace(
        response,
        data=replace(
            data, bands=(CustomRankingBand("qualified", LocalizedText("Qualified", "晋级")),)
        ),
    )
    a.component._reproject()
    accepted = a.component.accepted_config
    model = a.component.model
    response = a.component.accepted_response
    target = replace(
        a.component.candidate,
        metric_id="second",
        partition_by=None,
        group_by=None,
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=replace(
            a.component.candidate.presentation, label_color_mode="none", legend="hidden"
        ),
    )
    if pending == "switch":
        a.component.begin_metric_switch(target)
    else:
        a.component.configure(
            replace(a.component.candidate, date_range=target.date_range), data_affecting=True
        )
    a.pane.lifecycle.request(
        LifecycleTrigger.PERIODIC,
        generation=a.component.generation,
        now=0,
        start=lambda _operation: (SimpleNamespace(), lambda: None),
    )
    generation = a.component.generation
    configs = []
    original = rendering._render_custom_projection

    def capture(projection, config, *args, **kwargs):
        assert projection is model
        configs.append(config)
        return original(projection, config, *args, **kwargs)

    monkeypatch.setattr(rendering, "_render_custom_projection", capture)

    def render():
        result = _pane_render(
            a.pane,
            load_translator("en"),
            Terminal(100, 30, color=True, ascii=True),
            dashboard=a.session.options,
        ).chart
        assert configs[-1] == replace(accepted, presentation=a.component.candidate.presentation)
        assert "Alpha" in result
        assert "2026-09-01" not in result
        return result

    before = render()
    for _ in range(4):
        a.press("C")
    assert a.component.candidate.presentation.label_color_mode == "band"
    band = render()
    assert "Qualified" in band and band != before
    a.press("l")
    assert "Qualified" not in render()
    a.press("l")
    assert "Qualified" in render()
    assert a.component.accepted_config is accepted
    assert a.component.model is model
    assert a.component.accepted_response is response
    assert a.component.generation == generation
    assert not a.submitted
    if pending == "switch":
        assert a.component.switch_target_config == target


@pytest.mark.parametrize("kind", ("ranking", "partitioned-ranking"))
@pytest.mark.parametrize("pending", ("refresh", "switch"))
@pytest.mark.parametrize("source_visible", (True, False))
@pytest.mark.parametrize("style", ("dot", "list"))
def test_pending_percentage_edits_update_render_and_copy_without_advancing_baseline(
    audit, kind, pending, source_visible, style
):
    a = audit(kind)
    a.component.configure(
        replace(
            a.component.candidate,
            presentation=replace(a.component.candidate.presentation, style=style),
        ),
        data_affecting=False,
    )
    metric = a.descriptor.metrics[0]
    caps = metric.capabilities
    descriptor = replace(
        a.descriptor,
        metrics=(
            replace(
                metric,
                capabilities=replace(
                    caps,
                    charts={
                        "ranking": replace(caps.charts["ranking"], show_percentage=source_visible)
                    },
                ),
            ),
            *a.descriptor.metrics[1:],
        ),
    )
    audit_helpers._accept_historical(a.component, descriptor)
    accepted = a.component.accepted_config
    model = a.component.model
    response = a.component.accepted_response
    target = replace(
        a.component.candidate,
        metric_id="second",
        partition_by=None,
        group_by=None,
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2)),
    )
    if pending == "switch":
        a.component.begin_metric_switch(target)
    else:
        a.component.configure(
            replace(a.component.candidate, date_range=target.date_range), data_affecting=True
        )
    a.pane.lifecycle.request(
        LifecycleTrigger.PERIODIC,
        generation=a.component.generation,
        now=0,
        start=lambda _operation: (SimpleNamespace(), lambda: None),
    )
    generation = a.component.generation
    a.session.history = DashboardHistory(history.capture_dashboard_state(a.session))

    def assert_presentation(visible):
        output = a.render()
        assert "Alpha" in output and "2026-09-01" not in output
        assert ("%" in output) == visible
        viewport = a.pane.active_ranking_viewport
        assert viewport.percentage_visible == visible
        assert ("%" in viewport.clipboard_all_text()) == visible
        identity = (
            ("group", viewport.visible_groups[0][0].id)
            if kind == "partitioned-ranking"
            else next(iter(viewport.by_id))
        )
        assert ("%" in viewport.clipboard_text(identity)) == visible
        direct = _render_custom_projection(
            model,
            replace(accepted, presentation=a.component.candidate.presentation),
            load_translator("en"),
            Terminal(100, 30, color=False, ascii=True),
            accepted_at=a.component.accepted_at,
            interval=None,
            pending=False,
            refreshing=True,
            surface=dashboard_pane_surface("ranking"),
        ).chart
        assert ("%" in direct) == visible
        assert a.component.accepted_config is accepted
        assert a.component.model is model
        assert a.component.accepted_response is response
        assert a.component.generation == generation
        assert not a.submitted
        if pending == "switch":
            assert a.component.switch_target_config == target

    assert_presentation(source_visible)
    a.press("%")
    assert a.session.adjustment_page == "advanced"
    assert_presentation(not source_visible)
    a.press("u")
    assert a.component.candidate.presentation.show_percentage is None
    assert_presentation(source_visible)
    a.press("U")
    assert_presentation(not source_visible)


def test_saved_band_absence_survives_other_edits_and_can_leave(audit):
    a = audit("ranking")
    a.component.configure(
        replace(
            a.component.candidate,
            presentation=replace(a.component.candidate.presentation, label_color_mode="band"),
        ),
        data_affecting=False,
    )
    a.session.history = DashboardHistory(history.capture_dashboard_state(a.session))
    a.press("t")
    a.press("l")
    assert a.component.candidate.presentation.label_color_mode == "band"
    a.press("C")
    assert a.component.candidate.presentation.label_color_mode == "none"
    a.press("u")
    assert a.component.candidate.presentation.label_color_mode == "band"
    a.press("U")
    assert a.component.candidate.presentation.label_color_mode == "none"
    assert not a.submitted


def test_native_label_legend_history_does_not_fill_missing_comparisons(audit, monkeypatch):
    a = audit()
    chart = RankingConfig("ranking", DateRange(date(2026, 10, 2), date(2026, 10, 8)))
    pane = _new_pane(a.session.options, ChartPaneConfig(chart), "audit-native", None)
    assert isinstance(pane, TuiChartPane)
    pane.pane_id = 0
    a.session.panes = [pane]
    a.session.history = DashboardHistory(history.capture_dashboard_state(a.session))
    monkeypatch.setattr(
        type(pane.component),
        "missing_comparison_coverage",
        lambda self: type("Coverage", (), {"intervals": (1,)})(),
    )
    for mode in ("increase", "decrease", "direction", "none", "change"):
        a.press("C")
        assert pane.component.candidate.chart.presentation.label_color_mode == mode
        assert mode in _pane_adjustment_state(pane, "advanced", load_translator("en"))
    a.press("l")
    assert pane.component.candidate.chart.presentation.legend == "below-title"
    assert "Legend" not in _pane_adjustment_state(pane, "advanced", load_translator("en"))
    assert not a.submitted


def test_generic_custom_cycle_never_infers_band_from_config(audit):
    a = audit("ranking")
    chart = a.component.candidate
    modes = []
    for _ in range(5):
        chart = adjust_custom_chart(chart, "C")
        modes.append(chart.presentation.label_color_mode)
    assert modes == ["increase", "decrease", "direction", "none", "change"]
