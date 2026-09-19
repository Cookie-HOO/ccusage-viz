from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from ccusage_viz.chart_models import (
    ChangeDirection,
    ComparisonState,
    PercentChange,
    PeriodSummary,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import UsageRecord


def period_start(day: date, period: str) -> date:
    if period == "month":
        return day.replace(day=1)
    if period == "quarter":
        return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
    if period == "year":
        return day.replace(month=1, day=1)
    return day


def _shift_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _period_end(start: date, period: str) -> date:
    if period == "month":
        return date(start.year, start.month, monthrange(start.year, start.month)[1])
    if period == "quarter":
        return _shift_months(start, 3) - timedelta(days=1)
    if period == "year":
        return date(start.year, 12, 31)
    return start


def _elapsed_interval(start: date, elapsed_days: int, period: str) -> DateInterval:
    return DateInterval(
        start, min(start + timedelta(days=elapsed_days - 1), _period_end(start, period))
    )


def summary_intervals(end: date, period: str) -> tuple[DateInterval, ...]:
    current_start = period_start(end, period)
    current = DateInterval(current_start, end)
    if period == "day":
        return (
            current,
            DateInterval(end - timedelta(days=1), end - timedelta(days=1)),
            DateInterval(end - timedelta(days=7), end - timedelta(days=7)),
        )
    elapsed = (end - current_start).days + 1
    if period == "month":
        sequential_start = _shift_months(current_start, -1)
        yearly_start = _shift_months(current_start, -12)
        return (
            current,
            _elapsed_interval(sequential_start, elapsed, period),
            _elapsed_interval(yearly_start, elapsed, period),
        )
    if period == "quarter":
        sequential_start = _shift_months(current_start, -3)
        yearly_start = _shift_months(current_start, -12)
        return (
            current,
            _elapsed_interval(sequential_start, elapsed, period),
            _elapsed_interval(yearly_start, elapsed, period),
        )
    previous_start = date(current_start.year - 1, 1, 1)
    return (current, _elapsed_interval(previous_start, elapsed, "year"))


def required_summary_coverage(end: date, period: str) -> DateCoverage:
    coverage = DateCoverage()
    for interval in summary_intervals(end, period):
        coverage = coverage.merge(DateCoverage((interval,)))
    return coverage


def percent_change(current: int, baseline: int) -> PercentChange:
    if current == baseline:
        return PercentChange(ChangeDirection.UNCHANGED)
    if baseline == 0:
        return PercentChange(ChangeDirection.FROM_ZERO)
    if current > baseline:
        return PercentChange(ChangeDirection.INCREASE, (current - baseline) / baseline * 100)
    return PercentChange(ChangeDirection.DECREASE, (baseline - current) / baseline * 100)


def build_range_summary(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    coverage: DateCoverage,
    *,
    enabled: bool = True,
    filter_count: int = 0,
) -> PeriodSummary | None:
    if not enabled or not coverage.covers(DateInterval(date_range.since, date_range.until)):
        return None
    total = sum(
        record.usage.total
        for record in records
        if record.day is not None and date_range.since <= record.day <= date_range.until
    )
    return PeriodSummary(
        "range",
        date_range.until,
        total,
        None,
        filter_count=filter_count,
        sequential_state=ComparisonState.UNAVAILABLE,
        year_over_year_state=ComparisonState.UNAVAILABLE,
    )


def build_period_summary(
    records: Iterable[UsageRecord],
    end: date,
    period: str,
    coverage: DateCoverage,
    *,
    enabled: bool = True,
    filter_count: int = 0,
) -> PeriodSummary | None:
    if not enabled:
        return None
    intervals = summary_intervals(end, period)
    current_interval = intervals[0]
    if not coverage.covers(current_interval):
        return None
    totals: dict[date, int] = defaultdict(int)
    for record in records:
        if record.day is not None:
            totals[record.day] += record.usage.total

    def total(interval: DateInterval) -> int:
        return sum(
            totals[interval.since + timedelta(days=offset)]
            for offset in range((interval.until - interval.since).days + 1)
        )

    current = total(current_interval)
    sequential_ready = coverage.covers(intervals[1])
    sequential = percent_change(current, total(intervals[1])) if sequential_ready else None
    yearly_interval = intervals[2] if len(intervals) > 2 else None
    yearly_ready = yearly_interval is not None and coverage.covers(yearly_interval)
    yearly = percent_change(current, total(yearly_interval)) if yearly_ready else None
    return PeriodSummary(
        period,
        end,
        current,
        sequential,
        yearly,
        end - timedelta(days=7) if period == "day" else None,
        filter_count=filter_count,
        sequential_state=(ComparisonState.READY if sequential_ready else ComparisonState.PENDING),
        year_over_year_state=(
            ComparisonState.READY
            if yearly_ready
            else ComparisonState.UNAVAILABLE
            if yearly_interval is None
            else ComparisonState.PENDING
        ),
    )
