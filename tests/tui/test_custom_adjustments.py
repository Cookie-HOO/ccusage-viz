from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

import ccusage_viz.tui.custom_adjustments as tui_custom_adjustments
import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.models as tui_models
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.cli.configuration import _to_options
from ccusage_viz.command_parsing.parser import build_parser
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
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_protocol.responses import CustomChartResponse, CustomPaneResponse
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import CustomChartConfig, CustomCommandSource, adjust_custom_chart
from ccusage_viz.tui.custom_adjustments import _custom_capability_for_component
from ccusage_viz.tui.pane_lifecycle import _new_pane

from .custom_helpers import _accepted_metric_help_pane


def test_custom_capabilities_are_unavailable_after_source_replacement() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )
    component = tui_models.CustomHistoricalComponent(chart)
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
        for action in tui_custom_rendering._custom_standalone_actions(
            component, load_translator("en")
        )
    }
    assert (
        tui_custom_adjustments._cycle_custom_grouping(
            component.candidate, capability.group_by
        ).group_by
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
                "timeline": tui_models.V2HistoricalChartCapability(("day",), (), (), ("7d", "30d")),
                "calendar": tui_models.V2HistoricalChartCapability(("day",), (), ()),
                "ranking": tui_models.V2HistoricalChartCapability(("day",), (), (), ("all",)),
            },
        ),
        {},
    )

    assert tui_models._custom_metric_periods(metric, "timeline") == ("7d", "30d")
    assert tui_models._custom_metric_periods(metric, "ranking") == ("all",)
    assert tui_models._custom_metric_periods(metric, "calendar") == ()
    assert tui_models._custom_metric_periods(metric, "missing") == ()


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

    effective = tui_custom_adjustments._custom_period_adjustment_chart(chart, capability)

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
                {"ranking": tui_models.V2HistoricalChartCapability(("day",), (), (), periods)},
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

    target = tui_custom_adjustments._custom_period_adjustment_target(component)
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

    effective = tui_custom_adjustments._custom_period_adjustment_chart(
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


def test_custom_dashboard_adjustment_uses_native_footer() -> None:
    chart = CustomChartConfig(
        "timeline",
        CustomCommandSource("reading", ("reader", "ccuv")),
        DateRange(date(2026, 1, 1), date(2026, 1, 14)),
    )
    options = _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "--empty"]))
    pane = _new_pane(options, tui_models.CustomChartPaneConfig(chart), "test-custom")
    assert isinstance(pane, tui_models.TuiCustomPane)

    footer = tui_custom_adjustments._custom_adjustment_footer(
        pane, "quick", load_translator("en"), 120, color=False
    )
    advanced = tui_custom_adjustments._custom_adjustment_footer(
        pane, "advanced", load_translator("en"), 120, color=False
    )

    assert "Quick settings" in footer[1]
    assert "Dashboard Pane Management" in footer[2]
    assert "source" not in footer[1]
    assert "Advanced settings" in advanced[1]
    assert "e source" not in advanced[1]
    assert "L logs" in advanced[1]
    assert ("e", "custom_source") not in tui_custom_adjustments._custom_pane_adjustment_bindings(
        pane, "advanced"
    )
    assert ("L", "custom_logs") in tui_custom_adjustments._custom_pane_adjustment_bindings(
        pane, "advanced"
    )


def test_custom_metric_switch_binding_requires_declared_group() -> None:
    pane = _accepted_metric_help_pane()
    descriptor = pane.component.v2_descriptor
    assert isinstance(descriptor, V2ProbeDescriptor)

    assert ("m/M", "metric") not in tui_custom_adjustments._custom_pane_adjustment_bindings(
        pane, "quick"
    )

    pane.component.v2_descriptor = replace(
        descriptor,
        metrics=(replace(descriptor.metrics[0], group_id="github"), *descriptor.metrics[1:]),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )

    assert ("m/M", "metric") in tui_custom_adjustments._custom_pane_adjustment_bindings(
        pane, "quick"
    )


def test_custom_metric_switch_binding_omits_undeclared_group() -> None:
    pane = _accepted_metric_help_pane()
    descriptor = pane.component.v2_descriptor
    assert isinstance(descriptor, V2ProbeDescriptor)
    pane.component.v2_descriptor = replace(
        descriptor, metrics=(replace(descriptor.metrics[0], group_id="missing"),)
    )

    assert ("m/M", "metric") not in tui_custom_adjustments._custom_pane_adjustment_bindings(
        pane, "quick"
    )


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
    pane = tui_models.TuiCustomPane(
        component,
        FixedIntervalScheduler(10, now=0),
        LifecycleOperation("custom-ranking-state"),
        _to_options(
            build_parser(load_translator("en")).parse_args(["dashboard", "--empty"])
        ).process,
    )

    quick = tui_custom_adjustments._custom_pane_adjustment_state(
        pane, "quick", load_translator("en")
    )
    advanced = tui_custom_adjustments._custom_pane_adjustment_state(
        pane, "advanced", load_translator("en")
    )

    assert "Group book" in quick
    assert "Top 10" in quick
    assert (
        "+/- Top"
        in tui_custom_adjustments._custom_adjustment_footer(
            pane, "quick", load_translator("en"), 160, color=False
        )[1]
    )
    assert "Other show" in advanced


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

    assert tui_custom_adjustments._custom_top_refresh_required(
        component, replace(component.candidate, top=11)
    )
    assert not tui_custom_adjustments._custom_top_refresh_required(
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

    assert not tui_custom_adjustments._custom_top_refresh_required(
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
    assert not tui_custom_adjustments._custom_top_refresh_required(
        component, replace(component.candidate, top=11)
    )


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

    updated = tui_custom_adjustments._cycle_custom_grouping(chart, (None, "book"), step=step)

    assert updated.group_by == ("book" if group_by is None else None)
    assert updated.top is top


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
    assert isinstance(pane, tui_models.TuiCustomPane)

    from tests.custom_component.helpers import response

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

    assert tui_custom_adjustments._custom_capability(pane) is None
