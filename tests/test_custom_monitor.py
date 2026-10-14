from concurrent.futures import Future
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
from ccusage_viz.errors import SchemaError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    resolve_date_range,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom_monitor import render_custom_monitor
from ccusage_viz.terminal import Frame, Terminal


def config() -> CustomChartConfig:
    return CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        resolve_date_range("timeline", period="14d", since=None, until=None),
        metric_id="tokens",
        metric_titles=("Tokens", "Token"),
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


def test_standalone_initial_probe_failure_renders_localized_error_before_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = StandaloneLaunch(
        ProcessConfig(query_timeout=1),
        StandaloneHostConfig(ascii=True, interval=15, timezone="UTC"),
        config(),
    )
    painted: list[str] = []

    class Handle:
        def result(self) -> object:
            raise SchemaError("error.schema", path="$.metrics", reason="expected array")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, _intent: object) -> Handle:
            return Handle()

        def cancel(self) -> None:
            pass

    class ImmediateExecutor:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def submit(self, function: Any) -> Future[object]:
            future: Future[object] = Future()
            try:
                future.set_result(function())
            except BaseException as error:
                future.set_exception(error)
            return future

        def shutdown(self, **_kwargs: object) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: Frame, **_kwargs: object) -> None:
            painted.append("\n".join(frame.rows))

        def finish(self) -> None:
            pass

    monkeypatch.setattr(custom_monitor_host, "build_query_runtime", Runtime)
    monkeypatch.setattr(custom_monitor_host, "ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(custom_monitor_host, "FramePainter", Screen)
    monkeypatch.setattr(custom_monitor_host, "input_mode", nullcontext)
    monkeypatch.setattr(custom_monitor_host, "read_key", lambda _timeout: "\x03")
    monkeypatch.setattr(
        custom_monitor_host,
        "inspect_terminal",
        lambda *_args, **_kwargs: Terminal(80, 20, False, True),
    )

    assert custom_monitor_host.run_custom_monitor(launch, load_translator("zh")) == 0
    assert len(painted) == 1
    assert "ccusage 在 $.metrics 返回了不兼容的数据：expected array" in painted[0]
    assert load_translator("zh").text("status.querying") not in painted[0]
    assert "Tokens" not in painted[0]
    assert "window" not in painted[0]


def test_render_source_owned_observation_and_interval_mismatch_notice() -> None:
    component = CustomMonitorComponent(config())
    component.set_capability(probe().descriptor.metrics[0].capabilities)
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
    assert component.candidate.presentation.style == "ranking-dot"
    assert _adjust(component, "s")
    assert component.candidate.presentation.style == "list"
    assert _adjust(component, "w")
    assert component.display_window_seconds == 43200
    metadata = component.heading_metadata(language="en")
    assert (metadata.metric, metadata.dimension, metadata.window_seconds) == ("Tokens", None, 60)

    component.configure(
        replace(
            component.candidate,
            presentation=replace(component.candidate.presentation, style="cumulative-bars"),
        ),
        data_affecting=False,
    )
    assert _adjust(component, "w")
    rendered = render_custom_monitor(
        component,
        RenderContext(80, 20, load_translator("en"), color=False, style="cumulative-bars"),
    )
    assert "Tokens · Cumulative bars · 1m window" in rendered.splitlines()[0]
    assert "yesterday" not in rendered.splitlines()[0]
    assert "hourly" not in rendered.splitlines()[0]


def described_monitor_component(style: str | None = None) -> CustomMonitorComponent:
    """Build an accepted Custom Monitor component with a description and display."""
    presentation = ChartPresentation(style=style or "ranking", density="detailed")
    chart = replace(
        config(),
        metric_titles=("Requests", "请求数"),
        group_by="model",
        presentation=presentation,
    )
    component = CustomMonitorComponent(chart)
    component.set_capability(
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(90, 10, ("model",), ())})
    )
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

    detailed_ctx = RenderContext(
        34, 20, load_translator("en"), color=False, ascii=True, density="detailed"
    )
    normal_ctx = RenderContext(
        34, 20, load_translator("en"), color=False, ascii=True, density="normal"
    )

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


@pytest.mark.parametrize(
    ("style", "view"),
    (
        ("line", "Trend"),
        ("ranking", "Ranking"),
        ("list", "List"),
        ("cumulative-bars", "Cumulative bars"),
    ),
)
def test_custom_monitor_style_families_use_canonical_accepted_heading(
    style: str, view: str
) -> None:
    component = described_monitor_component(style=style)
    component.configure_display_window(43_200)
    context = RenderContext(80, 20, load_translator("en"), color=False, ascii=True, style=style)

    heading = render_custom_monitor(component, context).splitlines()[0].strip()

    assert heading == f"Requests · {view} · by Model · 90s window"
    for excluded in ("view", "data window", "12h", "router-dataset", "tokens", "token"):
        assert excluded not in heading.lower()


@pytest.mark.parametrize(
    ("style", "view"),
    (
        ("line", "Trend"),
        ("ranking", "Ranking"),
        ("list", "List"),
        ("cumulative-bars", "Cumulative bars"),
    ),
)
@pytest.mark.parametrize(
    ("error", "detail", "querying"),
    ((None, "querying", True), (RuntimeError("failed"), "failed", False)),
)
def test_standalone_custom_monitor_transient_states_use_canonical_heading(
    style: str, view: str, error: BaseException | None, detail: str, querying: bool
) -> None:
    chart = replace(
        config(),
        metric_titles=("Requests", "请求数"),
        group_by="model",
        presentation=ChartPresentation(style=style),
    )
    component = CustomMonitorComponent(chart)
    capability = V2MonitorCapability(90, 10, ("model",), ())
    component.set_capability(V2MetricCapabilities((), (), {"monitor": capability}))
    if error is not None:
        component.fail(error, generation=component.generation)

    rendered = _render(
        component,
        capability,
        load_translator("en"),
        Terminal(80, 20, False, True),
        15,
    )
    heading, rendered_detail = rendered.splitlines()
    expected = f"Requests · {view} · by Model · 90s window"
    if querying:
        expected += " · querying"

    assert heading.strip() == expected
    assert rendered_detail == detail
    assert all(display_width(line) <= 80 for line in rendered.splitlines())
    for excluded in ("view", "data window", "router-dataset", "tokens", "token"):
        assert excluded not in heading.lower()


def test_standalone_pending_reconfiguration_uses_accepted_monitor_semantics() -> None:
    component = described_monitor_component(style="ranking")
    component.configure(
        replace(
            component.candidate,
            group_by=None,
            top=1,
            presentation=replace(component.candidate.presentation, style="line"),
        ),
        data_affecting=True,
    )

    rendered = _render(
        component,
        V2MonitorCapability(90, 10, ("model",), ()),
        load_translator("en"),
        Terminal(80, 20, False, True),
        15,
    )

    heading, detail = rendered.splitlines()
    assert heading.strip() == "Requests · Ranking · by Model · 90s window · querying"
    assert detail == "querying"
    assert "Trend" not in heading
    assert "Total" not in heading


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
    component.set_capability(probe().descriptor.metrics[0].capabilities)
    component.accept(
        CustomMonitorCompletion(
            0,
            config(),
            V2MonitorResponse(
                "tokens",
                V2MonitorObservation(
                    datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
                    Decimal("175"),
                    (V2MetricValue("terra", LocalizedText("Terra", "Terra"), Decimal("175")),),
                ),
            ),
        ),
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
