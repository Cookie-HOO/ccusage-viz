from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

import ccusage_viz.tui as tui_module
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli import _to_options, build_parser
from ccusage_viz.configuration import default_custom_pane
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomComparison,
    CustomData,
    CustomDataset,
    CustomMetric,
    CustomPaneSummary,
    CustomPoint,
    CustomProtocolFailure,
    CustomSeries,
    CustomSummary,
    CustomSummaryCurrent,
    CustomSummaryMetric,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.custom_protocol import CustomPaneResponse, CustomSummaryResponse
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
)
from ccusage_viz.render.surfaces import dashboard_pane_surface
from ccusage_viz.terminal import Terminal, compose_frame
from ccusage_viz.tui import (
    _choose_custom_pane_config,
    _custom_capability_for_component,
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


def test_custom_standalone_replacement_renders_candidate_loading_placeholder() -> None:
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
    )

    assert "时间趋势 · 2026-09-17–2026-09-30" in rendered.chart
    assert "正在加载数据…" in rendered.chart
    assert "今日 阅读" not in rendered.chart
    assert "查询中" not in rendered.chart


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
    assert "Total · Reading · Timeline · 2026-09-01–2026-09-02" in rendered.chart
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

    assert tui_module._custom_failure_log_detail(
        failure, load_translator("en")
    ) == "source_unavailable: Safe source category (range.period=1w)"
    assert tui_module._custom_failure_log_detail(
        failure, load_translator("zh")
    ) == "source_unavailable: 安全的数据源分类 (range.period=1w)"


def test_custom_failure_log_detail_hides_unstructured_exception_text() -> None:
    assert tui_module._custom_failure_log_detail(
        RuntimeError("private stderr and credential"), load_translator("en")
    ) == "error"


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
