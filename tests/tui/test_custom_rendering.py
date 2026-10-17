from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui.adjustments as tui_adjustments
import ccusage_viz.tui.controls as tui_controls
import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.dashboard_events as tui_dashboard_events
import ccusage_viz.tui.datasets.blocking as tui_datasets_blocking
import ccusage_viz.tui.datasets.catalog as tui_datasets_catalog
import ccusage_viz.tui.datasets.chooser as tui_datasets_chooser
import ccusage_viz.tui.datasets.modal as tui_datasets_modal
import ccusage_viz.tui.events as tui_events
import ccusage_viz.tui.help as tui_help
import ccusage_viz.tui.history as tui_history
import ccusage_viz.tui.input as tui_input
import ccusage_viz.tui.models as tui_models
import ccusage_viz.tui.painting as tui_painting
import ccusage_viz.tui.pane_events as tui_pane_events
import ccusage_viz.tui.pane_lifecycle as tui_pane_lifecycle
import ccusage_viz.tui.pointer as tui_pointer
import ccusage_viz.tui.queries as tui_queries
import ccusage_viz.tui.rendering as tui_rendering
import ccusage_viz.tui.runtime as tui_runtime
import ccusage_viz.tui.session as tui_session
import ccusage_viz.tui.structure as tui_structure
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomComparison,
    CustomData,
    CustomDataset,
    CustomDimension,
    CustomMetric,
    CustomPaneSummary,
    CustomPoint,
    CustomPresentationDescriptor,
    CustomProtocolWarning,
    CustomSeries,
    CustomUnit,
    LocalizedText,
    V2MetricCapabilities,
    V2MetricDescriptor,
)
from ccusage_viz.custom_protocol.requests import V2SummaryRequest
from ccusage_viz.custom_protocol.responses import CustomChartResponse, CustomPaneResponse
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.render.surfaces import dashboard_pane_surface
from ccusage_viz.terminal import Terminal, compose_frame
from ccusage_viz.tui.custom_rendering import _custom_ranking_clipboard_text
from ccusage_viz.tui.pane_lifecycle import _new_pane
from ccusage_viz.tui.rendering import _local_pane_content, _pane_render
from ccusage_viz.tui_input import KeyEvent

from .custom_helpers import custom_summary_response


def test_custom_ranking_project_copy_appends_the_project_link() -> None:
    assert _custom_ranking_clipboard_text(
        "Project",
        "Read [documentation](https://example.com/docs)",
        "https://example.com/projects/project",
    ) == (
        "Project\nRead documentation https://example.com/docs\nhttps://example.com/projects/project"
    )
    assert _custom_ranking_clipboard_text("Project", None, None) == "Project"

def test_custom_standalone_timeline_keeps_x_axis_labels_inside_frame() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
    )
    unit = CustomUnit("page", LocalizedText("pages", "页"), "suffix", 2)
    response = CustomPaneResponse(
        CustomDataset(LocalizedText("Reading", "阅读"), LocalizedText("Daily", "每日"), unit),
        CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
        CustomData(
            (
                CustomSeries(
                    "total",
                    LocalizedText("Total", "总计"),
                    (
                        CustomPoint(date(2026, 9, 1), Decimal("1")),
                        CustomPoint(date(2026, 9, 2), Decimal("2")),
                    ),
                ),
            )
        ),
        CustomPaneSummary(
            CustomMetric(
                "read",
                LocalizedText("Read", "阅读"),
                unit,
                Decimal("3"),
                CustomComparison("unavailable"),
                CustomComparison("unavailable"),
            )
        ),
    )
    component = tui_models.CustomHistoricalComponent(chart)
    assert component.accept_response(response)
    terminal = Terminal(58, 14, color=False, ascii=True)

    rendered = tui_custom_rendering._custom_standalone_render(
        component, load_translator("en"), terminal, pending=False
    )
    frame = compose_frame(
        rendered.chart,
        "refresh every 60s",
        "controls",
        height=16,
    )

    assert "09-01" in "\n".join(frame.rows)
    assert "09-02" in "\n".join(frame.rows)
    assert frame.rows[0] == "refresh every 60s"
    assert frame.rows[-1] == "controls"

@pytest.mark.parametrize(
    ("density", "visible"),
    (
        ("minimal", False),
        ("compact", False),
        ("normal", False),
        ("full", True),
        ("detailed", True),
    ),
)
def test_custom_ranking_description_visibility_follows_density(density: str, visible: bool) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        group_by="book",
        presentation=replace(ChartPresentation(), density=density),
    )
    text = LocalizedText("Reading", "阅读")
    unit = CustomUnit("page", text, "suffix", 0)
    component = CustomHistoricalComponent(chart)
    response = CustomChartResponse(
        CustomDataset(text, text, unit),
        CustomCapabilities(
            (CustomDimension("book", text),),
            (),
            {
                "ranking": CustomChartCapability(
                    ("day",), ("book",), (), descriptions_default="expanded"
                )
            },
        ),
        CustomData(
            (
                CustomSeries(
                    "book-1",
                    text,
                    (CustomPoint(date(2026, 9, 1), Decimal("1")),),
                    LocalizedText("Release validation", "发布验证"),
                ),
            )
        ),
    )
    assert component.accept_response(response)

    rendered = tui_custom_rendering._render_custom_projection(
        component.model,
        chart,
        load_translator("en"),
        Terminal(80, 24, color=False, ascii=True),
        accepted_at=None,
        interval=None,
        pending=False,
        surface=dashboard_pane_surface("ranking"),
    )
    assert ("Release validation" in rendered.chart) is visible
    assert "D" not in {
        action.key
        for action in tui_custom_rendering._custom_standalone_actions(component, load_translator("en"))
    }

def test_custom_standalone_renders_accepted_dataset_summary() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
    )
    component = CustomHistoricalComponent(chart)
    from tests.custom_component.helpers import response

    assert component.accept_response(response())
    summary = tui_models.CustomDashboardSummary(
        chart.source,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("standalone:custom:summary"),
        response=custom_summary_response(display="68 pages"),
        accepted_period="day",
        accepted_as_of_date=date(2026, 9, 2),
    )

    rendered = tui_custom_rendering._custom_standalone_render(
        component,
        load_translator("en"),
        Terminal(100, 24, color=False, ascii=True),
        pending=False,
        summary=summary,
    )

    assert "68 pages" in rendered.chart

def test_custom_ranking_pane_restores_preset_item_spacing() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=ChartPresentation(style="list"),
    )

    pane = _new_pane(
        dashboard,
        tui_models.CustomChartPaneConfig(chart, ranking_item_spacing="dashed"),
        "dashboard:pane:spacing",
        build_query_runtime(),
    )

    assert isinstance(pane, tui_models.TuiCustomPane)
    assert pane.ranking_item_spacing == "dashed"

def test_v2_custom_pane_owns_a_metric_scoped_summary_lifecycle() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    pane = _new_pane(
        dashboard,
        default_custom_pane(
            "ranking",
            source=CustomCommandSource("weread", ("weread", "ccuv")),
            dashboard=dashboard,
            metric_id="reading_time",
            metric_summary="comparisons",
        ),
        "dashboard:pane:v2-summary",
        build_query_runtime(),
    )

    assert isinstance(pane, tui_models.TuiCustomPane)
    assert pane.summary is not None

def test_v2_custom_pane_summary_request_uses_the_selected_metric() -> None:
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("weread", ("weread", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 10, 8), relative_until=True, period="1y"),
        metric_id="reading_time",
    )
    plan = tui_queries.summary_query_plan(date(2026, 10, 8), "day")

    intent = tui_queries.custom_v2_summary_query_intent(
        config,
        plan,
        timezone="Asia/Shanghai",
        owner_id="dashboard:pane:v2-summary:summary",
        generation=3,
        trigger=tui_queries.query_trigger(LifecycleTrigger.STARTUP),
    )

    assert isinstance(intent.payload, V2SummaryRequest)
    assert intent.payload.metric_id == "reading_time"

def test_pending_metric_switch_rendering_retains_accepted_projection() -> None:
    from tests.custom_component.helpers import response

    accepted = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2), period="1d"),
        metric_id="stars",
    )
    component = CustomHistoricalComponent(accepted)
    assert component.accept_response(response())
    anchor = datetime(2026, 10, 15, 12, tzinfo=UTC)
    target = V2MetricDescriptor(
        "recent",
        LocalizedText("Recent", "最近"),
        LocalizedText("Recent", "最近"),
        CustomUnit("count", LocalizedText("count", "次"), "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {"ranking": tui_models.V2HistoricalChartCapability((), (None,), (), ("10m",))},
        ),
        {"ranking": CustomChartDefaults("10m", None, None)},
    )
    component.begin_metric_switch(replace(accepted, metric_id="recent"), now=anchor, timezone="UTC")
    assert component.retry_metric_switch("range.period", target)
    assert component.request_config.metric_id == "recent"
    assert component.request_config.date_range == TimestampRange(
        anchor - timedelta(minutes=10), anchor, relative_until=True, period="10m"
    )

    standalone = tui_custom_rendering._custom_standalone_render(
        component,
        load_translator("en"),
        Terminal(160, 24, color=False, ascii=True),
        pending=True,
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("pending-switch"),
        SimpleNamespace(),
        probe_complete=True,
    )
    dashboard = _pane_render(pane, load_translator("en"), Terminal(160, 24, False, True))

    assert "Ranking · 10m" in standalone.chart
    assert "Ranking · 10m" in dashboard.chart
    assert "2026-09-01–2026-09-02" not in standalone.chart
    assert "2026-09-01–2026-09-02" not in dashboard.chart
    assert "Loading data…" in standalone.chart
    assert "Loading data…" in dashboard.chart

def test_custom_standalone_refresh_retains_accepted_projection() -> None:
    from tests.custom_component.helpers import response

    component = CustomHistoricalComponent(
        CustomChartConfig(
            "timeline",
            CustomCommandSource("reading", ("reader", "ccuv")),
            DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        )
    )
    assert component.accept_response(response((("total", "10"),)))
    component.configure(
        replace(component.candidate, date_range=DateRange(date(2026, 9, 17), date(2026, 9, 30))),
        data_affecting=True,
    )

    rendered = tui_custom_rendering._custom_standalone_render(
        component,
        load_translator("zh"),
        Terminal(80, 16, color=False, ascii=True),
        pending=True,
        pending_trigger=LifecycleTrigger.MANUAL,
    )

    assert "时间趋势 · 2026-09-01–2026-09-02" in rendered.chart
    assert "时间趋势 · 2026-09-17–2026-09-30" not in rendered.chart
    assert "正在加载数据…" not in rendered.chart

def test_custom_dashboard_refresh_retains_accepted_ranking_with_visible_audit() -> None:
    from tests.custom_component.helpers import response

    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        group_by="book",
        presentation=replace(ChartPresentation(), density="detailed"),
    )
    component = CustomHistoricalComponent(chart)
    assert component.accept_response(response((("accepted-series-label", "10"),)))
    component.configure(
        replace(component.candidate, date_range=DateRange(date(2026, 9, 17), date(2026, 9, 30))),
        data_affecting=True,
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("dashboard-refresh"),
        SimpleNamespace(),
        probe_complete=True,
    )

    # A periodic Router-style refresh may queue behind an active comparison or
    # configuration request. Its queued intent, not the older active trigger,
    # controls whether the accepted ranking remains visible.
    pane.lifecycle.request(
        LifecycleTrigger.CONFIGURATION,
        generation=component.generation,
        now=0,
        start=lambda _operation: (SimpleNamespace(), lambda: None),
    )
    pane.lifecycle.request(
        LifecycleTrigger.PERIODIC,
        generation=component.generation,
        now=1,
        start=lambda _operation: (SimpleNamespace(), lambda: None),
    )
    rendered = _pane_render(pane, load_translator("en"), Terminal(100, 24, False, True))

    assert "accepted-series-label" in rendered.chart
    assert "2026-09-01–2026-09-02" in rendered.chart
    assert "2026-09-17–2026-09-30" not in rendered.chart
    assert "??" not in rendered.chart
    assert "refreshing" in rendered.chart.lower()

def test_custom_standalone_initial_pending_uses_authoritative_legacy_presentation() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("opaque-dataset-id", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
    )
    component = CustomHistoricalComponent(chart)
    component.presentation = CustomPresentationDescriptor(
        CustomDataset(
            LocalizedText("Reading", "阅读"),
            LocalizedText("Daily reading", "每日阅读"),
            CustomUnit("page", LocalizedText("pages", "页"), "suffix", 0),
        ),
        {},
        {},
        {},
    )
    component.pending_generation = component.generation

    rendered = tui_custom_rendering._custom_standalone_render(
        component,
        load_translator("en"),
        Terminal(80, 16, color=False, ascii=True),
        pending=True,
    )

    assert "Reading · Timeline · 2026-09-01–2026-09-02" in rendered.chart
    assert "Loading data…" in rendered.chart
    assert "opaque-dataset-id" not in rendered.chart
    assert "pages" not in rendered.chart

def test_custom_heading_lifecycle_uses_canonical_identity_and_pending_query_marker() -> None:
    from tests.custom_component.helpers import response

    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("opaque-source-id", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2), relative_until=True, period="1d"),
        group_by="book",
        metric_titles=("Reading metric", "阅读指标"),
    )
    component = CustomHistoricalComponent(chart)
    component.pending_generation = component.generation
    terminal = Terminal(120, 24, color=False, ascii=True)
    translator = load_translator("en")

    pending = tui_custom_rendering._custom_standalone_render(
        component, translator, terminal, pending=True
    ).chart
    assert "Reading metric · Ranking · by book · 1d · querying" in pending
    assert "opaque-source-id" not in pending

    assert component.accept_response(response())
    accepted = tui_custom_rendering._custom_standalone_render(
        component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 1d" in accepted
    assert "Reading metric" not in accepted
    assert "querying" not in accepted

    empty_component = CustomHistoricalComponent(chart)
    assert empty_component.accept_response(response(()))
    empty = tui_custom_rendering._custom_standalone_render(
        empty_component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 1d" in empty
    assert "Reading metric" not in empty
    assert "querying" not in empty
    assert "No data found for the selected range." in empty

    assert component.fail(RuntimeError("refresh unavailable"), generation=component.generation)
    same_query_failure = tui_custom_rendering._custom_standalone_render(
        component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 1d" in same_query_failure
    assert "Reading metric" not in same_query_failure
    assert "querying" not in same_query_failure

    replacement = replace(
        chart,
        date_range=DateRange(
            date(2026, 9, 17), date(2026, 9, 30), relative_until=True, period="14d"
        ),
        metric_titles=("Replacement metric", "替换指标"),
    )
    component.configure(replacement, data_affecting=True)
    replacement_pending = tui_custom_rendering._custom_standalone_render(
        component, translator, terminal, pending=True
    ).chart
    assert "Reading · Ranking · by book · 14d · querying" in replacement_pending
    assert "Reading metric" not in replacement_pending
    assert "Replacement metric" not in replacement_pending

    assert component.fail(RuntimeError("replacement unavailable"), generation=component.generation)
    replacement_failure = tui_custom_rendering._custom_standalone_render(
        component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 14d" in replacement_failure
    assert "Reading metric" not in replacement_failure
    assert "Replacement metric" not in replacement_failure
    assert "querying" not in replacement_failure

def test_custom_standalone_low_density_refresh_retains_chart_without_audit_row() -> None:
    from tests.custom_component.helpers import response

    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=replace(ChartPresentation(), density="minimal"),
    )
    component = CustomHistoricalComponent(chart)
    assert component.accept_response(response((("accepted-series-label", "10"),)))
    component.configure(
        replace(component.candidate, date_range=DateRange(date(2026, 9, 17), date(2026, 9, 30))),
        data_affecting=True,
    )

    rendered = tui_custom_rendering._custom_standalone_render(
        component,
        load_translator("en"),
        Terminal(80, 16, color=False, ascii=True),
        pending=True,
    )

    assert "Loading data…" in rendered.chart
    assert "accepted-series-label" not in rendered.chart
    assert "refreshing" not in rendered.chart.lower()

@pytest.mark.parametrize("language", ("en", "zh"))
def test_custom_action_labels_are_localized(language: str) -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )
    component = tui_models.CustomHistoricalComponent(chart)
    translator = load_translator(language)

    actions = tui_custom_rendering._custom_standalone_actions(component, translator)
    action_text = {action.key: action.text for action in actions}

    assert "e" not in action_text
    assert action_text["L"]
    assert translator.text("label.adjust_chart")
    assert tui_controls._localized_actions((("L", "custom_logs"),), translator)

def test_dashboard_subday_ranking_suppresses_summary_and_date_restore_reuses_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 10, 15), date(2026, 10, 15), relative_until=True, period="1d"),
        metric_id="requests",
        metric_periods=("10m", "1d"),
    )
    component = CustomHistoricalComponent(chart)
    from tests.custom_component.helpers import response

    assert component.accept_response(response(point_date=date(2026, 10, 15)))
    component.set_capability(CustomChartCapability((), (None,), (), periods=("10m", "1d")))
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(3600, now=tui_rendering.time.monotonic()),
        LifecycleOperation("subday-summary"),
        options.process,
        probe_complete=True,
    )
    pane.summary = tui_models.CustomDashboardSummary(
        chart.source,
        FixedIntervalScheduler(3600, now=tui_rendering.time.monotonic()),
        LifecycleOperation("subday-summary:summary"),
        response=custom_summary_response(display="STALE SUMMARY"),
        accepted_period="day",
        accepted_as_of_date=date(2026, 10, 15),
    )
    submitted: list[object] = []
    frames: list[str] = []

    class FailedHandle:
        def result(self) -> object:
            raise QueryError("error.custom_command_protocol")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, intent: object) -> FailedHandle:
            submitted.append(intent)
            return FailedHandle()

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append("\n".join(frame.rows))  # type: ignore[attr-defined]

        def finish(self) -> None:
            pass

    # Open adjustments, move 1d -> 10m, manually refresh there, restore 1d,
    # then manually refresh again so the normal date-summary route is exercised.
    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("P"),
            KeyEvent("r"),
            KeyEvent("p"),
            KeyEvent("r"),
            KeyEvent("\x03"),
        )
    )
    monkeypatch.setattr(tui_session, 'build_query_runtime', Runtime)
    monkeypatch.setattr(tui_pane_lifecycle, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_session, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_structure, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_history, '_new_pane', lambda *_args: pane)
    monkeypatch.setattr(tui_session, 'FramePainter', Screen)
    monkeypatch.setattr(tui_adjustments, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_catalog, 'FramePainter', Screen)
    monkeypatch.setattr(tui_datasets_chooser, 'FramePainter', Screen)
    monkeypatch.setattr(tui_runtime, 'tui_input_mode', nullcontext)
    monkeypatch.setattr(tui_adjustments, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_input, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_catalog, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_datasets_chooser, 'read_event', lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(tui_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_runtime, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_dashboard_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pane_events, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_painting, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_pointer, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_help, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_history, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_catalog, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_chooser, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_blocking, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))
    monkeypatch.setattr(tui_datasets_modal, 'get_terminal_size', lambda: __import__('os').terminal_size((100, 30)))

    assert tui_runtime.run_tui(options, load_translator("en")) == 0
    summary_intents = [
        intent for intent in submitted if isinstance(intent.payload, V2SummaryRequest)
    ]
    timestamp_chart_intents = [
        intent for intent in submitted if getattr(intent.payload, "start_at", None) is not None
    ]

    assert timestamp_chart_intents
    assert len(summary_intents) == 2  # startup and restored date-range manual refresh
    subday_frames = [frame for frame in frames if "T" in frame and "[" in frame]
    assert subday_frames
    assert all("STALE SUMMARY" not in frame for frame in subday_frames)

def test_grouped_custom_ranking_dispatch_uses_grouped_viewport_and_clears_flat_state() -> None:
    from tests.ranking_scroll.helpers import grouped_projection

    model = grouped_projection()
    flat = tui_models.RankingViewport(offset=4)
    grouped = tui_models.GroupedRankingViewport()
    rendered = tui_custom_rendering._render_custom_projection(
        model,
        replace(model.config, metric_titles=("Requests", "请求")),
        load_translator("en"),
        Terminal(80, 10, color=False, ascii=True),
        accepted_at=None,
        interval=None,
        pending=False,
        surface=dashboard_pane_surface("ranking"),
        ranking_viewport=flat,
        grouped_ranking_viewport=grouped,
    )

    assert grouped.active and grouped.rows and grouped.hits
    assert not flat.active and flat.offset == 0
    assert "Coding Model" in rendered.chart

def test_custom_ranking_viewport_preserves_renderer_column_padding() -> None:
    chart = "    Centered ranking\n 1     API       ···● 10  60%\n 2     Longer API ·●··  5  40%"

    content, offset, line_count, visible_rows = _local_pane_content(
        chart,
        (),
        width=40,
        height=3,
        scrollable=True,
        preserve_layout=True,
        return_metadata=True,
    )

    assert content.splitlines() == chart.splitlines()
    assert (offset, line_count, visible_rows) == (0, 3, 3)

def test_custom_ranking_viewport_keeps_heading_search_and_columns_fixed() -> None:
    chart = "Ranking\nShowing 3 item(s)\nRank Project Current\n 1 A 10\n 2 B 8\n 3 C 5"
    fixed_rows = tui_custom_rendering._ranking_fixed_rows(chart)

    content, offset, line_count, visible_rows = _local_pane_content(
        chart,
        (),
        width=40,
        height=5,
        offset=1,
        scrollable=True,
        preserve_layout=True,
        fixed_rows=fixed_rows,
        return_metadata=True,
    )

    assert content.splitlines() == [
        "Ranking",
        "Showing 3 item(s)",
        "Rank Project Current",
        " 2 B 8",
        " 3 C 5",
    ]
    assert (offset, line_count, visible_rows) == (1, 3, 2)

def test_v2_ranking_source_limit_is_a_pane_local_notice() -> None:
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("weread", ("weread",)),
            DateRange(date(2026, 1, 1), date(2026, 10, 8)),
            metric_id="reading_time",
            group_by="book",
            top=11,
        )
    )
    component.set_capability(CustomChartCapability(("day",), ("book",), (), max_items=10))
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-ranking-limit"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    assert tui_custom_adjustments._custom_top_limit_notice(pane, load_translator("en")) == (
        "This Dataset can provide at most 10 ranking items.",
    )

    pane.body_view = "command"
    assert tui_custom_adjustments._custom_top_limit_notice(pane, load_translator("en")) == ()

def test_custom_dashboard_context_matches_native_timeline_presentation() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    chart = default_custom_pane(
        "timeline",
        source=CustomCommandSource("reading", ("reader", "ccuv")),
        dashboard=dashboard,
    ).chart

    english = tui_custom_rendering._custom_render_context(
        chart,
        load_translator("en"),
        Terminal(80, 12, color=False, ascii=True),
        accepted_at=None,
        interval=60,
        pending=False,
        surface=dashboard_pane_surface(chart.kind),
    )
    chinese = tui_custom_rendering._custom_render_context(
        chart,
        load_translator("zh"),
        Terminal(80, 12, color=False, ascii=True),
        accepted_at=None,
        interval=60,
        pending=False,
        surface=dashboard_pane_surface(chart.kind),
    )

    assert english.hide_upper_right_axes
    assert english.period == "14d"
    assert english.title_content == "Total"
    assert chinese.title_content == "总量"

def test_custom_dashboard_pane_renders_accepted_response_warnings_as_local_notices() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    pane = _new_pane(
        dashboard,
        default_custom_pane(
            "timeline",
            source=CustomCommandSource("reading", ("reader", "ccuv")),
            dashboard=dashboard,
        ),
        "dashboard:pane:0",
        build_query_runtime(),
    )
    assert isinstance(pane, tui_models.TuiCustomPane)
    pane.component.configure(
        replace(pane.component.candidate, date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2))),
        data_affecting=False,
    )
    from tests.custom_component.helpers import response

    source = response()
    warnings = (
        CustomProtocolWarning("coverage", LocalizedText("using 2d", "使用 2 天")),
        CustomProtocolWarning("other", LocalizedText("second notice", "第二条提示")),
    )
    warned = CustomPaneResponse(
        source.dataset, source.capabilities, source.data, source.summary, warnings=warnings
    )
    pane.component.accept_response(warned)

    english = _pane_render(pane, load_translator("en"), Terminal(80, 12, False, True))
    chinese = _pane_render(pane, load_translator("zh"), Terminal(80, 12, False, True))

    assert "a" in english.chart
    assert english.notices == ("using 2d", "second notice")
    assert "using 2d" not in english.chart
    assert chinese.notices == ("使用 2 天", "第二条提示")

def test_custom_dashboard_pane_renders_accepted_decimal_projection() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    pane = _new_pane(
        dashboard,
        default_custom_pane(
            "timeline",
            source=CustomCommandSource("reading", ("reader", "ccuv")),
            dashboard=dashboard,
        ),
        "dashboard:pane:0",
        build_query_runtime(),
    )
    assert isinstance(pane, tui_models.TuiCustomPane)

    from tests.custom_component.helpers import response

    pane.component.configure(
        replace(pane.component.candidate, date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2))),
        data_affecting=False,
    )
    pane.component.accept_response(response())
    rendered = _pane_render(pane, load_translator("en"), Terminal(80, 12, False, True))

    assert "Today’s Read 3.50 pages" not in rendered.chart
    assert "Reading · Timeline · 2026-09-01–2026-09-02" in rendered.chart
    assert "+" in rendered.chart
    assert "09-01" in rendered.chart
    assert "a · o b · D c" in rendered.chart

@pytest.mark.parametrize("density", ("compact", "full", "detailed"))
def test_custom_dashboard_timeline_keeps_x_axis_labels_after_local_clipping(
    density: str,
) -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    pane = _new_pane(
        dashboard,
        default_custom_pane(
            "timeline",
            source=CustomCommandSource("reading", ("reader", "ccuv")),
            dashboard=dashboard,
        ),
        "dashboard:pane:0",
        build_query_runtime(),
    )
    assert isinstance(pane, tui_models.TuiCustomPane)

    from tests.custom_component.helpers import response

    configured = replace(
        pane.component.candidate,
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=replace(pane.component.candidate.presentation, density=density),
    )
    pane.component.configure(configured, data_affecting=False)
    pane.component.accept_response(response())
    pane.summary = tui_models.CustomDashboardSummary(
        configured.source,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("dashboard:pane:0:summary"),
        response=custom_summary_response(year_over_year=CustomComparison("ready", Decimal("34"))),
        accepted_period="month",
        accepted_as_of_date=date(2026, 9, 2),
    )
    terminal = Terminal(80, 12, False, True)
    rendered = _pane_render(pane, load_translator("en"), terminal)

    content = _local_pane_content(rendered.chart, rendered.notices, height=terminal.height)

    assert isinstance(content, str)
    assert "09-01" in content
    assert "09-02" in content
