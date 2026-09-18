from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import Notice, TokenUsage

GroupKey = Hashable


class ChangeDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    UNCHANGED = "unchanged"
    FROM_ZERO = "from_zero"


@dataclass(frozen=True, slots=True)
class PercentChange:
    direction: ChangeDirection
    percent: float | None = None


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    period: str
    day: date
    total: int
    sequential: PercentChange | None
    year_over_year: PercentChange | None = None
    previous_week_day: date | None = None
    all_agents: bool = False
    current_filter_total: bool = False
    chart_top: int | None = None

    @property
    def day_over_day(self) -> PercentChange | None:
        return self.sequential

    @property
    def week_over_week(self) -> PercentChange | None:
        return self.year_over_year


@dataclass(frozen=True, slots=True)
class DailySummary:
    """Legacy daily summary input retained for API compatibility."""

    day: date
    total: int
    day_over_day: PercentChange
    week_over_week: PercentChange
    previous_week_day: date
    all_agents: bool = False
    current_filter_total: bool = False
    chart_top: int | None = None


@dataclass(frozen=True, slots=True)
class Series:
    key: GroupKey
    label: str
    values: tuple[TokenUsage, ...]
    is_other: bool = False

    @property
    def total(self) -> TokenUsage:
        return sum(self.values, start=TokenUsage.zero())


@dataclass(frozen=True, slots=True)
class TimelineModel:
    days: tuple[date, ...]
    series: tuple[Series, ...]
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    summary: PeriodSummary | DailySummary | None = None
    aggregation: str = "day"

    @property
    def total(self) -> TokenUsage:
        return sum((item.total for item in self.series), start=TokenUsage.zero())


@dataclass(frozen=True, slots=True)
class CalendarDay:
    day: date
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class CalendarModel:
    days: tuple[CalendarDay, ...]
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    summary: PeriodSummary | DailySummary | None = None

    @property
    def total(self) -> TokenUsage:
        return sum((item.usage for item in self.days), start=TokenUsage.zero())

    @property
    def active_days(self) -> int:
        return sum(item.usage.total > 0 for item in self.days)

    @property
    def peak(self) -> CalendarDay | None:
        active = [item for item in self.days if item.usage.total > 0]
        return (
            max(active, key=lambda item: (item.usage.total, -item.day.toordinal()))
            if active
            else None
        )

    @property
    def average(self) -> float:
        return self.total.total / len(self.days) if self.days else 0.0

    @property
    def longest_streak(self) -> int:
        longest = current = 0
        for item in self.days:
            current = current + 1 if item.usage.total > 0 else 0
            longest = max(longest, current)
        return longest

    @property
    def current_streak(self) -> int:
        current = 0
        for item in reversed(self.days):
            if item.usage.total <= 0:
                break
            current += 1
        return current


@dataclass(frozen=True, slots=True)
class StackModel:
    days: tuple[date, ...]
    components: tuple[Series, ...]
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    summary: PeriodSummary | DailySummary | None = None
    aggregation: str = "day"

    @property
    def total(self) -> TokenUsage:
        # Every component series stores a usage with only its represented amount in total.
        total = sum((item.total.total for item in self.components), start=0)
        return TokenUsage(total, 0, 0, 0, 0, total)


@dataclass(frozen=True, slots=True)
class RankingEntry:
    key: GroupKey
    label: str
    usage: TokenUsage
    is_other: bool = False


@dataclass(frozen=True, slots=True)
class RankingModel:
    entries: tuple[RankingEntry, ...]
    date_range: DateRange
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    denominator: TokenUsage | None = None
    summary: PeriodSummary | DailySummary | None = None

    @property
    def total(self) -> TokenUsage:
        return sum((item.usage for item in self.entries), start=TokenUsage.zero())

    @property
    def percentage_total(self) -> TokenUsage:
        """Return the full filtered total used for entry percentages."""
        return self.denominator if self.denominator is not None else self.total
