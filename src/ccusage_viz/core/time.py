from __future__ import annotations

import os
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone_name

_PERIOD_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>d|w|mo|q|y)$")


@dataclass(frozen=True, slots=True)
class DateRange:
    since: date
    until: date
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
        raise ValueError("period must be a positive integer followed by d, w, mo, q, or y")
    return int(match["value"]), match["unit"]


def natural_period_start(end: date, value: int, unit: str) -> date:
    if unit == "d":
        return end - timedelta(days=value - 1)
    if unit == "w":
        return end - timedelta(days=end.weekday() + 7 * (value - 1))
    if unit == "mo":
        month_index = end.year * 12 + end.month - 1 - (value - 1)
        return date(month_index // 12, month_index % 12 + 1, 1)
    if unit == "q":
        quarter_index = end.year * 4 + (end.month - 1) // 3 - (value - 1)
        return date(quarter_index // 4, quarter_index % 4 * 3 + 1, 1)
    if unit == "y":
        return date(end.year - value + 1, 1, 1)
    raise ValueError(f"unsupported period unit: {unit}")


def validate_timezone(value: str) -> str:
    """Validate an IANA timezone identifier used in Dataset requests."""
    if not value or value.strip() != value:
        raise ValueError("timezone must be a non-empty IANA timezone name")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid IANA timezone: {value}") from exc
    return value


def system_timezone() -> str:
    """Return the local system timezone as an IANA identifier."""
    try:
        return validate_timezone(get_localzone_name())
    except (OSError, ValueError, ZoneInfoNotFoundError):
        pass

    configured = os.environ.get("TZ")
    candidates = (configured,) if configured else ()
    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        try:
            target = localtime.resolve()
            candidates += (str(target).partition("zoneinfo/")[2],)
        except OSError:
            pass
    timezone_link = Path("/var/db/timezone/zoneinfo/localtime")
    if timezone_link.is_symlink():
        with suppress(OSError):
            candidates += (str(timezone_link.resolve()).partition("zoneinfo/")[2],)
    for candidate in candidates:
        if candidate:
            try:
                return validate_timezone(candidate)
            except ValueError:
                continue
    zone = datetime.now().astimezone().tzinfo
    key = getattr(zone, "key", None)
    if isinstance(key, str):
        return validate_timezone(key)
    raise ValueError("could not determine the system IANA timezone; use --timezone")


def local_today(today: date | None = None, *, timezone: str | None = None) -> date:
    if today is not None:
        return today
    return datetime.now(ZoneInfo(validate_timezone(timezone))).date() if timezone else date.today()


def refresh_date_range(
    date_range: DateRange, *, today: date | None = None, timezone: str | None = None
) -> DateRange:
    """Advance a rolling period while leaving startup-anchored ranges frozen."""
    if not date_range.relative_until or date_range.period is None:
        return date_range
    end = local_today(today, timezone=timezone)
    if date_range.period == "all":
        return replace(date_range, until=end)
    value, unit = parse_period(date_range.period)
    return replace(date_range, since=natural_period_start(end, value, unit), until=end)
