



import pytest

from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import standalone_from_chart_pane
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPaneConfig, CustomChartPaneConfig


def test_custom_pane_fragment_preserves_normalized_filters_and_compact_density() -> None:
    parser = build_parser(load_translator("en"))

    dashboard = _to_options(
        parser.parse_args(
            [
                "dashboard",
                "--pane",
                'custom timeline --dataset reading --command "reader export" '
                "--filter category=fiction --filter category=literature",
            ]
        )
    )

    pane = dashboard.panes[0]
    assert isinstance(pane, CustomChartPaneConfig)
    assert pane.chart.filters == (("category", ("fiction", "literature")),)
    assert pane.chart.presentation.density == "compact"

def test_demo_seed_is_shared_by_dashboard_panes_and_varies_between_invocations() -> None:
    parser = build_parser(load_translator("en"))

    first = _to_options(parser.parse_args(["dashboard", "--demo", "small"]))
    second = _to_options(parser.parse_args(["dashboard", "--demo", "small"]))
    fixed = _to_options(parser.parse_args(["dashboard", "--demo", "small", "--demo-seed", "47"]))

    assert first.host.demo_seed is not None
    assert first.host.demo_seed != second.host.demo_seed
    assert fixed.host.demo_seed == 47
    assert all(
        standalone_from_chart_pane(fixed, pane).host.demo_seed == 47
        for pane in fixed.panes
        if isinstance(pane, ChartPaneConfig)
    )

@pytest.mark.parametrize(
    "fragment",
    [
        "timeline --interval 10",
        "timeline --interval=10",
        "timeline --inter=10",
        "timeline --no-watch",
        "timeline --no-wat",
        "timeline --watch",
        "timeline --ascii",
        "timeline --demo small",
        "timeline --lang zh",
        "timeline --ccusage-bin custom",
        "timeline --ccusage-b custom",
        "timeline --query-timeout 5",
        "timeline --query-time 5",
        "timeline --pane stack",
        "timeline --grid 1x1",
        "timeline --refresh-interval 5",
        "monitor --sampling-interval 5",
        "timeline --header-style compact",
        "timeline --header-summary month",
        "timeline --header-interval 5",
        "dashboard",
        "timeline 'unterminated",
    ],
)
def test_dashboard_pane_rejects_host_process_and_lifecycle_options(fragment: str) -> None:
    parser = build_parser(load_translator("en"))
    with pytest.raises(UsageError) as caught:
        _to_options(parser.parse_args(["dashboard", "--pane", fragment]))
    assert caught.value.key == "error.tui_panel"
