from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from ccusage_viz.configuration import apply_custom_probe_defaults
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
)
from ccusage_viz.options import (
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    EmptyPaneConfig,
)
from ccusage_viz.presets.document import DashboardPresetDocument, preset_from_launch
from ccusage_viz.presets.materialize import empty_preset_launch, materialize_preset
from ccusage_viz.presets.values import DashboardPresetValidationError

from .helpers import NOW, RANGE, _installed_source, _launch


def test_custom_ranking_timestamp_preset_refreshes_relative_and_preserves_fixed() -> None:
    relative = TimestampRange(NOW - timedelta(minutes=10), NOW, relative_until=True, period="10m")
    fixed = TimestampRange(NOW - timedelta(minutes=5), NOW, fixed_bounds=True)
    panes = (
        CustomChartPaneConfig(
            CustomChartConfig(
                "ranking",
                _installed_source("a"),
                relative,
                presentation=ChartPresentation(style="dot"),
                metric_id="tokens",
            )
        ),
        CustomChartPaneConfig(
            CustomChartConfig(
                "ranking",
                _installed_source("b"),
                fixed,
                presentation=ChartPresentation(style="dot"),
                metric_id="tokens",
            )
        ),
    )
    record = preset_from_launch("timestamps", _launch(panes=panes), now=NOW)
    parsed = DashboardPresetDocument.parse(DashboardPresetDocument((record,)).to_wire()).presets[0]
    fresh = NOW + timedelta(hours=2)

    restored = materialize_preset(parsed, _installed_source, now=fresh)

    relative_chart = restored.panes[0]
    fixed_chart = restored.panes[1]
    assert isinstance(relative_chart, CustomChartPaneConfig)
    assert isinstance(fixed_chart, CustomChartPaneConfig)
    assert relative_chart.chart.date_range.end_at == fresh  # type: ignore[union-attr]
    assert fixed_chart.chart.date_range == fixed

def test_loaded_custom_preset_preserves_its_configuration_over_probe_defaults() -> None:
    saved_chart = CustomChartConfig(
        "ranking",
        _installed_source(),
        RANGE,
        group_by="book",
        top=3,
        presentation=ChartPresentation(theme="nord", style="dot"),
    )
    record = preset_from_launch(
        "reading-ranking", _launch(panes=(CustomChartPaneConfig(saved_chart),)), now=NOW
    )
    parsed = DashboardPresetDocument.parse(DashboardPresetDocument((record,)).to_wire()).presets[0]
    loaded = materialize_preset(parsed, _installed_source)
    pane = loaded.panes[0]
    assert isinstance(pane, CustomChartPaneConfig)

    descriptor = CustomProbeDescriptor(
        1,
        "1.0",
        CustomDataset("Reading", "", "books"),
        CustomCapabilities(
            ("book",),
            (),
            {"ranking": CustomChartCapability((), ("book",), ())},
        ),
        {
            "ranking": CustomChartDefaults(
                "7d",
                "book",
                10,
                style="bars",
                theme="classic",
                declared=frozenset({"period", "group_by", "top", "style", "theme"}),
            )
        },
        (),
    )

    assert apply_custom_probe_defaults(pane.chart, descriptor, timezone="UTC") == pane.chart

def test_installed_custom_sources_are_resolved_only_when_materialized() -> None:
    record = preset_from_launch(
        "dataset",
        _launch(
            panes=(
                CustomChartPaneConfig(CustomChartConfig("timeline", _installed_source(), RANGE)),
            )
        ),
        now=NOW,
    )
    parsed = DashboardPresetDocument.parse(DashboardPresetDocument((record,)).to_wire()).presets[0]

    with pytest.raises(DashboardPresetValidationError, match="unsafe source"):
        materialize_preset(parsed, lambda dataset_id: CustomCommandSource(dataset_id, ("temp",)))

    restored = materialize_preset(parsed, _installed_source).panes[0]
    assert isinstance(restored, CustomChartPaneConfig)
    assert restored.chart.initial_explicit
    original = record.panes[0]
    assert isinstance(original, CustomChartPaneConfig)
    assert replace(restored.chart, initial_explicit=frozenset()) == original.chart

def test_named_empty_preserves_launch_configuration_and_replaces_only_panes() -> None:
    launch = _launch(panes=(EmptyPaneConfig(), ChartPaneConfig(CalendarConfig("calendar", RANGE))))
    emptied = empty_preset_launch(launch)

    assert emptied.process is launch.process
    assert emptied.host is launch.host
    assert len(emptied.panes) == 2
    assert all(isinstance(pane, EmptyPaneConfig) for pane in emptied.panes)
    assert launch.panes[1] != emptied.panes[1]
