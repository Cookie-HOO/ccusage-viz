from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from threading import Event, Thread
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from ccusage_viz.options import StandaloneLaunch

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.errors import QueryError
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
    QueryPlan,
    QuerySpec,
)
from ccusage_viz.query.planner import plan_queries
from ccusage_viz.query.provider import ProviderCapabilities, ProviderDefinition
from ccusage_viz.schema import parse_usage_records

CCUSAGE_PROVIDER = ProviderRef("ccusage")
_STDERR_LIMIT: Final = 16 * 1024
_TERMINATE_GRACE: Final = 0.25
_OPERATION_SOURCES = {
    "unified_daily": QueryKind.UNIFIED_DAILY,
    "claude_daily_projects": QueryKind.CLAUDE_DAILY_PROJECTS,
    "codex_sessions": QueryKind.CODEX_SESSIONS,
}

_OPERATION_KINDS = _OPERATION_SOURCES


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
        records = parse_usage_records(_OPERATION_SOURCES[result.query.operation], data)
        return ProviderResultFragment(
            records,
            (ProviderProvenance(result.query.provider, result.query.fingerprint),),
            DataResolution.DATE,
            result.query.coverage,
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
                query.operation in {"claude_daily_projects", "codex_sessions"}
                for query in plan.queries
            ),
        )


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
        while chunk := pipe.read1(64 * 1024):
            target.extend(chunk)
            if bounded and len(target) > output_limit:
                exceeded.set()
                return
            if not bounded and len(target) > _STDERR_LIMIT:
                del target[:-_STDERR_LIMIT]

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
    stdout_thread.join()
    stderr_thread.join()
    if cancelled.is_set():
        raise QueryError("error.ccusage_cancelled", query=operation)
    if exceeded.is_set():
        raise QueryError("error.ccusage_output_limit", query=operation, limit=output_limit)
    if timed_out:
        raise QueryError("error.ccusage_timeout", query=operation, seconds=timeout)
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
