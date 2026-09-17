from __future__ import annotations

from ccusage_viz.coverage import DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.options import CommandOptions
from ccusage_viz.query.models import QueryKind, QueryPlan, QuerySpec


def _bounds(options: CommandOptions, compact: bool = False) -> tuple[str, str]:
    since = options.date_range.since.isoformat()
    until = options.date_range.until.isoformat()
    if compact:
        return since.replace("-", ""), until.replace("-", "")
    return since, until


def _timezone(options: CommandOptions) -> tuple[str, ...]:
    if options.date_range.timezone:
        return ("--timezone", options.date_range.timezone)
    return ()


def plan_queries(options: CommandOptions) -> QueryPlan:
    if options.demo:
        return QueryPlan(())
    coverage = DateInterval(options.date_range.since, options.date_range.until)
    project_required = bool(options.projects) or options.by == "project"
    if options.command in {"timeline", "calendar", "stack"} and project_required:
        since, until = _bounds(options, compact=True)
        query = QuerySpec(
            QueryKind.CLAUDE_DAILY_PROJECTS,
            (
                "claude",
                "daily",
                "--instances",
                "--json",
                "--since",
                since,
                "--until",
                until,
                *_timezone(options),
                "--offline",
            ),
            coverage,
        )
        notice = Notice("notice.daily_project_omitted", {"agent": "Codex"})
        return QueryPlan((query,), (notice,))

    if options.command == "ranking" and project_required:
        since, until = _bounds(options)
        compact_since, compact_until = _bounds(options, compact=True)
        claude = QuerySpec(
            QueryKind.CLAUDE_DAILY_PROJECTS,
            (
                "claude",
                "daily",
                "--instances",
                "--json",
                "--since",
                compact_since,
                "--until",
                compact_until,
                *_timezone(options),
                "--offline",
            ),
            coverage,
        )
        codex = QuerySpec(
            QueryKind.CODEX_SESSIONS,
            (
                "codex",
                "session",
                "--json",
                "--since",
                since,
                "--until",
                until,
                *_timezone(options),
                "--offline",
                "--no-cost",
            ),
        )
        return QueryPlan(
            (claude, codex),
            summary_notices=(Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),),
        )

    since, until = _bounds(options)
    unified = QuerySpec(
        QueryKind.UNIFIED_DAILY,
        (
            "daily",
            "--by-agent",
            "--json",
            "--since",
            since,
            "--until",
            until,
            *_timezone(options),
            "--offline",
            "--no-cost",
        ),
        coverage,
    )
    return QueryPlan((unified,))
