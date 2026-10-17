import threading
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import ccusage_viz.tui as tui_module
from ccusage_viz.adjustment_timeout import AdjustmentTimeout
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli import _to_options, build_parser
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
    CustomFilter,
    CustomFilterOption,
    CustomMetric,
    CustomPaneSummary,
    CustomPoint,
    CustomPresentationDescriptor,
    CustomProtocolFailure,
    CustomProtocolWarning,
    CustomSeries,
    CustomSummary,
    CustomSummaryCurrent,
    CustomSummaryMetric,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2MetricValue,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
    custom_monitor_y_axis_max,
)
from ccusage_viz.custom_protocol import (
    CustomChartResponse,
    CustomPaneResponse,
    CustomSummaryResponse,
    V2ChartResponse,
    V2MonitorResponse,
    V2SummaryRequest,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger
from ccusage_viz.options import (
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    adjust_custom_chart,
)
from ccusage_viz.render import RenderContext
from ccusage_viz.render.custom_monitor import render_custom_monitor
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.surfaces import dashboard_pane_surface
from ccusage_viz.terminal import Terminal, compose_frame
from ccusage_viz.tui import (
    _choose_custom_pane_config,
    _custom_capability_for_component,
    _custom_ranking_clipboard_text,
    _local_pane_content,
    _new_pane,
    _pane_render,
)
from ccusage_viz.tui_input import InputDecoder, KeyEvent, PasteEvent


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
    component = tui_module.CustomHistoricalComponent(chart)
    assert component.accept_response(response)
    terminal = Terminal(58, 14, color=False, ascii=True)

    rendered = tui_module._custom_standalone_render(
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

    rendered = tui_module._render_custom_projection(
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
        for action in tui_module._custom_standalone_actions(component, load_translator("en"))
    }


def test_custom_standalone_renders_accepted_dataset_summary() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 9, 1), date(2026, 9, 2)),
    )
    component = CustomHistoricalComponent(chart)
    from test_custom_component import response

    assert component.accept_response(response())
    summary = tui_module.CustomDashboardSummary(
        chart.source,
        FixedIntervalScheduler(60, now=0),
        LifecycleOperation("standalone:custom:summary"),
        response=custom_summary_response(display="68 pages"),
        accepted_period="day",
        accepted_as_of_date=date(2026, 9, 2),
    )

    rendered = tui_module._custom_standalone_render(
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
        tui_module.CustomChartPaneConfig(chart, ranking_item_spacing="dashed"),
        "dashboard:pane:spacing",
        build_query_runtime(),
    )

    assert isinstance(pane, tui_module.TuiCustomPane)
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

    assert isinstance(pane, tui_module.TuiCustomPane)
    assert pane.summary is not None


def test_v2_custom_pane_summary_request_uses_the_selected_metric() -> None:
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("weread", ("weread", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 10, 8), relative_until=True, period="1y"),
        metric_id="reading_time",
    )
    plan = tui_module.summary_query_plan(date(2026, 10, 8), "day")

    intent = tui_module.custom_v2_summary_query_intent(
        config,
        plan,
        timezone="Asia/Shanghai",
        owner_id="dashboard:pane:v2-summary:summary",
        generation=3,
        trigger=tui_module.query_trigger(LifecycleTrigger.STARTUP),
    )

    assert isinstance(intent.payload, V2SummaryRequest)
    assert intent.payload.metric_id == "reading_time"


def test_pending_metric_switch_rendering_retains_accepted_projection() -> None:
    from test_custom_component import response

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
            {"ranking": tui_module.V2HistoricalChartCapability((), (None,), (), ("10m",))},
        ),
        {"ranking": CustomChartDefaults("10m", None, None)},
    )
    component.begin_metric_switch(replace(accepted, metric_id="recent"), now=anchor, timezone="UTC")
    assert component.retry_metric_switch("range.period", target)
    assert component.request_config.metric_id == "recent"
    assert component.request_config.date_range == TimestampRange(
        anchor - timedelta(minutes=10), anchor, relative_until=True, period="10m"
    )

    standalone = tui_module._custom_standalone_render(
        component,
        load_translator("en"),
        Terminal(160, 24, color=False, ascii=True),
        pending=True,
    )
    pane = tui_module.TuiCustomPane(
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
    from test_custom_component import response

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

    rendered = tui_module._custom_standalone_render(
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
    from test_custom_component import response

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
    pane = tui_module.TuiCustomPane(
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

    rendered = tui_module._custom_standalone_render(
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
    from test_custom_component import response

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

    pending = tui_module._custom_standalone_render(
        component, translator, terminal, pending=True
    ).chart
    assert "Reading metric · Ranking · by book · 1d · querying" in pending
    assert "opaque-source-id" not in pending

    assert component.accept_response(response())
    accepted = tui_module._custom_standalone_render(
        component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 1d" in accepted
    assert "Reading metric" not in accepted
    assert "querying" not in accepted

    empty_component = CustomHistoricalComponent(chart)
    assert empty_component.accept_response(response(()))
    empty = tui_module._custom_standalone_render(
        empty_component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 1d" in empty
    assert "Reading metric" not in empty
    assert "querying" not in empty
    assert "No data found for the selected range." in empty

    assert component.fail(RuntimeError("refresh unavailable"), generation=component.generation)
    same_query_failure = tui_module._custom_standalone_render(
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
    replacement_pending = tui_module._custom_standalone_render(
        component, translator, terminal, pending=True
    ).chart
    assert "Reading · Ranking · by book · 14d · querying" in replacement_pending
    assert "Reading metric" not in replacement_pending
    assert "Replacement metric" not in replacement_pending

    assert component.fail(RuntimeError("replacement unavailable"), generation=component.generation)
    replacement_failure = tui_module._custom_standalone_render(
        component, translator, terminal, pending=False
    ).chart
    assert "Reading · Ranking · by book · 14d" in replacement_failure
    assert "Reading metric" not in replacement_failure
    assert "Replacement metric" not in replacement_failure
    assert "querying" not in replacement_failure


def test_custom_standalone_low_density_refresh_retains_chart_without_audit_row() -> None:
    from test_custom_component import response

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

    rendered = tui_module._custom_standalone_render(
        component,
        load_translator("en"),
        Terminal(80, 16, color=False, ascii=True),
        pending=True,
    )

    assert "Loading data…" in rendered.chart
    assert "accepted-series-label" not in rendered.chart
    assert "refreshing" not in rendered.chart.lower()


def test_custom_capabilities_are_unavailable_after_source_replacement() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )
    component = tui_module.CustomHistoricalComponent(chart)
    response = CustomPaneResponse(
        CustomDataset(
            LocalizedText("Reading", "阅读"),
            LocalizedText("Daily", "每日"),
            CustomUnit("page", LocalizedText("pages", "页"), "suffix", 2),
        ),
        CustomCapabilities(
            (),
            (),
            {"timeline": CustomChartCapability(("day", "week"), ("book",), ())},
        ),
        CustomData(()),
        CustomPaneSummary(
            CustomMetric(
                "read",
                LocalizedText("Read", "阅读"),
                CustomUnit("page", LocalizedText("pages", "页"), "suffix", 2),
                Decimal(),
                CustomComparison("unavailable"),
                CustomComparison("unavailable"),
            )
        ),
    )
    component.accept_response(response)

    assert _custom_capability_for_component(component) is not None

    component.configure(
        replace(component.candidate, source=CustomCommandSource("other", ("other",))),
        data_affecting=True,
    )

    assert _custom_capability_for_component(component) is None


def test_probe_capability_keeps_period_and_group_controls_after_rejected_query() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("weread", ("weread",)),
        DateRange(date(1971, 1, 1), date(2026, 10, 8), relative_until=True, period="all"),
        metric_periods=("all",),
    )
    capability = CustomChartCapability(("day",), ("book",), ())
    component = CustomHistoricalComponent(chart)
    component.set_capability(capability)
    failure = QueryError(
        "error.custom_command_protocol",
        custom_failure=CustomProtocolFailure(
            "unsupported_query",
            LocalizedText("Only books are supported", "仅支持按书籍分组"),
            {"field": "query.group_by", "value": ""},
        ),
    )

    component.configure(replace(chart, group_by="book", top=3), data_affecting=True)
    assert component.fail(failure, generation=component.generation)

    assert _custom_capability_for_component(component) == capability
    assert "p/P" in {
        action.key
        for action in tui_module._custom_standalone_actions(component, load_translator("en"))
    }
    assert (
        tui_module._cycle_custom_grouping(component.candidate, capability.group_by).group_by
        == "book"
    )


def test_custom_metric_periods_follow_the_selected_chart_kind() -> None:
    metric = V2MetricDescriptor(
        "reading",
        LocalizedText("Reading", "阅读"),
        LocalizedText("Reading", "阅读"),
        CustomUnit("page", LocalizedText("pages", "页"), "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {
                "timeline": tui_module.V2HistoricalChartCapability(("day",), (), (), ("7d", "30d")),
                "calendar": tui_module.V2HistoricalChartCapability(("day",), (), ()),
                "ranking": tui_module.V2HistoricalChartCapability(("day",), (), (), ("all",)),
            },
        ),
        {},
    )

    assert tui_module._custom_metric_periods(metric, "timeline") == ("7d", "30d")
    assert tui_module._custom_metric_periods(metric, "ranking") == ("all",)
    assert tui_module._custom_metric_periods(metric, "calendar") == ()
    assert tui_module._custom_metric_periods(metric, "missing") == ()


def test_live_capability_periods_replace_stale_pane_periods_for_adjustment() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("reading", ("reader",)),
        DateRange(
            date(2026, 10, 12),
            date(2026, 10, 12),
            relative_until=True,
            period="1d",
        ),
        metric_periods=("all",),
    )
    capability = CustomChartCapability(("day",), (), (), periods=("1d", "7d"))

    effective = tui_module._custom_period_adjustment_chart(chart, capability)

    assert effective.metric_periods == ("1d", "7d")
    assert adjust_custom_chart(effective, "p").date_range.period == "7d"
    assert adjust_custom_chart(effective, "P").date_range.period == "7d"


def test_pending_metric_switch_uses_target_metric_periods() -> None:
    text = LocalizedText("GitHub", "GitHub")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str, periods: tuple[str, ...]) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier, identifier),
            text,
            unit,
            "sum",
            V2MetricCapabilities(
                (),
                (),
                {"ranking": tui_module.V2HistoricalChartCapability(("day",), (), (), periods)},
            ),
            {},
            group_id="github",
        )

    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("github", ("github",)),
            DateRange(
                date(1971, 1, 1),
                date(2026, 10, 12),
                relative_until=True,
                period="all",
            ),
            metric_id="stars",
            metric_periods=("all",),
        )
    )
    component.capability = CustomChartCapability(("day",), (), (), periods=("all",))
    component.v2_descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (
            metric("stars", ("all",)),
            metric("growth", ("1d", "7d", "14d")),
        ),
        (),
        metric_groups=(V2MetricGroup("github", text),),
    )
    component.begin_metric_switch(
        replace(
            component.candidate,
            metric_id="growth",
            date_range=DateRange(
                date(2026, 10, 12),
                date(2026, 10, 12),
                relative_until=True,
                period="1d",
            ),
        )
    )

    target = tui_module._custom_period_adjustment_target(component)
    updated = adjust_custom_chart(target, "p")

    assert target.metric_id == "growth"
    assert target.metric_periods == ("1d", "7d", "14d")
    assert updated.metric_id == "growth"
    assert updated.date_range.period == "7d"


def test_undeclared_live_periods_restore_generic_period_cycling() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader",)),
        DateRange(
            date(2026, 10, 6),
            date(2026, 10, 12),
            relative_until=True,
            period="7d",
        ),
        metric_periods=("all",),
    )

    effective = tui_module._custom_period_adjustment_chart(
        chart, CustomChartCapability(("day",), (), ())
    )

    assert effective.metric_periods == ()
    assert adjust_custom_chart(effective, "p").date_range.period == "14d"


def test_probe_capability_remains_available_before_the_first_chart_response() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader",)),
        DateRange(date(2026, 10, 1), date(2026, 10, 7), relative_until=True, period="7d"),
        metric_periods=("7d", "30d"),
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(CustomChartCapability(("day",), ("book",), ()))

    assert _custom_capability_for_component(component) is not None
    assert adjust_custom_chart(component.candidate, "p").date_range.period == "30d"


@pytest.mark.parametrize("language", ("en", "zh"))
def test_custom_action_labels_are_localized(language: str) -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )
    component = tui_module.CustomHistoricalComponent(chart)
    translator = load_translator(language)

    actions = tui_module._custom_standalone_actions(component, translator)
    action_text = {action.key: action.text for action in actions}

    assert "e" not in action_text
    assert action_text["L"]
    assert translator.text("label.adjust_chart")
    assert tui_module._localized_actions((("L", "custom_logs"),), translator)


def test_grouped_ranking_bindings_scope_partition_spacing_and_filters() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        partition_by="logical",
        group_by="real",
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(
        CustomChartCapability(
            ("day",),
            ("logical", "real", "provider"),
            (),
            partition_by=(None, "logical", "real"),
        )
    )
    component.runtime = V2Runtime(
        filters=(
            CustomFilter(
                "provider",
                LocalizedText("Provider", "提供商"),
                (CustomFilterOption("all", LocalizedText("All", "全部")),),
            ),
        )
    )
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("grouped-controls"),
        SimpleNamespace(),
    )

    quick = dict(tui_module._custom_pane_adjustment_bindings(pane, "quick"))
    advanced = dict(tui_module._custom_pane_adjustment_bindings(pane, "advanced"))
    assert quick["g/G"] == "partition"
    assert quick["s/S"] == "style"
    assert "f" not in quick
    assert advanced["s/S"] == "spacing"
    assert advanced["f"] == "filters"


def test_partition_and_group_cycles_skip_each_other_in_both_directions() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        partition_by="logical",
        group_by="real",
    )
    forward_partition = tui_module._cycle_custom_partitioning(
        chart, (None, "logical", "real"), ("logical", "real", "provider"), step=1
    )
    reverse_partition = tui_module._cycle_custom_partitioning(
        chart, (None, "logical", "real"), ("logical", "real", "provider"), step=-1
    )
    assert (forward_partition.partition_by, forward_partition.group_by) == (None, "real")
    assert (reverse_partition.partition_by, reverse_partition.group_by) == (None, "real")
    assert (
        tui_module._cycle_custom_grouping(chart, ("logical", "real", "provider"), step=1).group_by
        == "provider"
    )
    assert (
        tui_module._cycle_custom_grouping(chart, ("logical", "real", "provider"), step=-1).group_by
        == "provider"
    )
    assert tui_module._cycle_custom_grouping(chart, ("logical", "real")) == chart
    skipped = tui_module._cycle_custom_partitioning(
        chart, ("logical", "real", "provider"), ("logical", "real", "provider")
    )
    restricted = tui_module._cycle_custom_partitioning(
        chart, ("logical", "real"), ("logical", "real")
    )
    assert (skipped.partition_by, skipped.group_by) == ("provider", "real")
    assert restricted == chart


def test_partition_cycle_atomically_groups_a_flat_ranking_in_both_directions() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )

    forward = tui_module._cycle_custom_partitioning(
        chart,
        (None, "logical", "real"),
        (None, "real", "provider"),
        step=1,
    )
    reverse = tui_module._cycle_custom_partitioning(
        chart,
        (None, "logical", "real"),
        (None, "real", "provider"),
        step=-1,
    )

    assert (forward.partition_by, forward.group_by, forward.top) == ("logical", "real", 3)
    assert (reverse.partition_by, reverse.group_by, reverse.top) == (
        "real",
        "provider",
        3,
    )


def test_partition_cycle_supports_required_partitions_and_retains_no_legal_pair() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )

    required = tui_module._cycle_custom_partitioning(
        chart, ("logical", "real"), ("logical", "real"), step=1
    )
    restricted = tui_module._cycle_custom_partitioning(
        chart, ("logical",), (None, "logical"), step=1
    )

    assert (required.partition_by, required.group_by) == ("logical", "real")
    assert restricted == chart


def test_partition_cycle_skips_choice_matching_existing_group() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="logical",
    )

    updated = tui_module._cycle_custom_partitioning(
        chart, (None, "logical"), ("logical", "real"), step=1
    )

    assert updated == chart


@pytest.mark.parametrize(
    ("step", "expected"),
    (
        (1, ("logical", "real")),
        (-1, ("real", "logical")),
    ),
    ids=("forward", "reverse"),
)
def test_partition_cycle_recovers_from_stale_non_null_grouping(
    step: int, expected: tuple[str, str]
) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="stale",
    )

    updated = tui_module._cycle_custom_partitioning(
        chart,
        (None, "logical", "real"),
        (None, "logical", "real"),
        step=step,
    )

    assert (updated.partition_by, updated.group_by) == expected


def test_partition_cycle_preserves_a_legal_current_group_before_catalog_fallback() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="provider",
    )

    updated = tui_module._cycle_custom_partitioning(
        chart, (None, "logical"), ("real", "provider"), step=1
    )

    assert (updated.partition_by, updated.group_by) == ("logical", "provider")


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
    from test_custom_component import response

    assert component.accept_response(response(point_date=date(2026, 10, 15)))
    component.set_capability(CustomChartCapability((), (None,), (), periods=("10m", "1d")))
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(3600, now=tui_module.time.monotonic()),
        LifecycleOperation("subday-summary"),
        options.process,
        probe_complete=True,
    )
    pane.summary = tui_module.CustomDashboardSummary(
        chart.source,
        FixedIntervalScheduler(3600, now=tui_module.time.monotonic()),
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
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0
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


@pytest.mark.parametrize(
    ("key", "partitions", "groupings", "expected", "restricted"),
    (
        ("g", (None, "logical", "real"), (None, "real", "provider"), ("logical", "real"), False),
        ("G", (None, "logical", "real"), (None, "real", "provider"), ("real", "provider"), False),
        ("g", (None, "logical"), (None, "logical"), (None, None), True),
        ("G", (None, "logical"), (None, "logical"), (None, None), True),
    ),
    ids=("forward-refresh", "reverse-refresh", "forward-restricted", "reverse-restricted"),
)
def test_dashboard_partition_interaction_refreshes_or_reports_restriction(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    partitions: tuple[str | None, ...],
    groupings: tuple[str | None, ...],
    expected: tuple[str | None, str | None],
    restricted: bool,
) -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        metric_titles=("Router", "路由"),
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(
        CustomChartCapability(("day",), groupings, (), partition_by=partitions)
    )
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(3600, now=tui_module.time.monotonic()),
        LifecycleOperation("partition-interaction"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
        probe_complete=True,
    )
    submitted: list[object] = []
    frames: list[str] = []

    class Runtime:
        def submit(self, intent: object) -> object:
            submitted.append(intent)
            raise RuntimeError("stop test submission")

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append("\n".join(frame.rows))  # type: ignore[attr-defined]

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), KeyEvent(key), KeyEvent("\x03")))
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((100, 30))
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert (component.candidate.partition_by, component.candidate.group_by) == expected
    configuration_submissions = [
        intent
        for intent in submitted
        if intent.trigger.value == "refresh"  # type: ignore[attr-defined]
    ]
    assert bool(configuration_submissions) is not restricted
    if restricted:
        message = load_translator("en").text("status.custom_partition_restricted")
        assert any(message in frame for frame in frames)
        assert "Quick settings" in frames[-1]
        assert "Advanced settings" not in frames[-1]


def test_partition_binding_requires_multiple_effective_choices() -> None:
    chart = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
        group_by="logical",
    )
    component = CustomHistoricalComponent(chart)
    component.set_capability(
        CustomChartCapability(("day",), ("logical",), (), partition_by=(None, "logical"))
    )
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("restricted-partition"),
        SimpleNamespace(),
    )
    assert ("g/G", "partition") not in tui_module._custom_pane_adjustment_bindings(pane, "quick")


def test_custom_dashboard_adjustment_uses_native_footer() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    pane = _new_pane(options, tui_module.CustomChartPaneConfig(chart), "test-custom")
    assert isinstance(pane, tui_module.TuiCustomPane)

    footer = tui_module._custom_adjustment_footer(
        pane, "quick", load_translator("en"), 120, color=False
    )
    advanced = tui_module._custom_adjustment_footer(
        pane, "advanced", load_translator("en"), 120, color=False
    )

    assert "Quick settings" in footer[1]
    assert "Dashboard Pane Management" in footer[2]
    assert "source" not in footer[1]
    assert "Advanced settings" in advanced[1]
    assert "e source" not in advanced[1]
    assert "L logs" in advanced[1]
    assert ("e", "custom_source") not in tui_module._custom_pane_adjustment_bindings(
        pane, "advanced"
    )
    assert ("L", "custom_logs") in tui_module._custom_pane_adjustment_bindings(pane, "advanced")


def test_custom_metric_switch_binding_requires_declared_group() -> None:
    pane = _accepted_metric_help_pane()
    descriptor = pane.component.v2_descriptor
    assert isinstance(descriptor, V2ProbeDescriptor)

    assert ("m/M", "metric") not in tui_module._custom_pane_adjustment_bindings(pane, "quick")

    pane.component.v2_descriptor = replace(
        descriptor,
        metrics=(replace(descriptor.metrics[0], group_id="github"), *descriptor.metrics[1:]),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )

    assert ("m/M", "metric") in tui_module._custom_pane_adjustment_bindings(pane, "quick")


def test_custom_metric_switch_binding_omits_undeclared_group() -> None:
    pane = _accepted_metric_help_pane()
    descriptor = pane.component.v2_descriptor
    assert isinstance(descriptor, V2ProbeDescriptor)
    pane.component.v2_descriptor = replace(
        descriptor, metrics=(replace(descriptor.metrics[0], group_id="missing"),)
    )

    assert ("m/M", "metric") not in tui_module._custom_pane_adjustment_bindings(pane, "quick")


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
                (), (), {"timeline": tui_module.V2HistoricalChartCapability(("day",), (), ())}
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


@pytest.mark.parametrize("edited", (None, (("source", ("app",)),)), ids=("cancel", "apply"))
def test_dashboard_custom_filter_modal_forces_entry_and_restoration(
    monkeypatch: pytest.MonkeyPatch, edited: object
) -> None:
    pane = _accepted_metric_help_pane()
    choice = CustomFilter(
        "source",
        LocalizedText("Source", "来源"),
        (CustomFilterOption("app", LocalizedText("App", "应用")),),
    )
    pane.component.runtime = V2Runtime((choice,))
    force_flags: list[bool] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, *, force: bool = False, **_kwargs: object) -> None:
            force_flags.append(force)

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), KeyEvent("a"), KeyEvent("f"), KeyEvent("\x03")))

    def editor(*_args: object, **kwargs: object) -> object:
        kwargs["paint"]("filter body", "filter controls")  # type: ignore[index,operator]
        return edited

    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(tui_module, "run_custom_filter_editor", editor)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert any(pair == (True, True) for pair in zip(force_flags, force_flags[1:], strict=False)), (
        force_flags
    )


def test_dashboard_custom_filter_timeout_forces_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = _accepted_metric_help_pane()
    choice = CustomFilter(
        "source",
        LocalizedText("Source", "来源"),
        (CustomFilterOption("app", LocalizedText("App", "应用")),),
    )
    pane.component.runtime = V2Runtime((choice,))
    force_flags: list[bool] = []

    class Runtime:
        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, _frame: object, *, force: bool = False, **_kwargs: object) -> None:
            force_flags.append(force)

        def finish(self) -> None:
            pass

    events = iter((KeyEvent("m"), KeyEvent("a"), KeyEvent("f"), KeyEvent("\x03")))
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "_new_pane", lambda *_args: pane)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )
    monkeypatch.setattr(
        tui_module,
        "run_custom_filter_editor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AdjustmentTimeout()),
    )

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert force_flags[-1] is True


def test_accepted_custom_metric_help_uses_only_committed_v2_metric() -> None:
    pane = _accepted_metric_help_pane()
    translator = load_translator("en")

    assert tui_module._accepted_custom_metric_help_node(pane, translator) == (
        translator.text("status.tui_help_current_metric"),
        (("Stars", (("Total GitHub stars", ()),)),),
    )


@pytest.mark.parametrize("missing", ("accepted_config", "v1", "metric"))
def test_accepted_custom_metric_help_omits_unusable_metadata(missing: str) -> None:
    pane = _accepted_metric_help_pane()
    if missing == "accepted_config":
        pane.component.accepted_config = None
    elif missing == "v1":
        pane.component.v2_descriptor = SimpleNamespace(metrics=())
    else:
        assert pane.component.accepted_config is not None
        pane.component.accepted_config = replace(
            pane.component.accepted_config, metric_id="missing"
        )

    assert tui_module._accepted_custom_metric_help_node(pane, load_translator("en")) is None


def test_accepted_custom_metric_help_is_localized() -> None:
    assert tui_module._accepted_custom_metric_help_node(
        _accepted_metric_help_pane(), load_translator("zh")
    ) == ("当前指标", (("星标", (("GitHub 星标总数", ()),)),))


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


def test_dashboard_help_overlay_shows_committed_localized_v2_metric_and_omits_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v2_help = _dashboard_help_frames(
        monkeypatch, _accepted_metric_help_pane(), language="zh", width=80
    )

    assert "当前指标" in v2_help
    assert "星标" in v2_help
    assert "GitHub 星标总数" in v2_help
    visible_lines = [strip_ansi(line) for line in v2_help.splitlines()]
    current_metric_index = next(
        index for index, line in enumerate(visible_lines) if line.strip(" |") == "当前指标"
    )
    controls_index = next(
        index for index, line in enumerate(visible_lines) if line.strip(" |") == "操作"
    )
    assert current_metric_index < controls_index
    assert "当前 Pane 没有可调整参数" not in v2_help

    pane = _accepted_metric_help_pane()
    assert pane.component.apply_provider_result(
        SimpleNamespace(
            custom_response=CustomChartResponse(
                CustomDataset(
                    LocalizedText("Dataset", "数据集"),
                    LocalizedText("Daily", "每日"),
                    CustomUnit("count", LocalizedText("Dataset", "数据集"), "suffix", 0),
                ),
                CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
                CustomData(()),
            )
        )
    )
    assert pane.component.v2_descriptor is None
    v1_help = _dashboard_help_frames(monkeypatch, pane, language="zh", width=80)

    assert "当前指标" not in v1_help
    assert "星标" not in v1_help


def test_dashboard_help_overlay_omits_monitor_metric_after_descriptorless_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Router", "路由")
    unit = CustomUnit("count", text, "suffix", 0)
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router",)),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        metric_id="tokens",
    )
    component = CustomMonitorComponent(chart)
    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (
            V2MetricDescriptor(
                "tokens",
                LocalizedText("Tokens", "令牌"),
                LocalizedText("Current token rate", "当前令牌速率"),
                unit,
                "sum",
                V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
                {},
            ),
        ),
        (),
    )
    observation = V2MonitorObservation(datetime(2026, 10, 8, 12, tzinfo=UTC), Decimal("1"), ())
    assert component.accept(
        CustomMonitorCompletion(0, chart, V2MonitorResponse("tokens", observation, descriptor)),
        accepted_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )
    assert component.accept(
        CustomMonitorCompletion(0, chart, V2MonitorResponse("tokens", observation)),
        accepted_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )
    assert component.v2_descriptor is None
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("monitor-v1-metric-help"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    help_overlay = _dashboard_help_frames(monkeypatch, pane, language="en", width=80)

    assert "CURRENT METRIC" not in help_overlay
    assert "Tokens" not in help_overlay


def test_dashboard_help_overlay_wraps_metric_description_at_tree_continuation_indent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = _accepted_metric_help_pane()
    assert isinstance(pane.component.v2_descriptor, V2ProbeDescriptor)
    metric = pane.component.v2_descriptor.metrics[0]
    pane.component.v2_descriptor = replace(
        pane.component.v2_descriptor,
        metrics=(
            replace(
                metric,
                description=LocalizedText(
                    "A description long enough to wrap through the current Metric tree node.",
                    "A description long enough to wrap through the current Metric tree node.",
                ),
            ),
            *pane.component.v2_descriptor.metrics[1:],
        ),
    )
    lines = [
        strip_ansi(line)
        for line in _dashboard_help_frames(monkeypatch, pane, language="en", width=44).splitlines()
    ]
    first = next(index for index, line in enumerate(lines) if "A description long" in line)

    assert "└─ A description long" in lines[first]
    continuation = next(line for line in lines[first + 1 :] if "through the" in line)
    assert continuation.index("through the") == lines[first].index("A description long") + 3


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


def test_custom_monitor_renders_source_owned_monitor_presentations_without_shares() -> None:
    component = _custom_monitor_component()
    terminal = Terminal(80, 16, color=False, ascii=True)
    translated = load_translator("en")

    bars = tui_module._render_custom_monitor(component, translated, terminal, interval=10).chart
    component.configure(
        tui_module._adjust_custom_monitor_chart(component.candidate, "s"), data_affecting=False
    )
    line = tui_module._render_custom_monitor(component, translated, terminal, interval=10).chart
    component.configure(
        tui_module._adjust_custom_monitor_chart(component.candidate, "s"), data_affecting=False
    )
    step = tui_module._render_custom_monitor(component, translated, terminal, interval=10).chart

    assert "Alpha" in bars and "Beta" in bars
    assert "Other" not in bars
    assert "%" not in bars and "%" not in line and "%" not in step
    assert "Requests · Trend · by real_model · 1m window" in bars
    assert "view 1h" not in bars
    assert "data window" not in bars


def test_custom_monitor_retains_accepted_values_only_for_refreshes() -> None:
    component = _custom_monitor_component()
    terminal = Terminal(80, 16, color=False, ascii=True)

    periodic = tui_module._render_custom_monitor(
        component,
        load_translator("en"),
        terminal,
        interval=10,
        refreshing=True,
    ).chart
    assert "Alpha" in periodic
    assert "querying" in periodic

    component.configure(replace(component.candidate, group_by=None), data_affecting=True)
    switched = tui_module._render_custom_monitor(
        component,
        load_translator("en"),
        terminal,
        interval=10,
    ).chart
    assert "Loading…" in switched
    assert "Alpha" not in switched


@pytest.mark.parametrize(
    ("style", "view"),
    (
        ("line", "Trend"),
        ("ranking", "Ranking"),
        ("list", "List"),
        ("cumulative-bars", "Cumulative bars"),
    ),
)
@pytest.mark.parametrize("failed", (False, True), ids=("pending", "error"))
def test_custom_monitor_transient_states_use_canonical_heading(
    style: str, view: str, failed: bool
) -> None:
    component = _custom_monitor_component()
    component.accepted_response = None
    component.accepted_config = None
    component.configure(
        replace(
            component.candidate, presentation=replace(component.candidate.presentation, style=style)
        ),
        data_affecting=False,
    )
    component.error = RuntimeError("source failed") if failed else None

    rendered = tui_module._render_custom_monitor(
        component,
        load_translator("en"),
        Terminal(80, 16, color=False, ascii=True),
        interval=10,
    )
    heading = rendered.chart.splitlines()[0].strip()

    expected = f"Requests · {view} · by real_model · 1m window"
    assert heading == (expected if failed else f"{expected} · querying")
    assert rendered.error_body is failed
    assert ("source failed" in rendered.chart) is failed
    for excluded in ("view", "data window", "router-dataset", "token"):
        assert excluded not in heading.lower()
    assert all(display_width(line) <= 80 for line in rendered.chart.splitlines())


@pytest.mark.parametrize("failed", (False, True), ids=("pending", "error"))
def test_custom_monitor_unresolved_transient_state_omits_unfactual_heading(
    failed: bool,
) -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("private-dataset-id", ("router-dataset",)),
        DateRange(date(2026, 10, 8), date(2026, 10, 8)),
        metric_id="private-metric-id",
    )
    component = CustomMonitorComponent(chart)
    component.error = RuntimeError("probe failed") if failed else None

    rendered = tui_module._render_custom_monitor(
        component,
        load_translator("en"),
        Terminal(24, 10, color=False, ascii=True),
        interval=10,
    )

    assert rendered.chart == ("probe failed" if failed else "Loading…")
    assert "private-dataset-id" not in rendered.chart
    assert "private-metric-id" not in rendered.chart
    assert rendered.error_body is failed


def test_custom_monitor_pane_preserves_probe_error_body() -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        DateRange(date(2026, 10, 8), date(2026, 10, 8)),
        metric_id="tokens",
    )
    component = CustomMonitorComponent(chart)
    assert component.fail(RuntimeError("probe failed"), generation=component.generation)
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-monitor-probe-error"),
        SimpleNamespace(),
    )

    rendered = _pane_render(pane, load_translator("en"), Terminal(80, 16, color=False, ascii=True))

    assert rendered.error_body
    assert rendered.chart == "probe failed"


def test_custom_monitor_ranking_and_list_keep_native_row_geometry() -> None:
    component = _custom_monitor_component()
    translator = load_translator("en")

    for style in ("ranking", "list"):
        config = replace(
            component.candidate, presentation=replace(component.candidate.presentation, style=style)
        )
        component.configure(config, data_affecting=False)
        context = RenderContext(80, 16, translator, color=False, ascii=True, style=style)

        native_rows = render_ranking(component.ranking_model(language="en"), context).splitlines()[
            1:
        ]
        custom_rows = render_custom_monitor(component, context).splitlines()[1:]

        assert custom_rows == native_rows
        assert all(display_width(row) <= context.width for row in custom_rows)
        assert "%" not in "\n".join(custom_rows)


def test_custom_monitor_cycles_only_native_compatible_presentations() -> None:
    chart = _custom_monitor_component().candidate
    styles = []
    for _ in range(4):
        chart = tui_module._adjust_custom_monitor_chart(chart, "s")
        styles.append(chart.presentation.style)

    assert styles == ["step", "points", "line-points", "ranking"]


def test_custom_monitor_dashboard_context_hides_upper_right_axes_and_stabilizes_zero_values() -> (
    None
):
    component = _custom_monitor_component(total="0")
    terminal = Terminal(80, 16, color=False, ascii=False)

    rendered = tui_module._render_custom_monitor(
        component, load_translator("en"), terminal, interval=10
    )

    assert "plotext.figure" not in rendered.chart
    assert "┐" not in rendered.chart
    assert "┘" not in rendered.chart
    assert component.timeline_model(language="en").y_axis_max == 1.0
    assert custom_monitor_y_axis_max([4.2, 4.2]) == 4.2


def test_custom_value_monitor_excludes_cumulative_bars() -> None:
    chart = _custom_monitor_component().candidate
    styles = []
    for _ in range(4):
        chart = tui_module._adjust_custom_monitor_chart(chart, "s", aggregation="value")
        styles.append(chart.presentation.style)

    assert styles == ["step", "points", "line-points", "ranking"]


def test_custom_monitor_window_control_reprojects_without_query_configuration() -> None:
    component = _custom_monitor_component()
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-monitor-window"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    assert ("w", "window") in tui_module._custom_pane_adjustment_bindings(pane, "quick")
    assert tui_module._cycle_custom_monitor_window(3600) == 21600
    candidate = component.candidate
    component.configure_display_window(tui_module._cycle_custom_monitor_window(3600))

    assert component.candidate == candidate


def test_custom_ranking_adjustment_state_exposes_top_and_other_projection() -> None:
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("weread", ("reader", "ccuv")),
            DateRange(date(2026, 10, 1), date(2026, 10, 8)),
            group_by="book",
            top=10,
        )
    )
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-ranking-state"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    quick = tui_module._custom_pane_adjustment_state(pane, "quick", load_translator("en"))
    advanced = tui_module._custom_pane_adjustment_state(pane, "advanced", load_translator("en"))

    assert "Group book" in quick
    assert "Top 10" in quick
    assert (
        "+/- Top"
        in tui_module._custom_adjustment_footer(
            pane, "quick", load_translator("en"), 160, color=False
        )[1]
    )
    assert "Other show" in advanced


def test_grouped_custom_ranking_dispatch_uses_grouped_viewport_and_clears_flat_state() -> None:
    from test_custom_ranking_scroll import grouped_projection

    model = grouped_projection()
    flat = tui_module.RankingViewport(offset=4)
    grouped = tui_module.GroupedRankingViewport()
    rendered = tui_module._render_custom_projection(
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
    fixed_rows = tui_module._ranking_fixed_rows(chart)

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


def test_v2_ranking_top_refreshes_only_when_it_outgrows_retrieved_coverage() -> None:
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("example", ("example",)),
            DateRange(date(2026, 1, 1), date(2026, 10, 8)),
            metric_id="events",
            group_by="project",
            top=10,
        )
    )
    component.set_capability(CustomChartCapability(("day",), ("project",), (), max_items=50))
    component.retrieval_top = 10

    assert tui_module._custom_top_refresh_required(component, replace(component.candidate, top=11))
    assert not tui_module._custom_top_refresh_required(
        component, replace(component.candidate, top=10)
    )


def test_v2_ranking_top_above_dataset_maximum_does_not_request_more_coverage() -> None:
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("weread", ("weread",)),
            DateRange(date(2026, 1, 1), date(2026, 10, 8)),
            metric_id="reading_time",
            group_by="book",
            top=10,
        )
    )
    component.set_capability(CustomChartCapability(("day",), ("book",), (), max_items=10))
    component.retrieval_top = 10

    assert not tui_module._custom_top_refresh_required(
        component, replace(component.candidate, top=11)
    )


def test_v2_ranking_response_keeps_the_source_limit_for_later_top_adjustments() -> None:
    component = CustomHistoricalComponent(
        CustomChartConfig(
            "ranking",
            CustomCommandSource("weread", ("weread",)),
            DateRange(date(2026, 1, 1), date(2026, 10, 8)),
            metric_id="reading_time",
            group_by="book",
            top=10,
        )
    )
    source = CustomChartResponse(
        CustomDataset(
            LocalizedText("WeRead", "微信读书"),
            LocalizedText("Reading time", "阅读时长"),
            CustomUnit("minute", LocalizedText("minutes", "分钟"), "suffix", 2),
        ),
        CustomCapabilities(
            (CustomDimension("book", LocalizedText("Book", "书籍")),),
            (),
            {"ranking": CustomChartCapability(("day",), ("book",), (), max_items=10)},
        ),
        CustomData(
            (
                CustomSeries(
                    "book:1",
                    LocalizedText("One", "一"),
                    (CustomPoint(date(2026, 10, 8), Decimal("1")),),
                ),
            )
        ),
    )

    assert component.accept_response(source)

    assert component.capability is not None
    assert component.capability.max_items == 10
    assert not tui_module._custom_top_refresh_required(
        component, replace(component.candidate, top=11)
    )


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
    pane = tui_module.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-ranking-limit"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    assert tui_module._custom_top_limit_notice(pane, load_translator("en")) == (
        "This Dataset can provide at most 10 ranking items.",
    )

    pane.body_view = "command"
    assert tui_module._custom_top_limit_notice(pane, load_translator("en")) == ()


@pytest.mark.parametrize("group_by", (None, "book"))
@pytest.mark.parametrize("step", (1, -1))
@pytest.mark.parametrize("top", (None, 6))
def test_custom_historical_grouping_cycles_preserve_top_at_group_boundaries(
    group_by, step, top
) -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        group_by=group_by,
        top=top,
    )

    updated = tui_module._cycle_custom_grouping(chart, (None, "book"), step=step)

    assert updated.group_by == ("book" if group_by is None else None)
    assert updated.top is top


@pytest.mark.parametrize("group_by", (None, "model"))
@pytest.mark.parametrize("step", (1, -1))
@pytest.mark.parametrize("top", (None, 6))
def test_custom_monitor_grouping_cycles_preserve_top_at_group_boundaries(
    group_by, step, top
) -> None:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router", "ccuv")),
        DateRange(date(2026, 10, 1), date(2026, 10, 8)),
        group_by=group_by,
        top=top,
    )

    updated = tui_module._cycle_custom_grouping(chart, (None, "model"), step=step)

    assert (updated.group_by, updated.top) == (
        "model" if group_by is None else None,
        top,
    )


def test_custom_monitor_grouping_cycles_from_total_in_declared_order() -> None:
    component = _custom_monitor_component(grouped=False)
    capability = tui_module._custom_capability_for_component(component)
    assert isinstance(capability, V2MonitorCapability)

    forward = tui_module._cycle_custom_grouping(component.candidate, capability.group_by)
    second = tui_module._cycle_custom_grouping(forward, capability.group_by)
    reverse = tui_module._cycle_custom_grouping(component.candidate, capability.group_by, step=-1)

    assert forward.group_by == "public_model"
    assert second.group_by == "real_model"
    assert reverse.group_by == "real_model"


def test_custom_monitor_attachment_activity_uses_dataset_observation_total() -> None:
    component = _custom_monitor_component(total="90")
    attachment = tui_module.new_animation_session(
        tui_module.default_animation_spec("monitor"), theme="classic"
    )
    attachment.set_visible(True, 0)
    attachment.set_viable(True, 0)

    tui_module._update_custom_monitor_attachment_activity(
        component,
        attachment,
        now=1,
        wall=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert attachment.playback_requested

    component.accepted_response = V2MonitorResponse(
        "tokens",
        V2MonitorObservation(datetime(2026, 10, 8, 12, 1, tzinfo=UTC), Decimal(), ()),
    )
    tui_module._update_custom_monitor_attachment_activity(
        component,
        attachment,
        now=2,
        wall=datetime(2026, 10, 8, 12, 1, tzinfo=UTC),
        translator=load_translator("en"),
    )
    assert not attachment.playback_requested


def test_dataset_metric_chooser_groups_declared_metrics_and_keeps_ungrouped_flat() -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str, group_id: str | None = None) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier, f"{identifier}-zh"),
            text,
            unit,
            "sum",
            V2MetricCapabilities(
                (), (), {"ranking": tui_module.V2HistoricalChartCapability(("day",), (None,), ())}
            ),
            {},
            group_id=group_id,
        )

    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (metric("stars", "github"), metric("updated", "github"), metric("legacy")),
        (),
        metric_groups=(
            V2MetricGroup("github", LocalizedText("GitHub tools", "GitHub 工具")),
            V2MetricGroup("empty", LocalizedText("Empty", "空")),
        ),
    )

    rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("en"))

    assert [(row.kind, row.text, row.metric_index) for row in rows] == [
        ("group", "GitHub tools", None),
        ("metric", "├─ stars", 0),
        ("description", "│  └─ Dataset", None),
        ("metric", "└─ updated", 1),
        ("description", "   └─ Dataset", None),
        ("metric", "legacy", 2),
        ("description", "  └─ Dataset", None),
    ]

    chinese_rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("zh"))
    assert [(row.text, row.metric_index) for row in chinese_rows] == [
        ("GitHub 工具", None),
        ("├─ stars-zh", 0),
        ("│  └─ 数据集", None),
        ("└─ updated-zh", 1),
        ("   └─ 数据集", None),
        ("legacy-zh", 2),
        ("  └─ 数据集", None),
    ]


def test_metric_chooser_previous_offset_reveals_hidden_first_group_heading() -> None:
    rows = (
        tui_module.MetricChooserRow("group", "GitHub"),
        tui_module.MetricChooserRow("metric", "├─ Stars", 0),
        tui_module.MetricChooserRow("description", "│  └─ Star count"),
        tui_module.MetricChooserRow("metric", "└─ Forks", 1),
    )

    assert tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=1) == 0
    assert (
        tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=0) is None
    )
    assert (
        tui_module._metric_chooser_previous_offset(rows, selected_metric_index=1, offset=1) is None
    )


def test_metric_chooser_previous_offset_requires_immediate_predecessor_hidden() -> None:
    rows = (
        tui_module.MetricChooserRow("group", "GitHub"),
        tui_module.MetricChooserRow("description", "Repository metrics"),
        tui_module.MetricChooserRow("metric", "├─ Stars", 0),
        tui_module.MetricChooserRow("description", "│  └─ Star count"),
        tui_module.MetricChooserRow("metric", "└─ Forks", 1),
    )

    assert (
        tui_module._metric_chooser_previous_offset(rows, selected_metric_index=0, offset=1) is None
    )


def test_metric_chooser_display_rows_use_ascii_connectors_and_wrap_descriptions() -> None:
    rows = (
        tui_module.MetricChooserRow("group", "GitHub"),
        tui_module.MetricChooserRow("metric", "├─ Stars", 0),
        tui_module.MetricChooserRow(
            "description", "│  └─ A deliberately long metric description for narrow terminals"
        ),
        tui_module.MetricChooserRow("metric", "└─ Forks", 1),
        tui_module.MetricChooserRow(
            "description", "   └─ Another deliberately long description for the viewport"
        ),
    )

    displayed = tui_module._metric_chooser_display_rows(rows, width=20, ascii=True)
    choices = [f"{'>' if row.metric_index == 1 else ' '} {row.text}" for row in displayed]
    body, offset = tui_module._chooser_viewport(
        choices,
        index=next(index for index, row in enumerate(displayed) if row.metric_index == 1),
        offset=0,
        height=5,
        reserved_rows=2,
    )

    assert all(display_width(row.text) <= 18 for row in displayed)
    assert all(display_width(choice) <= 20 for choice in choices)
    assert any("|- Stars" in choice for choice in choices)
    assert "|  \\- " in "\n".join(choices)
    assert "   \\- " in "\n".join(choices)
    assert "├" not in "\n".join(choices)
    assert body.splitlines()[-1].startswith("> \\- Forks")
    assert offset == next(index for index, row in enumerate(displayed) if row.metric_index == 1) - 2


def test_standalone_metric_chooser_uses_ascii_host_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = LocalizedText("Dataset", "数据集")
    metric = V2MetricDescriptor(
        "stars",
        LocalizedText("Stars", "星标"),
        LocalizedText("Long description for ASCII chooser output", "描述"),
        CustomUnit("count", text, "suffix", 0),
        "sum",
        V2MetricCapabilities(
            (), (), {"ranking": tui_module.V2HistoricalChartCapability(("day",), (None,), ())}
        ),
        {},
        group_id="github",
    )
    forks = replace(metric, id="forks", title=LocalizedText("Forks", "分支"))
    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (metric, forks),
        (),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def registered_command_source(self, _dataset_id: str) -> CustomCommandSource:
            return CustomCommandSource("dataset", ("dataset",))

    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

    bodies: list[str] = []
    events = iter((KeyEvent("\r"), KeyEvent("j"), KeyEvent("\r"), KeyEvent("\r")))

    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty", "--ascii"])
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((20, 24))
    )

    config = tui_module._choose_dataset_pane_config(
        Screen(),
        load_translator("en"),
        InputDecoder(),
        height=8,
        dashboard=dashboard,
        paint_choices=lambda body, *_args: bodies.append(body),
        read_input=lambda: next(events),
    )

    assert config is not None
    assert config.chart.metric_id == "forks"
    metric_body = next(body for body in bodies if "Stars" in body)
    assert "\\- Long" in metric_body
    assert "└" not in metric_body
    assert "\x1b[1mGitHub\x1b[0m" in metric_body
    assert "\x1b[2m|  \\- Long descrip\x1b[0m" in metric_body


@pytest.mark.parametrize(
    ("height", "up_keys"),
    ((6, 2), (20, 1)),
    ids=("hidden_heading_revealed_before_wrap", "visible_heading_wraps_immediately"),
)
def test_standalone_metric_chooser_up_reveals_hidden_group_heading_before_wrapping(
    monkeypatch: pytest.MonkeyPatch, height: int, up_keys: int
) -> None:
    """The blocking chooser reveals its clipped heading before it wraps selection."""

    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier.title(), identifier),
            text,
            unit,
            "sum",
            V2MetricCapabilities(
                (), (), {"ranking": tui_module.V2HistoricalChartCapability(("day",), (None,), ())}
            ),
            {},
            group_id="github",
        )

    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (metric("stars"), metric("forks")),
        (),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def registered_command_source(self, _dataset_id: str) -> CustomCommandSource:
            return CustomCommandSource("dataset", ("dataset",))

    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

    bodies: list[str] = []
    navigation = (KeyEvent("j"), KeyEvent("k")) if height == 6 else ()
    events = iter(
        (
            KeyEvent("\r"),
            *navigation,
            *(KeyEvent("\x1b[A") for _ in range(up_keys)),
            KeyEvent("\r"),
            KeyEvent("\r"),
        )
    )
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((80, 24))
    )

    config = tui_module._choose_dataset_pane_config(
        Screen(),
        load_translator("en"),
        InputDecoder(),
        height=height,
        dashboard=dashboard,
        paint_choices=lambda body, *_args: bodies.append(body),
        read_input=lambda: next(events),
    )

    assert config is not None
    assert config.chart.metric_id == "forks"
    metric_bodies = [body for body in bodies if "Choose a metric" in body]
    if height == 6:
        # Down then Up leaves the first Metric selected while its heading is clipped.
        assert "› ├─ Stars" in metric_bodies[2]
        assert "GitHub" not in metric_bodies[2]
        # The first Up is viewport-only; the second wraps to the final Metric.
        assert "GitHub" in metric_bodies[3]
        assert "› ├─ Stars" in metric_bodies[3]
        assert "› └─ Forks" in metric_bodies[4]
    else:
        assert "GitHub" in metric_bodies[0]
        assert "› ├─ Stars" in metric_bodies[0]
        assert "› └─ Forks" in metric_bodies[1]


def test_dashboard_metric_modal_wraps_to_target_pane_and_submits_selected_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live Dashboard modal uses its pane width and navigates metric rows only."""

    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)

    def metric(identifier: str, description: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier.title(), identifier),
            LocalizedText(description, description),
            unit,
            "sum",
            V2MetricCapabilities(
                (), (), {"ranking": tui_module.V2HistoricalChartCapability(("day",), (None,), ())}
            ),
            {},
            group_id="github",
        )

    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(text, text),
        (
            metric(
                "stars", "A deliberately long description that must wrap inside this narrow pane."
            ),
            metric(
                "forks", "Another deliberately long description that must not become selectable."
            ),
        ),
        (),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )
    status = SimpleNamespace(
        registration=SimpleNamespace(
            dataset_id="dataset", probe=SimpleNamespace(descriptor=descriptor)
        )
    )
    submitted: list[str | None] = []
    frames: list[object] = []

    class DatasetService:
        def ready_registered_sources(self) -> tuple[object, ...]:
            return (status,)

        def registered_command_source(self, _dataset_id: str) -> CustomCommandSource:
            return CustomCommandSource("dataset", ("dataset",))

    class FailedHandle:
        def result(self) -> object:
            raise QueryError("error.custom_command_protocol")

        def cancel(self) -> None:
            pass

    class Runtime:
        def submit(self, _intent: object) -> FailedHandle:
            return FailedHandle()

        def cancel(self) -> None:
            pass

    class Screen:
        def __init__(self, _stream: object) -> None:
            pass

        def paint(self, frame: object, **_kwargs: object) -> None:
            frames.append(frame)

        def finish(self) -> None:
            pass

    original_default_custom_pane = tui_module.default_custom_pane

    def record_default_custom_pane(*args: object, **kwargs: object) -> object:
        submitted.append(kwargs.get("metric_id"))
        return original_default_custom_pane(*args, **kwargs)

    # Enter pane management, open Dataset chooser, select Datasets, then drive
    # the live metric modal with j/Enter before accepting its chart kind.
    events = iter(
        (
            KeyEvent("m"),
            KeyEvent("r"),
            KeyEvent("k"),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("j"),
            KeyEvent("\r"),
            KeyEvent("\r"),
            KeyEvent("\x03"),
        )
    )
    options = _to_options(
        build_parser(load_translator("en")).parse_args(
            ["dashboard", "--empty", "--header-style", "hidden"]
        )
    )
    monkeypatch.setattr("ccusage_viz.datasets.service.DatasetService", DatasetService)
    monkeypatch.setattr(tui_module, "build_query_runtime", Runtime)
    monkeypatch.setattr(tui_module, "FramePainter", Screen)
    monkeypatch.setattr(tui_module, "tui_input_mode", __import__("contextlib").nullcontext)
    monkeypatch.setattr(tui_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(
        tui_module, "get_terminal_size", lambda: __import__("os").terminal_size((44, 20))
    )
    monkeypatch.setattr(tui_module, "default_custom_pane", record_default_custom_pane)

    assert tui_module.run_tui(options, load_translator("en")) == 0
    assert submitted == ["forks"]

    metric_frames = [
        "\n".join(frame.rows) for frame in frames if "rrow pane." in "\n".join(frame.rows)
    ]
    assert metric_frames
    # Pane zero is framed and its interior is 20 columns wide at this terminal
    # size.  The visible wrapped description reaches its frame boundary without
    # leaking into the adjacent pane.
    metric_lines = [
        strip_ansi(line)
        for line in metric_frames[-1].splitlines()
        if "rrow pane." in strip_ansi(line)
    ]
    assert metric_lines
    assert all(display_width(line[:22]) == 22 and line[21] == "│" for line in metric_lines)


def test_dataset_metric_chooser_keeps_legacy_descriptor_flat() -> None:
    text = LocalizedText("Dataset", "数据集")
    unit = CustomUnit("count", text, "suffix", 0)
    metric = V2MetricDescriptor(
        "stars",
        LocalizedText("Stars", "Star"),
        text,
        unit,
        "sum",
        V2MetricCapabilities(
            (), (), {"ranking": tui_module.V2HistoricalChartCapability(("day",), (None,), ())}
        ),
        {},
    )
    descriptor = V2ProbeDescriptor("revision", "1", V2Dataset(text, text), (metric,), ())

    rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("en"))

    assert [(row.kind, row.text, row.metric_index) for row in rows] == [
        ("metric", "Stars", 0),
        ("description", "  └─ Dataset", None),
    ]


def test_dataset_metric_chooser_titles_the_selected_dataset() -> None:
    text = LocalizedText("Large Model Routing", "大模型路由")
    metric = V2MetricDescriptor(
        "tokens",
        LocalizedText("TPM", "TPM"),
        text,
        CustomUnit("token", text, "suffix", 0),
        "sum",
        V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
        {},
    )
    descriptor = V2ProbeDescriptor("router-live-v1", "0.1.0", V2Dataset(text, text), (metric,), ())

    chrome = tui_module._dataset_metric_chooser_chrome(descriptor, load_translator("zh"))

    assert chrome == ("数据集：大模型路由 · 0.1.0", "选择一个指标")


def test_dataset_source_chooser_uses_the_non_parameterized_title() -> None:
    assert load_translator("zh").text("status.dataset_chooser_title") == "数据集"


def test_custom_dashboard_context_matches_native_timeline_presentation() -> None:
    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    chart = default_custom_pane(
        "timeline",
        source=CustomCommandSource("reading", ("reader", "ccuv")),
        dashboard=dashboard,
    ).chart

    english = tui_module._custom_render_context(
        chart,
        load_translator("en"),
        Terminal(80, 12, color=False, ascii=True),
        accepted_at=None,
        interval=60,
        pending=False,
        surface=dashboard_pane_surface(chart.kind),
    )
    chinese = tui_module._custom_render_context(
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
    assert isinstance(pane, tui_module.TuiCustomPane)
    pane.component.configure(
        replace(pane.component.candidate, date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2))),
        data_affecting=False,
    )
    from test_custom_component import response

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
    assert isinstance(pane, tui_module.TuiCustomPane)

    from test_custom_component import response

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
    assert isinstance(pane, tui_module.TuiCustomPane)

    from test_custom_component import response

    configured = replace(
        pane.component.candidate,
        date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2)),
        presentation=replace(pane.component.candidate.presentation, density=density),
    )
    pane.component.configure(configured, data_affecting=False)
    pane.component.accept_response(response())
    pane.summary = tui_module.CustomDashboardSummary(
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


def test_custom_pane_chooser_builds_a_source_config_and_rejects_invalid_drafts() -> None:
    class Screen:
        def paint(self, *_args: object, **_kwargs: object) -> None:
            pass

    dashboard = _to_options(
        build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
    )
    events = iter(
        (
            KeyEvent("\t"),
            PasteEvent("reading"),
            KeyEvent("\t"),
            PasteEvent("reader ccuv"),
            KeyEvent("\r"),
        )
    )
    config = _choose_custom_pane_config(
        Screen(),
        load_translator("en"),
        InputDecoder(),
        height=20,
        dashboard=dashboard,
        read_input=lambda: next(events),
    )

    assert config is not None
    assert config.chart.kind == "timeline"
    assert config.chart.source == CustomCommandSource("reading", ("reader", "ccuv"))


def test_custom_capabilities_are_hidden_when_the_source_changes() -> None:
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
    assert isinstance(pane, tui_module.TuiCustomPane)

    from test_custom_component import response

    pane.component.configure(
        replace(pane.component.candidate, date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2))),
        data_affecting=False,
    )
    pane.component.accept_response(response())
    pane.component.configure(
        CustomChartConfig(
            "timeline",
            CustomCommandSource("other", ("other", "ccuv")),
            pane.component.candidate.date_range,
        ),
        data_affecting=True,
    )

    assert tui_module._custom_capability(pane) is None


def test_custom_failure_log_detail_uses_only_validated_protocol_fields() -> None:
    failure = QueryError(
        "error.custom_command_protocol",
        custom_failure=CustomProtocolFailure(
            "source_unavailable",
            LocalizedText("Safe source category", "安全的数据源分类"),
            {"field": "range.period", "value": "1w"},
        ),
    )

    assert (
        tui_module._custom_failure_log_detail(failure, load_translator("en"))
        == "source_unavailable: Safe source category (range.period=1w)"
    )
    assert (
        tui_module._custom_failure_log_detail(failure, load_translator("zh"))
        == "source_unavailable: 安全的数据源分类 (range.period=1w)"
    )


def test_custom_failure_log_detail_hides_unstructured_exception_text() -> None:
    assert (
        tui_module._custom_failure_log_detail(
            RuntimeError("private stderr and credential"), load_translator("en")
        )
        == "error"
    )


def test_custom_log_records_render_localized_statuses() -> None:
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
    assert isinstance(pane, tui_module.TuiCustomPane)
    pane.logs.extend(
        (
            tui_module.CustomLogRecord(datetime(2026, 9, 30, 10, 20), "ok", "done"),
            tui_module.CustomLogRecord(datetime(2026, 9, 30, 10, 21), "error", "failed"),
        )
    )

    rows = tuple(
        f"{load_translator('zh').text(f'status.custom_log_{record.status}')} "
        f"{record.timestamp:%H:%M:%S}: {record.detail}"
        for record in pane.logs
    )

    assert rows == ("成功 10:20:00: done", "错误 10:21:00: failed")
