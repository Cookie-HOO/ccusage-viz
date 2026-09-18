from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.options import StandaloneLaunch

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.query.models import (
    DataResolution,
    PhysicalPlan,
    PhysicalQuery,
    ProviderRef,
    QueryIntent,
    QueryKind,
    QueryPlan,
    QuerySpec,
)
from ccusage_viz.query.planner import plan_queries
from ccusage_viz.query.provider import ProviderCapabilities, ProviderDefinition

CCUSAGE_PROVIDER = ProviderRef("ccusage")

_OPERATION_KINDS = {
    "unified_daily": QueryKind.UNIFIED_DAILY,
    "claude_daily_projects": QueryKind.CLAUDE_DAILY_PROJECTS,
    "codex_sessions": QueryKind.CODEX_SESSIONS,
}


@dataclass(frozen=True, slots=True)
class CcusageProvider:
    provider = CCUSAGE_PROVIDER
    capabilities = ProviderCapabilities(
        resolutions=(DataResolution.DATE.value,),
        dimensions=("agent", "model", "project"),
        execution_options=("chart_kind",),
    )

    def compile(self, intent: QueryIntent) -> PhysicalPlan:
        if intent.provider.provider_id != self.provider.provider_id:
            raise ValueError("ccusage provider cannot compile an intent for another provider")
        self.capabilities.validate(intent)
        options = dict(intent.execution_options)
        chart_kind = str(options.get("chart_kind", "timeline"))
        project_required = "project" in intent.dimensions
        mode = (
            "project_ranking"
            if chart_kind == "ranking" and project_required
            else "claude_daily_projects"
            if chart_kind in {"timeline", "calendar", "stack"} and project_required
            else "unified_daily"
        )
        queries: list[PhysicalQuery] = []
        for interval in intent.missing_intervals:
            queries.extend(self._compile_interval(intent, interval, mode))
        notices = (
            (Notice("notice.daily_project_omitted", {"agent": "Codex"}),)
            if mode == "claude_daily_projects"
            else ()
        )
        summary_notices = (
            (Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),)
            if mode == "project_ranking"
            else ()
        )
        return PhysicalPlan(intent.fingerprint, tuple(queries), notices, summary_notices)

    @staticmethod
    def _compile_interval(
        intent: QueryIntent, interval: DateInterval, mode: str
    ) -> tuple[PhysicalQuery, ...]:
        since = interval.since.isoformat()
        until = interval.until.isoformat()
        timezone = ("--timezone", intent.scope.timezone) if intent.scope.timezone else ()
        coverage = DateCoverage.from_interval(interval.since, interval.until)
        if mode == "claude_daily_projects":
            return (
                PhysicalQuery(
                    intent.provider,
                    mode,
                    (
                        "claude",
                        "daily",
                        "--instances",
                        "--json",
                        "--since",
                        since.replace("-", ""),
                        "--until",
                        until.replace("-", ""),
                        *timezone,
                        "--offline",
                    ),
                    intent.execution_context,
                    coverage,
                ),
            )
        if mode == "project_ranking":
            return (
                *CcusageProvider._compile_interval(intent, interval, "claude_daily_projects"),
                PhysicalQuery(
                    intent.provider,
                    "codex_sessions",
                    (
                        "codex",
                        "session",
                        "--json",
                        "--since",
                        since,
                        "--until",
                        until,
                        *timezone,
                        "--offline",
                        "--no-cost",
                    ),
                    intent.execution_context,
                    coverage,
                ),
            )
        if mode != "unified_daily":
            raise ValueError(f"unsupported ccusage query mode: {mode}")
        return (
            PhysicalQuery(
                intent.provider,
                mode,
                (
                    "daily",
                    "--by-agent",
                    "--json",
                    "--since",
                    since,
                    "--until",
                    until,
                    *timezone,
                    "--offline",
                    "--no-cost",
                ),
                intent.execution_context,
                coverage,
            ),
        )

    def fingerprint(self, query: PhysicalQuery) -> str:
        if query.provider.provider_id != self.provider.provider_id:
            raise ValueError("ccusage provider cannot fingerprint another provider's query")
        return query.fingerprint


CCUSAGE_DEFINITION = ProviderDefinition(CcusageProvider())


def plan_ccusage_queries(options: StandaloneLaunch) -> QueryPlan:
    """Temporary adapter for legacy consumers during phased runtime migration."""
    if options.host.demo_size:
        return QueryPlan(())
    return _legacy_plan(plan_queries(options, CCUSAGE_DEFINITION.provider))


def _legacy_plan(physical: PhysicalPlan) -> QueryPlan:
    queries = tuple(
        QuerySpec(
            _OPERATION_KINDS[query.operation],
            query.arguments,
            query.coverage.intervals[0] if query.coverage.intervals else None,
        )
        for query in physical.queries
    )
    return QueryPlan(queries, physical.notices, physical.summary_notices)
