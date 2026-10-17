import json
from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage import CcusageProvider
from ccusage_viz.providers.ccusage_definition import CCUSAGE_DEFINITION
from ccusage_viz.query.models import (
    DataResolution,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderRef,
    ProviderResultFragment,
)

from .helpers import (
    _fallback_replacement_case,
    _observation,
    intent,
    observation_payload,
    project_intent,
)


def test_project_ranking_compiles_primary_queries_without_speculative_fallbacks() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent("ranking"))

    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_ranking_sessions",
    ]
    assert plan.queries[0].arguments[5] == "20260102"
    assert plan.queries[1].arguments[4:7] == ("2026-01-02", "--until", "2026-01-03")
    assert plan.queries[2].arguments[4:7] == ("2026-01-02", "--until", "2026-01-03")
    assert plan.queries[2].coverage == DateCoverage.from_interval(
        date(2026, 1, 2), date(2026, 1, 3)
    )
    assert plan.summary_notices == ()

def test_newer_unresolved_compile_does_not_block_older_fallback_learning() -> None:
    provider = CcusageProvider()
    older = provider.compile(project_intent())
    provider.compile(project_intent())  # Cancelled before observation resolution.

    provider.resolve_queries(
        older,
        (provider.normalize(PhysicalResult(_observation(older), observation_payload("old"))),),
    )

    latest = provider.compile(project_intent())
    assert [
        query.arguments[0]
        for query in latest.queries
        if query.operation.startswith("project_fallback")
    ] == ["old"]

@pytest.mark.parametrize(
    ("fallback_total", "attributed"),
    [(20, True), (19, True), (20, False)],
    ids=["matching-total", "mismatched-total", "unresolved-project"],
)
def test_successful_fallback_directly_replaces_observation(
    fallback_total: int, attributed: bool
) -> None:
    provider, plan, observation, fallback = _fallback_replacement_case(
        fallback_total=fallback_total,
        attributed=attributed,
    )

    result = provider.assemble(plan, (observation, fallback))

    assert result.records == fallback.records
    if not attributed:
        (record,) = result.records
        assert record.project is not None
        assert record.project.display_name == "Unverified"
        assert record.attribution == "unverified"

def test_empty_successful_fallback_directly_replaces_observation() -> None:
    provider, plan, observation, fallback = _fallback_replacement_case()
    empty_fallback = replace(fallback, records=())

    result = provider.assemble(plan, (observation, empty_fallback))

    assert result.records == ()

def test_missing_required_fallback_fragment_is_incomplete() -> None:
    provider, plan, observation, _ = _fallback_replacement_case()

    with pytest.raises(QueryError) as caught:
        provider.assemble(plan, (observation,))

    assert caught.value.key == "error.ccusage_project_fallback_incomplete"
    assert caught.value.values["agent"] == "pi"

def test_fallback_replacement_associates_crossed_totals_with_each_interval() -> None:
    provider = CcusageProvider()
    first = provider.compile(project_intent(since=date(2026, 1, 1), until=date(2026, 1, 1)))
    first_a = provider.normalize(
        PhysicalResult(_observation(first), observation_payload("pi", total=10))
    )
    first_b_query = provider.resolve_queries(first, (first_a,))[0]
    second = provider.compile(project_intent(since=date(2026, 1, 2), until=date(2026, 1, 2)))
    second_a = provider.normalize(
        PhysicalResult(_observation(second), observation_payload("pi", total=20))
    )
    second_b_query = provider.resolve_queries(second, (second_a,))[0]

    def fallback(query: PhysicalQuery, total: int) -> ProviderResultFragment:
        metadata = provider.normalize(PhysicalResult(query, b'{"sessions": []}')).provider_metadata
        return ProviderResultFragment(
            (
                UsageRecord(
                    query.coverage.intervals[0].until,
                    "pi",
                    TokenUsage.from_parts(
                        total=total, input=total, output=0, cache_read=0, cache_creation=0
                    ),
                    SourceKind.PROJECT_SESSIONS,
                    ProjectRef("pi", "/project", "project", True),
                ),
            ),
            (ProviderProvenance(query.provider, query.fingerprint),),
            DataResolution.DATE,
            query.coverage,
            provider_metadata=metadata,
        )

    combined = PhysicalPlan("two-intervals", first.queries + second.queries)
    result = provider.assemble(
        combined,
        (first_a, second_a, fallback(first_b_query, 20), fallback(second_b_query, 10)),
    )

    assert [(record.day, record.usage.total) for record in result.records] == [
        (date(2026, 1, 1), 20),
        (date(2026, 1, 2), 10),
    ]

def test_fallback_normalization_accepts_pi_local_and_generic_absolute_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CcusageProvider()
    plan = provider.compile(project_intent(since=date(2026, 1, 3), until=date(2026, 1, 3)))
    observation = provider.normalize(
        PhysicalResult(_observation(plan), observation_payload("pi", "future-agent"))
    )
    required = provider.resolve_queries(plan, (observation,))
    queries = {query.arguments[0]: query for query in required}
    monkeypatch.setattr(
        "ccusage_viz.providers.ccusage_fallback.resolve_pi_session_cwds",
        lambda session_ids: {"pi-session": "/local/pi-project"},
    )

    def fallback(agent: str, session_id: str, project_path: str) -> ProviderResultFragment:
        return provider.normalize(
            PhysicalResult(
                queries[agent],
                json.dumps(
                    {
                        "sessions": [
                            {
                                "sessionId": session_id,
                                "projectPath": project_path,
                                "inputTokens": 20,
                                "outputTokens": 0,
                                "cacheReadTokens": 0,
                                "cacheCreationTokens": 0,
                                "totalTokens": 20,
                            }
                        ]
                    }
                ).encode(),
            )
        )

    pi = fallback("pi", "pi-session", "/reported/pi-project")
    future = fallback("future-agent", "future-session", "/workspace/future-project")
    result = provider.assemble(plan, (observation, pi, future))

    assert {
        (record.agent, record.project.raw_id if record.project else None)
        for record in result.records
    } == {
        ("pi", "/local/pi-project"),
        ("future-agent", "/workspace/future-project"),
    }
    assert all(record.attribution is None for record in result.records)

def test_generic_fallback_encoded_project_path_remains_unverified() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "project_fallback_sessions:future-agent",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    payload = {
        "sessions": [
            {
                "sessionId": "future-session",
                "projectPath": "--workspace-future-project--",
                "inputTokens": 20,
                "outputTokens": 0,
                "cacheReadTokens": 0,
                "cacheCreationTokens": 0,
                "totalTokens": 20,
            }
        ]
    }
    (record,) = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    ).records
    assert record.project is not None
    assert record.project.display_name == "Unverified"
    assert record.attribution == "unverified"
    assert record.source_project == "--workspace-future-project--"

def test_project_fallback_normalization_resolves_pi_session_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "project_fallback_sessions:pi",
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 3)),
    )
    monkeypatch.setattr(
        "ccusage_viz.providers.ccusage_fallback.resolve_pi_session_cwds",
        lambda session_ids: {"pi-session": "/workspace/github-projects"},
    )
    payload = {
        "sessions": [
            {
                "sessionId": "pi-session",
                "projectPath": "--workspace-github-projects--",
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
            }
        ]
    }

    (record,) = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    ).records

    assert record.day == date(2026, 1, 3)
    assert record.project is not None
    assert record.project.key == ("pi", "/workspace/github-projects")
    assert record.attribution is None

def test_project_fallback_replaces_matching_unverified_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily_agent_observation",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    session = PhysicalQuery(
        ProviderRef("ccusage"),
        "project_fallback_sessions:pi",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr(
        "ccusage_viz.providers.ccusage_fallback.resolve_pi_session_cwds",
        lambda session_ids: {"pi-session": "/workspace/github-projects"},
    )
    observation_fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            observation,
            json.dumps(
                {
                    "daily": [
                        {
                            "date": "2026-01-03",
                            "agents": [
                                {
                                    "agent": "pi",
                                    "project": "--workspace-github-projects--",
                                    "inputTokens": 2,
                                    "outputTokens": 3,
                                    "cacheReadTokens": 5,
                                    "cacheCreationTokens": 7,
                                    "totalTokens": 20,
                                }
                            ],
                        }
                    ]
                }
            ).encode(),
        )
    )
    session_fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            session,
            json.dumps(
                {
                    "sessions": [
                        {
                            "sessionId": "pi-session",
                            "projectPath": "--workspace-github-projects--",
                            "inputTokens": 2,
                            "outputTokens": 3,
                            "cacheReadTokens": 5,
                            "cacheCreationTokens": 7,
                            "totalTokens": 20,
                        }
                    ]
                }
            ).encode(),
        )
    )

    result = CCUSAGE_DEFINITION.provider.assemble(
        PhysicalPlan("pi-reconciliation", (observation, session)),
        (observation_fragment, session_fragment),
    )

    assert [
        (record.agent, record.project.raw_id) for record in result.records if record.project
    ] == [("pi", "/workspace/github-projects")]

def test_pending_unverified_agents_generate_optional_session_fallbacks() -> None:
    observation = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily_agent_observation",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            observation,
            json.dumps(
                {
                    "daily": [
                        {
                            "date": "2026-01-03",
                            "agents": [
                                {
                                    "agent": "pi",
                                    "project": "encoded-pi-project",
                                    "inputTokens": 2,
                                    "outputTokens": 3,
                                    "cacheReadTokens": 5,
                                    "cacheCreationTokens": 7,
                                    "totalTokens": 20,
                                },
                                {
                                    "agent": "future-agent",
                                    "project": "opaque-future-project",
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
            ).encode(),
        )
    )

    queries = CCUSAGE_DEFINITION.provider.supplemental_queries(
        PhysicalPlan("fallbacks", (observation,)), (fragment,)
    )

    assert [query.arguments[:3] for query in queries] == [
        ("future-agent", "session", "--json"),
        ("pi", "session", "--json"),
    ]
    assert all(query.required is False for query in queries)

def test_pending_unassigned_agent_generates_optional_session_fallback() -> None:
    observation = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily_agent_observation",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            observation,
            json.dumps(
                {
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
                                }
                            ],
                        }
                    ]
                }
            ).encode(),
        )
    )

    (query,) = CCUSAGE_DEFINITION.provider.supplemental_queries(
        PhysicalPlan("fallbacks", (observation,)), (fragment,)
    )

    assert query.arguments[:3] == ("pi", "session", "--json")
    assert query.required is False

def test_project_agent_observation_maps_unreliable_agents_to_fixed_projects() -> None:
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
                        "project": "relative/project",
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cacheReadTokens": 5,
                        "cacheCreationTokens": 7,
                        "totalTokens": 20,
                    },
                    {
                        "agent": "dsh",
                        "project": "/Users/me/Projects/demo",
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

    assert not fragment.coverage.intervals
    assert [
        (record.agent, record.project.display_name if record.project else None)
        for record in fragment.records
    ] == [
        ("pi", "Unverified"),
        ("dsh", "demo"),
        ("antigravity", "Unassigned"),
        ("opencode", "Unassigned"),
    ]
    assert not result.notices
    assert result.includes_project_attribution

def test_project_agent_observation_maps_relative_dsh_project_to_unverified() -> None:
    query = PhysicalQuery(ProviderRef("ccusage"), "unified_daily_agent_observation")
    payload = {
        "daily": [
            {
                "date": "2026-01-03",
                "agents": [
                    {
                        "agent": "dsh",
                        "project": "relative/project",
                        "inputTokens": 2,
                        "outputTokens": 3,
                        "cacheReadTokens": 5,
                        "cacheCreationTokens": 7,
                        "totalTokens": 20,
                    }
                ],
            }
        ]
    }

    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    )

    (record,) = fragment.records
    assert record.project is not None
    assert record.project.display_name == "Unverified"
    assert record.attribution == "unverified"
    assert record.source_project == "relative/project"
