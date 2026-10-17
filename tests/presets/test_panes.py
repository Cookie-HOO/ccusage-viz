from __future__ import annotations

from copy import deepcopy

import pytest

from ccusage_viz.animation import animation_spec, animation_style_choices
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.options import (
    AnimationPaneConfig,
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    EmptyPaneConfig,
    MonitorConfig,
    RankingConfig,
    StackConfig,
)
from ccusage_viz.presets.document import DashboardPresetDocument, preset_from_launch
from ccusage_viz.presets.materialize import materialize_preset
from ccusage_viz.presets.values import DashboardPresetValidationError

from .helpers import NOW, RANGE, _installed_source, _launch


def test_round_trip_persists_safe_configuration_not_runtime_or_environment() -> None:
    record = preset_from_launch("weekly-review", _launch(), now=NOW)
    wire = DashboardPresetDocument((record,)).to_wire()

    assert wire["presets"][0]["process"] == {
        "ccusage_bin": "custom-ccusage",
        "query_timeout": 9.5,
        "output_limit": 2048,
    }
    restored = DashboardPresetDocument.parse(wire).presets[0].materialize()

    assert restored.process.environment == ()
    assert restored.process.ccusage_bin == "custom-ccusage"
    assert restored.host.timezone == "Asia/Shanghai"
    assert restored.explicit == frozenset()
    assert restored.launcher == "ccuv"
    assert restored.panes == record.panes

def test_round_trip_all_pane_kinds_and_trusted_command_configuration() -> None:
    animation_style = animation_style_choices("pane")[0]
    panes = (
        EmptyPaneConfig(),
        ChartPaneConfig(CalendarConfig("calendar", RANGE)),
        ChartPaneConfig(StackConfig("stack", RANGE, cache="combined", by="project", top=3)),
        ChartPaneConfig(RankingConfig("ranking", RANGE, by="model", top=2)),
        ChartPaneConfig(MonitorConfig("monitor", 3600, by="agent", top=3)),
        CustomChartPaneConfig(
            CustomChartConfig(
                "timeline",
                CustomCommandSource("reading", ("my-reader", "ccuv")),
                RANGE,
                filters=(("book", ("one", "two")),),
                group_by="book",
                top=5,
                metric_id="pages",
                metric_summary="total",
                metric_periods=("7d",),
                metric_titles=("Pages", "页数"),
            )
        ),
        AnimationPaneConfig(
            animation_spec(animation_style, target="pane"),
            OverlayConfig(command="date +%H:%M", offset_x=-5000, offset_y=9000),
        ),
    )
    record = preset_from_launch("all-panes", _launch(panes=panes), now=NOW)
    parsed = DashboardPresetDocument.parse(DashboardPresetDocument((record,)).to_wire()).presets[0]

    launch = materialize_preset(parsed, _installed_source)

    assert len(launch.panes) == len(panes)
    custom = launch.panes[5]
    assert isinstance(custom, CustomChartPaneConfig)
    assert custom.chart.source == CustomCommandSource("reading", ("my-reader", "ccuv"))
    animation = launch.panes[6]
    assert isinstance(animation, AnimationPaneConfig)
    assert animation.overlay.offset_x == -5000
    assert animation.overlay.offset_y == 9000
    assert animation.overlay.command == "date +%H:%M"

def test_round_trip_preserves_monitor_attachment_configuration() -> None:
    panes = (
        ChartPaneConfig(
            MonitorConfig("monitor", 3600, by="agent"),
            attachment_style="rain",
            attachment_theme="dracula",
        ),
        CustomChartPaneConfig(
            CustomChartConfig(
                "monitor",
                CustomCommandSource("reader", ("reader",)),
                RANGE,
                presentation=ChartPresentation(style="points"),
            ),
            attachment_style="snow",
            attachment_theme="nord",
        ),
    )
    record = preset_from_launch("monitors", _launch(panes=panes), now=NOW)
    restored = DashboardPresetDocument.parse(DashboardPresetDocument((record,)).to_wire()).presets

    assert restored[0].panes[0] == panes[0]
    custom = restored[0].panes[1]
    original_custom = panes[1]
    assert isinstance(custom, CustomChartPaneConfig)
    assert isinstance(original_custom, CustomChartPaneConfig)
    assert custom.attachment_style == original_custom.attachment_style
    assert custom.attachment_theme == original_custom.attachment_theme

def test_custom_ranking_item_spacing_round_trips_and_old_preset_defaults_compact() -> None:
    chart = CustomChartConfig(
        "ranking",
        _installed_source(),
        RANGE,
        group_by="real_model",
        metric_id="tokens",
        presentation=ChartPresentation(style="list"),
    )
    record = preset_from_launch(
        "spaced-ranking",
        _launch(panes=(CustomChartPaneConfig(chart, ranking_item_spacing="dashed"),)),
        now=NOW,
    )
    wire = DashboardPresetDocument((record,)).to_wire()
    custom_wire = wire["presets"][0]["panes"][0]
    assert custom_wire["ranking_item_spacing"] == "dashed"

    parsed = DashboardPresetDocument.parse(wire).presets[0].panes[0]
    assert isinstance(parsed, CustomChartPaneConfig)
    assert parsed.ranking_item_spacing == "dashed"

    old_wire = deepcopy(wire)
    del old_wire["presets"][0]["panes"][0]["ranking_item_spacing"]
    old = DashboardPresetDocument.parse(old_wire).presets[0].panes[0]
    assert isinstance(old, CustomChartPaneConfig)
    assert old.ranking_item_spacing == "compact"

def test_custom_ranking_item_spacing_rejects_nonranking_chart() -> None:
    chart = CustomChartConfig("timeline", _installed_source(), RANGE)
    with pytest.raises(ValueError, match="requires a ranking"):
        CustomChartPaneConfig(chart, ranking_item_spacing="line")

def test_custom_partition_round_trips_and_old_preset_remains_flat() -> None:
    chart = CustomChartConfig(
        "ranking",
        _installed_source(),
        RANGE,
        group_by="real_model",
        partition_by="logical_model",
        metric_id="tokens",
        presentation=ChartPresentation(style="list"),
    )
    record = preset_from_launch(
        "partitioned", _launch(panes=(CustomChartPaneConfig(chart),)), now=NOW
    )
    wire = DashboardPresetDocument((record,)).to_wire()
    custom_wire = wire["presets"][0]["panes"][0]
    assert custom_wire["partition_by"] == "logical_model"

    parsed = DashboardPresetDocument.parse(wire).presets[0].panes[0]
    assert isinstance(parsed, CustomChartPaneConfig)
    assert parsed.chart.partition_by == "logical_model"
    assert "partition_by" in parsed.chart.initial_explicit

    old_wire = deepcopy(wire)
    del old_wire["presets"][0]["panes"][0]["partition_by"]
    old = DashboardPresetDocument.parse(old_wire).presets[0].panes[0]
    assert isinstance(old, CustomChartPaneConfig)
    assert old.chart.partition_by is None

@pytest.mark.parametrize("chart_kind", ("timeline", "calendar", "stack", "monitor"))
def test_custom_partition_preset_rejects_non_ranking_chart_kinds(chart_kind: str) -> None:
    chart = CustomChartConfig(
        "ranking",
        _installed_source(),
        RANGE,
        group_by="real_model",
        partition_by="logical_model",
    )
    wire = DashboardPresetDocument(
        (
            preset_from_launch(
                "partitioned", _launch(panes=(CustomChartPaneConfig(chart),)), now=NOW
            ),
        )
    ).to_wire()
    wire["presets"][0]["panes"][0]["chart_kind"] = chart_kind

    with pytest.raises(DashboardPresetValidationError, match="only by ranking"):
        DashboardPresetDocument.parse(wire)

def test_custom_partition_preset_rejects_missing_or_equal_grouping() -> None:
    chart = CustomChartConfig(
        "ranking",
        _installed_source(),
        RANGE,
        group_by="real_model",
        partition_by="logical_model",
    )
    wire = DashboardPresetDocument(
        (
            preset_from_launch(
                "partitioned", _launch(panes=(CustomChartPaneConfig(chart),)), now=NOW
            ),
        )
    ).to_wire()

    missing_group = deepcopy(wire)
    missing_group["presets"][0]["panes"][0]["group_by"] = None
    with pytest.raises(DashboardPresetValidationError, match="requires"):
        DashboardPresetDocument.parse(missing_group)

    equal = deepcopy(wire)
    equal["presets"][0]["panes"][0]["group_by"] = "logical_model"
    with pytest.raises(DashboardPresetValidationError, match="must differ"):
        DashboardPresetDocument.parse(equal)
