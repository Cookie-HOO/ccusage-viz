from datetime import date

import pytest

from ccusage_viz.coverage import DateInterval
from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ProviderRef,
    QueryIntent,
    QueryTrigger,
)


def intent(chart_kind: str) -> QueryIntent:
    interval = DateInterval(date(2026, 1, 2), date(2026, 1, 3))
    return QueryIntent(
        "standalone",
        0,
        QueryTrigger.STARTUP,
        ProviderRef("ccusage"),
        DataScope((interval,), "UTC"),
        (interval,),
        DataResolution.DATE,
        ("project",) if chart_kind == "ranking" else ("agent",),
        (("chart_kind", chart_kind),),
    )


def test_ccusage_provider_owns_logical_to_physical_planning() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent("timeline"))
    (query,) = plan.queries

    assert query.operation == "unified_daily"
    assert query.arguments[:3] == ("daily", "--by-agent", "--json")
    assert query.arguments[-4:] == ("--timezone", "UTC", "--offline", "--no-cost")
    assert CCUSAGE_DEFINITION.provider.fingerprint(query) == query.fingerprint


def test_project_ranking_compiles_the_current_parallel_pair() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent("ranking"))

    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "codex_sessions",
    ]
    assert plan.queries[0].arguments[5] == "20260102"
    assert plan.queries[1].arguments[4] == "2026-01-02"
    assert plan.queries[0].coverage == plan.queries[1].coverage


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
