from dataclasses import replace
from datetime import UTC, date, datetime

from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.domain import ModelBreakdown, ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.monitor_component import MonitorCompletion, MonitorComponent
from ccusage_viz.options import (
    ChartPresentation,
    Filters,
    MonitorConfig,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
)
from ccusage_viz.query.models import QueryTrigger


def usage(total: int) -> TokenUsage:
    return TokenUsage(total, total, 0, 0, 0)


def record(total: int, *, models: dict[str, int] | None = None) -> UsageRecord:
    return UsageRecord(
        date(2026, 9, 19),
        "claude",
        usage(total),
        SourceKind.UNIFIED_DAILY,
        models=tuple(ModelBreakdown(name, usage(value)) for name, value in (models or {}).items()),
    )


def options(
    *,
    by: str | None = None,
    style: str = "bars",
    window_seconds: int = 300,
    top: int | None = None,
    filters: Filters | None = None,
    project_aggregation: str = "name",
) -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(interval=10),
        MonitorConfig(
            "monitor",
            window_seconds,
            filters=filters or Filters(),
            presentation=ChartPresentation(style=style),
            by=by,
            top=top,
            project_aggregation=project_aggregation,
        ),
    )


def completion(
    component: MonitorComponent,
    records: tuple[UsageRecord, ...],
    *,
    elapsed: float = 0.1,
) -> MonitorCompletion:
    return MonitorCompletion(component.generation, component.candidate, records, elapsed)


def test_monitor_component_submits_provider_backed_demo_samples() -> None:
    launch = replace(options(), host=replace(options().host, demo_size="small"))
    runtime = build_query_runtime()
    component = MonitorComponent(
        launch,
        registry=build_chart_registry(),
        owner_id="standalone:monitor",
        runtime=runtime,
    )

    try:
        assert component.monitor_started_at is None
        first = component.submit(QueryTrigger.STARTUP, sample_ordinal=1, today=date(2026, 9, 19))
        started_at = component.monitor_started_at
        assert started_at is not None
        first_result = first.result()
        second = component.submit(QueryTrigger.TICK, sample_ordinal=2, today=date(2026, 9, 19))
        second_result = second.result()
        component.submit(QueryTrigger.STARTUP, sample_ordinal=3, today=date(2026, 9, 19)).cancel()
        component.submit(QueryTrigger.REFRESH, sample_ordinal=4, today=date(2026, 9, 19)).cancel()

        assert first.generation == component.generation
        assert first.options == launch
        assert first_result.records
        assert sum(record.usage.total for record in second_result.records) > sum(
            record.usage.total for record in first_result.records
        )
        assert first_result.elapsed >= 0
        assert component.monitor_started_at == started_at
    finally:
        runtime.cancel()


def test_monitor_component_preserves_an_injected_start_marker() -> None:
    started_at = datetime(2026, 9, 19, 11, 59, tzinfo=UTC)
    runtime = build_query_runtime()
    component = MonitorComponent(
        replace(options(), host=replace(options().host, demo_size="small")),
        registry=build_chart_registry(),
        runtime=runtime,
        monitor_started_at=started_at,
    )

    try:
        component.submit(QueryTrigger.STARTUP, sample_ordinal=1, today=date(2026, 9, 19)).cancel()
        assert component.monitor_started_at == started_at
    finally:
        runtime.cancel()


def test_monitor_component_accepts_cumulative_samples_and_projects_timeline() -> None:
    started_at = datetime(2026, 9, 19, 11, 59, tzinfo=UTC)
    component = MonitorComponent(
        options(), registry=build_chart_registry(), monitor_started_at=started_at
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

    assert component.accept(completion(component, (record(100),)), now=0, wall=wall)
    baseline = component.timeline_model(now=0, count=3, wall=wall)
    assert baseline.observed_scope is not None
    assert baseline.observed_scope.state == "sampling"
    assert baseline.metric.unit == "tpm"

    assert component.accept(completion(component, (record(160),)), now=10, wall=wall)
    model = component.timeline_model(now=10, count=3, wall=wall)

    assert model.observed_scope is not None
    assert model.observed_scope.state == "ready"
    assert model.metric.unit == "tpm"
    assert model.observed_at[-1] == wall
    assert model.monitor_started_at == started_at
    assert model.observed_series[0].key == "Total"
    assert model.observed_series[0].values[-1] == 360
    assert model.y_axis_max == 500
    assert component.last_elapsed == 0.1
    assert component.accepted_records == (record(160),)
    assert component.error is None


def test_monitor_list_uses_the_same_observed_ranking_model() -> None:
    ranking = MonitorComponent(
        options(by="model", style="ranking"), registry=build_chart_registry()
    )
    listing = MonitorComponent(options(by="model", style="list"), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    samples = (
        (record(100, models={"a": 60, "b": 40}),),
        (record(160, models={"a": 100, "b": 60}),),
    )
    for component in (ranking, listing):
        for now, records in zip((0, 10), samples, strict=True):
            assert component.accept(completion(component, records), now=now, wall=wall)

    assert ranking.model(now=10, count=4, wall=wall) == listing.model(now=10, count=4, wall=wall)


def test_monitor_project_ranking_and_list_share_safe_merged_labels() -> None:
    ranking = MonitorComponent(
        options(by="project", style="ranking"), registry=build_chart_registry()
    )
    listing = MonitorComponent(options(by="project", style="list"), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    samples = (
        (
            UsageRecord(
                date(2026, 9, 19),
                "claude",
                usage(100),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                ProjectRef("claude", "-private-work-app", "app"),
            ),
            UsageRecord(
                date(2026, 9, 19),
                "codex",
                usage(100),
                SourceKind.CODEX_SESSIONS,
                ProjectRef("codex", "/private/work/app", "app"),
            ),
        ),
        (
            UsageRecord(
                date(2026, 9, 19),
                "claude",
                usage(160),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                ProjectRef("claude", "-private-work-app", "app"),
            ),
            UsageRecord(
                date(2026, 9, 19),
                "codex",
                usage(140),
                SourceKind.CODEX_SESSIONS,
                ProjectRef("codex", "/private/work/app", "app"),
            ),
        ),
    )
    for component in (ranking, listing):
        for now, records in zip((0, 10), samples, strict=True):
            assert component.accept(completion(component, records), now=now, wall=wall)

    entries = ranking.ranking_model(now=10, count=4, wall=wall).observed_entries
    assert {(entry.agent, entry.label) for entry in entries} == {(None, "app")}
    assert ranking.model(now=10, count=4, wall=wall) == listing.model(now=10, count=4, wall=wall)


def test_monitor_project_aggregation_switches_presentation_without_rebaseline() -> None:
    component = MonitorComponent(
        options(by="project", style="ranking"), registry=build_chart_registry()
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    samples = (
        (
            UsageRecord(
                date(2026, 9, 19),
                "claude",
                usage(100),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                ProjectRef("claude", "-private-work-app", "app"),
            ),
            UsageRecord(
                date(2026, 9, 19),
                "codex",
                usage(100),
                SourceKind.CODEX_SESSIONS,
                ProjectRef("codex", "/private/work/app", "app"),
            ),
        ),
        (
            UsageRecord(
                date(2026, 9, 19),
                "claude",
                usage(160),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                ProjectRef("claude", "-private-work-app", "app"),
            ),
            UsageRecord(
                date(2026, 9, 19),
                "codex",
                usage(140),
                SourceKind.CODEX_SESSIONS,
                ProjectRef("codex", "/private/work/app", "app"),
            ),
        ),
    )
    for now, records in zip((0, 10), samples, strict=True):
        assert component.accept(completion(component, records), now=now, wall=wall)

    name_entries = component.ranking_model(now=10, count=4, wall=wall).observed_entries
    intervals = tuple(component.observer.intervals)
    generation = component.generation
    component.configure(
        replace(
            component.candidate,
            chart=replace(component.candidate.chart, project_aggregation="exact"),
        ),
        data_affecting=False,
    )
    exact_entries = component.ranking_model(now=10, count=4, wall=wall).observed_entries

    assert component.generation == generation
    assert not component.rebaseline_pending
    assert tuple(component.observer.intervals) == intervals
    assert [(entry.agent, entry.label, entry.value) for entry in name_entries] == [
        (None, "app", 100.0)
    ]
    assert {(entry.agent, entry.label, entry.value) for entry in exact_entries} == {
        ("claude", "claude · app", 60.0),
        ("codex", "codex · app", 40.0),
    }
    assert sum(entry.value for entry in exact_entries) == name_entries[0].value


def test_monitor_component_total_and_model_presentation_stays_at_accepted_sample() -> None:
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    later_wall = datetime(2026, 9, 19, 12, 30, tzinfo=UTC)
    total = MonitorComponent(options(), registry=build_chart_registry())
    model = MonitorComponent(options(by="model", style="ranking"), registry=build_chart_registry())
    for component in (total, model):
        component.accept(
            completion(component, (record(100, models={"a": 60, "b": 40}),)),
            now=0,
            wall=wall,
        )
        component.accept(
            completion(component, (record(160, models={"a": 100, "b": 60}),)),
            now=10,
            wall=wall,
        )

    total_accepted = total.timeline_model(now=10, count=4, wall=wall)
    model_accepted = model.ranking_model(now=10, count=4, wall=wall)

    assert total.timeline_model(now=1800, count=4, wall=later_wall) == total_accepted
    assert model.ranking_model(now=1800, count=4, wall=later_wall) == model_accepted
    assert (
        total.preview(total.candidate).timeline_model(now=1800, count=4, wall=later_wall)
        == total_accepted
    )
    assert (
        model.preview(model.candidate).ranking_model(now=1800, count=4, wall=later_wall)
        == model_accepted
    )


def test_monitor_component_agent_and_project_values_stay_at_accepted_sample() -> None:
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    later_wall = datetime(2026, 9, 19, 12, 30, tzinfo=UTC)
    agent = MonitorComponent(options(by="agent", style="ranking"), registry=build_chart_registry())
    project = MonitorComponent(
        options(by="project", style="ranking"), registry=build_chart_registry()
    )
    for component in (agent, project):
        component.accept(completion(component, (record(100),)), now=0, wall=wall)
        component.accept(completion(component, (record(130),)), now=10, wall=wall)

    agent_accepted = agent.ranking_model(now=10, count=4, wall=wall)
    project_accepted = project.ranking_model(now=10, count=4, wall=wall)

    assert agent.ranking_model(now=1800, count=4, wall=later_wall) == agent_accepted
    assert project.ranking_model(now=1800, count=4, wall=later_wall) == project_accepted


def test_monitor_component_next_accept_advances_projection_but_stale_does_not() -> None:
    component = MonitorComponent(options(), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100),)), now=0, wall=wall)
    component.accept(completion(component, (record(160),)), now=10, wall=wall)
    accepted = component.timeline_model(now=10, count=4, wall=wall)

    stale = completion(component, (record(220),))
    component.configure(options(window_seconds=600), data_affecting=True)
    assert not component.accept(stale, now=20, wall=wall)
    cleared = component.timeline_model(now=1800, count=4, wall=wall)
    assert cleared.observed_series == accepted.observed_series
    assert cleared.observed_current == ()

    component.accept(completion(component, (record(220),)), now=20, wall=wall)
    advanced = component.timeline_model(now=20, count=4, wall=wall)
    assert advanced != accepted
    assert (
        component.timeline_model(
            now=1800,
            count=4,
            wall=datetime(2026, 9, 19, 12, 30, tzinfo=UTC),
        )
        == advanced
    )


def test_monitor_component_uses_bucket_token_growth_for_agent_ranking() -> None:
    component = MonitorComponent(
        options(by="agent", style="ranking"), registry=build_chart_registry()
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100),)), now=0, wall=wall)
    component.accept(completion(component, (record(130),)), now=10, wall=wall)

    model = component.ranking_model(now=10, count=4, wall=wall)

    assert model.metric.unit == "tokens"
    assert [(entry.key, entry.value) for entry in model.observed_entries] == [("claude", 30)]


def test_monitor_component_projects_model_top_other_and_tracks_changes() -> None:
    component = MonitorComponent(
        options(by="model", style="ranking", top=1), registry=build_chart_registry()
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(
        completion(component, (record(100, models={"a": 60, "b": 40}),)), now=0, wall=wall
    )
    component.accept(
        completion(component, (record(160, models={"a": 100, "b": 60}),)), now=10, wall=wall
    )
    first = component.ranking_model(now=10, count=4, wall=wall)
    component.accept(
        completion(component, (record(250, models={"a": 130, "b": 120}),)), now=20, wall=wall
    )
    second = component.ranking_model(now=20, count=4, wall=wall)

    assert [entry.key for entry in first.observed_entries] == ["a", "Other"]
    assert [entry.key for entry in second.observed_entries] == ["b", "Other"]
    assert "Other" not in component.rank_deltas
    assert component.deltas


def test_monitor_component_rejects_stale_completion_and_failure() -> None:
    component = MonitorComponent(options(), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    stale = completion(component, (record(100),))
    component.configure(options(window_seconds=600), data_affecting=True)

    assert not component.accept(stale, now=0, wall=wall)
    assert component.accepted_records == ()
    assert component.observer.previous is None
    assert not component.fail(RuntimeError("stale"), generation=0)
    assert component.error is None


def test_monitor_candidate_preview_hides_accepted_values_for_data_configuration() -> None:
    component = MonitorComponent(
        options(by="model", style="ranking"), registry=build_chart_registry()
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(
        completion(component, (record(100, models={"a": 60, "b": 40}),)), now=0, wall=wall
    )
    component.accept(
        completion(component, (record(160, models={"a": 100, "b": 60}),)), now=10, wall=wall
    )
    accepted_buckets = component.buckets(4, now=10, wall=wall)
    accepted_options = component.accepted_options

    changed = replace(
        component.candidate,
        chart=replace(
            component.candidate.chart,
            by="agent",
            window_seconds=600,
            filters=Filters(agents=("claude",)),
        ),
    )
    component.configure(changed, data_affecting=True)
    preview = component.display()

    assert preview.display_query_pending
    assert preview.ranking_model(now=10, wall=wall).observed_entries == ()
    assert preview.timeline_model(now=10, count=4, wall=wall).observed_series == ()
    assert component.accepted_options == accepted_options
    assert component.buckets(4, now=10, wall=wall) == accepted_buckets


def test_monitor_window_preview_reprojects_retained_values_without_querying() -> None:
    started_at = datetime(2026, 9, 19, 11, 59, tzinfo=UTC)
    component = MonitorComponent(
        options(window_seconds=300),
        registry=build_chart_registry(),
        monitor_started_at=started_at,
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100),)), now=0, wall=wall)
    component.accept(completion(component, (record(160),)), now=10, wall=wall)

    component.configure(
        replace(component.candidate, chart=replace(component.candidate.chart, window_seconds=600)),
        data_affecting=False,
    )
    preview = component.display()

    assert not preview.display_query_pending
    assert preview.monitor_started_at == started_at
    assert preview.timeline_model(now=10, count=4, wall=wall).monitor_started_at == started_at
    assert preview.observer.window_seconds == 600
    assert preview.ranking_model(now=10, wall=wall).observed_entries == (
        component.ranking_model(now=10, wall=wall).observed_entries
    )


def test_monitor_data_candidate_marker_clears_after_matching_sample() -> None:
    component = MonitorComponent(options(by="model"), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(
        completion(component, (record(100, models={"a": 60, "b": 40}),)), now=0, wall=wall
    )
    component.configure(
        replace(component.candidate, chart=replace(component.candidate.chart, by="agent")),
        data_affecting=True,
    )

    assert component.display().display_query_pending
    assert component.accept(completion(component, (record(160),)), now=10, wall=wall)
    assert not component.display().display_query_pending


def test_monitor_presentation_preview_retains_accepted_values() -> None:
    component = MonitorComponent(options(), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100),)), now=0, wall=wall)
    component.accept(completion(component, (record(160),)), now=10, wall=wall)

    presentation = replace(
        component.candidate,
        chart=replace(
            component.candidate.chart,
            presentation=replace(component.candidate.chart.presentation, style="line"),
        ),
    )
    component.configure(presentation, data_affecting=False)

    assert component.display().timeline_model(now=10, count=4, wall=wall).observed_series == (
        component.timeline_model(now=10, count=4, wall=wall).observed_series
    )


def test_monitor_component_reconfigures_without_losing_observed_history() -> None:
    component = MonitorComponent(options(), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100),)), now=0, wall=wall)
    component.accept(completion(component, (record(160),)), now=60, wall=wall)
    intervals = tuple(component.observer.intervals)
    generation = component.generation

    presentation = replace(
        component.candidate,
        chart=replace(
            component.candidate.chart,
            presentation=replace(
                component.candidate.chart.presentation,
                style="line",
                density="compact",
            ),
        ),
    )
    revision = component.render_revision
    component.configure(presentation, data_affecting=False)
    assert component.generation == generation
    assert component.render_revision == revision + 1
    assert component.candidate.chart.presentation.density == "compact"
    assert tuple(component.observer.intervals) == intervals

    top = replace(
        component.candidate,
        chart=replace(component.candidate.chart, top=1),
    )
    component.configure(top, data_affecting=False)
    assert component.observer.top == 1
    assert tuple(component.observer.intervals) == intervals

    changed = replace(
        component.candidate,
        chart=replace(component.candidate.chart, filters=Filters(agents=("claude",))),
    )
    component.configure(changed, data_affecting=True)
    assert component.generation == generation + 1
    assert component.rebaseline_pending
    assert tuple(component.observer.intervals) == intervals

    component.accept(completion(component, (record(200),)), now=120, wall=wall)
    assert tuple(component.observer.intervals) == intervals
    assert not component.rebaseline_pending


def test_monitor_component_clears_current_across_pause_resume_and_restores_next_pair() -> None:
    component = MonitorComponent(
        options(by="model", style="ranking"), registry=build_chart_registry()
    )
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100, models={"a": 100}),)), now=0, wall=wall)
    component.accept(completion(component, (record(160, models={"a": 160}),)), now=10, wall=wall)
    assert [
        (entry.key, entry.value) for entry in component.ranking_model(now=10).observed_entries
    ] == [("a", 360.0)]

    intervals = tuple(component.observer.intervals)
    component.pause()
    assert component.ranking_model(now=10).observed_entries == ()
    assert tuple(component.observer.intervals) == intervals

    component.resume(now=20, wall=wall)
    component.accept(completion(component, (record(190, models={"a": 190}),)), now=30, wall=wall)
    assert [
        (entry.key, entry.value) for entry in component.ranking_model(now=30).observed_entries
    ] == [("a", 180.0)]
    assert tuple(component.observer.intervals)[:1] == intervals


def test_monitor_component_gap_rebaselines_and_stale_failure_keeps_accepted_state() -> None:
    component = MonitorComponent(options(), registry=build_chart_registry())
    wall = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    component.accept(completion(component, (record(100),)), now=0, wall=wall)
    component.accept(completion(component, (record(160),)), now=10, wall=wall)
    intervals = tuple(component.observer.intervals)

    component.accept(completion(component, (record(220),)), now=40, wall=wall)
    assert component.current_values(40, wall=wall) == {}
    assert component.timeline_model(now=40, count=4, wall=wall).observed_current == ()
    assert tuple(component.observer.intervals) == intervals
    assert component.observer.previous is not None
    assert component.observer.previous.total.total == 220
    assert component.observer.y_axis_max is not None
    assert component.observer.y_axis_max > 0

    assert component.fail(RuntimeError("current"), generation=component.generation)
    assert isinstance(component.error, RuntimeError)
    assert component.accept(completion(component, (record(240),)), now=50, wall=wall)
    assert component.error is None
