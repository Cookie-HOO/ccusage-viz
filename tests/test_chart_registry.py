import pytest

from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.charts.registry import ChartRegistry


def test_registry_preserves_registration_order_and_rejects_duplicates() -> None:
    builtins = tuple(build_chart_registry())
    registry = ChartRegistry()

    registry.register(builtins[1])
    registry.register(builtins[0])

    assert [definition.chart_id for definition in registry] == ["calendar", "timeline"]
    with pytest.raises(ValueError, match="duplicate chart ID: calendar"):
        registry.register(builtins[1])


def test_registry_freeze_rejects_registration_but_keeps_lookup_available() -> None:
    registry = build_chart_registry()

    assert registry.frozen
    assert registry.get("timeline").chart_id == "timeline"
    with pytest.raises(RuntimeError, match="chart registry is frozen"):
        registry.register(registry.get("calendar"))
    with pytest.raises(KeyError, match="unknown chart ID: absent"):
        registry.get("absent")


def test_bootstrap_explicitly_registers_historical_builtins() -> None:
    registry = build_chart_registry()

    assert [definition.chart_id for definition in registry] == [
        "timeline",
        "calendar",
        "stack",
        "ranking",
    ]
    for definition in registry:
        assert definition.processor is registry.get(definition.chart_id).processor
        assert definition.config_type.__name__.casefold().startswith(definition.chart_id)
        assert definition.model_type.__name__.casefold().startswith(definition.chart_id)
