from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Literal, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ccusage_viz.core.time import DateRange, natural_period_start, today_for_timezone
from ccusage_viz.core.time import parse_period as parse_core_period
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

Dimension: TypeAlias = Literal["agent", "model", "project"]


@dataclass(frozen=True, slots=True)
class ProcessConfig:
    ccusage_bin: str = "ccusage"
    query_timeout: float = 30.0
    output_limit: int = 16 * 1024 * 1024
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Filters:
    agents: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChartPresentation:
    theme: str = "classic"
    style: str = "linear"
    legend: str = "below-title"


@dataclass(frozen=True, slots=True)
class TimelineConfig:
    kind: Literal["timeline"]
    date_range: DateRange
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation()
    by: Dimension | None = None
    top: int | None = None
    other: str = "show"
    granularity: str = "day"
    weekdays: str = "show"


@dataclass(frozen=True, slots=True)
class CalendarConfig:
    kind: Literal["calendar"]
    date_range: DateRange
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation(style="relative")


@dataclass(frozen=True, slots=True)
class StackConfig:
    kind: Literal["stack"]
    date_range: DateRange
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation(style="stacked")
    cache: str = "combined"
    granularity: str = "day"
    weekdays: str = "show"


@dataclass(frozen=True, slots=True)
class RankingConfig:
    kind: Literal["ranking"]
    date_range: DateRange
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation(style="bar")
    by: Dimension = "project"
    top: int = 10
    other: str = "show"


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    kind: Literal["monitor"]
    window_seconds: int
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation(style="bars")
    by: Dimension | None = None
    top: int | None = None


HistoricalChartConfig: TypeAlias = TimelineConfig | CalendarConfig | StackConfig | RankingConfig
ChartConfig: TypeAlias = HistoricalChartConfig | MonitorConfig


@dataclass(frozen=True, slots=True)
class StandaloneHostConfig:
    provider: str = "ccusage"
    timezone: str | None = None
    ascii: bool = False
    demo_size: str | None = None
    watch: bool = True
    interval: float = 10.0


@dataclass(frozen=True, slots=True)
class PaneConfig:
    chart: ChartConfig


@dataclass(frozen=True, slots=True)
class DashboardHostConfig:
    provider: str = "ccusage"
    timezone: str | None = None
    ascii: bool = False
    demo_size: str | None = None
    grid: str = "2x2"
    refresh_interval: float = 15.0
    sampling_interval: float = 15.0
    header_style: str = "panel"
    header_summary: str = "day"
    header_interval: float = 60.0
    theme: str = "classic"
    style: str = DEFAULT_DASHBOARD_STYLE


@dataclass(frozen=True, slots=True)
class StandaloneLaunch:
    process: ProcessConfig
    host: StandaloneHostConfig
    chart: ChartConfig
    explicit: frozenset[str] = frozenset()

    def was_explicit(self, field: str) -> bool:
        return field in self.explicit


@dataclass(frozen=True, slots=True)
class DashboardLaunch:
    process: ProcessConfig
    host: DashboardHostConfig
    panes: tuple[PaneConfig, ...]
    explicit: frozenset[str] = frozenset()

    def was_explicit(self, field: str) -> bool:
        return field in self.explicit


LaunchConfig: TypeAlias = StandaloneLaunch | DashboardLaunch


@dataclass(frozen=True, slots=True)
class StandaloneRoute:
    launch: StandaloneLaunch


@dataclass(frozen=True, slots=True)
class DashboardRoute:
    launch: DashboardLaunch


LaunchRoute: TypeAlias = StandaloneRoute | DashboardRoute


def chart_kind(chart: ChartConfig) -> str:
    return chart.kind


def compatible_styles(command: str, by: str | None) -> tuple[str, ...]:
    styles = COMMAND_STYLES[command]
    if command == "timeline" and by is not None:
        return tuple(style for style in styles if style != "area")
    if command == "monitor" and by is not None:
        return tuple(style for style in styles if style != "bars")
    return styles


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


def adjust_chart(chart: ChartConfig, key: str, *, demo: bool = False) -> ChartConfig:
    if key in {"s", "S"}:
        styles = compatible_styles(chart.kind, getattr(chart, "by", None))
        current = chart.presentation.style
        style = _cycle(styles, current if current in styles else styles[0], 1 if key == "s" else -1)
        return replace(chart, presentation=replace(chart.presentation, style=style))
    if key in {"t", "T"}:
        from ccusage_viz.render.palette import COLOR_SCHEMES

        theme = _cycle(COLOR_SCHEMES, chart.presentation.theme, 1 if key == "t" else -1)
        return replace(chart, presentation=replace(chart.presentation, theme=theme))
    if key in {"p", "P"} and not isinstance(chart, MonitorConfig):
        if not chart.date_range.relative_until or chart.date_range.period is None:
            return chart
        value, unit = parse_period(chart.date_range.period)
        presets = PERIOD_PRESETS[unit]
        nearest = min(presets, key=lambda preset: abs(preset - value))
        next_value = presets[(presets.index(nearest) + 1) % len(presets)]
        period = f"{next_value}{unit}"
        end = chart.date_range.until
        return replace(
            chart,
            date_range=replace(
                chart.date_range, since=natural_period_start(end, next_value, unit), period=period
            ),
        )
    if key in {"g", "G"} and isinstance(chart, (TimelineConfig, StackConfig)):
        return replace(chart, granularity=_cycle(GRANULARITIES, chart.granularity, 1))
    if key in {"k", "K"} and isinstance(chart, (TimelineConfig, StackConfig)):
        return replace(chart, weekdays=_cycle(WEEKDAY_MODES, chart.weekdays, 1))
    if key in {"l", "L"} and isinstance(chart, (TimelineConfig, StackConfig, MonitorConfig)):
        values = (
            ("below-title", "hidden")
            if isinstance(chart, StackConfig)
            else ("below-title", "inside", "values", "hidden")
            if isinstance(chart, MonitorConfig)
            else ("below-title", "inside", "hidden")
        )
        return replace(
            chart,
            presentation=replace(
                chart.presentation, legend=_cycle(values, chart.presentation.legend, 1)
            ),
        )
    if key in {"c", "C"} and isinstance(chart, StackConfig):
        return replace(chart, cache=_cycle(CACHE_MODES, chart.cache, 1))
    if key in {"b", "B"} and isinstance(chart, (TimelineConfig, RankingConfig, MonitorConfig)):
        values: tuple[Dimension | None, ...] = (
            (None, "agent", "model", "project")
            if not isinstance(chart, RankingConfig)
            else ("agent", "model", "project")
        )
        current = chart.by if chart.by in values else values[0]
        by = values[(values.index(current) + 1) % len(values)]
        styles = compatible_styles(chart.kind, by)
        top = None if by is None else chart.top or 3
        presentation = (
            chart.presentation
            if chart.presentation.style in styles
            else replace(chart.presentation, style=styles[0])
        )
        return replace(chart, by=by, top=top, presentation=presentation)
    if (
        key in {"+", "="}
        and isinstance(chart, (TimelineConfig, RankingConfig, MonitorConfig))
        and chart.by is not None
    ):
        return replace(chart, top=(chart.top or 0) + 1)
    if (
        key in {"-", "_"}
        and isinstance(chart, (TimelineConfig, RankingConfig, MonitorConfig))
        and chart.by is not None
    ):
        return replace(chart, top=max(1, (chart.top or 1) - 1))
    if key in {"o", "O"} and isinstance(chart, (TimelineConfig, RankingConfig)):
        return replace(chart, other=_cycle(OTHER_MODES, chart.other, 1))
    if key in {"w", "W"} and isinstance(chart, MonitorConfig):
        values = (300, 900, 1800, 3600, 21600, 43200, 86400)
        nearest = min(values, key=lambda value: abs(value - chart.window_seconds))
        return replace(chart, window_seconds=values[(values.index(nearest) + 1) % len(values)])
    return chart


def adjust_standalone(config: StandaloneLaunch, key: str) -> StandaloneLaunch:
    if key in {"i", "I"} and isinstance(config.chart, MonitorConfig):
        values = (1.0, 5.0, 15.0, 30.0, 60.0) if config.host.demo_size else (5.0, 15.0, 30.0, 60.0)
        current = config.host.interval
        index = values.index(current) if current in values else 2
        return replace(
            config, host=replace(config.host, interval=values[(index + 1) % len(values)])
        )
    return replace(
        config, chart=adjust_chart(config.chart, key, demo=config.host.demo_size is not None)
    )


def parse_period(value: str) -> tuple[int, str]:
    try:
        return parse_core_period(value)
    except ValueError as exc:
        raise UsageError(
            "error.arguments",
            detail="--period must be a positive integer followed by d, mo, q, or y",
        ) from exc


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
            start, end, timezone, fixed_bounds=until is not None, implicit_until=until is None
        )
    canonical_period = period or COMMAND_DEFAULT_PERIODS[command]
    value, unit = parse_period(canonical_period)
    try:
        start = natural_period_start(end, value, unit)
    except (OverflowError, ValueError) as exc:
        raise UsageError("error.arguments", detail="--period is out of range") from exc
    return DateRange(start, end, timezone, relative_until=True, period=canonical_period)
