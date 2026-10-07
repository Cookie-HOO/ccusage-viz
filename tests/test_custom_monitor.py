from datetime import UTC, datetime
from decimal import Decimal

from ccusage_viz.custom_models import (
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2MetricValue,
    V2MonitorObservation,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor import _metric_capability, _render
from ccusage_viz.custom_monitor_component import CustomMonitorCompletion, CustomMonitorComponent
from ccusage_viz.custom_protocol import V2MonitorResponse, V2ProbeResponse
from ccusage_viz.custom_models import CustomUnit
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomChartConfig, CustomCommandSource, resolve_date_range
from ccusage_viz.terminal import Terminal


def config() -> CustomChartConfig:
    return CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        resolve_date_range("timeline", period="14d", since=None, until=None),
        metric_id="tokens",
    )


def probe() -> V2ProbeResponse:
    text = LocalizedText("Tokens", "Token")
    metric = V2MetricDescriptor(
        "tokens", text, text, CustomUnit("token", text, "suffix", 0), "sum",
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}), {},
    )
    return V2ProbeResponse("router", V2ProbeDescriptor("router-1", "0.1.0", V2Dataset(text, text), (metric,), ()))


def test_render_source_owned_observation_and_interval_mismatch_notice() -> None:
    component = CustomMonitorComponent(config())
    response = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(
            datetime(2026, 10, 8, 12, 0, tzinfo=UTC), Decimal("175"),
            (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("175")),),
        ),
    )
    component.accept(CustomMonitorCompletion(0, config(), response), accepted_at=datetime.now(UTC))

    rendered = _render(component, _metric_capability(probe(), config()), load_translator("en"), Terminal(80, 20, False, True), 15)

    assert "175" in rendered
    assert "Dataset 10s" in rendered
