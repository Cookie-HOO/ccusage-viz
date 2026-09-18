from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_PERIOD_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>d|mo|q|y)$")


@dataclass(frozen=True, slots=True)
class DateRange:
    since: date
    until: date
    timezone: str | None
    relative_until: bool = False
    period: str | None = None
    fixed_bounds: bool = False
    implicit_until: bool = False

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1


def parse_period(value: str) -> tuple[int, str]:
    match = _PERIOD_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("period must be a positive integer followed by d, mo, q, or y")
    return int(match["value"]), match["unit"]


def natural_period_start(end: date, value: int, unit: str) -> date:
    if unit == "d":
        return end - timedelta(days=value - 1)
    if unit == "mo":
        month_index = end.year * 12 + end.month - 1 - (value - 1)
        return date(month_index // 12, month_index % 12 + 1, 1)
    if unit == "q":
        quarter_index = end.year * 4 + (end.month - 1) // 3 - (value - 1)
        return date(quarter_index // 4, quarter_index % 4 * 3 + 1, 1)
    if unit == "y":
        return date(end.year - value + 1, 1, 1)
    raise ValueError(f"unsupported period unit: {unit}")


def today_for_timezone(timezone: str | None, today: date | None = None) -> date:
    if today is not None:
        return today
    if timezone is None:
        return date.today()
    return datetime.now(ZoneInfo(timezone)).date()


def refresh_date_range(date_range: DateRange, *, today: date | None = None) -> DateRange:
    """Advance a rolling period while leaving startup-anchored ranges frozen."""
    if not date_range.relative_until or date_range.period is None:
        return date_range
    end = today_for_timezone(date_range.timezone, today)
    value, unit = parse_period(date_range.period)
    return replace(date_range, since=natural_period_start(end, value, unit), until=end)
