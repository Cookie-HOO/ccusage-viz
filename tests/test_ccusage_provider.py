import json
from datetime import date

import pytest

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
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
        DataScope((interval,)),
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
    assert query.arguments[-2:] == ("--offline", "--no-cost")
    assert CCUSAGE_DEFINITION.provider.fingerprint(query) == query.fingerprint


def test_project_ranking_compiles_codex_as_single_day_queries() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent("ranking"))

    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_sessions",
        "codex_sessions",
    ]
    assert plan.queries[0].arguments[5] == "20260102"
    assert plan.queries[1].arguments[4:7] == ("2026-01-02", "--until", "2026-01-03")
    assert [query.arguments[4:7] for query in plan.queries[2:]] == [
        ("2026-01-02", "--until", "2026-01-02"),
        ("2026-01-03", "--until", "2026-01-03"),
    ]
    assert [query.coverage for query in plan.queries[2:]] == [
        DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 2)),
        DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    ]
    assert plan.summary_notices == ()


def test_codex_normalization_attributes_a_singleton_query_to_its_day() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "cwd": "/workspace/project",
            }
        ]
    }

    (record,) = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    ).records

    assert record.day == date(2026, 1, 3)
    assert record.project is not None
    assert record.project.raw_id == "/workspace/project"
    assert record.usage.total == 20


def test_codex_normalization_uses_local_session_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr(
        "ccusage_viz.providers.ccusage.resolve_codex_session_cwds",
        lambda session_ids: {"2026/01/03/rollout-test": "/workspace/from-session"},
    )
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "directory": "2026/01/03",
                "sessionId": "2026/01/03/rollout-test",
            }
        ]
    }

    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    )
    (record,) = fragment.records

    assert record.project is not None
    assert record.project.key == ("codex", "/workspace/from-session")
    assert record.day == date(2026, 1, 3)
    assert fragment.provider_metadata == ()


def test_codex_normalization_falls_back_without_treating_directory_as_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr("ccusage_viz.providers.ccusage.resolve_codex_session_cwds", lambda _: {})
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "directory": "2026/01/03",
                "sessionId": "2026/01/03/rollout-missing",
            }
        ]
    }

    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    )
    (record,) = fragment.records

    assert record.project is not None
    assert record.project.key == ("codex", "unassigned-codex")
    assert fragment.provider_metadata == (("codex_project_attribution_incomplete", True),)


def test_codex_incomplete_attribution_emits_a_generic_notice() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            query,
            json.dumps(
                {
                    "sessions": [
                        {
                            "inputTokens": 2,
                            "outputTokens": 3,
                            "cacheReadTokens": 5,
                            "cacheCreationTokens": 7,
                            "totalTokens": 20,
                            "sessionId": "missing",
                        }
                    ]
                }
            ).encode(),
        )
    )

    result = CCUSAGE_DEFINITION.provider.assemble(PhysicalPlan("plan", (query,)), (fragment,))

    assert result.notices == (Notice("notice.codex_project_attribution_incomplete"),)


def test_codex_normalization_rejects_non_singleton_coverage() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 3)),
    )

    with pytest.raises(QueryError) as caught:
        CCUSAGE_DEFINITION.provider.normalize(PhysicalResult(query, b'{"sessions": []}'))

    assert caught.value.key == "error.ccusage_codex_date_attribution"


def test_project_agent_observation_warns_without_contributing_records() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily_agent_observation",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    payload = {
        "daily": [
            {
                "date": "2026-01-03",
                "agents": [
                    {
                        "agent": "pi",
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cacheReadTokens": 5,
                        "cacheCreationTokens": 7,
                        "totalTokens": 20,
                    },
                    {
                        "agent": "antigravity",
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cacheReadTokens": 5,
                        "cacheCreationTokens": 7,
                        "totalTokens": 20,
                    },
                    {
                        "agent": "opencode",
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cacheReadTokens": 5,
                        "cacheCreationTokens": 7,
                        "totalTokens": 20,
                    },
                    {
                        "agent": "codex",
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cacheReadTokens": 5,
                        "cacheCreationTokens": 7,
                        "totalTokens": 20,
                    },
                ],
            }
        ]
    }
    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    )
    result = CCUSAGE_DEFINITION.provider.assemble(PhysicalPlan("plan", (query,)), (fragment,))

    assert not fragment.records
    assert not fragment.coverage.intervals
    assert result.notices == (
        Notice(
            "notice.project_agent_attribution_unsupported",
            {"agents": "antigravity, opencode"},
        ),
        Notice("notice.project_agent_attribution_unverified", {"agents": "pi"}),
    )
    assert not result.includes_project_attribution


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
