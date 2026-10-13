import json
from dataclasses import replace
from datetime import UTC, date, datetime
from threading import Event
from typing import cast

import pytest

from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.chart_models import PeriodSummary
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import (
    ProjectRef,
    SourceKind,
    TokenUsage,
    UsageRecord,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalCompletion,
    HistoricalPurpose,
    UsageSnapshot,
    historical_replacement_required,
)
from ccusage_viz.options import (
    ChartPresentation,
    Density,
    ProcessConfig,
    RankingConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.providers.ccusage import CcusageProvider
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.models import PhysicalQuery, PhysicalResult, QueryTrigger
from ccusage_viz.query.provider import ProviderDefinition
from ccusage_viz.query.registry import ProviderRegistry
from ccusage_viz.query.runtime import QueryRuntime


def options() -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(provider="demo", demo_size="small"),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 7)),
            presentation=ChartPresentation(theme="no-color"),
        ),
    )


def component() -> HistoricalChartComponent:
    return HistoricalChartComponent(
        options(),
        owner_id="test:chart",
        runtime=build_query_runtime(),
        registry=build_chart_registry(),
    )


class _AtomicProjectProvider(CcusageProvider):
    """In-process ccusage boundary fake; compile/normalize/assemble stay real."""

    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "fallback_total", 20)
        object.__setattr__(self, "observation_has_exception", True)
        object.__setattr__(self, "fallback_fails", False)
        object.__setattr__(self, "operations", [])

    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
        del cancelled
        self.operations.append(query.operation)
        day = query.coverage.intervals[0].until.isoformat()
        if query.operation == "unified_daily_agent_observation":
            agents = (
                [
                    {
                        "agent": "future-agent",
                        "project": "relative/project",
                        "inputTokens": 20,
                        "outputTokens": 0,
                        "cacheReadTokens": 0,
                        "cacheCreationTokens": 0,
                        "totalTokens": 20,
                    }
                ]
                if self.observation_has_exception
                else []
            )
            payload = {"daily": [{"date": day, "agents": agents}]}
        elif query.operation.startswith("project_fallback_sessions:"):
            if self.fallback_fails:
                raise QueryError("error.ccusage_failed", query=query.operation, code=1, stderr="")
            payload = {
                "sessions": [
                    {
                        "sessionId": "accepted-session",
                        "projectPath": "/workspace/attributed",
                        "inputTokens": self.fallback_total,
                        "outputTokens": 0,
                        "cacheReadTokens": 0,
                        "cacheCreationTokens": 0,
                        "totalTokens": self.fallback_total,
                    }
                ]
            }
        elif query.operation == "claude_daily_projects":
            payload = {"daily": []}
        elif query.operation == "codex_ranking_sessions":
            payload = {"sessions": []}
        else:  # pragma: no cover - protects this focused fake from planner drift
            raise AssertionError(f"unexpected operation: {query.operation}")
        return PhysicalResult(query, json.dumps(payload).encode())


def _atomic_project_component() -> tuple[HistoricalChartComponent, _AtomicProjectProvider]:
    provider = _AtomicProjectProvider()
    providers = ProviderRegistry()
    providers.register(ProviderDefinition(provider))
    providers.freeze()
    runtime = QueryRuntime(providers, QueryCoordinator(max_parallel=4))
    selected = replace(
        options(),
        host=StandaloneHostConfig(provider="ccusage"),
        chart=RankingConfig(
            "ranking",
            options().chart.date_range,
            presentation=ChartPresentation(theme="no-color", style="bar"),
        ),
    )
    return (
        HistoricalChartComponent(
            selected,
            owner_id="test:atomic-project-ranking",
            runtime=runtime,
            registry=build_chart_registry(),
        ),
        provider,
    )


def test_historical_replacement_classifier_ignores_granularity_and_presentation() -> None:
    previous = options()
    assert not historical_replacement_required(previous, previous)
    changed_period = replace(
        previous,
        chart=replace(previous.chart, date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7))),
    )
    assert historical_replacement_required(previous, changed_period)
    changed_filter = replace(
        previous,
        chart=replace(previous.chart, filters=replace(previous.chart.filters, agents=("claude",))),
    )
    assert historical_replacement_required(previous, changed_filter)
    changed_granularity = replace(previous, chart=replace(previous.chart, granularity="month"))
    assert not historical_replacement_required(previous, changed_granularity)
    changed_presentation = replace(
        previous,
        chart=replace(
            previous.chart, presentation=replace(previous.chart.presentation, style="points")
        ),
    )
    assert not historical_replacement_required(previous, changed_presentation)


def _seed_atomic_project_component(
    chart: HistoricalChartComponent,
) -> tuple[UsageSnapshot, datetime, UsageRecord]:
    old_record = UsageRecord(
        date(2026, 1, 7),
        "future-agent",
        TokenUsage(7, 7, 0, 0, 0),
        SourceKind.PROJECT_SESSIONS,
        ProjectRef("future-agent", "/workspace/previous", "previous", True),
    )
    old_snapshot = UsageSnapshot(
        (old_record,),
        (),
        0.1,
        includes_project_attribution=True,
        coverage=chart.display_coverage(),
    )
    old_accepted_at = datetime(2026, 1, 8, tzinfo=UTC)
    chart.seed(chart.candidate, old_snapshot, accepted_at=old_accepted_at)
    changed = replace(
        chart.candidate,
        chart=replace(
            chart.candidate.chart,
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7)),
        ),
    )
    chart.configure(changed, data_affecting=True)
    return old_snapshot, old_accepted_at, old_record


def test_project_ranking_accepts_fallback_total_mismatch_atomically() -> None:
    chart, provider = _atomic_project_component()
    assert chart.runtime is not None
    try:
        old_snapshot, _, _ = _seed_atomic_project_component(chart)
        object.__setattr__(provider, "fallback_total", 19)

        completion = chart.submit(QueryTrigger.REFRESH).result()
        assert chart.snapshot is old_snapshot
        assert chart.accept(completion)

        assert chart.snapshot is completion.snapshot
        assert chart.error is None
        (accepted_record,) = chart.snapshot.records
        assert accepted_record.usage.total == 19
        assert accepted_record.project is not None
        assert accepted_record.project.raw_id == "/workspace/attributed"
        assert accepted_record.attribution is None
    finally:
        chart.runtime.cancel()


def test_project_ranking_b_command_failure_retains_exact_state_then_retry_succeeds() -> None:
    chart, provider = _atomic_project_component()
    assert chart.runtime is not None
    try:
        old_snapshot, old_accepted_at, old_record = _seed_atomic_project_component(chart)
        old_model = chart.model
        old_options = chart.accepted_options
        object.__setattr__(provider, "fallback_fails", True)

        failed = chart.submit(QueryTrigger.REFRESH)
        with pytest.raises(QueryError, match="error.ccusage_failed") as caught:
            failed.result()
        assert chart.fail(caught.value, generation=failed.generation)
        assert chart.snapshot is old_snapshot
        assert chart.model is old_model
        assert chart.accepted_options is old_options
        assert chart.accepted_at is old_accepted_at
        assert chart.snapshot.records == (old_record,)

        object.__setattr__(provider, "fallback_fails", False)
        retry = chart.submit(QueryTrigger.REFRESH)
        completion = retry.result()
        retry_accepted_at = datetime(2026, 2, 8, tzinfo=UTC)
        assert chart.accept(completion, accepted_at=retry_accepted_at)

        assert chart.snapshot is completion.snapshot
        assert chart.accepted_options == chart.candidate
        assert chart.accepted_at is retry_accepted_at
        assert chart.error is None
        (accepted_record,) = chart.snapshot.records
        assert accepted_record.project is not None
        assert accepted_record.project.raw_id == "/workspace/attributed"
        assert accepted_record.attribution is None
    finally:
        chart.runtime.cancel()


def test_period_switch_drops_failed_prefetch_when_observation_no_longer_requires_it() -> None:
    chart, provider = _atomic_project_component()
    assert chart.runtime is not None
    try:
        learned = chart.submit(QueryTrigger.STARTUP).result()
        assert chart.accept(learned)
        assert provider.operations.count("project_fallback_sessions:future-agent") == 1

        object.__setattr__(provider, "observation_has_exception", False)
        object.__setattr__(provider, "fallback_fails", True)
        switched = replace(
            chart.candidate,
            chart=replace(
                chart.candidate.chart,
                date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7)),
            ),
        )
        chart.configure(switched, data_affecting=True)
        completion = chart.submit(QueryTrigger.REFRESH).result()
        assert chart.accept(completion)
        assert completion.snapshot.records == ()
        assert provider.operations.count("project_fallback_sessions:future-agent") == 2

        following = replace(
            chart.candidate,
            chart=replace(
                chart.candidate.chart,
                date_range=DateRange(date(2026, 3, 1), date(2026, 3, 7)),
            ),
        )
        chart.configure(following, data_affecting=True)
        completion = chart.submit(QueryTrigger.REFRESH).result()
        assert chart.accept(completion)
        assert provider.operations.count("project_fallback_sessions:future-agent") == 2
    finally:
        chart.runtime.cancel()


def test_component_acquires_and_accepts_provider_snapshot() -> None:
    chart = component()
    runtime = chart.runtime
    assert runtime is not None

    try:
        completion = chart.submit(QueryTrigger.STARTUP).result()
        assert completion.options == chart.candidate
        assert completion.snapshot.records
        assert completion.snapshot.coverage.covers(DateInterval(date(2026, 1, 1), date(2026, 1, 7)))
        assert completion.snapshot.includes_project_attribution
        assert completion.snapshot.elapsed >= 0
        assert chart.accept(completion)
        assert chart.snapshot is completion.snapshot
    finally:
        runtime.cancel()


def test_component_accepts_snapshot_and_coverage_atomically() -> None:
    chart = component()
    coverage = DateCoverage((DateInterval(date(2026, 1, 1), date(2026, 1, 7)),))
    snapshot = UsageSnapshot((), (), 0.25, coverage=coverage)
    accepted_at = datetime(2026, 1, 8, tzinfo=UTC)

    accepted = chart.accept(
        HistoricalCompletion(chart.generation, chart.candidate, snapshot),
        accepted_at=accepted_at,
    )

    assert accepted
    assert chart.snapshot is snapshot
    assert chart.snapshot.coverage == coverage
    assert chart.model is not None
    assert chart.accepted_at == accepted_at
    assert chart.error is None


def test_component_rejects_stale_success_and_failure_without_mutation() -> None:
    chart = component()
    original_snapshot = UsageSnapshot((), (), 0.1)
    chart.seed(chart.candidate, original_snapshot)
    original_model = chart.model
    original_accepted_at = chart.accepted_at
    changed = replace(
        chart.candidate,
        chart=replace(
            chart.candidate.chart,
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7)),
        ),
    )
    chart.configure(changed, data_affecting=True)

    assert not chart.accept(HistoricalCompletion(0, options(), UsageSnapshot((), (), 0.5)))
    assert not chart.fail(RuntimeError("stale"), generation=0)
    assert chart.snapshot is original_snapshot
    assert chart.model is original_model
    assert chart.accepted_at == original_accepted_at
    assert chart.error is None


def test_component_keeps_render_only_candidate_when_query_completes() -> None:
    chart = component()
    submission_options = chart.candidate
    presentation = replace(
        chart.candidate.chart.presentation,
        style="points",
        density="compact",
    )
    updated = replace(
        chart.candidate,
        host=replace(chart.candidate.host, ascii=True),
        chart=replace(chart.candidate.chart, presentation=presentation),
    )
    chart.configure(updated, data_affecting=False)

    assert chart.accept(
        HistoricalCompletion(chart.generation, submission_options, UsageSnapshot((), (), 0.1))
    )
    assert chart.candidate.host.ascii
    assert chart.candidate.chart.presentation.style == "points"
    assert chart.candidate.chart.presentation.density == "compact"
    assert chart.accepted_options == chart.candidate


def test_component_keeps_accepted_options_until_replacement_succeeds() -> None:
    chart = component()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1))
    accepted = chart.accepted_options
    changed = replace(
        chart.candidate,
        chart=replace(
            chart.candidate.chart,
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7)),
        ),
    )

    chart.configure(changed, data_affecting=True)

    assert chart.candidate == changed
    assert chart.accepted_options == accepted
    assert chart.is_pending
    assert chart.has_pending_unknowns

    assert chart.fail(RuntimeError("replacement failed"), generation=chart.generation)
    assert not chart.is_pending
    assert chart.accepted_options == accepted


def test_component_reverts_pending_candidate_to_accepted_projection() -> None:
    chart = component()
    snapshot = UsageSnapshot((), (), 0.1)
    chart.seed(chart.candidate, snapshot)
    accepted = chart.accepted_options
    assert accepted is not None
    changed = replace(
        accepted,
        chart=replace(
            accepted.chart,
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7)),
        ),
    )
    chart.configure(changed, data_affecting=True)

    chart.configure(accepted, data_affecting=False)

    assert chart.candidate == accepted
    assert chart.accepted_options == accepted
    assert not chart.is_pending
    assert chart.model is not None


def test_component_clears_current_error_when_submitting_again() -> None:
    chart = component()
    assert chart.fail(RuntimeError("temporary"), generation=chart.generation)

    submission = chart.submit(QueryTrigger.REFRESH)
    submission.cancel()

    assert chart.error is None


def test_component_separates_data_generation_from_render_revision() -> None:
    chart = component()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1))
    generation = chart.generation
    revision = chart.render_revision
    presentation = replace(
        chart.candidate.chart.presentation,
        style="points",
        density="compact",
    )

    chart.configure(
        replace(chart.candidate, chart=replace(chart.candidate.chart, presentation=presentation)),
        data_affecting=False,
    )

    assert chart.generation == generation
    assert chart.render_revision == revision + 1
    assert chart.model is not None


def test_component_persists_injected_summary_through_model_recreation() -> None:
    chart = HistoricalChartComponent(
        options(),
        owner_id="standalone:test",
        runtime=None,
        registry=build_chart_registry(),
        include_summary=False,
    )
    summary = PeriodSummary("day", date(2026, 1, 7), 42, None)

    chart.set_summary(summary)
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1, coverage=chart.display_coverage()))
    assert chart.model is not None
    assert chart.model.summary == summary
    updated = replace(
        chart.candidate,
        chart=replace(chart.candidate.chart, presentation=ChartPresentation(style="points")),
    )
    chart.configure(updated, data_affecting=False)

    assert chart.summary == summary
    assert chart.model is not None
    assert chart.model.summary == summary


def test_component_reprojects_project_aggregation_without_new_generation() -> None:
    selected = replace(
        options(),
        chart=replace(options().chart, by="project", project_aggregation="name"),
    )
    chart = HistoricalChartComponent(
        selected,
        owner_id="test:aggregation",
        runtime=None,
        registry=build_chart_registry(),
    )
    snapshot = UsageSnapshot(
        (
            UsageRecord(
                date(2026, 1, 1),
                "claude",
                TokenUsage(20, 20, 0, 0, 0),
                SourceKind.CLAUDE_DAILY_PROJECTS,
                ProjectRef("claude", "claude-app", "app"),
            ),
            UsageRecord(
                date(2026, 1, 1),
                "codex",
                TokenUsage(10, 10, 0, 0, 0),
                SourceKind.CODEX_SESSIONS,
                ProjectRef("codex", "codex-app", "app"),
            ),
        ),
        (),
        0.1,
    )
    chart.seed(selected, snapshot)
    generation = chart.generation
    revision = chart.render_revision

    exact = replace(
        selected,
        chart=replace(selected.chart, project_aggregation="exact"),
    )
    chart.configure(exact, data_affecting=False)

    assert chart.snapshot is snapshot
    assert chart.generation == generation
    assert chart.render_revision == revision + 1
    assert chart.accepted_options == exact
    assert chart.model is not None
    assert [series.key for series in chart.model.series] == [
        ("project", "exact", "claude", "claude-app"),
        ("project", "exact", "codex", "codex-app"),
    ]


@pytest.mark.parametrize("density", ("minimal", "compact", "full", "detailed"))
def test_timeline_component_requires_only_display_coverage_at_all_densities(density: str) -> None:
    selected = replace(
        options(),
        chart=replace(
            options().chart, presentation=ChartPresentation(density=cast(Density, density))
        ),
    )
    chart = HistoricalChartComponent(
        selected,
        owner_id="test:density",
        runtime=None,
        registry=build_chart_registry(),
    )
    display = chart.display_coverage()
    chart.seed(selected, UsageSnapshot((), (), 0.1, coverage=display))

    assert chart.required_coverage() == display
    assert not chart.missing_comparison_coverage().intervals
    assert not chart.has_pending_unknowns


def test_timeline_component_has_no_chart_owned_comparison_coverage() -> None:
    chart = component()
    display = chart.display_coverage()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1, coverage=display))

    assert chart.required_coverage() == display
    assert not chart.missing_comparison_coverage().intervals
    assert not chart.has_pending_unknowns


def test_component_fixed_range_requires_no_comparison_coverage() -> None:
    selected = replace(
        options(),
        chart=replace(
            options().chart,
            date_range=replace(options().chart.date_range, fixed_bounds=True),
        ),
    )
    chart = HistoricalChartComponent(
        selected,
        owner_id="test:fixed",
        runtime=None,
        registry=build_chart_registry(),
    )
    display = chart.display_coverage()
    chart.seed(selected, UsageSnapshot((), (), 0.1, coverage=display))

    assert chart.required_coverage() == display
    assert not chart.missing_comparison_coverage().intervals


def test_component_merges_supplement_without_replacing_display_facts() -> None:
    chart = component()
    display_record = UsageRecord(
        date(2026, 1, 7),
        "claude",
        TokenUsage(20, 20, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    display = chart.display_coverage()
    chart.seed(
        chart.candidate,
        UsageSnapshot((display_record,), (), 0.1, coverage=display),
    )
    comparison = DateCoverage.from_interval(date(2025, 12, 31), date(2025, 12, 31))
    comparison_record = replace(
        display_record, day=date(2025, 12, 31), usage=TokenUsage(10, 10, 0, 0, 0)
    )

    assert chart.accept(
        HistoricalCompletion(
            chart.generation,
            chart.candidate,
            UsageSnapshot((comparison_record,), (), 0.2, coverage=comparison),
            HistoricalPurpose.SUPPLEMENTAL,
            comparison,
        )
    )

    assert chart.snapshot is not None
    assert chart.snapshot.records == (display_record, comparison_record)
    assert chart.snapshot.coverage == display.merge(comparison)
    assert not chart.has_pending_unknowns
    assert chart.model is not None
    assert chart.model.summary is not None
    assert chart.model.summary.week_over_week is not None


def test_component_supplement_failure_preserves_facts_and_adds_local_notice() -> None:
    chart = component()
    display = chart.display_coverage()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1, coverage=display))
    snapshot = chart.snapshot

    assert chart.fail(
        RuntimeError("comparison failed"),
        generation=chart.generation,
        purpose=HistoricalPurpose.SUPPLEMENTAL,
    )

    assert chart.snapshot is snapshot
    assert chart.error is None
    assert chart.supplemental_error is not None
    assert not chart.has_pending_unknowns
    assert chart.model is not None
    assert chart.model.notices[-1].key == "notice.comparison_refresh_failed"
    assert not chart.missing_comparison_coverage().intervals


def test_component_successful_supplement_clears_failure_notice() -> None:
    chart = component()
    display = chart.display_coverage()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1, coverage=display))
    comparison = chart.missing_comparison_coverage()
    assert chart.fail(
        RuntimeError("comparison failed"),
        generation=chart.generation,
        purpose=HistoricalPurpose.SUPPLEMENTAL,
    )

    assert chart.accept(
        HistoricalCompletion(
            chart.generation,
            chart.candidate,
            UsageSnapshot((), (), 0.2, coverage=comparison),
            HistoricalPurpose.SUPPLEMENTAL,
            comparison,
        )
    )

    assert chart.supplemental_error is None
    assert chart.model is not None
    assert all(notice.key != "notice.comparison_refresh_failed" for notice in chart.model.notices)
    assert not chart.missing_comparison_coverage().intervals


def test_component_primary_replaces_empty_returned_interval() -> None:
    chart = component()
    stale = UsageRecord(
        date(2026, 1, 7),
        "claude",
        TokenUsage(20, 20, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    display = chart.display_coverage()
    comparison = DateCoverage.from_interval(date(2025, 12, 31), date(2025, 12, 31))
    comparison_record = replace(stale, day=date(2025, 12, 31))
    chart.seed(
        chart.candidate,
        UsageSnapshot(
            (stale, comparison_record),
            (),
            0.1,
            coverage=display.merge(comparison),
        ),
    )

    assert chart.accept(
        HistoricalCompletion(
            chart.generation,
            chart.candidate,
            UsageSnapshot((), (), 0.2, coverage=display),
        )
    )

    assert chart.snapshot is not None
    assert chart.snapshot.records == (comparison_record,)
    assert chart.snapshot.coverage == display.merge(comparison)


def test_component_new_generation_primary_resets_old_facts() -> None:
    chart = component()
    old = UsageRecord(
        date(2026, 1, 7),
        "claude",
        TokenUsage(20, 20, 0, 0, 0),
        SourceKind.UNIFIED_DAILY,
    )
    chart.seed(
        chart.candidate,
        UsageSnapshot((old,), (), 0.1, coverage=chart.display_coverage()),
    )
    changed = replace(
        chart.candidate,
        chart=replace(
            chart.candidate.chart,
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7)),
        ),
    )
    chart.configure(changed, data_affecting=True)
    new = replace(old, day=date(2026, 2, 7))
    new_coverage = chart.display_coverage()

    assert chart.accept(
        HistoricalCompletion(
            chart.generation,
            changed,
            UsageSnapshot((new,), (), 0.2, coverage=new_coverage),
        )
    )

    assert chart.snapshot is not None
    assert chart.snapshot.records == (new,)
    assert chart.snapshot.coverage == new_coverage


def test_component_exposes_ranking_refresh_state_from_accepted_model() -> None:
    selected = replace(
        options(),
        chart=RankingConfig(
            "ranking",
            options().chart.date_range,
            presentation=ChartPresentation(theme="no-color", style="bar"),
        ),
    )
    chart = HistoricalChartComponent(
        selected,
        owner_id="test:ranking",
        runtime=None,
        registry=build_chart_registry(),
    )
    records = (
        UsageRecord(
            date(2026, 1, 1),
            "claude",
            TokenUsage(20, 20, 0, 0, 0),
            SourceKind.UNIFIED_DAILY,
            ProjectRef("claude", "api", "API"),
        ),
        UsageRecord(
            date(2026, 1, 1),
            "claude",
            TokenUsage(10, 10, 0, 0, 0),
            SourceKind.UNIFIED_DAILY,
            ProjectRef("claude", "web", "Web"),
        ),
    )
    chart.seed(selected, UsageSnapshot(records, (), 0.1))

    assert chart.ranking_values() == {
        ("project", "exact", "claude", "api"): 20.0,
        ("project", "exact", "claude", "web"): 10.0,
    }
    assert chart.ranking_keys() == (
        ("project", "exact", "claude", "api"),
        ("project", "exact", "claude", "web"),
    )


def test_component_rejects_ranking_state_for_another_chart() -> None:
    chart = component()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1))

    with pytest.raises(TypeError, match="accepted ranking model"):
        chart.ranking_values()


def test_component_rejects_monitor_configuration() -> None:
    from ccusage_viz.options import MonitorConfig

    selected = replace(options(), chart=MonitorConfig("monitor", 3600))
    with pytest.raises(TypeError, match="historical components"):
        HistoricalChartComponent(
            selected,
            owner_id="test:monitor",
            runtime=build_query_runtime(),
            registry=build_chart_registry(),
        )
