from dataclasses import replace
from datetime import date

from ccusage_viz.acquisition import (
    builtin_summary_query_intent,
    builtin_summary_query_plan,
    custom_dashboard_summary_query_intent,
    custom_historical_query_intent,
    custom_summary_query_intent,
    historical_query_intent,
    monitor_query_intent,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.options import (
    CalendarConfig,
    CustomChartConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    Filters,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.processing.summaries import summary_query_plan
from ccusage_viz.providers.ccusage_definition import CCUSAGE_DEFINITION
from ccusage_viz.providers.custom_command import CUSTOM_COMMAND_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
from ccusage_viz.query.models import QueryTrigger


def options(
    command: str, *, by: str | None = None, projects: tuple[str, ...] = ()
) -> StandaloneLaunch:
    date_range = DateRange(date(2026, 1, 2), date(2026, 1, 3))
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
        StandaloneHostConfig(demo_size=demo_size),
        MonitorConfig("monitor", 300, by=by),
    )


def test_custom_dashboard_summary_intent_uses_dashboard_header_period() -> None:
    dashboard = DashboardLaunch(
        ProcessConfig(query_timeout=12.0, output_limit=2048),
        DashboardHostConfig(header_summary="quarter", timezone="Asia/Shanghai"),
        (),
    )

    intent = custom_dashboard_summary_query_intent(
        CustomCommandSource("reading", ("reading-export", "ccuv")),
        dashboard,
        owner_id="dashboard:header:custom:reading",
        generation=4,
        trigger=QueryTrigger.REFRESH,
        as_of_date=date(2026, 9, 30),
    )
    request = intent.payload

    assert request.dataset_id == "reading"
    assert request.command_argv == ("reading-export", "ccuv")
    assert request.scope == "quarter"
    assert request.current == DateInterval(date(2026, 7, 1), date(2026, 9, 30))
    assert request.sequential == DateInterval(date(2026, 4, 1), date(2026, 6, 30))
    assert request.year_over_year == DateInterval(date(2025, 7, 1), date(2025, 9, 30))
    assert intent.owner_id == "dashboard:header:custom:reading"
    assert intent.generation == 4


def test_matching_custom_header_and_pane_summaries_have_the_same_physical_input() -> None:
    source = CustomCommandSource("reading", ("reading-export", "ccuv"))
    plan = summary_query_plan(date(2026, 9, 30), "month")
    chart = CustomChartConfig(
        "timeline",
        source,
        DateRange(date(2026, 9, 17), date(2026, 9, 30)),
        group_by="book",
        granularity="day",
    )

    pane_summary = custom_summary_query_intent(
        source,
        plan,
        timezone="Asia/Shanghai",
        owner_id="dashboard:pane:1:summary",
        generation=2,
        trigger=QueryTrigger.REFRESH,
    )
    header_summary = custom_summary_query_intent(
        source,
        plan,
        timezone="Asia/Shanghai",
        owner_id="dashboard:header:custom:reading",
        generation=4,
        trigger=QueryTrigger.REFRESH,
    )
    chart_intent = custom_historical_query_intent(
        chart,
        timezone="Asia/Shanghai",
        owner_id="dashboard:pane:1",
        generation=2,
        trigger=QueryTrigger.REFRESH,
    )

    pane_query = CUSTOM_COMMAND_DEFINITION.provider.compile(pane_summary).queries[0]
    header_query = CUSTOM_COMMAND_DEFINITION.provider.compile(header_summary).queries[0]
    chart_query = CUSTOM_COMMAND_DEFINITION.provider.compile(chart_intent).queries[0]

    assert pane_query.fingerprint == header_query.fingerprint
    assert chart_query.fingerprint != pane_query.fingerprint


def test_builtin_summary_query_ignores_chart_display_shape() -> None:
    base = options("ranking", by="project")
    changed = replace(
        base,
        chart=replace(base.chart, by="model", top=3, other="hide"),
    )
    plan = summary_query_plan(date(2026, 9, 30), "day")

    base_intent = builtin_summary_query_intent(
        base,
        CCUSAGE_DEFINITION,
        plan,
        owner_id="dashboard:pane:1:summary",
        generation=0,
        trigger=QueryTrigger.STARTUP,
    )
    changed_intent = builtin_summary_query_intent(
        changed,
        CCUSAGE_DEFINITION,
        plan,
        owner_id="dashboard:pane:1:summary",
        generation=0,
        trigger=QueryTrigger.STARTUP,
    )

    assert base_intent.scope == changed_intent.scope
    assert base_intent.dimensions == changed_intent.dimensions == ("agent",)
    assert dict(base_intent.execution_options) == {"chart_kind": "timeline"}
    assert CCUSAGE_DEFINITION.provider.compile(base_intent).queries[0].operation == "unified_daily"


def test_builtin_summary_plan_follows_timeline_stack_granularity_only() -> None:
    today = date(2026, 9, 30)
    timeline = replace(
        options("timeline"), chart=replace(options("timeline").chart, granularity="month")
    )
    stack = replace(options("stack"), chart=replace(options("stack").chart, granularity="week"))

    assert builtin_summary_query_plan(timeline, today=today).scope == "month"
    assert builtin_summary_query_plan(stack, today=today).scope == "week"
    assert builtin_summary_query_plan(options("calendar"), today=today).scope == "day"
    assert builtin_summary_query_plan(options("ranking"), today=today).scope == "day"


def test_builtin_summary_plan_uses_one_total_for_fixed_range() -> None:
    fixed_range = DateRange(date(2026, 8, 1), date(2026, 8, 19), fixed_bounds=True)
    selected = replace(
        options("timeline"), chart=replace(options("timeline").chart, date_range=fixed_range)
    )

    plan = builtin_summary_query_plan(selected, today=date(2026, 9, 30))

    assert plan.scope == "range"
    assert plan.intervals == (DateInterval(date(2026, 8, 1), date(2026, 8, 19)),)


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


def test_monitor_demo_report_time_is_independent_of_sample_ordinal(
    monkeypatch,
) -> None:
    options = monitor_options(demo_size="small")
    options = replace(options, host=replace(options.host, demo_seed=31))
    monkeypatch.setattr("ccusage_viz.acquisition.time.monotonic", lambda: 123.4)

    first = monitor_query_intent(
        options,
        DEMO_DEFINITION,
        owner_id="standalone:monitor",
        generation=0,
        trigger=QueryTrigger.TICK,
        sample_ordinal=1,
        today=date(2026, 1, 3),
    )
    second = monitor_query_intent(
        options,
        DEMO_DEFINITION,
        owner_id="standalone:monitor",
        generation=0,
        trigger=QueryTrigger.TICK,
        sample_ordinal=99,
        today=date(2026, 1, 3),
    )

    assert (
        first.execution_options
        == second.execution_options
        == (
            ("demo_report_time", 123.4),
            ("demo_seed", 31),
            ("demo_size", "small"),
        )
    )


def test_default_plan_uses_unified_by_agent_query() -> None:
    (query,) = CCUSAGE_DEFINITION.provider.compile(intent(options("timeline"))).queries
    assert query.operation == "unified_daily"
    assert query.arguments[:3] == ("daily", "--by-agent", "--json")
    assert query.arguments[-2:] == ("--offline", "--no-cost")
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


def test_project_ranking_uses_one_codex_range_query() -> None:
    plan = CCUSAGE_DEFINITION.provider.compile(intent(options("ranking", by="project")))
    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_ranking_sessions",
    ]
    assert "--instances" in plan.queries[0].arguments
    assert plan.queries[0].arguments[5] == "20260102"
    assert plan.queries[1].arguments[4:7] == ("2026-01-02", "--until", "2026-01-03")
    assert plan.queries[2].arguments[4:7] == ("2026-01-02", "--until", "2026-01-03")
    assert [query.coverage.intervals for query in plan.queries] == [
        (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),),
        (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),),
        (DateInterval(date(2026, 1, 2), date(2026, 1, 3)),),
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


def test_project_grouped_stack_requests_project_attribution() -> None:
    launch = options("stack")
    grouped = replace(launch, chart=replace(launch.chart, by="project"))

    plan = CCUSAGE_DEFINITION.provider.compile(intent(grouped))

    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_sessions",
        "codex_sessions",
    ]


def test_yearly_project_ranking_uses_one_codex_range_query() -> None:
    launch = options("ranking", by="project")
    yearly = replace(
        launch,
        chart=replace(launch.chart, date_range=DateRange(date(2025, 1, 1), date(2025, 12, 31))),
    )

    plan = CCUSAGE_DEFINITION.provider.compile(intent(yearly))

    assert [query.operation for query in plan.queries] == [
        "claude_daily_projects",
        "unified_daily_agent_observation",
        "codex_ranking_sessions",
    ]
    assert plan.queries[-1].arguments[4:7] == ("2025-01-01", "--until", "2025-12-31")


def test_provider_neutral_planner_compiles_demo_acquisition() -> None:
    demo = replace(options("timeline"), host=replace(options("timeline").host, demo_size="small"))

    (query,) = DEMO_DEFINITION.provider.compile(intent(demo, DEMO_DEFINITION)).queries

    assert query.provider == DEMO_DEFINITION.provider.provider
    assert query.operation == "generate"
    assert query.arguments == ("small", "2026-01-02", "2026-01-03", "0")


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
