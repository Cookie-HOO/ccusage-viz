from dataclasses import replace
from types import SimpleNamespace

from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomRankingBand,
    LocalizedText,
    V2RankingData,
    V2RankingGroup,
)
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartPaneConfig,
    DashboardHostConfig,
    DashboardLaunch,
    ProcessConfig,
)
from ccusage_viz.render.custom import render_custom_projection
from ccusage_viz.terminal import Terminal
from ccusage_viz.tui.models import TuiCustomPane
from ccusage_viz.tui.pane_lifecycle import _refresh_custom_ranking_values
from ccusage_viz.tui.rendering import _pane_render
from tests.ranking_scroll.helpers import context
from tests.test_custom_ranking_projection import config, entry, response


def test_real_pane_scalar_acceptance_preparation_and_grouped_viewport():
    chart = config(
        top=None,
        other="hide",
        partition_by="route",
        presentation=ChartPresentation(style="dot", density="compact", label_color_mode="band"),
    )
    component = CustomHistoricalComponent(chart)
    bands = (
        CustomRankingBand("full", LocalizedText("Full load", "满载")),
        CustomRankingBand("available", LocalizedText("Available", "可用")),
    )
    data = V2RankingData(
        groups=(
            V2RankingGroup(
                "one",
                LocalizedText("One", "一"),
                (
                    replace(entry("same", "19"), band_id="full"),
                    replace(entry("second", "9"), band_id="available"),
                ),
            ),
            V2RankingGroup(
                "two",
                LocalizedText("Two", "二"),
                (replace(entry("same", "8"), band_id="available"),),
            ),
        ),
        bands=bands,
    )
    assert component.apply_provider_result(SimpleNamespace(custom_response=response(data)))
    pane = TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("band-render"),
        ProcessConfig(),
        probe_complete=True,
    )
    _refresh_custom_ranking_values(pane)
    dashboard = DashboardLaunch(
        ProcessConfig(), DashboardHostConfig(), (CustomChartPaneConfig(chart),)
    )
    terminal = Terminal(100, 8, color=False, ascii=True)
    rendered = _pane_render(pane, load_translator("en"), terminal, dashboard=dashboard)
    lines = rendered.chart.splitlines()
    first = next(i for i, line in enumerate(lines) if "One" in line)
    assert "Full load" in lines[first + 1]
    viewport = pane.grouped_ranking_viewport
    assert viewport.active and viewport.scrollbar is not None
    assert viewport.scrollbar.total_rows == viewport.total_rows
    assert ("series", "one", "same") in viewport.by_id
    assert ("series", "two", "same") in viewport.by_id
    assert first in viewport.hits and first + 1 not in viewport.hits
    assert "Full load" not in viewport.clipboard_all_text()
    warm = _pane_render(pane, load_translator("en"), terminal, dashboard=dashboard)
    assert warm.chart == rendered.chart
    for width in (60, 100):
        _pane_render(
            pane, load_translator("en"), replace(terminal, width=width), dashboard=dashboard
        )
    assert (
        _pane_render(pane, load_translator("en"), terminal, dashboard=dashboard).chart
        == rendered.chart
    )
    assert component.model is not None
    direct = strip_ansi(
        render_custom_projection(
            component.model, replace(context(height=30), label_color_mode="band")
        )
    )
    direct_lines = direct.splitlines()
    first = next(i for i, line in enumerate(direct_lines) if "One" in line)
    assert "Full load" in direct_lines[first + 1]
