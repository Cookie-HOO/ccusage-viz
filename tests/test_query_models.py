from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ExecutionContext,
    PhysicalQuery,
    ProviderProvenance,
    ProviderRef,
    QueryIntent,
    QueryTrigger,
)


def _intent(*, owner: str = "pane:1", generation: int = 4) -> QueryIntent:
    interval = DateInterval(date(2026, 1, 2), date(2026, 1, 3))
    return QueryIntent(
        owner,
        generation,
        QueryTrigger.REFRESH,
        ProviderRef("ccusage"),
        DataScope((interval,), "UTC"),
        (interval,),
        DataResolution.DATE,
        ("agent", "project"),
        (("query_mode", "unified_daily"),),
    )


def test_intent_fingerprint_is_deterministic_and_captures_owner_semantics() -> None:
    first = _intent()

    assert first.fingerprint == _intent().fingerprint
    assert first.fingerprint != _intent(owner="pane:2").fingerprint
    assert first.fingerprint != _intent(generation=5).fingerprint
    with pytest.raises(FrozenInstanceError):
        first.generation = 5  # type: ignore[misc]


def test_physical_fingerprint_excludes_logical_owner_and_is_deterministic() -> None:
    interval = DateInterval(date(2026, 1, 2), date(2026, 1, 3))
    first = PhysicalQuery(
        ProviderRef("ccusage"),
        "daily",
        ("--since", "2026-01-02"),
        coverage=DateCoverage((interval,)),
    )
    second = PhysicalQuery(
        ProviderRef("ccusage"),
        "daily",
        ("--since", "2026-01-02"),
        coverage=DateCoverage((interval,)),
    )

    assert first.fingerprint == second.fingerprint
    assert (
        first.fingerprint
        != PhysicalQuery(ProviderRef("ccusage"), "daily", ("--since", "2026-01-03")).fingerprint
    )
    assert (
        first.fingerprint
        == PhysicalQuery(
            ProviderRef("ccusage"),
            "daily",
            ("--since", "2026-01-02"),
            coverage=DateCoverage(),
            required=False,
        ).fingerprint
    )


def test_physical_fingerprint_captures_execution_context() -> None:
    first = PhysicalQuery(
        ProviderRef("ccusage"),
        "daily",
        execution_context=ExecutionContext("ccusage", 30.0, 1024, (("A", "1"),)),
    )
    second = PhysicalQuery(
        ProviderRef("ccusage"),
        "daily",
        execution_context=ExecutionContext("/other/ccusage", 30.0, 1024, (("A", "1"),)),
    )

    assert first.fingerprint != second.fingerprint


def test_duplicate_heterogeneous_options_have_stable_validation_error() -> None:
    with pytest.raises(ValueError, match="execution option keys must be unique"):
        QueryIntent(
            "pane:1",
            0,
            QueryTrigger.REFRESH,
            ProviderRef("ccusage"),
            DataScope(()),
            (),
            DataResolution.DATE,
            execution_options=(("same", 1), ("same", "two")),
        )


def test_provider_refs_and_provenance_are_extensible_immutable_values() -> None:
    provider = ProviderRef("future-source", "billing")
    provenance = ProviderProvenance(provider, "abc123")

    assert provenance.provider == provider
    assert provenance.physical_fingerprint == "abc123"
    with pytest.raises(FrozenInstanceError):
        provider.provider_id = "other"  # type: ignore[misc]
