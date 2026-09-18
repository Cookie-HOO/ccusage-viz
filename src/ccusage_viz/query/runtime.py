from __future__ import annotations

from ccusage_viz.query.coordinator import QueryCoordinator, QueryHandle
from ccusage_viz.query.models import ProviderResult, QueryIntent
from ccusage_viz.query.provider import ProviderDefinition
from ccusage_viz.query.registry import ProviderRegistry


class QueryRuntime:
    """Shared Standalone/Pane runtime for provider-backed acquisition."""

    __slots__ = ("_coordinator", "_registry")

    def __init__(self, registry: ProviderRegistry, coordinator: QueryCoordinator) -> None:
        if not registry.frozen:
            raise ValueError("provider registry must be frozen before runtime use")
        self._registry = registry
        self._coordinator = coordinator

    def definition(self, provider_id: str) -> ProviderDefinition:
        return self._registry.get(provider_id)

    def submit(self, intent: QueryIntent) -> QueryHandle[ProviderResult]:
        provider = self._registry.get(intent.provider.provider_id).provider
        plan = provider.compile(intent)
        return self._coordinator.submit(plan, provider)

    def acquire(self, intent: QueryIntent) -> ProviderResult:
        return self.submit(intent).result()

    def cancel(self) -> None:
        self._coordinator.cancel()
