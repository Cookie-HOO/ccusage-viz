from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import timedelta
from threading import Event, Thread
from typing import Any, Final

from ccusage_viz.codex_sessions import resolve_codex_session_cwds
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.project_identity import (
    fixed_project_ref,
    make_project_ref,
    normalized_absolute_project_path,
)
from ccusage_viz.query.models import (
    DataResolution,
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
from ccusage_viz.schema import codex_project_identity, parse_usage_records

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


@dataclass(frozen=True, slots=True)
class CcusageProvider:
    provider = CCUSAGE_PROVIDER
    capabilities = ProviderCapabilities(
        resolutions=(DataResolution.DATE.value,),
        dimensions=("agent", "model", "project"),
        execution_options=("chart_kind",),
        dependencies=("ccusage",),
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
        for interval in intent.missing_intervals:
            queries.extend(self._compile_interval(intent, interval, mode))
        notices = (
            (Notice("notice.daily_project_omitted", {"agent": "Codex"}),)
            if mode == "claude_daily_projects"
            else ()
        )
        return PhysicalPlan(intent.fingerprint, tuple(queries), notices)

    @staticmethod
    def _compile_interval(
        intent: QueryIntent, interval: DateInterval, mode: str
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
            return (
                *CcusageProvider._compile_interval(intent, interval, "claude_daily_projects"),
                PhysicalQuery(
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
                ),
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
            observation = PhysicalQuery(
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
        records = parse_usage_records(_OPERATION_SOURCES[result.query.operation], data)
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
        if result.query.operation == "unified_daily_agent_observation":
            records = _fixed_project_observation_records(data, records)
        return ProviderResultFragment(
            records,
            (ProviderProvenance(result.query.provider, result.query.fingerprint),),
            DataResolution.DATE,
            DateCoverage()
            if result.query.operation == "unified_daily_agent_observation"
            else result.query.coverage,
            provider_metadata=(),
        )

    def assemble(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> ProviderResult:
        records = ()
        provenance = ()
        coverage = DateCoverage()
        notices = plan.notices
        for fragment in fragments:
            records += fragment.records
            provenance += fragment.provenance
            coverage = coverage.merge(fragment.coverage)
            notices += fragment.notices
        return ProviderResult(
            records,
            provenance,
            DataResolution.DATE,
            coverage,
            notices,
            plan.summary_notices,
            includes_project_attribution=any(
                query.operation
                in {"claude_daily_projects", "codex_sessions", "codex_ranking_sessions"}
                for query in plan.queries
            )
            or any(record.project is not None for record in records),
        )


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


def _enrich_codex_project_rows(data: object) -> object:
    if not isinstance(data, dict):
        return data
    rows: list[dict[str, Any]] = []
    for field in ("sessions", "session", "data"):
        value = data.get(field)
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
