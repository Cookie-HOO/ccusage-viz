from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ccusage_viz.core.time import (
    DateRange,
    natural_period_start,
    today_for_timezone,
)
from ccusage_viz.core.time import (
    parse_period as parse_core_period,
)
from ccusage_viz.errors import UsageError

GRANULARITIES = ("day", "month", "quarter", "year")
HEADER_SUMMARIES = (*GRANULARITIES, "none")
PERIOD_UNITS = {"day": "d", "month": "mo", "quarter": "q", "year": "y"}
UNIT_GRANULARITIES = {unit: granularity for granularity, unit in PERIOD_UNITS.items()}
PERIOD_PRESETS = {
    "d": (7, 14, 30, 365),
    "mo": (3, 6, 13, 24),
    "q": (4, 8, 12),
    "y": (3, 5, 10),
}
COMMAND_DEFAULT_PERIODS = {"timeline": "14d", "calendar": "365d", "stack": "14d", "ranking": "14d"}
WEEKDAY_MODES = ("show", "hide")
OTHER_MODES = ("show", "hide")
CACHE_MODES = ("combined", "split")
COMMAND_STYLES = {
    "timeline": ("linear", "step", "no-line", "points", "line-points", "stem", "area"),
    "calendar": ("relative", "absolute"),
    "stack": ("stacked", "stacked-pattern", "grouped", "grouped-thin", "normalized"),
    "ranking": ("bar", "dot", "dots"),
    "monitor": ("bars", "line", "step", "points", "line-points", "ranking"),
}
DEFAULT_STYLES = {command: styles[0] for command, styles in COMMAND_STYLES.items()}
DASHBOARD_STYLES = ("minimal", "split", "framed", "accent")
DEFAULT_DASHBOARD_STYLE = "split"
MINIMUM_SIZES = {
    "timeline": (58, 16),
    "calendar": (58, 16),
    "stack": (58, 16),
    "ranking": (58, 16),
    "monitor": (40, 10),
}


def parse_period(value: str) -> tuple[int, str]:
    try:
        return parse_core_period(value)
    except ValueError as exc:
        raise UsageError(
            "error.arguments",
            detail="--period must be a positive integer followed by d, mo, q, or y",
        ) from exc


@dataclass(frozen=True, slots=True)
class CommandOptions:
    command: str
    date_range: DateRange
    by: str | None
    top: int | None
    other: str
    cache: str
    agents: tuple[str, ...]
    models: tuple[str, ...]
    projects: tuple[str, ...]
    demo: str | None
    ccusage_bin: str
    query_timeout: float
    no_color: bool
    ascii: bool
    color_scheme: str = "classic"
    style: str = "linear"
    window_seconds: int | None = None
    interval: float | None = None
    legend: str = "below-title"
    panes: tuple[str, ...] = ()
    grid: str = "2x2"
    header_style: str = "panel"
    header_summary: str = "day"
    header_interval: float = 60.0
    dashboard_style: str = DEFAULT_DASHBOARD_STYLE
    granularity: str = "day"
    weekdays: str = "show"
    no_watch: bool = False
    explicit: frozenset[str] = frozenset()

    def was_explicit(self, field: str) -> bool:
        return field in self.explicit


@dataclass(frozen=True, slots=True)
class TuiPanel:
    options: CommandOptions
    interval: float
    label: str


def compatible_styles(command: str, by: str | None) -> tuple[str, ...]:
    """Return styles that can represent the selected series shape."""
    styles = COMMAND_STYLES[command]
    if command == "timeline" and by is not None:
        return tuple(style for style in styles if style != "area")
    if command == "monitor" and by is not None:
        return tuple(style for style in styles if style != "bars")
    return styles


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


def adjust_option(options: CommandOptions, key: str) -> CommandOptions:
    """Apply one shared interactive option transition, if the key supports it."""
    if key in {"s", "S"}:
        styles = compatible_styles(options.command, options.by)
        current = options.style if options.style in styles else styles[0]
        return replace(options, style=_cycle(styles, current, 1 if key == "s" else -1))
    if key in {"t", "T"}:
        from ccusage_viz.render.palette import COLOR_SCHEMES

        color_scheme = _cycle(COLOR_SCHEMES, options.color_scheme, 1 if key == "t" else -1)
        return replace(options, color_scheme=color_scheme, no_color=color_scheme == "no-color")
    if key in {"i", "I"} and options.command == "monitor":
        interval_values: tuple[float, ...] = (
            (1.0, 5.0, 15.0, 30.0, 60.0) if options.demo else (5.0, 15.0, 30.0, 60.0)
        )
        current = options.interval
        index = interval_values.index(current) if current in interval_values else 2
        return replace(options, interval=interval_values[(index + 1) % len(interval_values)])
    if key in {"p", "P"} and options.command != "monitor":
        if not options.date_range.relative_until or options.date_range.period is None:
            return options
        granularity = options.granularity
        unit = PERIOD_UNITS[granularity]
        value, period_unit = parse_period(options.date_range.period)
        presets = PERIOD_PRESETS[period_unit]
        nearest = min(presets, key=lambda preset: abs(preset - value))
        next_value = presets[(presets.index(nearest) + 1) % len(presets)]
        unit = period_unit
        period = f"{next_value}{unit}"
        end = options.date_range.until
        return replace(
            options,
            date_range=DateRange(
                natural_period_start(end, next_value, unit),
                end,
                options.date_range.timezone,
                relative_until=True,
                period=period,
            ),
        )
    if key in {"g", "G"} and options.command in {"timeline", "stack"}:
        return replace(options, granularity=_cycle(GRANULARITIES, options.granularity, 1))
    if key in {"k", "K"} and options.command in {"timeline", "stack"}:
        return replace(options, weekdays=_cycle(WEEKDAY_MODES, options.weekdays, 1))
    if key in {"l", "L"} and options.command in {"timeline", "stack", "monitor"}:
        positions = (
            ("below-title", "hidden")
            if options.command == "stack"
            else ("below-title", "inside", "values", "hidden")
            if options.command == "monitor"
            else ("below-title", "inside", "hidden")
        )
        return replace(options, legend=_cycle(positions, options.legend, 1))
    if key in {"c", "C"} and options.command == "stack":
        return replace(options, cache=_cycle(CACHE_MODES, options.cache, 1))
    if key in {"b", "B"} and options.command in {"timeline", "ranking", "monitor"}:
        values: tuple[str | None, ...] = (
            (None, "agent", "model", "project")
            if options.command == "timeline"
            else ("agent", "model", "project")
            if options.command == "ranking"
            else (None, "agent", "model", "project")
        )
        current = options.by if options.by in values else values[0]
        by = values[(values.index(current) + 1) % len(values)]
        styles = compatible_styles(options.command, by)
        top = options.top
        if by is None:
            top = None
        elif top is None:
            top = 3
        return replace(
            options, by=by, top=top, style=options.style if options.style in styles else styles[0]
        )
    if (
        key in {"+", "="}
        and options.command in {"timeline", "ranking", "monitor"}
        and options.by is not None
    ):
        return replace(options, top=(options.top or 0) + 1)
    if (
        key in {"-", "_"}
        and options.command in {"timeline", "ranking", "monitor"}
        and options.by is not None
    ):
        return replace(options, top=max(1, (options.top or 1) - 1))
    if key in {"o", "O"} and options.command in {"timeline", "ranking"}:
        return replace(options, other=_cycle(OTHER_MODES, options.other, 1))
    if key in {"w", "W"} and options.command == "monitor":
        values = (300, 900, 1800, 3600, 21600, 43200, 86400)
        current = options.window_seconds or 3600
        nearest = min(values, key=lambda value: abs(value - current))
        return replace(options, window_seconds=values[(values.index(nearest) + 1) % len(values)])
    return options


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise UsageError("error.date_invalid", value=value) from exc


def resolve_date_range(
    command: str,
    *,
    period: str | None,
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
    try:
        current = today_for_timezone(timezone, today)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UsageError("error.timezone", value=timezone) from exc
    if period is not None and (since is not None or until is not None):
        raise UsageError("error.date_conflict")
    if until is not None and since is None:
        raise UsageError("error.date_order")
    end = _parse_date(until) if until else current
    if end > current:
        raise UsageError("error.future_until")
    if since is not None:
        start = _parse_date(since)
        if start > end:
            raise UsageError("error.date_order")
        return DateRange(
            start,
            end,
            timezone,
            fixed_bounds=until is not None,
            implicit_until=until is None,
        )

    canonical_period = period or COMMAND_DEFAULT_PERIODS[command]
    value, unit = parse_period(canonical_period)
    try:
        start = natural_period_start(end, value, unit)
    except (OverflowError, ValueError) as exc:
        raise UsageError("error.arguments", detail="--period is out of range") from exc
    return DateRange(start, end, timezone, relative_until=True, period=canonical_period)
