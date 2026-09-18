from datetime import date

from ccusage_viz.chart_models import ChangeDirection
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.processing.summaries import build_period_summary, summary_intervals


def record(day: date, total: int) -> UsageRecord:
    return UsageRecord(day, "claude", TokenUsage(total, total, 0, 0, 0, 0), SourceKind.UNIFIED_DAILY)


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
    assert summary.year_over_year is None


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
