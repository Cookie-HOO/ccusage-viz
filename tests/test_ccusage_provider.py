import json
from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION, CcusageProvider
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ExecutionContext,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderRef,
    ProviderResultFragment,
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


def project_intent(
    *,
    source_id: str = "learned-source",
    since: date = date(2026, 1, 2),
    until: date = date(2026, 1, 3),
    executable: str = "ccusage",
    environment: tuple[tuple[str, str], ...] = (),
) -> QueryIntent:
    interval = DateInterval(since, until)
    return QueryIntent(
        "standalone",
        0,
        QueryTrigger.STARTUP,
        ProviderRef("ccusage", source_id),
        DataScope((interval,)),
        (interval,),
        DataResolution.DATE,
        ("project",),
        (("chart_kind", "ranking"),),
        ExecutionContext(executable, 10, 1024, environment),
    )


def observation_payload(*agents: str, total: int = 20) -> bytes:
    return json.dumps(
        {
            "daily": [
                {
                    "date": "2026-01-03",
                    "agents": [
                        {
                            "agent": agent,
                            "project": "relative/project",
                            "inputTokens": total,
                            "outputTokens": 0,
                            "cacheReadTokens": 0,
                            "cacheCreationTokens": 0,
                            "totalTokens": total,
                        }
                        for agent in agents
                    ],
                }
            ]
        }
    ).encode()


def _observation(plan: PhysicalPlan) -> PhysicalQuery:
    return next(
        query for query in plan.queries if query.operation == "unified_daily_agent_observation"
    )


def test_ccusage_provider_owns_logical_to_physical_planning() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent("timeline"))
    (query,) = plan.queries

    assert query.operation == "unified_daily"
    assert query.arguments[:3] == ("daily", "--by-agent", "--json")
    assert query.arguments[-2:] == ("--offline", "--no-cost")
    assert CCUSAGE_DEFINITION.provider.fingerprint(query) == query.fingerprint


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


def test_fallback_memory_learns_and_prefetches_with_preserved_source() -> None:
    provider = CcusageProvider()
    plan = provider.compile(project_intent(source_id="workspace-a"))
    assert not any(query.operation.startswith("project_fallback") for query in plan.queries)
    observation = _observation(plan)
    fragment = provider.normalize(
        PhysicalResult(observation, observation_payload("pi", "future-agent"))
    )

    required = provider.resolve_queries(plan, (fragment,))

    assert [query.arguments[0] for query in required] == ["future-agent", "pi"]
    assert all(query.provider == ProviderRef("ccusage", "workspace-a") for query in required)
    assert all(query.required and not query.speculative for query in required)
    assert all(query.scheduling_group == "ccusage-project-fallback" for query in required)
    assert all(query.scheduling_limit == 4 for query in required)
    next_plan = provider.compile(project_intent(source_id="workspace-a"))
    speculative = [q for q in next_plan.queries if q.operation.startswith("project_fallback")]
    assert [query.arguments[0] for query in speculative] == ["future-agent", "pi"]
    assert all(not query.required and query.speculative for query in speculative)
    assert [query.fingerprint for query in speculative] == [query.fingerprint for query in required]


def test_fallback_memory_isolates_source_executable_and_environment_digest() -> None:
    provider = CcusageProvider()
    seeded = provider.compile(
        project_intent(source_id="a", executable="one", environment=(("TOKEN", "secret"),))
    )
    provider.resolve_queries(
        seeded,
        (provider.normalize(PhysicalResult(_observation(seeded), observation_payload("pi"))),),
    )

    same = provider.compile(
        project_intent(source_id="a", executable="one", environment=(("TOKEN", "secret"),))
    )
    assert any(query.operation.endswith(":pi") for query in same.queries)
    for isolated in (
        project_intent(source_id="b", executable="one", environment=(("TOKEN", "secret"),)),
        project_intent(source_id="a", executable="two", environment=(("TOKEN", "secret"),)),
        project_intent(source_id="a", executable="one", environment=(("TOKEN", "other"),)),
    ):
        assert not any(
            query.operation.startswith("project_fallback")
            for query in provider.compile(isolated).queries
        )
    metadata = dict(
        provider.normalize(
            PhysicalResult(_observation(same), observation_payload("pi"))
        ).provider_metadata
    )
    assert metadata["ccusage_environment_digest"] != "secret"


def test_fallback_memory_reuses_period_then_adds_removes_and_clears() -> None:
    provider = CcusageProvider()
    first = provider.compile(project_intent())
    provider.resolve_queries(
        first,
        (
            provider.normalize(
                PhysicalResult(_observation(first), observation_payload("pi", "old-agent"))
            ),
        ),
    )
    changed = provider.compile(project_intent(since=date(2026, 2, 1), until=date(2026, 2, 5)))
    fallbacks = [q for q in changed.queries if q.operation.startswith("project_fallback")]
    assert {query.arguments[0] for query in fallbacks} == {"pi", "old-agent"}
    assert all(
        "2026-02-01" in query.arguments and "2026-02-05" in query.arguments for query in fallbacks
    )
    provider.resolve_queries(
        changed,
        (
            provider.normalize(
                PhysicalResult(_observation(changed), observation_payload("pi", "new-agent"))
            ),
        ),
    )
    updated = provider.compile(project_intent())
    assert {
        query.arguments[0]
        for query in updated.queries
        if query.operation.startswith("project_fallback")
    } == {"pi", "new-agent"}
    provider.resolve_queries(
        updated,
        (provider.normalize(PhysicalResult(_observation(updated), observation_payload())),),
    )
    assert not any(
        query.operation.startswith("project_fallback")
        for query in provider.compile(project_intent()).queries
    )


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


def test_out_of_order_fallback_revision_cannot_overwrite_newer_memory() -> None:
    provider = CcusageProvider()
    older = provider.compile(project_intent())
    newer = provider.compile(project_intent())
    provider.resolve_queries(
        newer,
        (provider.normalize(PhysicalResult(_observation(newer), observation_payload("new"))),),
    )
    provider.resolve_queries(
        older,
        (provider.normalize(PhysicalResult(_observation(older), observation_payload("old"))),),
    )
    latest = provider.compile(project_intent())
    assert [
        query.arguments[0]
        for query in latest.queries
        if query.operation.startswith("project_fallback")
    ] == ["new"]


def _strict_fallback_case(
    *, observation_total: int = 20, fallback_total: int = 20, attributed: bool = True
):
    provider = CcusageProvider()
    plan = provider.compile(project_intent(since=date(2026, 1, 3), until=date(2026, 1, 3)))
    observation_fragment = provider.normalize(
        PhysicalResult(_observation(plan), observation_payload("pi", total=observation_total))
    )
    (required,) = provider.resolve_queries(plan, (observation_fragment,))
    fallback_fragment = provider.normalize(
        PhysicalResult(
            required,
            json.dumps(
                {
                    "sessions": [
                        {
                            "sessionId": "session",
                            "projectPath": "encoded",
                            "inputTokens": fallback_total,
                            "outputTokens": 0,
                            "cacheReadTokens": 0,
                            "cacheCreationTokens": 0,
                            "totalTokens": fallback_total,
                        }
                    ]
                }
            ).encode(),
        )
    )
    if attributed:
        fallback_fragment = replace(
            fallback_fragment,
            records=tuple(
                replace(
                    record,
                    project=ProjectRef("pi", "/project", "project", True),
                    attribution=None,
                )
                for record in fallback_fragment.records
            ),
        )
    return provider, plan, observation_fragment, fallback_fragment


def test_strict_fallback_reconciliation_succeeds() -> None:
    provider, plan, observation, fallback = _strict_fallback_case()

    result = provider.assemble(plan, (observation, fallback))

    assert len(result.records) == 1
    assert result.records[0].project is not None
    assert result.records[0].project.raw_id == "/project"


@pytest.mark.parametrize("failure", ["missing", "mismatch", "unresolved"])
def test_strict_fallback_reconciliation_rejects_incomplete(failure: str) -> None:
    provider, plan, observation, fallback = _strict_fallback_case(
        fallback_total=19 if failure == "mismatch" else 20,
        attributed=failure != "unresolved",
    )
    fragments = (observation,) if failure == "missing" else (observation, fallback)

    with pytest.raises(QueryError) as caught:
        provider.assemble(plan, fragments)

    assert caught.value.key == "error.ccusage_project_fallback_incomplete"
    assert caught.value.values["agent"] == "pi"


def test_strict_fallback_reconciles_each_interval_without_aggregate_cancellation() -> None:
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
    with pytest.raises(QueryError) as caught:
        provider.assemble(
            combined,
            (first_a, second_a, fallback(first_b_query, 20), fallback(second_b_query, 10)),
        )
    assert caught.value.key == "error.ccusage_project_fallback_incomplete"


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


def test_range_codex_ranking_normalization_anchors_totals_at_interval_end() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_ranking_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 3)),
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


def test_strict_fallback_normalization_accepts_pi_local_and_generic_absolute_paths(
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
        "ccusage_viz.providers.ccusage.resolve_pi_session_cwds",
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
        "ccusage_viz.providers.ccusage.resolve_pi_session_cwds",
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
        "ccusage_viz.providers.ccusage.resolve_pi_session_cwds",
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
    assert record.project.display_name == "Unassigned"
    assert record.attribution == "unassigned"
    assert record.session_id == "2026/01/03/rollout-missing"
    assert fragment.provider_metadata == ()


def test_codex_incomplete_attribution_retains_session_on_fixed_project_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr("ccusage_viz.providers.ccusage.resolve_codex_session_cwds", lambda _: {})
    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            query,
            json.dumps(
                {
                    "sessions": [
                        {
                            "sessionId": "2026/01/03/rollout-unassigned",
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

    (record,) = fragment.records
    assert record.project is not None
    assert record.project.display_name == "Unassigned"
    assert record.attribution == "unassigned"
    assert record.session_id == "2026/01/03/rollout-unassigned"


def test_codex_normalization_rejects_non_singleton_coverage() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 3)),
    )

    with pytest.raises(QueryError) as caught:
        CCUSAGE_DEFINITION.provider.normalize(PhysicalResult(query, b'{"sessions": []}'))

    assert caught.value.key == "error.ccusage_codex_date_attribution"


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
