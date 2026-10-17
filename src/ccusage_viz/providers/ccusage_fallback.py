from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from threading import Lock
from typing import Any, Final, Literal, cast

from ccusage_viz.codex_sessions import resolve_codex_session_cwds
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import SourceKind, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.pi_sessions import resolve_pi_session_cwds
from ccusage_viz.project_identity import (
    fixed_project_ref,
    make_project_ref,
    normalized_absolute_project_path,
)
from ccusage_viz.query.models import (
    ExecutionContext,
    PhysicalQuery,
    ProviderRef,
    ProviderResultFragment,
    QueryIntent,
    QueryKind,
)
from ccusage_viz.schema import codex_project_identity

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


