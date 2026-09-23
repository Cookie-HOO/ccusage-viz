from __future__ import annotations

from concurrent.futures import Future
from datetime import date
from threading import Event
from time import perf_counter
from typing import cast

import pytest

from ccusage_viz.acquisition import historical_query_intent
from ccusage_viz.core.time import DateRange
from ccusage_viz.options import (
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.query.coordinator import QueryCoordinator, QueryHandle
from ccusage_viz.query.models import PhysicalPlan, ProviderResult, QueryTrigger
from ccusage_viz.query.provider import Provider
from ccusage_viz.query.registry import ProviderRegistry
from ccusage_viz.query.runtime import QueryRuntime


def historical(*, demo_size: str | None = "small") -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(demo_size=demo_size),
        TimelineConfig("timeline", DateRange(date(2026, 1, 2), date(2026, 1, 3))),
    )


def test_runtime_requires_a_frozen_provider_registry() -> None:
    with pytest.raises(ValueError, match="provider registry must be frozen"):
        QueryRuntime(ProviderRegistry(), QueryCoordinator())


def test_runtime_selects_provider_from_query_intent() -> None:
    from ccusage_viz.bootstrap import build_query_runtime

    runtime = build_query_runtime()
    selected = historical_query_intent(
        historical(),
        runtime.definition("demo"),
        owner_id="standalone",
        generation=0,
        trigger=QueryTrigger.STARTUP,
    )
    result = runtime.acquire(selected)

    assert result.records
    assert result.provenance[0].provider.provider_id == "demo"
    assert result.includes_project_attribution


def test_runtime_submits_without_waiting_for_plan_compilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ccusage_viz.bootstrap import build_query_runtime

    runtime = build_query_runtime()
    selected = historical_query_intent(
        historical(),
        runtime.definition("demo"),
        owner_id="standalone",
        generation=0,
        trigger=QueryTrigger.STARTUP,
    )
    provider = runtime.definition("demo").provider
    started = Event()
    release = Event()
    provider_type = type(provider)
    original = provider_type.compile

    def compile_after_release(self, intent):
        started.set()
        assert release.wait(1)
        return original(self, intent)

    monkeypatch.setattr(provider_type, "compile", compile_after_release)
    before = perf_counter()
    handle = runtime.submit(selected)

    assert perf_counter() - before < 0.1
    assert started.wait(1)
    assert not handle.done()
    release.set()
    assert handle.result().records


def test_runtime_delegates_execution_and_cancellation() -> None:
    class Coordinator:
        def __init__(self) -> None:
            self.plan: PhysicalPlan | None = None
            self.provider: Provider | None = None
            self.cancelled = False

        def submit(self, plan: PhysicalPlan, provider: Provider) -> QueryHandle[ProviderResult]:
            self.plan = plan
            self.provider = provider
            future: Future[ProviderResult] = Future()
            future.set_result(provider.assemble(plan, ()))
            return QueryHandle(future, lambda: None)

        def cancel(self) -> None:
            self.cancelled = True

    from ccusage_viz.bootstrap import build_provider_registry

    coordinator = Coordinator()
    runtime = QueryRuntime(build_provider_registry(), cast(QueryCoordinator, coordinator))
    selected = historical_query_intent(
        historical(),
        runtime.definition("demo"),
        owner_id="standalone",
        generation=0,
        trigger=QueryTrigger.STARTUP,
    )
    handle = runtime.submit(selected)
    assert handle.result() == runtime.acquire(selected)
    runtime.cancel()

    assert coordinator.plan is not None
    assert coordinator.provider is not None
    assert coordinator.provider.provider.provider_id == "demo"
    assert coordinator.cancelled
