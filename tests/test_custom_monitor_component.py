from datetime import UTC, datetime
from decimal import Decimal

from ccusage_viz.custom_models import LocalizedText, V2MetricValue, V2MonitorObservation
from ccusage_viz.custom_models import V2Dataset, V2HistoricalChartCapability, V2MetricCapabilities, V2MetricDescriptor, V2MonitorCapability, V2ProbeDescriptor, CustomUnit
from ccusage_viz.custom_monitor_component import CustomMonitorCompletion, CustomMonitorComponent, resolve_metric
from ccusage_viz.custom_protocol import V2MonitorResponse
from ccusage_viz.options import CustomChartConfig, CustomCommandSource, resolve_date_range


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


def test_accepts_one_source_owned_observation_without_locally_combining_it() -> None:
    component = CustomMonitorComponent(config())

    accepted = component.accept(
        CustomMonitorCompletion(0, config(), response()), accepted_at=datetime(2026, 10, 7, 14, 0, tzinfo=UTC)
    )

    assert accepted
    assert component.accepted_response is not None
    assert component.accepted_response.observation.total == Decimal("120")


def test_rejects_stale_or_wrong_metric_observations() -> None:
    component = CustomMonitorComponent(config())
    component.configure(config(metric_id="completed_requests"), data_affecting=True)

    assert not component.accept(
        CustomMonitorCompletion(0, config(), response()), accepted_at=datetime.now(UTC)
    )
    assert not component.accept(
        CustomMonitorCompletion(1, config(metric_id="completed_requests"), response("tokens")), accepted_at=datetime.now(UTC)
    )


def test_resolves_default_or_unique_metric_and_rejects_ambiguous_probe() -> None:
    text = LocalizedText("Tokens", "Token")
    metric = lambda identifier: V2MetricDescriptor(
        identifier, text, text, CustomUnit("token", text, "suffix", 0), "sum",
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, None, (), ())}), {},
    )
    defaulted = V2ProbeDescriptor("r", "1", V2Dataset(text, text), (metric("tokens"), metric("requests")), (), default_metric_id="requests")
    unique = V2ProbeDescriptor("r", "1", V2Dataset(text, text), (metric("tokens"),), ())
    ambiguous = V2ProbeDescriptor("r", "1", V2Dataset(text, text), (metric("tokens"), metric("requests")), ())
    omitted = CustomChartConfig("monitor", CustomCommandSource("router", ("router",)), resolve_date_range("timeline", period="14d", since=None, until=None))

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
        "total_notes", text, text, CustomUnit("note", text, "suffix", 0), "sum",
        V2MetricCapabilities((), (), {"ranking": V2HistoricalChartCapability(("day",), ("book",), (), ("all",))}),
        {}, "total",
    )
    descriptor = V2ProbeDescriptor("r", "1", V2Dataset(text, text), (metric,), ())
    omitted = CustomChartConfig("ranking", CustomCommandSource("weread", ("weread",)), resolve_date_range("ranking", period="all", since=None, until=None))

    resolved = resolve_metric(omitted, descriptor)

    assert resolved.metric_periods == ("all",)
