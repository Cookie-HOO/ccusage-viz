from __future__ import annotations

from ccusage_viz.coverage import DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.options import MonitorConfig, StandaloneLaunch
from ccusage_viz.query.models import QueryKind, QueryPlan, QuerySpec


def _bounds(options: StandaloneLaunch, compact: bool = False) -> tuple[str, str]:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical query planning does not support monitor configurations")
    since = options.chart.date_range.since.isoformat()
    until = options.chart.date_range.until.isoformat()
    if compact:
        return since.replace("-", ""), until.replace("-", "")
    return since, until


def _timezone(options: StandaloneLaunch) -> tuple[str, ...]:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical query planning does not support monitor configurations")
    if options.chart.date_range.timezone:
        return ("--timezone", options.chart.date_range.timezone)
    return ()


def plan_queries(options: StandaloneLaunch) -> QueryPlan:
    if options.host.demo_size:
        return QueryPlan(())
    chart = options.chart
    if isinstance(chart, MonitorConfig):
        raise TypeError("historical query planning does not support monitor configurations")
    coverage = DateInterval(chart.date_range.since, chart.date_range.until)
    project_required = bool(chart.filters.projects) or getattr(chart, "by", None) == "project"
    if options.chart.kind in {"timeline", "calendar", "stack"} and project_required:
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

    if options.chart.kind == "ranking" and project_required:
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
