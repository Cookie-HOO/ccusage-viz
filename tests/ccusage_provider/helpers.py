import json
from dataclasses import replace
from datetime import date

from ccusage_viz.coverage import DateInterval
from ccusage_viz.domain import ProjectRef
from ccusage_viz.providers.ccusage import CcusageProvider
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ExecutionContext,
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


def _fallback_replacement_case(
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
