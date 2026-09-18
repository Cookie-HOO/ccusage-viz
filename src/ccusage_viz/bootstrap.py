from __future__ import annotations

from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.registry import ProviderRegistry
from ccusage_viz.query.runtime import QueryRuntime


def build_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(CCUSAGE_DEFINITION)
    registry.register(DEMO_DEFINITION)
    registry.freeze()
    return registry


def build_query_runtime(*, max_parallel: int = 2) -> QueryRuntime:
    return QueryRuntime(build_provider_registry(), QueryCoordinator(max_parallel=max_parallel))
