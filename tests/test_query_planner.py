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
from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
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
    (query,) = plan_queries(options("timeline"), CCUSAGE_DEFINITION.provider).queries
    assert query.operation == "unified_daily"
    assert query.arguments[:3] == ("daily", "--by-agent", "--json")
    assert query.arguments[-4:] == ("--timezone", "UTC", "--offline", "--no-cost")
    assert query.coverage.intervals == (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),)


def test_project_ranking_uses_fixed_parallel_pair() -> None:
    plan = plan_queries(options("ranking", by="project"), CCUSAGE_DEFINITION.provider)
    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "codex_sessions",
    ]
    assert "--instances" in plan.queries[0].arguments
    assert plan.queries[0].arguments[5] == "20260102"
    assert plan.queries[1].arguments[4] == "2026-01-02"
    expected = (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),)
    assert plan.queries[0].coverage.intervals == expected
    assert plan.queries[1].coverage.intervals == expected
    assert plan.summary_notices == (
        Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),
    )


def test_daily_project_view_omits_codex_with_notice() -> None:
    plan = plan_queries(
        options("stack", projects=("demo",)), CCUSAGE_DEFINITION.provider
    )
    assert len(plan.queries) == 1
    assert plan.queries[0].operation == "claude_daily_projects"
    assert plan.notices[0].key == "notice.daily_project_omitted"


def test_provider_neutral_planner_compiles_demo_acquisition() -> None:
    demo = replace(options("timeline"), host=replace(options("timeline").host, demo_size="small"))

    (query,) = plan_queries(demo, DEMO_DEFINITION.provider).queries

    assert query.provider == DEMO_DEFINITION.provider.provider
    assert query.operation == "generate"
    assert query.arguments == ("small", "2026-01-02", "2026-01-03")


def test_empty_provider_results_preserve_query_attribution_semantics() -> None:
    unified = CCUSAGE_DEFINITION.provider.assemble(
        plan_queries(options("timeline"), CCUSAGE_DEFINITION.provider), ()
    )
    project = CCUSAGE_DEFINITION.provider.assemble(
        plan_queries(options("ranking", by="project"), CCUSAGE_DEFINITION.provider), ()
    )
    demo = DEMO_DEFINITION.provider.assemble(
        plan_queries(
            replace(options("timeline"), host=replace(options("timeline").host, demo_size="small")),
            DEMO_DEFINITION.provider,
        ),
        (),
    )

    assert not unified.includes_project_attribution
    assert project.includes_project_attribution
    assert demo.includes_project_attribution
