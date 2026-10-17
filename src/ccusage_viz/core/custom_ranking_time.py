"""Time-range operations scoped to scalar V2 Custom Ranking charts."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ccusage_viz.core.time import DateRange, refresh_date_range, validate_timezone

_SUBDAY_PERIOD_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>s|m|h)$")


@dataclass(frozen=True, slots=True)
class TimestampRange:
    """An aware, nonempty, half-open timestamp interval."""

    start_at: datetime
    end_at: datetime
    relative_until: bool = False
    period: str | None = None
    fixed_bounds: bool = False

    def __post_init__(self) -> None:
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("timestamp range start_at must be timezone aware")
        if self.end_at.tzinfo is None or self.end_at.utcoffset() is None:
            raise ValueError("timestamp range end_at must be timezone aware")
        if self.end_at.astimezone(UTC) <= self.start_at.astimezone(UTC):
            raise ValueError("timestamp range end_at must be after start_at")
        if self.fixed_bounds and self.relative_until:
            raise ValueError("fixed timestamp range cannot be relative")
        if self.relative_until and self.period is None:
            raise ValueError("relative timestamp range requires a period")
        if self.period is not None:
            parse_subday_period(self.period)


def parse_subday_period(value: str) -> timedelta:
    """Parse a positive integer seconds/minutes/hours period."""

    match = _SUBDAY_PERIOD_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("period must be a positive integer followed by s, m, or h")
    multiplier = {"s": 1, "m": 60, "h": 3600}[match["unit"]]
    try:
        return timedelta(seconds=int(match["value"]) * multiplier)
    except OverflowError as exc:
        raise ValueError("period is out of range") from exc


def resolve_custom_ranking_range(
    period: str, *, now: datetime, timezone: str
) -> DateRange | TimestampRange:
    """Resolve a V2 Custom Ranking period, preserving legacy date periods."""

    zone = ZoneInfo(validate_timezone(timezone))
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    try:
        duration = parse_subday_period(period)
    except ValueError:
        from ccusage_viz.options import resolve_date_range

        return resolve_date_range(
            "ranking",
            period=period,
            since=None,
            until=None,
            today=now.astimezone(zone).date(),
            timezone=timezone,
        )
    end_utc = now.astimezone(UTC)
    try:
        start_utc = end_utc - duration
    except (OverflowError, ValueError) as exc:
        raise ValueError("period is out of range") from exc
    return TimestampRange(
        start_utc.astimezone(zone),
        end_utc.astimezone(zone),
        relative_until=True,
        period=period,
    )


def refresh_custom_ranking_range(
    value: DateRange | TimestampRange, *, now: datetime, timezone: str
) -> DateRange | TimestampRange:
    """Refresh a rolling Custom Ranking range using one supplied clock anchor."""

    if isinstance(value, DateRange):
        zone = ZoneInfo(validate_timezone(timezone))
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone aware")
        return refresh_date_range(value, today=now.astimezone(zone).date(), timezone=timezone)
    if not value.relative_until or value.period is None:
        return value
    return resolve_custom_ranking_range(value.period, now=now, timezone=timezone)


def previous_custom_ranking_range(value: TimestampRange) -> TimestampRange:
    """Return the immediately preceding interval with equal elapsed UTC duration."""

    start_utc = value.start_at.astimezone(UTC)
    end_utc = value.end_at.astimezone(UTC)
    duration = end_utc - start_utc
    try:
        previous_start = start_utc - duration
    except (OverflowError, ValueError) as exc:
        raise ValueError("previous timestamp range is out of range") from exc
    start_zone = value.start_at.tzinfo
    return replace(
        value,
        start_at=previous_start.astimezone(start_zone),
        end_at=start_utc.astimezone(start_zone),
        fixed_bounds=True,
        relative_until=False,
    )
