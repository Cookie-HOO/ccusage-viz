from __future__ import annotations

from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
from ccusage_viz.query.registry import ProviderRegistry


def build_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(CCUSAGE_DEFINITION)
    registry.register(DEMO_DEFINITION)
    registry.freeze()
    return registry
