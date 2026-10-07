from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from ccusage_viz.builtin_summary import build_builtin_pane_summary
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import ModelBreakdown, ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.options import (
    Filters,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.processing.summaries import (
    SummaryQueryPlan,
    range_summary_query_plan,
    summary_query_plan,
)

_DEFAULT_FILTERS = Filters()


def _options(*, fixed_bounds: bool = False, filters: Filters = _DEFAULT_FILTERS) -> StandaloneLaunch:
    return StandaloneLaunch(
        process=ProcessConfig(),
        host=StandaloneHostConfig(),
        chart=TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 7), fixed_bounds=fixed_bounds),
            filters=filters,
        ),
    )


def _record(
    day: date,
    agent: str,
    total: int,
    *,
    project: ProjectRef | None = None,
    model: str = "",
) -> UsageRecord:
    usage = TokenUsage(total, total, 0, 0, 0)
    models = (ModelBreakdown(model, usage),) if model else ()
    return UsageRecord(day, agent, usage, SourceKind.UNIFIED_DAILY, project, models)


def test_builtin_summary_filters_records_over_all_plan_intervals() -> None:
    chart = _options(filters=Filters(agents=("claude",), models=("sonnet",), projects=("web (claude)",)))
    plan = summary_query_plan(date(2026, 1, 7), "day")
    records = (
        _record(
            date(2026, 1, 7),
            "claude",
            10,
            project=ProjectRef("claude", "/repo/web", "web", path_backed=True),
            model="sonnet",
        ),
        _record(
            date(2026, 1, 6),
            "claude",
            5,
            project=ProjectRef("claude", "/repo/web", "web", path_backed=True),
            model="sonnet",
        ),
        _record(
            date(2025, 12, 31),
            "claude",
            3,
            project=ProjectRef("claude", "/repo/web", "web", path_backed=True),
            model="sonnet",
        ),
        _record(
            date(2026, 1, 7),
            "codex",
            100,
            project=ProjectRef("codex", "/repo/web", "web", path_backed=True),
            model="sonnet",
        ),
        _record(
            date(2026, 1, 7),
            "claude",
            100,
            project=ProjectRef("claude", "other", "Other"),
            model="sonnet",
        ),
        _record(
            date(2026, 1, 7),
            "claude",
            100,
            project=ProjectRef("claude", "/repo/web", "web", path_backed=True),
            model="haiku",
        ),
    )
    coverage = DateCoverage(plan.intervals)

    result = build_builtin_pane_summary(
        chart.chart, plan, records, coverage, accepted_at=datetime(2026, 1, 8, tzinfo=UTC)
    )

    assert result.summary is not None
    assert result.summary.total == 10
    assert result.summary.sequential is not None
    assert result.summary.year_over_year is not None
    assert result.summary.filter_count == 3


def test_builtin_range_summary_uses_only_chart_range() -> None:
    launch = _options(fixed_bounds=True)
    plan = range_summary_query_plan(launch.chart.date_range)
    records = (
        _record(date(2025, 12, 31), "claude", 100),
        _record(date(2026, 1, 1), "claude", 4),
        _record(date(2026, 1, 7), "claude", 6),
        _record(date(2026, 1, 8), "claude", 100),
    )

    result = build_builtin_pane_summary(
        launch.chart,
        plan,
        records,
        DateCoverage(plan.intervals),
        accepted_at=datetime(2026, 1, 8, tzinfo=UTC),
    )

    assert result.summary is not None
    assert result.summary.period == "range"
    assert result.summary.total == 10


@pytest.mark.parametrize(
    "plan",
    (
        SummaryQueryPlan("range", DateInterval(date(2026, 1, 2), date(2026, 1, 7))),
        SummaryQueryPlan("day", DateInterval(date(2026, 1, 7), date(2026, 1, 7))),
    ),
)
def test_builtin_range_summary_rejects_mismatched_plan(plan: SummaryQueryPlan) -> None:
    chart = _options(fixed_bounds=True).chart

    with pytest.raises(ValueError, match="range summary plan"):
        build_builtin_pane_summary(
            chart,
            plan,
            (),
            DateCoverage(plan.intervals),
            accepted_at=datetime(2026, 1, 8, tzinfo=UTC),
        )


def test_builtin_relative_summary_rejects_noncanonical_comparison_interval() -> None:
    chart = _options().chart
    valid = summary_query_plan(date(2026, 1, 7), "day")
    invalid = replace(valid, sequential=DateInterval(date(2026, 1, 5), date(2026, 1, 5)))

    with pytest.raises(ValueError, match="summary plan intervals"):
        build_builtin_pane_summary(
            chart,
            invalid,
            (),
            DateCoverage(invalid.intervals),
            accepted_at=datetime(2026, 1, 8, tzinfo=UTC),
        )
