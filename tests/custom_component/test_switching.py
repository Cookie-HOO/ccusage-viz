from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Literal

import pytest

from ccusage_viz.acquisition import custom_historical_query_intent
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_component import (
    CustomCompletion,
    CustomHistoricalComponent,
)
from ccusage_viz.custom_models import (
    CustomChartCapability,
    CustomChartDefaults,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2ProbeDescriptor,
)
from ccusage_viz.query.models import QueryTrigger

from .helpers import UNIT, config, response, v2_chart_response


def test_metric_switch_request_wire_uses_target_partition_declaration() -> None:
    declared = V2HistoricalChartCapability(
        ("day",), (None,), (), partition_by=(None, "logical_model")
    )
    undeclared = V2HistoricalChartCapability(("day",), (None,), ())
    metrics = (
        V2MetricDescriptor(
            "declared",
            LocalizedText("Declared", "已声明"),
            LocalizedText("Declared", "已声明"),
            UNIT,
            "sum",
            V2MetricCapabilities((), (), {"ranking": declared}),
            {},
        ),
        V2MetricDescriptor(
            "undeclared",
            LocalizedText("Undeclared", "未声明"),
            LocalizedText("Undeclared", "未声明"),
            UNIT,
            "sum",
            V2MetricCapabilities((), (), {"ranking": undeclared}),
            {},
        ),
    )
    descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(LocalizedText("Data", "数据"), LocalizedText("Data", "数据")),
        metrics,
        (),
    )

    def switch_wire(source: str, target: str) -> dict[str, object]:
        component = CustomHistoricalComponent(
            config(kind="ranking", group_by=None, top=None, metric_id=source)
        )
        component.v2_descriptor = descriptor
        component.capability = (
            CustomChartCapability(("day",), (None,), (), partition_by=(None, "logical_model"))
            if source == "declared"
            else CustomChartCapability(("day",), (None,), ())
        )
        component.begin_metric_switch(replace(component.candidate, metric_id=target))
        intent = custom_historical_query_intent(
            component.request_config,
            timezone="UTC",
            owner_id="pane",
            generation=component.generation,
            trigger=QueryTrigger.REFRESH,
            partition_declared=component.partition_declared_for_request,
        )
        return intent.payload.to_wire()["query"]  # type: ignore[no-any-return,union-attr]

    assert switch_wire("undeclared", "declared")["partition_by"] is None
    assert "partition_by" not in switch_wire("declared", "undeclared")

def test_metric_switch_first_request_clears_supported_partition_without_target_default() -> None:
    capability = V2HistoricalChartCapability(
        ("day",), ("logical_model", "real_model"), (), partition_by=(None, "logical_model")
    )
    metrics = tuple(
        V2MetricDescriptor(
            metric_id,
            LocalizedText(metric_id, metric_id),
            LocalizedText(metric_id, metric_id),
            UNIT,
            "sum",
            V2MetricCapabilities((), (), {"ranking": capability}),
            {},
        )
        for metric_id in ("current", "target")
    )
    component = CustomHistoricalComponent(
        config(
            kind="ranking",
            metric_id="current",
            partition_by="logical_model",
            group_by="real_model",
        )
    )
    component.v2_descriptor = V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(LocalizedText("Data", "数据"), LocalizedText("Data", "数据")),
        metrics,
        (),
    )

    component.begin_metric_switch(replace(component.candidate, metric_id="target"))

    intent = custom_historical_query_intent(
        component.request_config,
        timezone="UTC",
        owner_id="pane",
        generation=component.generation,
        trigger=QueryTrigger.REFRESH,
        partition_declared=component.partition_declared_for_request,
    )
    assert component.request_config.group_by == "real_model"
    assert intent.payload.to_wire()["query"]["partition_by"] is None  # type: ignore[union-attr]

def test_historical_metric_switch_commits_only_after_target_response() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.accept_response(response())
    old_model = component.model

    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "updated_days"
    assert component.model is old_model
    assert component.accept_response(response())
    assert component.candidate.metric_id == "updated_days"
    assert component.request_config.metric_id == "updated_days"

def test_historical_metric_switch_rejects_completion_for_previous_metric() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    issued = component.request_config
    component.begin_metric_switch(config(metric_id="updated_days"))

    assert not component.apply_result(CustomCompletion(component.generation, issued, response()))
    assert component.is_pending
    assert component.switch_target_config is not None
    assert component.switch_target_config.metric_id == "updated_days"

def test_historical_metric_switch_failure_retains_old_facts_and_metric() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.accept_response(response())
    old_model = component.model

    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.fail(RuntimeError("unavailable"), generation=component.generation)
    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "stars"
    assert component.model is old_model

def test_historical_metric_switch_retries_unsupported_period_with_target_default() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.accept_response(response())
    target = V2MetricDescriptor(
        "updated_days",
        LocalizedText("Updated", "更新"),
        LocalizedText("Updated", "更新"),
        UNIT,
        "sum",
        V2MetricCapabilities(
            (), (), {"timeline": V2HistoricalChartCapability(("day",), ("book",), (), ("30d",))}
        ),
        {"timeline": CustomChartDefaults("30d", "book", None)},
    )
    component.begin_metric_switch(
        replace(
            config(metric_id="updated_days"),
            date_range=DateRange(date(2026, 9, 1), date(2026, 9, 2), period="7d"),
        )
    )

    assert component.retry_metric_switch("range.period", target)
    assert component.candidate.metric_id == "stars"
    assert component.request_config.date_range.period == "30d"
    assert not component.retry_metric_switch("range.period", target)

def test_historical_metric_switch_retry_rejects_mismatched_target_without_mutation() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    component.begin_metric_switch(config(metric_id="updated_days"))
    target = V2MetricDescriptor(
        "different_metric",
        LocalizedText("Different", "不同"),
        LocalizedText("Different", "不同"),
        UNIT,
        "sum",
        V2MetricCapabilities(
            (), (), {"timeline": V2HistoricalChartCapability(("day",), ("book",), (), ("30d",))}
        ),
        {"timeline": CustomChartDefaults("30d", "book", None)},
    )
    request = component.request_config
    generation = component.generation
    pending_generation = component.pending_generation

    assert not component.retry_metric_switch("range.period", target)
    assert component.request_config is request
    assert component.generation == generation
    assert component.pending_generation == pending_generation
    assert component.switch_normalizations == frozenset()

@pytest.mark.parametrize("purpose", ("primary", "comparison"))
def test_metric_switch_rejects_v2_response_for_previous_metric_without_mutation(
    purpose: Literal["primary", "comparison"],
) -> None:
    component = CustomHistoricalComponent(config(kind="ranking", metric_id="stars"))
    assert component.accept_response(response())
    component.begin_metric_switch(config(kind="ranking", metric_id="updated_days"))
    if purpose == "comparison":
        assert component.start_comparison() is not None
    state = (
        component.candidate,
        component.switch_target_config,
        component.model,
        component.accepted_config,
        component.accepted_response,
        component.generation,
        component.pending_generation,
        component.comparison_pending_generation,
        component.is_pending,
        component.comparison_is_pending,
        component.capability,
        component.v2_descriptor,
        component.runtime,
        component.render_revision,
    )

    assert not component.apply_provider_result(
        SimpleNamespace(custom_response=v2_chart_response("stars")), purpose=purpose
    )
    assert (
        component.candidate,
        component.switch_target_config,
        component.model,
        component.accepted_config,
        component.accepted_response,
        component.generation,
        component.pending_generation,
        component.comparison_pending_generation,
        component.is_pending,
        component.comparison_is_pending,
        component.capability,
        component.v2_descriptor,
        component.runtime,
        component.render_revision,
    ) == state

def test_metric_switch_accepts_v2_response_for_requested_metric() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars"))
    assert component.accept_response(response())
    component.begin_metric_switch(config(metric_id="updated_days"))

    assert component.apply_provider_result(
        SimpleNamespace(custom_response=v2_chart_response("updated_days"))
    )
    assert component.candidate.metric_id == "updated_days"
    assert component.accepted_config is not None
    assert component.accepted_config.metric_id == "updated_days"
    assert not component.is_pending

def test_metric_switch_accepts_target_chart_periods() -> None:
    component = CustomHistoricalComponent(config(metric_id="stars", metric_periods=("all",)))
    assert component.accept_response(response())
    component.begin_metric_switch(config(metric_id="updated_days", metric_periods=("all",)))

    assert component.apply_provider_result(
        SimpleNamespace(custom_response=v2_chart_response("updated_days", periods=("1d", "7d")))
    )
    assert component.candidate.metric_periods == ("1d", "7d")
    assert component.accepted_config is not None
    assert component.accepted_config.metric_periods == ("1d", "7d")
    assert component.capability is not None
    assert component.capability.periods == ("1d", "7d")

@pytest.mark.parametrize(
    "changed",
    (
        lambda value: replace(value, metric_id="other"),
        lambda value: replace(value, group_by=None),
    ),
)
def test_primary_completion_rejects_different_metric_or_query(changed: object) -> None:
    component = CustomHistoricalComponent(config(metric_id="read", top=2))
    assert component.accept_response(response())
    issued = component.candidate
    assert callable(changed)
    component.configure(changed(issued), data_affecting=False)

    assert not component.apply_result(CustomCompletion(component.generation, issued, response()))
