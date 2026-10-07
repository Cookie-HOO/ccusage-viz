from datetime import UTC, datetime
from decimal import Decimal

from ccusage_viz.custom_models import LocalizedText, V2MetricValue, V2MonitorObservation
from ccusage_viz.custom_monitor_component import CustomMonitorCompletion, CustomMonitorComponent
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
