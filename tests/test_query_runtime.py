from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import cast

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.options import (
    MonitorConfig,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.models import PhysicalPlan, ProviderResult
from ccusage_viz.query.provider import Provider
from ccusage_viz.query.registry import ProviderRegistry
from ccusage_viz.query.runtime import QueryRuntime


def historical(*, demo_size: str | None = "small") -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(demo_size=demo_size),
        TimelineConfig("timeline", DateRange(date(2026, 1, 2), date(2026, 1, 3), None)),
    )


def test_runtime_requires_a_frozen_provider_registry() -> None:
    with pytest.raises(ValueError, match="provider registry must be frozen"):
        QueryRuntime(ProviderRegistry(), QueryCoordinator())


def test_runtime_selects_demo_provider_for_demo_acquisition() -> None:
    from ccusage_viz.bootstrap import build_query_runtime

    result = build_query_runtime().acquire(historical())

    assert result.records
    assert result.provenance[0].provider.provider_id == "demo"
    assert result.includes_project_attribution


def test_runtime_rejects_monitor_configuration() -> None:
    runtime = QueryRuntime.__new__(QueryRuntime)
    monitor = replace(historical(), chart=MonitorConfig("monitor", 3600))

    with pytest.raises(TypeError, match="does not support monitor"):
        runtime.acquire(monitor)


def test_runtime_delegates_execution_and_cancellation() -> None:
    class Coordinator:
        def __init__(self) -> None:
            self.plan: PhysicalPlan | None = None
            self.provider: Provider | None = None
            self.cancelled = False

        def run(self, plan: PhysicalPlan, provider: Provider) -> ProviderResult:
            self.plan = plan
            self.provider = provider
            return provider.assemble(plan, ())

        def cancel(self) -> None:
            self.cancelled = True

    from ccusage_viz.bootstrap import build_provider_registry

    coordinator = Coordinator()
    runtime = QueryRuntime(build_provider_registry(), cast(QueryCoordinator, coordinator))
    runtime.acquire(historical())
    runtime.cancel()

    assert coordinator.plan is not None
    assert coordinator.provider is not None
    assert coordinator.provider.provider.provider_id == "demo"
    assert coordinator.cancelled
