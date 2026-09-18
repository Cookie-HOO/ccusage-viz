from __future__ import annotations

from ccusage_viz.options import MonitorConfig, StandaloneLaunch
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.query.planner import plan_queries
from ccusage_viz.query.registry import ProviderRegistry


class QueryRuntime:
    """Shared Standalone/Pane runtime for provider-backed historical acquisition."""

    __slots__ = ("_coordinator", "_registry")

    def __init__(self, registry: ProviderRegistry, coordinator: QueryCoordinator) -> None:
        if not registry.frozen:
            raise ValueError("provider registry must be frozen before runtime use")
        self._registry = registry
        self._coordinator = coordinator

    def acquire(self, options: StandaloneLaunch) -> ProviderResult:
        if isinstance(options.chart, MonitorConfig):
            raise TypeError("historical query runtime does not support monitor configurations")
        provider_id = "demo" if options.host.demo_size else options.host.provider
        provider = self._registry.get(provider_id).provider
        plan = plan_queries(options, provider)
        return self._coordinator.run(plan, provider)

    def cancel(self) -> None:
        self._coordinator.cancel()
