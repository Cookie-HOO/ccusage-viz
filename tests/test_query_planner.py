from dataclasses import replace
from datetime import date

from ccusage_viz.acquisition import historical_query_intent, monitor_query_intent
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.options import (
    CalendarConfig,
    Filters,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
from ccusage_viz.query.models import QueryTrigger


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


def intent(
    options: StandaloneLaunch,
    definition=CCUSAGE_DEFINITION,
    *,
    owner_id: str = "test",
    generation: int = 0,
    trigger: QueryTrigger = QueryTrigger.STARTUP,
    coverage: DateCoverage | None = None,
    required_coverage: DateCoverage | None = None,
):
    return historical_query_intent(
        options,
        definition,
        owner_id=owner_id,
        generation=generation,
        trigger=trigger,
        coverage=coverage,
        required_coverage=required_coverage,
    )


def monitor_options(*, by: str | None = None, demo_size: str | None = None) -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(timezone="UTC", demo_size=demo_size),
        MonitorConfig("monitor", 300, by=by),
    )


def test_monitor_intent_always_queries_complete_yesterday_today_scope() -> None:
    selected = monitor_query_intent(
        monitor_options(),
        CCUSAGE_DEFINITION,
        owner_id="standalone:monitor",
        generation=3,
        trigger=QueryTrigger.TICK,
        today=date(2026, 1, 3),
    )

    expected = DateInterval(date(2026, 1, 2), date(2026, 1, 3))
    assert selected.scope.intervals == (expected,)
    assert selected.missing_intervals == (expected,)
    assert selected.scope.timezone == "UTC"
    assert selected.dimensions == ("agent",)
    assert dict(selected.execution_options) == {"chart_kind": "monitor"}
    assert CCUSAGE_DEFINITION.provider.compile(selected).queries[0].operation == "unified_daily"


def test_monitor_project_mode_uses_only_claude_daily_projects() -> None:
    selected = monitor_query_intent(
        monitor_options(by="project"),
        CCUSAGE_DEFINITION,
        owner_id="dashboard:pane:1",
        generation=0,
        trigger=QueryTrigger.STARTUP,
        today=date(2026, 1, 3),
    )
    plan = CCUSAGE_DEFINITION.provider.compile(selected)

    assert [query.operation for query in plan.queries] == ["claude_daily_projects"]
    assert plan.notices == (Notice("notice.daily_project_omitted", {"agent": "Codex"}),)


def test_monitor_demo_sample_ordinal_changes_physical_fingerprint() -> None:
    first = monitor_query_intent(
        monitor_options(demo_size="small"),
        DEMO_DEFINITION,
        owner_id="standalone:monitor",
        generation=0,
        trigger=QueryTrigger.TICK,
        sample_ordinal=1,
        today=date(2026, 1, 3),
    )
    second = replace(first, execution_options=(("demo_size", "small"), ("sample_ordinal", 2)))
    first_query = DEMO_DEFINITION.provider.compile(first).queries[0]
    second_query = DEMO_DEFINITION.provider.compile(second).queries[0]

    assert first_query.arguments == ("small", "2026-01-02", "2026-01-03", "1")
    assert first_query.fingerprint != second_query.fingerprint


def test_default_plan_uses_unified_by_agent_query() -> None:
    (query,) = CCUSAGE_DEFINITION.provider.compile(intent(options("timeline"))).queries
    assert query.operation == "unified_daily"
    assert query.arguments[:3] == ("daily", "--by-agent", "--json")
    assert query.arguments[-4:] == ("--timezone", "UTC", "--offline", "--no-cost")
    assert query.coverage.intervals == (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),)


def test_composition_preserves_owner_lifecycle_and_missing_coverage() -> None:
    selected = intent(
        options("timeline"),
        owner_id="dashboard:pane:2",
        generation=7,
        trigger=QueryTrigger.REFRESH,
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 2)),
    )

    assert selected.owner_id == "dashboard:pane:2"
    assert selected.generation == 7
    assert selected.trigger is QueryTrigger.REFRESH
    assert selected.missing_intervals == (DateInterval(date(2026, 1, 3), date(2026, 1, 3)),)
    (query,) = CCUSAGE_DEFINITION.provider.compile(selected).queries
    assert query.arguments[4:7] == ("2026-01-03", "--until", "2026-01-03")


def test_historical_intent_preserves_disjoint_required_coverage() -> None:
    required = DateCoverage(
        (
            DateInterval(date(2025, 12, 26), date(2025, 12, 26)),
            DateInterval(date(2026, 1, 2), date(2026, 1, 3)),
        )
    )
    accepted = DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 2))

    selected = intent(
        options("timeline"),
        coverage=accepted,
        required_coverage=required,
    )

    assert selected.scope.intervals == required.intervals
    assert selected.missing_intervals == (
        DateInterval(date(2025, 12, 26), date(2025, 12, 26)),
        DateInterval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    assert len(CCUSAGE_DEFINITION.provider.compile(selected).queries) == 2


def test_project_ranking_uses_daily_codex_queries() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent(options("ranking", by="project")))
    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_sessions",
        "codex_sessions",
    ]
    assert "--instances" in plan.queries[0].arguments
    assert plan.queries[0].arguments[5] == "20260102"
    assert plan.queries[1].arguments[4:7] == ("2026-01-02", "--until", "2026-01-03")
    assert [query.arguments[4:7] for query in plan.queries[2:]] == [
        ("2026-01-02", "--until", "2026-01-02"),
        ("2026-01-03", "--until", "2026-01-03"),
    ]
    assert plan.queries[0].coverage.intervals == (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),)
    assert plan.queries[1].coverage.intervals == (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),)
    assert [query.coverage.intervals for query in plan.queries[2:]] == [
        (DateInterval(date(2026, 1, 2), date(2026, 1, 2)),),
        (DateInterval(date(2026, 1, 3), date(2026, 1, 3)),),
    ]
    assert plan.summary_notices == ()


def test_historical_project_view_uses_daily_codex_queries() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent(options("stack", projects=("demo",))))

    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_sessions",
        "codex_sessions",
    ]
    assert plan.notices == ()


def test_provider_neutral_planner_compiles_demo_acquisition() -> None:
    demo = replace(options("timeline"), host=replace(options("timeline").host, demo_size="small"))

    (query,) = DEMO_DEFINITION.provider.compile(intent(demo, DEMO_DEFINITION)).queries

    assert query.provider == DEMO_DEFINITION.provider.provider
    assert query.operation == "generate"
    assert query.arguments == ("small", "2026-01-02", "2026-01-03")


def test_empty_provider_results_preserve_query_attribution_semantics() -> None:
    unified = CCUSAGE_DEFINITION.provider.assemble(
        CCUSAGE_DEFINITION.provider.compile(intent(options("timeline"))), ()
    )
    project = CCUSAGE_DEFINITION.provider.assemble(
        CCUSAGE_DEFINITION.provider.compile(intent(options("ranking", by="project"))), ()
    )
    demo = DEMO_DEFINITION.provider.assemble(
        DEMO_DEFINITION.provider.compile(
            intent(
                replace(
                    options("timeline"),
                    host=replace(options("timeline").host, demo_size="small"),
                ),
                DEMO_DEFINITION,
            )
        ),
        (),
    )

    assert not unified.includes_project_attribution
    assert project.includes_project_attribution
    assert demo.includes_project_attribution
