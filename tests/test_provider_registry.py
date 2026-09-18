import pytest

from ccusage_viz.bootstrap import build_provider_registry
from ccusage_viz.query.provider import ProviderDefinition
from ccusage_viz.query.registry import ProviderRegistry


def test_registry_preserves_registration_order_and_rejects_duplicates() -> None:
    builtins = build_provider_registry()
    first, second = tuple(builtins)
    registry = ProviderRegistry()

    registry.register(second)
    registry.register(first)

    assert [definition.provider_id for definition in registry] == ["demo", "ccusage"]
    with pytest.raises(ValueError, match="duplicate provider ID: demo"):
        registry.register(second)


def test_registry_freeze_rejects_registration_but_keeps_lookup_available() -> None:
    registry = build_provider_registry()

    assert registry.frozen
    assert registry.get("ccusage").provider_id == "ccusage"
    with pytest.raises(RuntimeError, match="provider registry is frozen"):
        registry.register(ProviderDefinition(registry.get("demo").provider))
    with pytest.raises(KeyError, match="unknown provider ID: absent"):
        registry.get("absent")


def test_bootstrap_explicitly_registers_frozen_builtins() -> None:
    registry = build_provider_registry()

    assert [definition.provider_id for definition in registry] == ["ccusage", "demo"]
    assert registry.get("demo").provider.capabilities.in_process
    assert not registry.get("ccusage").provider.capabilities.in_process
