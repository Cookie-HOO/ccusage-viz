from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalCompletion,
    UsageSnapshot,
)
from ccusage_viz.options import (
    ChartPresentation,
    ProcessConfig,
    RankingConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.query.models import QueryTrigger


def options() -> StandaloneLaunch:
    return StandaloneLaunch(
        ProcessConfig(),
        StandaloneHostConfig(provider="demo", demo_size="small"),
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 7), None),
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


def test_component_acquires_and_accepts_provider_snapshot() -> None:
    chart = component()
    runtime = chart.runtime
    assert runtime is not None

    try:
        completion = chart.submit(QueryTrigger.STARTUP).result()
        assert completion.options == chart.candidate
        assert completion.snapshot.records
        assert completion.snapshot.coverage.covers(
            DateInterval(date(2026, 1, 1), date(2026, 1, 7))
        )
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
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7), None),
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
    presentation = replace(chart.candidate.chart.presentation, style="points")
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
    assert chart.accepted_options == chart.candidate


def test_component_keeps_accepted_options_until_replacement_succeeds() -> None:
    chart = component()
    chart.seed(chart.candidate, UsageSnapshot((), (), 0.1))
    accepted = chart.accepted_options
    changed = replace(
        chart.candidate,
        chart=replace(
            chart.candidate.chart,
            date_range=DateRange(date(2026, 2, 1), date(2026, 2, 7), None),
        ),
    )

    chart.configure(changed, data_affecting=True)

    assert chart.candidate == changed
    assert chart.accepted_options == accepted


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
    presentation = replace(chart.candidate.chart.presentation, style="points")

    chart.configure(
        replace(chart.candidate, chart=replace(chart.candidate.chart, presentation=presentation)),
        data_affecting=False,
    )

    assert chart.generation == generation
    assert chart.render_revision == revision + 1
    assert chart.model is not None


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
        ("claude", "api"): 20.0,
        ("claude", "web"): 10.0,
    }
    assert chart.ranking_keys() == (("claude", "api"), ("claude", "web"))


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
