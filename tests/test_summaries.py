from datetime import date

from ccusage_viz.chart_models import ChangeDirection, ComparisonState
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.processing.summaries import (
    build_period_summary,
    required_summary_coverage,
    summary_intervals,
    summary_query_plan,
)


def record(day: date, total: int) -> UsageRecord:
    return UsageRecord(
        day, "claude", TokenUsage(total, total, 0, 0, 0, 0), SourceKind.UNIFIED_DAILY
    )


def test_month_to_date_uses_calendar_aligned_comparisons() -> None:
    end = date(2026, 3, 15)
    assert summary_intervals(end, "month") == (
        DateInterval(date(2026, 3, 1), end),
        DateInterval(date(2026, 2, 1), date(2026, 2, 15)),
        DateInterval(date(2025, 3, 1), date(2025, 3, 15)),
    )


def test_month_comparison_clamps_shorter_month() -> None:
    intervals = summary_intervals(date(2024, 3, 31), "month")
    assert intervals[1] == DateInterval(date(2024, 2, 1), date(2024, 2, 29))


def test_year_to_date_clamps_leap_day() -> None:
    intervals = summary_intervals(date(2024, 2, 29), "year")
    assert intervals[1] == DateInterval(date(2023, 1, 1), date(2023, 3, 1))


def test_missing_comparison_coverage_hides_only_that_comparison() -> None:
    end = date(2026, 3, 15)
    intervals = summary_intervals(end, "month")
    coverage = DateCoverage((intervals[0], intervals[1]))
    summary = build_period_summary((record(end, 10),), end, "month", coverage)

    assert summary is not None
    assert summary.sequential is not None
    assert summary.sequential.direction == ChangeDirection.FROM_ZERO
    assert summary.sequential_state == ComparisonState.READY
    assert summary.year_over_year is None
    assert summary.year_over_year_state == ComparisonState.PENDING


def test_week_summary_uses_current_partial_week_and_previous_complete_week() -> None:
    end = date(2026, 3, 18)

    plan = summary_query_plan(end, "week")

    assert plan.current == DateInterval(date(2026, 3, 16), end)
    assert plan.sequential == DateInterval(date(2026, 3, 9), date(2026, 3, 15))
    assert plan.year_over_year is None
    assert required_summary_coverage(end, "week") == DateCoverage(plan.intervals)


def test_week_summary_marks_year_over_year_as_unavailable() -> None:
    end = date(2026, 3, 18)
    coverage = required_summary_coverage(end, "week")
    summary = build_period_summary((), end, "week", coverage)

    assert summary is not None
    assert summary.sequential_state == ComparisonState.READY
    assert summary.year_over_year is None
    assert summary.year_over_year_state == ComparisonState.UNAVAILABLE


def test_year_summary_marks_year_over_year_as_unavailable() -> None:
    end = date(2026, 3, 15)
    coverage = DateCoverage(summary_intervals(end, "year"))
    summary = build_period_summary((), end, "year", coverage)

    assert summary is not None
    assert summary.sequential_state == ComparisonState.UNAVAILABLE
    assert summary.year_over_year is not None
    assert summary.year_over_year_state == ComparisonState.READY


def test_uncovered_current_period_has_no_numeric_summary() -> None:
    end = date(2026, 3, 15)
    assert build_period_summary((), end, "month", DateCoverage()) is None


def test_covered_empty_intervals_are_real_zeroes() -> None:
    end = date(2026, 3, 15)
    coverage = DateCoverage(summary_intervals(end, "month"))
    summary = build_period_summary((), end, "month", coverage)

    assert summary is not None
    assert summary.total == 0
    assert summary.sequential is not None
    assert summary.sequential.direction == ChangeDirection.UNCHANGED
    assert summary.year_over_year is not None
    assert summary.year_over_year.direction == ChangeDirection.UNCHANGED
