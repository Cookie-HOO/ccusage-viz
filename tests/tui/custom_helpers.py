import threading
from contextlib import nullcontext
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.runtime as tui_module
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomComparison,
    CustomData,
    CustomSummary,
    CustomSummaryCurrent,
    CustomSummaryMetric,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricValue,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
)
from ccusage_viz.custom_protocol.responses import (
    CustomSummaryResponse,
    V2ChartResponse,
    V2MonitorResponse,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
)
from ccusage_viz.tui_input import KeyEvent


def custom_summary_response(
    *,
    display: str = "68 pages",
    sequential: CustomComparison | None = None,
    year_over_year: CustomComparison | None = None,
) -> CustomSummaryResponse:
    return CustomSummaryResponse(
        CustomSummary(
            CustomSummaryMetric(
                "pages",
                LocalizedText("Pages read", "阅读页数"),
                CustomSummaryCurrent(Decimal("68"), LocalizedText(display, "68 页")),
                sequential or CustomComparison("ready", Decimal("56")),
                year_over_year or CustomComparison("unavailable"),
            )
        )
    )

def _accepted_metric_help_pane() -> tui_module.TuiCustomPane:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(
        identifier: str, title: LocalizedText, description: LocalizedText
    ) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            title,
            description,
            unit,
            "sum",
            V2MetricCapabilities(
                (), (), {"timeline": tui_models.V2HistoricalChartCapability(("day",), (), ())}
            ),
            {},
        )

    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("dataset", ("dataset",)),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        metric_id="stars",
    )
    component = CustomHistoricalComponent(chart)
    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (
            metric(
                "stars",
                LocalizedText("Stars", "星标"),
                LocalizedText("Total GitHub stars", "GitHub 星标总数"),
            ),
            metric(
                "growth",
                LocalizedText("Growth", "增长"),
                LocalizedText("New GitHub stars", "新增 GitHub 星标"),
            ),
        ),
        (),
    )
    assert component.apply_provider_result(
        SimpleNamespace(
            custom_response=V2ChartResponse("stars", CustomData(()), descriptor, V2Runtime(()))
        )
    )
    return tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("accepted-metric-help"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

def _dashboard_help_frames(
    monkeypatch: pytest.MonkeyPatch, pane: tui_module.TuiCustomPane, *, language: str, width: int
) -> str:
    """Drive Dashboard pane adjustment and Help using a production Custom Pane."""

    frames: list[object] = []

    class Handle:
        def cancel(self) -> None:
            pass

        def result(self) -> object:
            threading.Event().wait(1)
            raise RuntimeError("cancelled test query")

    class Runtime:
        def submit(self, _intent: object) -> Handle:
            return Handle()

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    options = _to_options(
        build_parser(load_translator(language)).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    events = iter((KeyEvent("m"), KeyEvent("h"), KeyEvent("\x03")))
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((width, 40))
    )

    translator = load_translator(language)
    assert tui_module.run_tui(options, translator) == 0
    overlays = [
        "\n".join(frame.rows)
        for frame in frames
        if translator.text("status.tui_help_title") in "\n".join(frame.rows)
    ]
    assert overlays
    return overlays[-1]

def _custom_monitor_component(*, grouped: bool = True, total: str = "90") -> CustomMonitorComponent:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        DateRange(date(2026, 10, 8), date(2026, 10, 8)),
        metric_id="tokens",
        metric_titles=("Requests", "请求数"),
        group_by="real_model" if grouped else None,
    )
    component = CustomMonitorComponent(chart)
    component.set_capability(
        V2MetricCapabilities(
            (),
            (),
            {"monitor": V2MonitorCapability(60, 10, (None, "public_model", "real_model"), ())},
        )
    )
    component.accept(
        CustomMonitorCompletion(
            0,
            chart,
            V2MonitorResponse(
                "tokens",
                V2MonitorObservation(
                    datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
                    Decimal(total),
                    tuple(
                        V2MetricValue(identifier, label, value)
                        for identifier, label, value in (
                            ("a", LocalizedText("Alpha", "阿尔法"), Decimal("60")),
                            ("b", LocalizedText("Beta", "贝塔"), Decimal("30")),
                        )
                        if total != "0"
                    ),
                ),
            ),
        ),
        accepted_at=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
    )
    return component
