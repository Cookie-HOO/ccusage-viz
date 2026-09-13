from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ccusage_viz.errors import UsageError

DEFAULT_DAYS = {"timeline": 14, "calendar": 365, "stack": 14, "ranking": 14}
COMMAND_STYLES = {
    "timeline": ("linear", "step", "stem", "area"),
    "calendar": ("relative", "absolute"),
    "stack": ("stacked", "stacked-pattern", "grouped", "grouped-thin", "normalized"),
    "ranking": ("bar", "dot", "dots"),
    "monitor": ("bars", "line", "step"),
}
DEFAULT_STYLES = {command: styles[0] for command, styles in COMMAND_STYLES.items()}
MINIMUM_SIZES = {
    "timeline": (60, 18),
    "calendar": (72, 14),
    "stack": (60, 18),
    "ranking": (60, 12),
    "monitor": (60, 18),
}


@dataclass(frozen=True, slots=True)
class DateRange:
    since: date
    until: date
    timezone: str | None
    relative_until: bool = False
    relative_days: int | None = None
    fixed_bounds: bool = False

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1


def refresh_date_range(date_range: DateRange, *, today: date | None = None) -> DateRange:
    """Advance an unanchored range to the current natural day."""
    if not date_range.relative_until:
        return date_range
    end = today_for_timezone(date_range.timezone, today)
    start = (
        end - timedelta(days=date_range.relative_days - 1)
        if date_range.relative_days is not None
        else date_range.since
    )
    return DateRange(
        start,
        end,
        date_range.timezone,
        relative_until=True,
        relative_days=date_range.relative_days,
        fixed_bounds=date_range.fixed_bounds,
    )


@dataclass(frozen=True, slots=True)
class CommandOptions:
    command: str
    date_range: DateRange
    by: str | None
    top: int | None
    show_other: bool
    split_cache: bool
    agents: tuple[str, ...]
    models: tuple[str, ...]
    projects: tuple[str, ...]
    watch: float | None
    demo: str | None
    ccusage_bin: str
    timeout: float
    no_color: bool
    ascii: bool
    color_scheme: str = "classic"
    style: str = "linear"
    pick: bool = False
    window_seconds: int | None = None
    interval: float | None = None
    no_summary: bool = False
    legend_position: str = "below-title"


def compatible_styles(command: str, by: str | None) -> tuple[str, ...]:
    """Return styles that can represent the selected series shape."""
    styles = COMMAND_STYLES[command]
    if command == "timeline" and by != "total":
        return tuple(style for style in styles if style != "area")
    if command == "monitor" and by is not None:
        return tuple(style for style in styles if style != "bars")
    return styles


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise UsageError("error.date_invalid", value=value) from exc


def today_for_timezone(timezone: str | None, today: date | None = None) -> date:
    if today is not None:
        return today
    if timezone is None:
        return date.today()
    try:
        return datetime.now(ZoneInfo(timezone)).date()
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UsageError("error.timezone", value=timezone) from exc


def resolve_date_range(
    command: str,
    *,
    days: int | None,
    since: str | None,
    until: str | None,
    timezone: str | None,
    today: date | None = None,
) -> DateRange:
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise UsageError("error.timezone", value=timezone) from exc
    current = today_for_timezone(timezone, today)
    if days is not None and days <= 0:
        raise UsageError("error.days_positive")
    if days is not None and since is not None:
        raise UsageError("error.date_conflict")
    end = _parse_date(until) if until else current
    if end > current:
        raise UsageError("error.future_until")
    if since is not None:
        start = _parse_date(since)
    else:
        actual_days = days if days is not None else DEFAULT_DAYS[command]
        try:
            start = end - timedelta(days=actual_days - 1)
        except OverflowError as exc:
            raise UsageError("error.days_positive") from exc
    if start > end:
        raise UsageError("error.date_order")
    relative_until = since is None and until is None
    return DateRange(
        start,
        end,
        timezone,
        relative_until=relative_until,
        relative_days=actual_days if relative_until else None,
        fixed_bounds=since is not None and until is not None,
    )
