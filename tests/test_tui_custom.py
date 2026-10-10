from dataclasses import replace
from datetime import UTC, date, datetime
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
    CustomDimension,
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
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricValue,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
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
    V2MonitorResponse,
    V2SummaryRequest,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.formatting import display_width
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
        "Project\n"
        "Read documentation https://example.com/docs\n"
        "https://example.com/projects/project"
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


def _custom_monitor_component(*, grouped: bool = True, total: str = "90") -> CustomMonitorComponent:
    chart = CustomChartConfig(
        "monitor",
        CustomCommandSource("router", ("router-dataset",)),
        DateRange(date(2026, 10, 8), date(2026, 10, 8)),
        metric_id="tokens",
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
    assert "real_model · tokens · view 1h · data window 1m" in bars


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
