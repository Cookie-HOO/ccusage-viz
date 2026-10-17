from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import nan

import pytest

from ccusage_viz.animation import animation_spec, animation_style_choices
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.configuration import apply_custom_probe_defaults
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
)
from ccusage_viz.dashboard_presets import (
    DashboardPresetDocument,
    DashboardPresetValidationError,
    empty_preset_launch,
    materialize_preset,
    preset_from_launch,
    validate_preset_name,
)
from ccusage_viz.options import (
    AnimationPaneConfig,
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    Filters,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    TimelineConfig,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
RANGE = DateRange(
    __import__("datetime").date(2026, 9, 1),
    __import__("datetime").date(2026, 10, 8),
    relative_until=True,
    period="30d",
    fixed_bounds=True,
    implicit_until=True,
)


def _installed_source(dataset_id: str = "reading") -> CustomCommandSource:
    return CustomCommandSource(dataset_id, ("ccuv-dataset", dataset_id), "installed")


def _launch(*, panes: tuple[object, ...] | None = None) -> DashboardLaunch:
    resolved_panes = panes or (
        ChartPaneConfig(
            TimelineConfig(
                "timeline",
                RANGE,
                Filters(agents=("claude",), projects=("ccusage-viz",)),
                ChartPresentation(style="linear"),
                by="model",
                top=4,
            )
        ),
    )
    return DashboardLaunch(
        ProcessConfig("custom-ccusage", 9.5, 2048, (("API_TOKEN", "secret"),)),
        DashboardHostConfig(
            grid="1x1" if len(resolved_panes) == 1 else "3x3",
            timezone="Asia/Shanghai",
            demo_size="small",
            demo_seed=3,
            refresh_interval=11,
            sampling_interval=7,
            header_interval=5,
            column_weights=(1,) if len(resolved_panes) == 1 else (2, 3, 4),
            row_weights=(1,) if len(resolved_panes) == 1 else (2, 3, 4),
        ),
        resolved_panes,  # type: ignore[arg-type]
        explicit=frozenset({"demo"}),
        launcher="test",
    )


@pytest.mark.parametrize("name", ("a", "weekly-review", "v2", "a0-9"))
def test_validate_preset_name_accepts_safe_identifiers(name: str) -> None:
    assert validate_preset_name(name) == name


@pytest.mark.parametrize(
    "name", ("", "1start", "Upper", "with_space", "with.dot", "with/slash", "中文")
)
def test_validate_preset_name_rejects_unsafe_identifiers(name: str) -> None:
    with pytest.raises(DashboardPresetValidationError):
        validate_preset_name(name)


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


def test_document_rejects_unknown_fields_nonfinite_values_and_duplicate_names() -> None:
    record = preset_from_launch("review", _launch(), now=NOW)
    wire = DashboardPresetDocument((record,)).to_wire()

    unknown = deepcopy(wire)
    unknown["presets"][0]["host"]["surprise"] = "no"
    with pytest.raises(DashboardPresetValidationError, match="unknown"):
        DashboardPresetDocument.parse(unknown)

    nonfinite = deepcopy(wire)
    nonfinite["presets"][0]["host"]["refresh_interval"] = nan
    with pytest.raises(DashboardPresetValidationError, match="finite"):
        DashboardPresetDocument.parse(nonfinite)

    duplicates = deepcopy(wire)
    duplicates["presets"].append(deepcopy(duplicates["presets"][0]))
    with pytest.raises(DashboardPresetValidationError, match="unique"):
        DashboardPresetDocument.parse(duplicates)


def test_document_save_overwrite_preserves_created_at_and_updates_timestamp() -> None:
    original = preset_from_launch("review", _launch(), now=NOW)
    replacement = preset_from_launch("review", _launch(), now=NOW + timedelta(days=1))
    saved = DashboardPresetDocument((original,)).with_saved(
        replacement, lambda: NOW + timedelta(days=2)
    )

    assert saved.presets[0].created_at == NOW
    assert saved.presets[0].updated_at == NOW + timedelta(days=2)
    assert saved.with_deleted("review").presets == ()


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
