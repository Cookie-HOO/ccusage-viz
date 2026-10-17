from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.models as tui_models
from ccusage_viz.chart_models import DistributionCoverage
from ccusage_viz.custom_models import (
    CustomDimension,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricValue,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.custom_monitor_defaults import resolve_metric
from ccusage_viz.custom_monitor_models import CustomMonitorCompletion, custom_monitor_styles
from ccusage_viz.custom_protocol.responses import V2MonitorResponse
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
    ProcessConfig,
    resolve_date_range,
)


def config(*, metric_id: str = "tokens") -> CustomChartConfig:
    return CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        resolve_date_range("timeline", period="14d", since=None, until=None),
        metric_id=metric_id,
    )


def response(metric_id: str = "tokens") -> V2MonitorResponse:
    return V2MonitorResponse(
        metric_id,
        V2MonitorObservation(
            datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
            Decimal("120"),
            (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("120")),),
        ),
    )


def test_monitor_metric_switch_commits_only_after_target_observation() -> None:
    component = CustomMonitorComponent(config(metric_id="stars"))
    assert component.accept(
        CustomMonitorCompletion(0, config(metric_id="stars"), response("stars")),
        accepted_at=datetime.now(UTC),
    )
    old_history = component.history

    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "updated_days"
    assert component.history is old_history
    assert component.accept(
        CustomMonitorCompletion(1, config(metric_id="updated_days"), response("updated_days")),
        accepted_at=datetime.now(UTC),
    )
    assert component.candidate.metric_id == "updated_days"
    assert [item.observation.total for item in component.history] == [Decimal("120")]
    assert component.history is not old_history


def test_monitor_metric_switch_pending_state_retains_accepted_metric_help() -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str, title: str, description: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(title, title),
            LocalizedText(description, description),
            unit,
            "sum",
            V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
            {},
        )

    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (
            metric("stars", "Stars", "Accepted stars help"),
            metric("growth", "Growth", "Pending growth help"),
        ),
        (),
    )
    component = CustomMonitorComponent(config(metric_id="stars"))
    assert component.accept(
        CustomMonitorCompletion(
            0,
            config(metric_id="stars"),
            V2MonitorResponse(
                "stars",
                response("stars").observation,
                descriptor=descriptor,
            ),
        ),
        accepted_at=datetime.now(UTC),
    )

    component.begin_metric_switch(config(metric_id="growth"))

    assert component.pending
    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "growth"
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("monitor-metric-help"),
        ProcessConfig(),
    )
    assert tui_custom_adjustments._accepted_custom_metric_help_node(
        pane, load_translator("en")
    ) == ("CURRENT METRIC", (("Stars", (("Accepted stars help", ()),)),))

    assert component.accept(
        CustomMonitorCompletion(1, config(metric_id="growth"), response("growth")),
        accepted_at=datetime.now(UTC),
    )
    assert component.candidate.metric_id == "growth"
    assert component.v2_descriptor is None
    assert (
        tui_custom_adjustments._accepted_custom_metric_help_node(pane, load_translator("en"))
        is None
    )


def test_monitor_metric_switch_failure_retains_old_sampling_state() -> None:
    component = CustomMonitorComponent(config(metric_id="stars"))
    assert component.accept(
        CustomMonitorCompletion(0, config(metric_id="stars"), response("stars")),
        accepted_at=datetime.now(UTC),
    )
    old_history = component.history

    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.fail(RuntimeError("unavailable"), generation=1)
    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "stars"
    assert component.history is old_history
    assert component.error is None


def test_accepts_one_source_owned_observation_without_locally_combining_it() -> None:
    component = CustomMonitorComponent(config())

    accepted = component.accept(
        CustomMonitorCompletion(0, config(), response()),
        accepted_at=datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )

    assert accepted
    assert component.accepted_response is not None
    assert component.accepted_response.observation.total == Decimal("120")


def test_retains_observations_for_window_timeline_and_marks_missing_distribution_intervals() -> (
    None
):
    component = CustomMonitorComponent(config())
    component.set_capability(
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())})
    )
    first = response()
    second = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(
            datetime(2026, 10, 7, 14, 2, tzinfo=UTC),
            Decimal("140"),
            (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("140")),),
        ),
    )

    for response_value in (first, second):
        assert component.accept(
            CustomMonitorCompletion(0, config(), response_value), accepted_at=datetime.now(UTC)
        )

    timeline = component.timeline_model(metric_title="TPM", language="en")
    distribution = component.distribution_model(metric_title="TPM")

    assert len(timeline.observed_at) == 61
    assert timeline.observed_series[0].values[-3:] == (120.0, None, 140.0)
    assert len(distribution.buckets) == 24
    assert distribution.buckets[14].coverage is DistributionCoverage.PARTIAL
    assert distribution.buckets[14].values == {"total": 140.0}


def test_display_window_reprojects_observations_without_changing_dataset_query() -> None:
    component = CustomMonitorComponent(config())
    component.set_capability(
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())})
    )
    for minute in range(3):
        observed = V2MonitorResponse(
            "tokens",
            V2MonitorObservation(
                datetime(2026, 10, 7, 14, minute, tzinfo=UTC),
                Decimal(str(120 + minute)),
                (),
            ),
        )
        assert component.accept(
            CustomMonitorCompletion(0, config(), observed), accepted_at=datetime.now(UTC)
        )

    component.configure_display_window(60)

    assert [
        value.strftime("%H:%M")
        for value in component.timeline_model(metric_title="TPM", language="en").observed_at
    ] == ["14:01", "14:02"]
    assert component.candidate == config()


def test_cumulative_bars_cover_the_display_horizon_in_the_host_timezone() -> None:
    component = CustomMonitorComponent(config())
    component.set_capability(
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())})
    )
    component.configure_display_window(300)
    component.configure_display_timezone(ZoneInfo("Asia/Shanghai"))
    for minute in (56, 57, 58, 59, 60):
        observed = V2MonitorResponse(
            "tokens",
            V2MonitorObservation(
                datetime(2026, 10, 7, 9 if minute < 60 else 10, minute % 60, tzinfo=UTC),
                Decimal("120"),
                (),
            ),
        )
        assert component.accept(
            CustomMonitorCompletion(0, config(), observed), accepted_at=datetime.now(UTC)
        )

    distribution = component.distribution_model()

    assert len(distribution.buckets) == 24
    assert distribution.buckets[17].coverage is DistributionCoverage.PARTIAL
    assert distribution.buckets[17].ended_at.strftime("%H:%M") == "18:00"


def _accepted_metric_component(*, style: str) -> CustomMonitorComponent:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        resolve_date_range("timeline", period="14d", since=None, until=None),
        metric_id="tokens",
        group_by="model",
        presentation=replace(config().presentation, style=style),
    )
    metric = V2MetricDescriptor(
        "tokens",
        LocalizedText("Requests", "请求数"),
        LocalizedText("Requests", "请求数"),
        CustomUnit("request", LocalizedText("requests", "请求"), "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (CustomDimension("model", LocalizedText("Model", "模型")),),
            (),
            {"monitor": V2MonitorCapability(90, 10, ("model",), ())},
        ),
        {},
    )
    component = CustomMonitorComponent(chart)
    component.set_metric(metric)
    return component


@pytest.mark.parametrize("style", ("ranking", "ranking-dot", "list", "line"))
def test_custom_monitor_heading_metadata_uses_metric_dimension_and_capability_window(
    style: str,
) -> None:
    component = _accepted_metric_component(style=style)
    component.configure_display_window(43_200)

    english = component.heading_metadata(language="en")
    chinese = component.heading_metadata(language="zh")

    assert (english.metric, english.dimension, english.window_seconds) == (
        "Requests",
        "Model",
        90,
    )
    assert (chinese.metric, chinese.dimension, chinese.window_seconds) == (
        "请求数",
        "模型",
        90,
    )


def test_custom_monitor_heading_metadata_rejects_unresolved_title_without_id_fallback() -> None:
    component = CustomMonitorComponent(config())
    component.set_capability(
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(90, 10, (), ())})
    )

    with pytest.raises(
        ValueError,
        match="requires presentation.title or metric_titles",
    ):
        component.heading_metadata(language="en")


def test_value_metrics_exclude_cumulative_bars() -> None:
    assert custom_monitor_styles("sum") == (
        "bars",
        "line",
        "step",
        "points",
        "line-points",
        "ranking",
        "ranking-dot",
        "list",
        "cumulative-bars",
    )
    assert custom_monitor_styles("value") == (
        "bars",
        "line",
        "step",
        "points",
        "line-points",
        "ranking",
        "ranking-dot",
        "list",
    )
    assert "bars" not in custom_monitor_styles("sum", "model")


def test_value_metric_normalizes_restored_cumulative_style() -> None:
    component = CustomMonitorComponent(
        replace(config(), presentation=replace(config().presentation, style="cumulative-bars"))
    )
    metric = V2MetricDescriptor(
        "tokens",
        LocalizedText("Latency", "延迟"),
        LocalizedText("Latency", "延迟"),
        CustomUnit("ms", LocalizedText("milliseconds", "毫秒"), "suffix", 0),
        "value",
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
        {},
    )

    component.set_metric(metric)

    assert component.candidate.presentation.style == "ranking"


def test_top_n_uses_other_only_for_sum_metrics() -> None:
    chart = replace(config(), group_by="model", top=1)
    component = CustomMonitorComponent(chart)
    observation = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(
            datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
            Decimal("100"),
            (
                V2MetricValue("a", LocalizedText("Alpha", "阿尔法"), Decimal("60")),
                V2MetricValue("b", LocalizedText("Beta", "贝塔"), Decimal("40")),
            ),
        ),
    )
    assert component.accept(
        CustomMonitorCompletion(0, chart, observation), accepted_at=datetime.now(UTC)
    )

    assert [(entry.key, entry.value) for entry in component.ranking().entries] == [
        ("a", Decimal("60")),
        ("Other", Decimal("40")),
    ]
    component.aggregation = "value"
    assert [(entry.key, entry.value) for entry in component.ranking().entries] == [
        ("a", Decimal("60")),
    ]


def test_pending_reconfiguration_projects_accepted_monitor_facts_consistently() -> None:
    accepted = replace(config(), group_by="model", metric_titles=("Tokens", "令牌"))
    component = CustomMonitorComponent(accepted)
    component.set_capability(
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, ("model",), ())})
    )
    observation = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(
            datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
            Decimal("100"),
            (
                V2MetricValue("a", LocalizedText("Alpha", "阿尔法"), Decimal("60")),
                V2MetricValue("b", LocalizedText("Beta", "贝塔"), Decimal("40")),
            ),
        ),
    )
    assert component.accept(
        CustomMonitorCompletion(0, accepted, observation), accepted_at=datetime.now(UTC)
    )

    component.configure(
        replace(
            accepted,
            group_by=None,
            top=1,
            other="hide",
            presentation=replace(accepted.presentation, style="line"),
        ),
        data_affecting=True,
    )

    assert component.pending
    assert [(entry.key, entry.value) for entry in component.ranking().entries] == [
        ("a", Decimal("60")),
        ("b", Decimal("40")),
    ]
    assert component.heading_metadata(language="en").dimension == "model"


def test_rejects_stale_or_wrong_metric_observations() -> None:
    component = CustomMonitorComponent(config())
    component.configure(config(metric_id="completed_requests"), data_affecting=True)

    assert not component.accept(
        CustomMonitorCompletion(0, config(), response()), accepted_at=datetime.now(UTC)
    )
    assert not component.accept(
        CustomMonitorCompletion(1, config(metric_id="completed_requests"), response("tokens")),
        accepted_at=datetime.now(UTC),
    )


def test_resolves_default_or_unique_metric_and_rejects_ambiguous_probe() -> None:
    text = LocalizedText("Tokens", "Token")

    def metric(identifier: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            text,
            text,
            CustomUnit("token", text, "suffix", 0),
            "sum",
            V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, None, (), ())}),
            {},
        )

    defaulted = V2ProbeDescriptor(
        "r",
        "1",
        V2Dataset(text, text),
        (metric("tokens"), metric("requests")),
        (),
        default_metric_id="requests",
    )
    unique = V2ProbeDescriptor("r", "1", V2Dataset(text, text), (metric("tokens"),), ())
    ambiguous = V2ProbeDescriptor(
        "r", "1", V2Dataset(text, text), (metric("tokens"), metric("requests")), ()
    )
    omitted = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("timeline", period="14d", since=None, until=None),
    )

    assert resolve_metric(omitted, defaulted).metric_id == "requests"
    assert resolve_metric(omitted, unique).metric_id == "tokens"
    try:
        resolve_metric(omitted, ambiguous)
    except ValueError as error:
        assert "--metric" in str(error)
    else:
        raise AssertionError("ambiguous metric resolution was accepted")


def test_resolved_metric_carries_declared_ranking_periods() -> None:
    text = LocalizedText("Notes", "笔记")
    metric = V2MetricDescriptor(
        "total_notes",
        text,
        text,
        CustomUnit("note", text, "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (), (), {"ranking": V2HistoricalChartCapability(("day",), ("book",), (), ("all",))}
        ),
        {},
        "total",
    )
    descriptor = V2ProbeDescriptor("r", "1", V2Dataset(text, text), (metric,), ())
    omitted = CustomChartConfig(
        "ranking",
        CustomCommandSource("weread", ("weread",)),
        resolve_date_range("ranking", period="all", since=None, until=None),
    )

    resolved = resolve_metric(omitted, descriptor)

    assert resolved.metric_periods == ("all",)


def test_custom_monitor_ranking_retains_localized_group_descriptions_and_displays() -> None:
    chart = replace(config(), group_by="model")
    component = CustomMonitorComponent(chart)
    component.accept(
        CustomMonitorCompletion(
            0,
            chart,
            V2MonitorResponse(
                "tokens",
                V2MonitorObservation(
                    datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
                    Decimal("11"),
                    (
                        V2MetricValue(
                            "slow",
                            LocalizedText("Slow", "慢"),
                            Decimal("2"),
                            description=LocalizedText("slow help", "慢说明"),
                            display=LocalizedText("20%", "20%"),
                        ),
                        V2MetricValue(
                            "fast",
                            LocalizedText("Fast", "快"),
                            Decimal("9"),
                            description=LocalizedText("fast help", "快说明"),
                            display=LocalizedText("90%", "90%"),
                        ),
                    ),
                ),
            ),
        ),
        accepted_at=datetime.now(UTC),
    )

    english = component.ranking_model(language="en").observed_entries
    chinese = component.ranking_model(language="zh").observed_entries

    assert [(entry.key, entry.description, entry.display) for entry in english] == [
        ("fast", "fast help", "90%"),
        ("slow", "slow help", "20%"),
    ]
    assert [(entry.key, entry.description, entry.display) for entry in chinese] == [
        ("fast", "快说明", "90%"),
        ("slow", "慢说明", "20%"),
    ]


def test_custom_monitor_ungrouped_ranking_has_no_description_or_display() -> None:
    component = CustomMonitorComponent(config())
    component.accept(
        CustomMonitorCompletion(
            0,
            config(),
            V2MonitorResponse(
                "tokens",
                V2MonitorObservation(
                    datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
                    Decimal("175"),
                    (),
                ),
            ),
        ),
        accepted_at=datetime.now(UTC),
    )

    entries = component.ranking_model(language="en").observed_entries
    assert len(entries) == 1
    assert entries[0].key == "total"
    assert entries[0].description is None
    assert entries[0].display is None


def test_custom_monitor_ranking_omits_description_and_display_when_not_provided() -> None:
    chart = replace(config(), group_by="model")
    component = CustomMonitorComponent(chart)
    component.accept(
        CustomMonitorCompletion(
            0,
            chart,
            V2MonitorResponse(
                "tokens",
                V2MonitorObservation(
                    datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
                    Decimal("175"),
                    (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("175")),),
                ),
            ),
        ),
        accepted_at=datetime.now(UTC),
    )

    entries = component.ranking_model(language="en").observed_entries
    assert len(entries) == 1
    assert entries[0].key == "terra"
    assert entries[0].description is None
    assert entries[0].display is None
