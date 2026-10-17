


import pytest

from ccusage_viz.providers.ccusage_definition import CCUSAGE_DEFINITION
from ccusage_viz.query.models import DataResolution, ProviderRef, QueryIntent

from .helpers import intent


def test_ccusage_provider_owns_logical_to_physical_planning() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent("timeline"))
    (query,) = plan.queries

    assert query.operation == "unified_daily"
    assert query.arguments[:3] == ("daily", "--by-agent", "--json")
    assert query.arguments[-2:] == ("--offline", "--no-cost")
    assert CCUSAGE_DEFINITION.provider.fingerprint(query) == query.fingerprint

def test_provider_preserves_source_identity() -> None:
    source_intent = intent("timeline")
    source_intent = QueryIntent(
        source_intent.owner_id,
        source_intent.generation,
        source_intent.trigger,
        ProviderRef("ccusage", "workspace-a"),
        source_intent.scope,
        source_intent.missing_intervals,
        source_intent.resolution,
        source_intent.dimensions,
        source_intent.execution_options,
    )

    (query,) = CCUSAGE_DEFINITION.provider.compile(source_intent).queries

    assert query.provider == ProviderRef("ccusage", "workspace-a")

def test_provider_rejects_unsupported_resolution() -> None:
    source = intent("timeline")
    unsupported = QueryIntent(
        source.owner_id,
        source.generation,
        source.trigger,
        source.provider,
        source.scope,
        source.missing_intervals,
        DataResolution.RANGE,
        source.dimensions,
        source.execution_options,
    )

    with pytest.raises(ValueError, match="unsupported resolution: range"):
        CCUSAGE_DEFINITION.provider.compile(unsupported)
