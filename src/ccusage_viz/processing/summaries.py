from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

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
    if period == "week":
        return day - timedelta(days=day.weekday())
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


def period_end(start: date, period: str) -> date:
    if period == "week":
        return start + timedelta(days=6)
    if period == "month":
        return date(start.year, start.month, monthrange(start.year, start.month)[1])
    if period == "quarter":
        return _shift_months(start, 3) - timedelta(days=1)
    if period == "year":
        return date(start.year, 12, 31)
    return start


SummaryScope = Literal["day", "week", "month", "quarter", "year", "range"]


@dataclass(frozen=True, slots=True)
class SummaryQueryPlan:
    """Resolved source-facing intervals for one user-visible summary scope."""

    scope: SummaryScope
    current: DateInterval
    sequential: DateInterval | None = None
    year_over_year: DateInterval | None = None

    @property
    def intervals(self) -> tuple[DateInterval, ...]:
        return tuple(
            interval
            for interval in (self.current, self.sequential, self.year_over_year)
            if interval is not None
        )


def _elapsed_interval(start: date, elapsed_days: int, period: str) -> DateInterval:
    return DateInterval(
        start, min(start + timedelta(days=elapsed_days - 1), period_end(start, period))
    )


def summary_query_plan(end: date, period: SummaryScope) -> SummaryQueryPlan:
    """Translate an as-of date and scope into source-query intervals exactly once."""
    if period == "range":
        raise ValueError("range summaries require an explicit DateRange")
    current_start = period_start(end, period)
    current = DateInterval(current_start, end)
    if period == "day":
        return SummaryQueryPlan(
            period,
            current,
            DateInterval(end - timedelta(days=1), end - timedelta(days=1)),
            DateInterval(end - timedelta(days=7), end - timedelta(days=7)),
        )
    if period == "week":
        return SummaryQueryPlan(
            period,
            current,
            DateInterval(current_start - timedelta(days=7), current_start - timedelta(days=1)),
        )
    elapsed = (end - current_start).days + 1
    if period == "month":
        sequential_start = _shift_months(current_start, -1)
        yearly_start = _shift_months(current_start, -12)
        return SummaryQueryPlan(
            period,
            current,
            _elapsed_interval(sequential_start, elapsed, period),
            _elapsed_interval(yearly_start, elapsed, period),
        )
    if period == "quarter":
        sequential_start = _shift_months(current_start, -3)
        yearly_start = _shift_months(current_start, -12)
        return SummaryQueryPlan(
            period,
            current,
            _elapsed_interval(sequential_start, elapsed, period),
            _elapsed_interval(yearly_start, elapsed, period),
        )
    previous_start = date(current_start.year - 1, 1, 1)
    return SummaryQueryPlan(
        period, current, None, _elapsed_interval(previous_start, elapsed, "year")
    )


def range_summary_query_plan(date_range: DateRange) -> SummaryQueryPlan:
    return SummaryQueryPlan("range", DateInterval(date_range.since, date_range.until))


def _summary_scope(period: str) -> SummaryScope:
    if period not in {"day", "week", "month", "quarter", "year", "range"}:
        raise ValueError(f"unsupported summary scope: {period}")
    return period


def summary_intervals(end: date, period: str) -> tuple[DateInterval, ...]:
    """Compatibility projection of a named summary plan for existing call sites."""
    return summary_query_plan(end, _summary_scope(period)).intervals


def ranking_comparison_interval(date_range: DateRange) -> DateInterval:
    """Return the contiguous prior interval with the displayed range's duration."""
    duration = (date_range.until - date_range.since).days + 1
    until = date_range.since - timedelta(days=1)
    return DateInterval(until - timedelta(days=duration - 1), until)


def required_summary_coverage(end: date, period: str) -> DateCoverage:
    return DateCoverage(summary_query_plan(end, _summary_scope(period)).intervals)


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
    plan = summary_query_plan(end, _summary_scope(period))
    current_interval = plan.current
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
    sequential_interval = plan.sequential
    sequential_ready = sequential_interval is not None and coverage.covers(sequential_interval)
    sequential = percent_change(current, total(sequential_interval)) if sequential_ready else None
    yearly_interval = plan.year_over_year
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
        sequential_state=(
            ComparisonState.READY
            if sequential_ready
            else ComparisonState.UNAVAILABLE
            if sequential_interval is None
            else ComparisonState.PENDING
        ),
        year_over_year_state=(
            ComparisonState.READY
            if yearly_ready
            else ComparisonState.UNAVAILABLE
            if yearly_interval is None
            else ComparisonState.PENDING
        ),
    )
