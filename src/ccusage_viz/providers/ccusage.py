from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field, replace
from threading import Event

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, SourceKind, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.project_identity import make_project_ref, normalized_absolute_project_path
from ccusage_viz.providers.ccusage_fallback import (
    _OPERATION_SOURCES,
    CCUSAGE_PROVIDER,
    _days,
    _enrich_codex_project_rows,
    _exception_agents,
    _fallback_agent,
    _fallback_session_cwds,
    _fallback_source,
    _FallbackSourceKey,
    _fixed_project_observation_records,
    _fragment_query_metadata,
    _normalized_query_metadata,
    _project_fallback_query,
    _project_fallback_replacement_records,
    _project_observation_query,
    _ProjectFallbackMemory,
    _query_dates,
    _query_metadata,
    _remembered_fallback_queries,
    _replace_unverified_records,
)
from ccusage_viz.providers.ccusage_process import _communicate_bounded, _decode_stderr
from ccusage_viz.query.models import (
    DataResolution,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderResult,
    ProviderResultFragment,
    QueryIntent,
)
from ccusage_viz.query.provider import ProviderCapabilities
from ccusage_viz.schema import parse_project_sessions, parse_usage_records


@dataclass(frozen=True, slots=True)
class CcusageProvider:
    provider = CCUSAGE_PROVIDER
    capabilities = ProviderCapabilities(
        resolutions=(DataResolution.DATE.value,),
        dimensions=("agent", "model", "project"),
        execution_options=("chart_kind",),
        dependencies=("ccusage",),
    )
    _fallback_memory: _ProjectFallbackMemory = field(
        default_factory=_ProjectFallbackMemory, compare=False, repr=False
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
            if project_required and chart_kind == "ranking"
            else "project_daily"
            if project_required and chart_kind != "monitor"
            else "claude_daily_projects"
            if chart_kind == "monitor" and project_required
            else "unified_daily"
        )
        queries: list[PhysicalQuery] = []
        fallback_state: tuple[_FallbackSourceKey, int, frozenset[str]] | None = None
        if mode in {"project_daily", "project_ranking"}:
            source = _fallback_source(intent.provider, intent.execution_context)
            revision, agents = self._fallback_memory.begin(source)
            fallback_state = source, revision, agents
        for interval in intent.missing_intervals:
            queries.extend(self._compile_interval(intent, interval, mode, fallback_state))
        notices = (
            (Notice("notice.daily_project_omitted", {"agent": "Codex"}),)
            if mode == "claude_daily_projects"
            else ()
        )
        return PhysicalPlan(intent.fingerprint, tuple(queries), notices)

    @staticmethod
    def _compile_interval(
        intent: QueryIntent,
        interval: DateInterval,
        mode: str,
        fallback_state: tuple[_FallbackSourceKey, int, frozenset[str]] | None = None,
    ) -> tuple[PhysicalQuery, ...]:
        since = interval.since.isoformat()
        until = interval.until.isoformat()
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
                        "--offline",
                    ),
                    intent.execution_context,
                    coverage,
                ),
            )
        if mode == "project_daily":
            observation = _project_observation_query(intent, since, until, coverage, fallback_state)
            fallbacks = _remembered_fallback_queries(observation, fallback_state)
            return (
                *CcusageProvider._compile_interval(intent, interval, "claude_daily_projects"),
                observation,
                *fallbacks,
                *tuple(
                    PhysicalQuery(
                        intent.provider,
                        "codex_sessions",
                        (
                            "codex",
                            "session",
                            "--json",
                            "--since",
                            day.isoformat(),
                            "--until",
                            day.isoformat(),
                            "--offline",
                            "--no-cost",
                        ),
                        intent.execution_context,
                        DateCoverage.from_interval(day, day),
                    )
                    for day in _days(interval)
                ),
            )
        if mode == "project_ranking":
            observation = _project_observation_query(intent, since, until, coverage, fallback_state)
            codex = PhysicalQuery(
                intent.provider,
                "codex_ranking_sessions",
                (
                    "codex",
                    "session",
                    "--json",
                    "--since",
                    since,
                    "--until",
                    until,
                    "--offline",
                    "--no-cost",
                ),
                intent.execution_context,
                coverage,
            )
            return (
                *CcusageProvider._compile_interval(intent, interval, "claude_daily_projects"),
                observation,
                *_remembered_fallback_queries(observation, fallback_state),
                codex,
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

    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
        context = query.execution_context
        if context is None:
            raise ValueError("ccusage physical queries require an execution context")
        environment = os.environ.copy()
        environment.update(context.environment)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [context.executable, *query.arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=os.name == "posix",
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                env=environment,
            )
            stdout, stderr = _communicate_bounded(
                process,
                context.output_limit,
                context.timeout,
                cancelled,
                query.operation,
            )
        except FileNotFoundError as exc:
            raise QueryError("error.ccusage_missing", binary=context.executable) from exc
        except OSError as exc:
            raise QueryError("error.ccusage_start", query=query.operation, detail=str(exc)) from exc
        if process.returncode != 0:
            raise QueryError(
                "error.ccusage_failed",
                query=query.operation,
                code=process.returncode,
                stderr=_decode_stderr(stderr),
            )
        if len(stdout) > context.output_limit:
            raise QueryError(
                "error.ccusage_output_limit",
                query=query.operation,
                limit=context.output_limit,
            )
        return PhysicalResult(query, stdout, stderr)

    def normalize(self, result: PhysicalResult) -> ProviderResultFragment:
        try:
            text = result.payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise QueryError("error.ccusage_utf8", query=result.query.operation) from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QueryError(
                "error.ccusage_json",
                query=result.query.operation,
                line=exc.lineno,
                column=exc.colno,
                stderr=_decode_stderr(result.diagnostics),
            ) from exc
        if result.query.operation in {"codex_sessions", "codex_ranking_sessions"}:
            data = _enrich_codex_project_rows(data)
        fallback_agent = _fallback_agent(result.query.operation)
        records = (
            parse_project_sessions(data, fallback_agent)
            if fallback_agent is not None
            else parse_usage_records(_OPERATION_SOURCES[result.query.operation], data)
        )
        if result.query.operation == "codex_sessions":
            intervals = result.query.coverage.intervals
            if len(intervals) != 1 or intervals[0].since != intervals[0].until:
                raise QueryError("error.ccusage_codex_date_attribution")
            records = tuple(replace(record, day=intervals[0].since) for record in records)
        elif result.query.operation == "codex_ranking_sessions":
            intervals = result.query.coverage.intervals
            if len(intervals) != 1:
                raise QueryError("error.ccusage_codex_date_attribution")
            # Session reports aggregate each session across the requested range.
            # Project ranking consumes period totals only, so anchor these private
            # range aggregates at the interval end without claiming daily detail.
            records = tuple(replace(record, day=intervals[0].until) for record in records)
        elif fallback_agent is not None:
            intervals = result.query.coverage.intervals
            if len(intervals) != 1:
                raise QueryError("error.ccusage_codex_date_attribution")
            cwds = _fallback_session_cwds(fallback_agent, records)
            normalized: list[UsageRecord] = []
            for record in records:
                candidate = cwds.get(record.session_id or "") or record.source_project
                path = (
                    normalized_absolute_project_path(candidate) if candidate is not None else None
                )
                normalized.append(
                    replace(
                        record,
                        day=intervals[0].until,
                        project=make_project_ref(fallback_agent, path, path_backed=True),
                        attribution=None,
                    )
                    if path is not None
                    else replace(record, day=intervals[0].until)
                )
            records = tuple(normalized)
        if result.query.operation == "unified_daily_agent_observation":
            records = _fixed_project_observation_records(data, records)
        return ProviderResultFragment(
            records,
            (ProviderProvenance(result.query.provider, result.query.fingerprint),),
            DataResolution.DATE,
            DateCoverage()
            if result.query.operation == "unified_daily_agent_observation"
            else result.query.coverage,
            provider_metadata=_normalized_query_metadata(result.query),
        )

    def resolve_queries(
        self,
        plan: PhysicalPlan,
        primary_fragments: tuple[ProviderResultFragment, ...],
    ) -> tuple[PhysicalQuery, ...]:
        observations = {
            metadata.observation_id: (metadata, fragment)
            for fragment in primary_fragments
            if (metadata := _fragment_query_metadata(fragment)) is not None
            and metadata.role == "project-observation"
        }
        by_revision: dict[tuple[_FallbackSourceKey, int], set[str]] = {}
        required: list[PhysicalQuery] = []
        for observation_id, (metadata, fragment) in observations.items():
            agents = _exception_agents(fragment.records)
            by_revision.setdefault((metadata.source, metadata.revision), set()).update(agents)
            observation = next(
                (
                    query
                    for query in plan.queries
                    if (query_metadata := _query_metadata(query)) is not None
                    and query_metadata.role == "project-observation"
                    and query_metadata.observation_id == observation_id
                ),
                None,
            )
            if observation is None:
                continue
            required.extend(
                _project_fallback_query(observation, metadata, agent, speculative=False)
                for agent in sorted(agents, key=str.casefold)
            )
        for (source, revision), agents in by_revision.items():
            self._fallback_memory.replace(source, revision, frozenset(agents))
        return tuple(required)

    def supplemental_queries(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> tuple[PhysicalQuery, ...]:
        """Try session reports for agents whose primary records lack a verified path."""

        observation = next(
            (
                query
                for query in plan.queries
                if query.operation == "unified_daily_agent_observation"
            ),
            None,
        )
        if observation is None:
            return ()
        since, until = _query_dates(observation.coverage)
        if since is None or until is None:
            return ()
        agents = tuple(
            sorted(
                {
                    record.agent.casefold()
                    for fragment in fragments
                    for record in fragment.records
                    if record.source is SourceKind.UNIFIED_DAILY
                    and record.attribution in {"unassigned", "unverified"}
                }
            )
        )
        return tuple(
            PhysicalQuery(
                observation.provider,
                f"project_fallback_sessions:{agent}",
                (
                    agent,
                    "session",
                    "--json",
                    "--since",
                    since,
                    "--until",
                    until,
                    "--offline",
                    "--no-cost",
                ),
                observation.execution_context,
                observation.coverage,
                required=False,
            )
            for agent in agents
        )

    def assemble(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> ProviderResult:
        tagged = any(_fragment_query_metadata(fragment) is not None for fragment in fragments)
        records: tuple[UsageRecord, ...] = ()
        provenance = ()
        coverage = DateCoverage()
        notices = plan.notices
        if tagged:
            records = _project_fallback_replacement_records(fragments)
        for fragment in fragments:
            metadata = _fragment_query_metadata(fragment)
            if not tagged or metadata is None:
                records += fragment.records
            provenance += fragment.provenance
            coverage = coverage.merge(fragment.coverage)
            notices += fragment.notices
        if not tagged:
            records = _replace_unverified_records(records)
        return ProviderResult(
            records,
            provenance,
            DataResolution.DATE,
            coverage,
            notices,
            plan.summary_notices,
            includes_project_attribution=any(
                query.operation
                in {
                    "claude_daily_projects",
                    "codex_sessions",
                    "codex_ranking_sessions",
                }
                for query in plan.queries
            )
            or any(record.project is not None for record in records),
        )
