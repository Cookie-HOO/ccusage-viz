from dataclasses import replace
from datetime import date

from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.options import (
    CalendarConfig,
    Filters,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.query.models import QueryKind
from ccusage_viz.query.planner import plan_queries


def options(
    command: str, *, by: str | None = None, projects: tuple[str, ...] = ()
) -> StandaloneLaunch:
    date_range = DateRange(date(2026, 1, 2), date(2026, 1, 3), "UTC")
    filters = Filters(projects=projects)
    chart = (
        TimelineConfig("timeline", date_range, filters=filters, by=by)
        if command == "timeline"
        else CalendarConfig("calendar", date_range, filters=filters)
        if command == "calendar"
        else StackConfig("stack", date_range, filters=filters)
        if command == "stack"
        else RankingConfig("ranking", date_range, filters=filters, by=by or "project")
    )
    return StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), chart)


def test_default_plan_uses_unified_by_agent_query() -> None:
    (query,) = plan_queries(options("timeline")).queries
    assert query.kind is QueryKind.UNIFIED_DAILY
    assert query.args[:3] == ("daily", "--by-agent", "--json")
    assert query.args[-4:] == ("--timezone", "UTC", "--offline", "--no-cost")
    assert query.daily_coverage == DateInterval(date(2026, 1, 2), date(2026, 1, 3))


def test_project_ranking_uses_fixed_parallel_pair() -> None:
    plan = plan_queries(options("ranking", by="project"))
    assert [query.kind for query in plan.queries] == [
        QueryKind.CLAUDE_DAILY_PROJECTS,
        QueryKind.CODEX_SESSIONS,
    ]
    assert "--instances" in plan.queries[0].args
    assert plan.queries[0].args[5] == "20260102"
    assert plan.queries[1].args[4] == "2026-01-02"
    assert plan.queries[0].daily_coverage == DateInterval(date(2026, 1, 2), date(2026, 1, 3))
    assert plan.queries[1].daily_coverage is None
    assert plan.summary_notices == (
        Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),
    )


def test_daily_project_view_omits_codex_with_notice() -> None:
    plan = plan_queries(options("stack", projects=("demo",)))
    assert len(plan.queries) == 1
    assert plan.queries[0].kind is QueryKind.CLAUDE_DAILY_PROJECTS
    assert plan.notices[0].key == "notice.daily_project_omitted"


def test_demo_plan_never_queries() -> None:
    demo = replace(options("timeline"), host=replace(options("timeline").host, demo_size="small"))
    assert not plan_queries(demo).queries
