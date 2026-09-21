from __future__ import annotations

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import Notice, TokenUsage

GroupKey = Hashable
ChartValue = int | float
MetricUnit = Literal["tokens", "tpm"]


@dataclass(frozen=True, slots=True)
class MetricDescriptor:
    unit: MetricUnit = "tokens"


@dataclass(frozen=True, slots=True)
class ObservedScope:
    window_seconds: int
    mode: Literal["total", "agent", "model", "project"]
    state: Literal["ready", "baseline", "sampling"] = "ready"
    agents: tuple[str, ...] = ()


class ChangeDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    UNCHANGED = "unchanged"
    FROM_ZERO = "from_zero"


class ComparisonState(StrEnum):
    READY = "ready"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


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
    _: KW_ONLY
    filter_count: int = 0
    sequential_state: ComparisonState = ComparisonState.READY
    year_over_year_state: ComparisonState = ComparisonState.READY

    @property
    def day_over_day(self) -> PercentChange | None:
        return self.sequential

    @property
    def week_over_week(self) -> PercentChange | None:
        return self.year_over_year


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
class ScalarSeries:
    key: GroupKey
    label: str
    values: tuple[ChartValue | None, ...]
    is_other: bool = False


@dataclass(frozen=True, slots=True)
class TimelineModel:
    days: tuple[date, ...]
    series: tuple[Series, ...]
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    summary: PeriodSummary | None = None
    aggregation: str = "day"
    observed_at: tuple[datetime, ...] = field(default_factory=tuple)
    monitor_started_at: datetime | None = None
    observed_series: tuple[ScalarSeries, ...] = field(default_factory=tuple)
    metric: MetricDescriptor = field(default_factory=MetricDescriptor)
    observed_scope: ObservedScope | None = None
    y_axis_max: float | None = None
    observed_current: tuple[ScalarRankingEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            not self.observed_at
            and self.monitor_started_at is None
            and not self.observed_series
            and not self.observed_current
            and self.observed_scope is None
        ):
            return
        if self.days or self.series or self.observed_scope is None:
            raise ValueError("observed timelines require only observed axis and series data")
        if any(len(series.values) != len(self.observed_at) for series in self.observed_series):
            raise ValueError("observed timeline values must align with observed timestamps")

    @property
    def is_observed(self) -> bool:
        return self.observed_scope is not None

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
    summary: PeriodSummary | None = None

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
    summary: PeriodSummary | None = None
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
class ScalarRankingEntry:
    key: GroupKey
    label: str
    value: ChartValue
    is_other: bool = False
    agent: str | None = None


@dataclass(frozen=True, slots=True)
class RankingModel:
    entries: tuple[RankingEntry, ...]
    date_range: DateRange | None
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    denominator: TokenUsage | None = None
    summary: PeriodSummary | None = None
    top: int | None = None
    top_share: float | None = None
    observed_entries: tuple[ScalarRankingEntry, ...] = field(default_factory=tuple)
    metric: MetricDescriptor = field(default_factory=MetricDescriptor)
    observed_scope: ObservedScope | None = None
    summary_notices: tuple[Notice, ...] = field(default_factory=tuple)
    project_aggregation: Literal["name", "exact"] = "name"

    def __post_init__(self) -> None:
        if not self.observed_entries and self.observed_scope is None:
            if self.date_range is None:
                raise ValueError("historical rankings require a date range")
            if self.top_share is not None:
                if self.top is None or not 0 <= self.top_share <= 1:
                    raise ValueError("ranking coverage requires Top and a valid share")
                if self.denominator is None or self.denominator.total <= 0:
                    raise ValueError("ranking coverage requires a positive denominator")
            elif self.top is not None:
                raise ValueError("ranking Top metadata requires coverage")
            return
        if self.entries or self.observed_scope is None or self.date_range is not None:
            raise ValueError("observed rankings require only observed entries and scope")
        if (
            self.denominator is not None
            or self.summary is not None
            or self.top is not None
            or self.top_share is not None
        ):
            raise ValueError("observed rankings do not support historical percentages or summaries")

    @property
    def is_observed(self) -> bool:
        return self.observed_scope is not None

    @property
    def total(self) -> TokenUsage:
        return sum((item.usage for item in self.entries), start=TokenUsage.zero())

    @property
    def percentage_total(self) -> TokenUsage:
        """Return the full filtered total used for historical entry percentages."""
        return self.denominator if self.denominator is not None else self.total
