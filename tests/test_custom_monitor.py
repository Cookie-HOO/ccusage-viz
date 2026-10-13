from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

import ccusage_viz.custom_monitor as custom_monitor_host
from ccusage_viz.adjustment_timeout import AdjustmentTimeout
from ccusage_viz.custom_models import (
    CustomChartDefaults,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricValue,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor import _adjust, _metric_capability, _render
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
    apply_custom_monitor_defaults,
)
from ccusage_viz.custom_protocol import V2MonitorResponse, V2ProbeResponse
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    resolve_date_range,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom_monitor import render_custom_monitor
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
        "tokens",
        text,
        text,
        CustomUnit("token", text, "suffix", 0),
        "sum",
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
        {
            "monitor": CustomChartDefaults(
                None,
                None,
                None,
                style="ranking",
                window_seconds=21600,
                declared=frozenset({"style", "window"}),
            )
        },
    )
    return V2ProbeResponse(
        "router", V2ProbeDescriptor("router-1", "0.1.0", V2Dataset(text, text), (metric,), ())
    )


def test_custom_monitor_filter_reader_propagates_idle_timeout() -> None:
    clock = iter((0.0, 180.0, 180.0))
    timer = custom_monitor_host.AdjustmentIdleTimer(clock=lambda: next(clock))

    with pytest.raises(AdjustmentTimeout):
        custom_monitor_host._read_filter_editor_key(lambda _timeout: None, timer)


def test_render_source_owned_observation_and_interval_mismatch_notice() -> None:
    component = CustomMonitorComponent(config())
    response = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(
            datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
            Decimal("175"),
            (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("175")),),
        ),
    )
    component.accept(CustomMonitorCompletion(0, config(), response), accepted_at=datetime.now(UTC))

    rendered = _render(
        component,
        _metric_capability(probe(), config()),
        load_translator("en"),
        Terminal(80, 20, False, True),
        15,
    )

    assert "175" in rendered
    assert "Dataset 10s" in rendered


def test_standalone_adjustment_uses_dataset_monitor_style_and_window_contract() -> None:
    component = CustomMonitorComponent(config())
    chart, display_window = apply_custom_monitor_defaults(
        component.candidate, probe().descriptor.metrics[0]
    )
    component.configure(chart, data_affecting=False)
    component.set_metric(probe().descriptor.metrics[0])
    assert component.candidate.presentation.style == "ranking"
    assert display_window == 21600
    component.configure_display_window(display_window)

    assert _adjust(component, "s")
    assert component.candidate.presentation.style == "list"
    assert _adjust(component, "w")
    assert component.display_window_seconds == 43200
    assert "view 12h · data window 1m" in component.heading(language="en")

    component.configure(
        replace(
            component.candidate,
            presentation=replace(component.candidate.presentation, style="cumulative-bars"),
        ),
        data_affecting=False,
    )
    assert _adjust(component, "w")
    assert "yesterday · hourly" in component.heading(language="en")


def described_monitor_component(style: str | None = None) -> CustomMonitorComponent:
    """Build an accepted Custom Monitor component with a description and display."""
    presentation = ChartPresentation(style=style or "ranking", density="detailed")
    chart = replace(config(), group_by="model", presentation=presentation)
    component = CustomMonitorComponent(chart)
    component.accept(
        CustomMonitorCompletion(
            0,
            chart,
            V2MonitorResponse(
                "tokens",
                V2MonitorObservation(
                    datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
                    Decimal("11"),
                    (
                        V2MetricValue(
                            "fast",
                            LocalizedText("Fast", "快"),
                            Decimal("9"),
                            description=LocalizedText("Release validation", "发布验证"),
                            display=LocalizedText("90%", "90%"),
                        ),
                    ),
                ),
            ),
        ),
        accepted_at=datetime.now(UTC),
    )
    return component


def test_custom_monitor_ranking_renders_descriptions_only_at_complete_density() -> None:
    component = described_monitor_component()

    detailed_ctx = RenderContext(34, 20, load_translator("en"), color=False, ascii=True, density="detailed")
    normal_ctx = RenderContext(34, 20, load_translator("en"), color=False, ascii=True, density="normal")

    detailed = render_custom_monitor(component, detailed_ctx)
    normal = render_custom_monitor(component, normal_ctx)

    assert "Release validation" in detailed
    assert "Release validation" not in normal


def test_custom_monitor_ranking_renders_display_as_value_text() -> None:
    component = described_monitor_component()
    ctx = RenderContext(50, 20, load_translator("en"), color=False, ascii=True, density="detailed")

    rendered = render_custom_monitor(component, ctx)

    assert "90%" in rendered


def test_custom_monitor_list_renders_display_without_description() -> None:
    component = described_monitor_component(style="list")
    ctx = RenderContext(
        50, 20, load_translator("en"), color=False, ascii=True, density="detailed", style="list"
    )

    rendered = render_custom_monitor(component, ctx)

    assert "90%" in rendered
    assert "Release validation" not in rendered


@pytest.mark.parametrize("style", ("line", "bars"))
def test_custom_monitor_time_based_views_hide_presentation_metadata(style: str) -> None:
    component = described_monitor_component(style=style)
    ctx = RenderContext(
        50, 20, load_translator("en"), color=False, ascii=True, density="detailed", style=style
    )

    rendered = render_custom_monitor(component, ctx)

    assert "90%" not in rendered
    assert "Release validation" not in rendered


def test_custom_monitor_description_free_output_unchanged() -> None:
    """Regression: description-free responses render exactly as before."""
    component = CustomMonitorComponent(config())
    component.accept(
        CustomMonitorCompletion(0, config(), V2MonitorResponse(
            "tokens",
            V2MonitorObservation(
                datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
                Decimal("175"),
                (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("175")),),
            ),
        )),
        accepted_at=datetime.now(UTC),
    )

    rendered = _render(
        component,
        _metric_capability(probe(), config()),
        load_translator("en"),
        Terminal(80, 20, False, True),
        15,
    )

    assert "175" in rendered
    assert "Release validation" not in rendered
