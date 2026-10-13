from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import timedelta
from threading import Event, Lock, Thread
from typing import Any, Final, Literal, cast

from ccusage_viz.codex_sessions import resolve_codex_session_cwds
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, SourceKind, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.pi_sessions import resolve_pi_session_cwds
from ccusage_viz.project_identity import (
    fixed_project_ref,
    make_project_ref,
    normalized_absolute_project_path,
)
from ccusage_viz.query.models import (
    DataResolution,
    ExecutionContext,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderRef,
    ProviderResult,
    ProviderResultFragment,
    QueryIntent,
    QueryKind,
)
from ccusage_viz.query.provider import ProviderCapabilities, ProviderDefinition
from ccusage_viz.schema import codex_project_identity, parse_project_sessions, parse_usage_records

CCUSAGE_PROVIDER = ProviderRef("ccusage")
_STDERR_LIMIT: Final = 16 * 1024
_TERMINATE_GRACE: Final = 0.25
_OPERATION_SOURCES = {
    "unified_daily": QueryKind.UNIFIED_DAILY,
    "unified_daily_agent_observation": QueryKind.UNIFIED_DAILY,
    "claude_daily_projects": QueryKind.CLAUDE_DAILY_PROJECTS,
    "codex_sessions": QueryKind.CODEX_SESSIONS,
    "codex_ranking_sessions": QueryKind.CODEX_SESSIONS,
}
_PROJECT_ATTRIBUTION_SUPPORTED_AGENTS = frozenset({"claude", "codex"})
_PROJECT_ATTRIBUTION_UNSUPPORTED_AGENTS = frozenset({"antigravity", "opencode"})
_FALLBACK_SCHEDULING_GROUP: Final = "ccusage-project-fallback"
_FALLBACK_SCHEDULING_LIMIT: Final = 4


@dataclass(frozen=True, slots=True)
class _FallbackSourceKey:
    source_id: str | None
    executable: str
    environment_digest: str


@dataclass(frozen=True, slots=True)
class _CcusageQueryMetadata:
    source: _FallbackSourceKey
    revision: int
    role: Literal["project-observation", "project-fallback"]
    observation_id: str
    agent: str | None = None


class _ProjectFallbackMemory:
    def __init__(self) -> None:
        self._lock = Lock()
        self._revisions: dict[_FallbackSourceKey, tuple[int, int]] = {}
        self._agents: dict[_FallbackSourceKey, frozenset[str]] = {}

    def begin(self, source: _FallbackSourceKey) -> tuple[int, frozenset[str]]:
        with self._lock:
            next_revision, accepted_revision = self._revisions.get(source, (0, 0))
            next_revision += 1
            self._revisions[source] = (next_revision, accepted_revision)
            return next_revision, self._agents.get(source, frozenset())

    def replace(self, source: _FallbackSourceKey, revision: int, agents: frozenset[str]) -> None:
        with self._lock:
            next_revision, accepted_revision = self._revisions.get(source, (0, 0))
            if revision < accepted_revision:
                return
            self._revisions[source] = (max(next_revision, revision), revision)
            if agents:
                self._agents[source] = agents
            else:
                self._agents.pop(source, None)


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


def _fallback_source(provider: ProviderRef, context: ExecutionContext | None) -> _FallbackSourceKey:
    if context is None:
        executable = ""
        environment: tuple[tuple[str, str], ...] = ()
    else:
        executable = context.executable
        environment = context.environment
    encoded = json.dumps(environment, ensure_ascii=True, separators=(",", ":"))
    return _FallbackSourceKey(
        provider.source_id,
        executable,
        hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


def _project_observation_query(
    intent: QueryIntent,
    since: str,
    until: str,
    coverage: DateCoverage,
    fallback_state: tuple[_FallbackSourceKey, int, frozenset[str]] | None,
) -> PhysicalQuery:
    if fallback_state is None:
        raise ValueError("project observations require fallback state")
    source, revision, _ = fallback_state
    query = PhysicalQuery(
        intent.provider,
        "unified_daily_agent_observation",
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
    )
    return replace(
        query,
        payload=_CcusageQueryMetadata(source, revision, "project-observation", query.fingerprint),
    )


def _remembered_fallback_queries(
    observation: PhysicalQuery,
    fallback_state: tuple[_FallbackSourceKey, int, frozenset[str]] | None,
) -> tuple[PhysicalQuery, ...]:
    if fallback_state is None:
        return ()
    source, revision, agents = fallback_state
    metadata = _CcusageQueryMetadata(
        source, revision, "project-observation", observation.fingerprint
    )
    return tuple(
        _project_fallback_query(observation, metadata, agent, speculative=True)
        for agent in sorted(agents, key=str.casefold)
    )


def _project_fallback_query(
    observation: PhysicalQuery,
    observation_metadata: _CcusageQueryMetadata,
    agent: str,
    *,
    speculative: bool,
) -> PhysicalQuery:
    since, until = _query_dates(observation.coverage)
    if since is None or until is None:
        raise ValueError("project fallback requires one coverage interval")
    return PhysicalQuery(
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
        required=not speculative,
        payload=_CcusageQueryMetadata(
            observation_metadata.source,
            observation_metadata.revision,
            "project-fallback",
            observation_metadata.observation_id,
            agent,
        ),
        scheduling_group=_FALLBACK_SCHEDULING_GROUP,
        scheduling_limit=_FALLBACK_SCHEDULING_LIMIT,
        speculative=speculative,
    )


def _query_metadata(query: PhysicalQuery) -> _CcusageQueryMetadata | None:
    return query.payload if isinstance(query.payload, _CcusageQueryMetadata) else None


def _normalized_query_metadata(query: PhysicalQuery):
    metadata = _query_metadata(query)
    if metadata is None:
        return ()
    return (
        ("ccusage_role", metadata.role),
        ("ccusage_source_id", metadata.source.source_id),
        ("ccusage_executable", metadata.source.executable),
        ("ccusage_environment_digest", metadata.source.environment_digest),
        ("ccusage_revision", metadata.revision),
        ("ccusage_observation_id", metadata.observation_id),
        ("ccusage_agent", metadata.agent),
    )


def _fragment_query_metadata(
    fragment: ProviderResultFragment,
) -> _CcusageQueryMetadata | None:
    values = dict(fragment.provider_metadata)
    role_value = values.get("ccusage_role")
    revision = values.get("ccusage_revision")
    observation_id = values.get("ccusage_observation_id")
    if (
        role_value not in {"project-observation", "project-fallback"}
        or not isinstance(revision, int)
        or not isinstance(observation_id, str)
    ):
        return None
    source_id = values.get("ccusage_source_id")
    executable = values.get("ccusage_executable")
    environment_digest = values.get("ccusage_environment_digest")
    agent = values.get("ccusage_agent")
    if (
        source_id is not None
        and not isinstance(source_id, str)
        or not isinstance(executable, str)
        or not isinstance(environment_digest, str)
        or agent is not None
        and not isinstance(agent, str)
    ):
        return None
    role = cast(Literal["project-observation", "project-fallback"], role_value)
    return _CcusageQueryMetadata(
        _FallbackSourceKey(source_id, executable, environment_digest),
        revision,
        role,
        observation_id,
        agent,
    )


def _exception_agents(records: tuple[UsageRecord, ...]) -> frozenset[str]:
    return frozenset(
        record.agent.casefold()
        for record in records
        if record.source is SourceKind.UNIFIED_DAILY
        and record.attribution in {"unassigned", "unverified"}
    )


def _project_fallback_replacement_records(
    fragments: tuple[ProviderResultFragment, ...],
) -> tuple[UsageRecord, ...]:
    observations = tuple(
        (metadata, fragment)
        for fragment in fragments
        if (metadata := _fragment_query_metadata(fragment)) is not None
        and metadata.role == "project-observation"
    )
    fallbacks = {
        (metadata.source, metadata.revision, metadata.observation_id, metadata.agent): fragment
        for fragment in fragments
        if (metadata := _fragment_query_metadata(fragment)) is not None
        and metadata.role == "project-fallback"
    }
    reconciled: list[UsageRecord] = []
    for metadata, observation in observations:
        exceptions = _exception_agents(observation.records)
        reconciled.extend(
            record
            for record in observation.records
            if not (
                record.agent.casefold() in exceptions
                and record.source is SourceKind.UNIFIED_DAILY
                and record.attribution in {"unassigned", "unverified"}
            )
        )
        for agent in sorted(exceptions):
            fallback = fallbacks.get(
                (metadata.source, metadata.revision, metadata.observation_id, agent)
            )
            if fallback is None:
                raise QueryError("error.ccusage_project_fallback_incomplete", agent=agent)
            reconciled.extend(fallback.records)
    return tuple(reconciled)


def _days(interval: DateInterval):
    day = interval.since
    while day <= interval.until:
        yield day
        day += timedelta(days=1)


def _fixed_project_observation_records(
    data: object, records: tuple[UsageRecord, ...]
) -> tuple[UsageRecord, ...]:
    """Map non-Claude observations to fixed project groups without losing token usage."""
    if not isinstance(data, dict) or not isinstance(daily := data.get("daily"), list):
        return ()
    rows = (
        row
        for day in daily
        if isinstance(day, dict) and isinstance(day.get("agents"), list)
        for row in day["agents"]
        if isinstance(row, dict)
    )
    projected: list[UsageRecord] = []
    for row, record in zip(rows, records, strict=True):
        project = row.get("project", row.get("cwd", row.get("projectPath")))
        if record.agent.casefold() in _PROJECT_ATTRIBUTION_SUPPORTED_AGENTS:
            continue
        if record.agent.casefold() in _PROJECT_ATTRIBUTION_UNSUPPORTED_AGENTS or not isinstance(
            project, str
        ):
            attribution = "unassigned"
        elif normalized_absolute_project_path(project) is None:
            attribution = "unverified"
        else:
            projected.append(
                replace(record, project=make_project_ref(record.agent, project, path_backed=True))
            )
            continue
        projected.append(
            replace(
                record,
                project=fixed_project_ref(record.agent, attribution),
                attribution=attribution,
                source_project=project if isinstance(project, str) else None,
            )
        )
    return tuple(projected)


def _fallback_agent(operation: str) -> str | None:
    marker = "project_fallback_sessions:"
    return operation.removeprefix(marker) if operation.startswith(marker) else None


def _query_dates(coverage: DateCoverage) -> tuple[str | None, str | None]:
    if len(coverage.intervals) != 1:
        return None, None
    interval = coverage.intervals[0]
    return interval.since.isoformat(), interval.until.isoformat()


def _fallback_session_cwds(agent: str, records: tuple[UsageRecord, ...]) -> dict[str, str]:
    if agent != "pi":
        return {}
    return resolve_pi_session_cwds(
        record.session_id for record in records if record.session_id is not None
    )


def _replace_unverified_records(records: tuple[UsageRecord, ...]) -> tuple[UsageRecord, ...]:
    """Use fully reconciled fallback session totals instead of unverified aggregates."""

    replaceable: set[str] = set()
    agents = {
        record.agent.casefold()
        for record in records
        if record.source is SourceKind.PROJECT_SESSIONS
    }
    for agent in agents:
        observations = tuple(
            record
            for record in records
            if record.agent.casefold() == agent
            and record.source is SourceKind.UNIFIED_DAILY
            and record.attribution in {"unassigned", "unverified"}
        )
        sessions = tuple(
            record
            for record in records
            if record.agent.casefold() == agent and record.source is SourceKind.PROJECT_SESSIONS
        )
        if observations and sum(record.usage.total for record in observations) == sum(
            record.usage.total for record in sessions
        ):
            replaceable.add(agent)
    return tuple(
        record
        for record in records
        if not (
            record.agent.casefold() in replaceable
            and record.source is SourceKind.UNIFIED_DAILY
            and record.attribution in {"unassigned", "unverified"}
        )
    )


def _enrich_codex_project_rows(data: object) -> object:
    if not isinstance(data, dict):
        return data
    rows: list[dict[str, Any]] = []
    for row_field in ("sessions", "session", "data"):
        value = data.get(row_field)
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
            break
    missing = [
        row.get("sessionId")
        for index, row in enumerate(rows)
        if codex_project_identity(row, f"$.sessions[{index}]") is None
    ]
    cwds = resolve_codex_session_cwds(
        session_id for session_id in missing if isinstance(session_id, str)
    )
    for index, row in enumerate(rows):
        if codex_project_identity(row, f"$.sessions[{index}]") is not None:
            continue
        session_id = row.get("sessionId")
        cwd = cwds.get(session_id) if isinstance(session_id, str) else None
        if cwd is not None:
            row["_ccusage_viz_project_cwd"] = cwd
    return data


CCUSAGE_DEFINITION = ProviderDefinition(CcusageProvider())


def _communicate_bounded(
    process: subprocess.Popen[bytes],
    output_limit: int,
    timeout: float,
    cancelled: Event,
    operation: str,
) -> tuple[bytes, bytes]:
    stdout = bytearray()
    stderr = bytearray()
    exceeded = Event()

    def drain(pipe, target: bytearray, *, bounded: bool) -> None:
        try:
            while chunk := pipe.read1(64 * 1024):
                target.extend(chunk)
                if bounded and len(target) > output_limit:
                    exceeded.set()
                    return
                if not bounded and len(target) > _STDERR_LIMIT:
                    del target[:-_STDERR_LIMIT]
        except (OSError, ValueError):
            # Abnormal cleanup closes the parent pipe to release readers even
            # when an escaped descendant still owns the write end.
            return

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = Thread(
        target=drain,
        args=(process.stdout, stdout),
        kwargs={"bounded": True},
        daemon=True,
    )
    stderr_thread = Thread(
        target=drain,
        args=(process.stderr, stderr),
        kwargs={"bounded": False},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None or stdout_thread.is_alive() or stderr_thread.is_alive():
        if cancelled.is_set():
            _stop(process)
            break
        if exceeded.is_set():
            _stop(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _stop(process)
            break
        time.sleep(0.01)
    if cancelled.is_set() or exceeded.is_set() or timed_out:
        # Do not close or join a stream here. Buffered pipe close can itself
        # wait for a concurrent read1(), and an escaped descendant can retain
        # the write end forever. The daemon readers may finish later, but must
        # never retain this query worker or a coordinator execution slot.
        if cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=operation)
        if exceeded.is_set():
            raise QueryError("error.ccusage_output_limit", query=operation, limit=output_limit)
        raise QueryError("error.ccusage_timeout", query=operation, seconds=timeout)
    stdout_thread.join()
    stderr_thread.join()
    return bytes(stdout), bytes(stderr)


def _stop(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with suppress(ChildProcessError):
            process.wait()
        return
    leader_exited = process.poll() is not None
    _signal_process_group(process, signal.SIGTERM)
    if leader_exited:
        time.sleep(_TERMINATE_GRACE)
        _signal_process_group(process, signal.SIGKILL)
        with suppress(ChildProcessError):
            process.wait()
        return
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=_TERMINATE_GRACE)
    _signal_process_group(process, signal.SIGKILL)
    with suppress(ChildProcessError):
        process.wait()


def _signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        with suppress(ProcessLookupError):
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()


def _decode_stderr(value: bytes) -> str:
    return value[-_STDERR_LIMIT:].decode("utf-8", errors="replace")
