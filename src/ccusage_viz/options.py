from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Literal, TypeAlias

from ccusage_viz.animation import AnimationSpec
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.core.time import DateRange, local_today, natural_period_start
from ccusage_viz.core.time import parse_period as parse_core_period
from ccusage_viz.errors import UsageError
from ccusage_viz.project_identity import ProjectAggregation

GRANULARITIES = ("day", "week", "month", "quarter", "year")
HEADER_SUMMARIES = (*GRANULARITIES, "none")
PERIOD_UNITS = {"day": "d", "week": "w", "month": "mo", "quarter": "q", "year": "y"}
UNIT_GRANULARITIES = {unit: granularity for granularity, unit in PERIOD_UNITS.items()}
PERIOD_PRESETS = {
    "day": ("7d", "14d", "30d", "90d", "180d", "365d"),
    "week": ("1w", "4w", "8w", "13w", "26w", "52w"),
    "month": ("2mo", "6mo", "12mo", "24mo"),
    "quarter": ("2q", "4q", "8q", "12q", "20q"),
    "year": ("1y", "3y", "5y", "10y"),
}
INTERACTIVE_PERIOD_PRESETS = (
    "7d",
    "14d",
    "30d",
    "90d",
    "180d",
    "365d",
    "1w",
    "1mo",
    "1y",
)
RANKING_INTERACTIVE_PERIOD_PRESETS = ("1d", *INTERACTIVE_PERIOD_PRESETS, "all")
ALL_PERIOD_START = date(1971, 1, 1)
DEFAULT_PERIODS = {
    "day": "14d",
    "week": "8w",
    "month": "12mo",
    "quarter": "8q",
    "year": "5y",
}
COMMAND_DEFAULT_PERIODS = {"timeline": "14d", "calendar": "365d", "stack": "14d", "ranking": "14d"}
WEEKDAY_MODES = ("show", "hide")
OTHER_MODES = ("show", "hide")
CACHE_MODES = ("combined", "split")
COMMAND_STYLES = {
    "timeline": ("linear", "step", "no-line", "points", "line-points", "stem", "area"),
    "calendar": ("relative", "grid"),
    "stack": ("stacked", "stacked-pattern", "grouped", "grouped-thin", "normalized"),
    "ranking": ("dot", "bar", "dots"),
    "monitor": (
        "bars",
        "line",
        "step",
        "points",
        "line-points",
        "ranking",
        "list",
        "cumulative-bars",
    ),
}
DEFAULT_STYLES = {command: styles[0] for command, styles in COMMAND_STYLES.items()}
DASHBOARD_STYLES = ("minimal", "split", "framed", "accent")
DEFAULT_DASHBOARD_STYLE = "split"
DENSITIES = ("minimal", "compact", "full", "detailed")
MINIMUM_SIZES = {
    "timeline": (58, 16),
    "calendar": (58, 16),
    "stack": (58, 16),
    "ranking": (58, 16),
    "monitor": (40, 10),
}

Dimension: TypeAlias = Literal["composition", "agent", "model", "project"]
Density: TypeAlias = Literal["minimal", "compact", "full", "detailed"]
MonitorDayWindow: TypeAlias = Literal["today", "yesterday"]


def has_complete_content(density: Density) -> bool:
    """Return whether a density includes comparisons and observed metrics."""
    return density in {"full", "detailed"}


MonitorDistributionGranularity: TypeAlias = Literal["hour", "half-hour"]


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
    density: Density = "detailed"


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
    project_aggregation: ProjectAggregation = "name"


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
    by: Dimension = "composition"
    top: int = 10
    other: str = "show"
    project_aggregation: ProjectAggregation = "name"


@dataclass(frozen=True, slots=True)
class RankingConfig:
    kind: Literal["ranking"]
    date_range: DateRange
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation(style="dot")
    by: Dimension = "project"
    top: int = 10
    other: str = "show"
    project_aggregation: ProjectAggregation = "name"


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    kind: Literal["monitor"]
    window_seconds: int
    filters: Filters = Filters()
    presentation: ChartPresentation = ChartPresentation(style="bars")
    by: Dimension | None = None
    top: int | None = None
    project_aggregation: ProjectAggregation = "name"
    day_window: MonitorDayWindow = "today"
    distribution_granularity: MonitorDistributionGranularity = "hour"


@dataclass(frozen=True, slots=True)
class CustomCommandSource:
    """The stable identity and argv of a custom dataset."""

    dataset_id: str
    command_argv: tuple[str, ...]
    source_kind: Literal["command", "installed"] = "command"

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("custom dataset_id must not be empty")
        if not self.command_argv:
            raise ValueError("custom command argv must not be empty")
        if self.source_kind not in {"command", "installed"}:
            raise ValueError("custom source_kind must be command or installed")


CustomFilters: TypeAlias = tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class CustomChartConfig:
    """Declarative V1 historical or V2 Metric chart configuration."""

    kind: Literal["timeline", "calendar", "stack", "ranking", "monitor"]
    source: CustomCommandSource
    date_range: DateRange
    filters: CustomFilters = ()
    presentation: ChartPresentation = ChartPresentation()
    group_by: str | None = None
    top: int | None = None
    other: str = "show"
    granularity: str = "day"
    weekdays: str = "show"
    initial_explicit: frozenset[str] = frozenset()
    metric_id: str | None = None
    metric_summary: Literal["comparisons", "total", "none"] = "comparisons"
    metric_periods: tuple[str, ...] = ()
    metric_titles: tuple[str, str] | None = None


HistoricalChartConfig: TypeAlias = TimelineConfig | CalendarConfig | StackConfig | RankingConfig
ChartConfig: TypeAlias = HistoricalChartConfig | MonitorConfig | CustomChartConfig


@dataclass(frozen=True, slots=True)
class StandaloneHostConfig:
    provider: str = "ccusage"
    ascii: bool = False
    demo_size: str | None = None
    watch: bool = True
    interval: float = 10.0
    demo_seed: int | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class ChartPaneConfig:
    chart: HistoricalChartConfig | MonitorConfig
    attachment_style: str | None = None
    attachment_theme: str | None = None


@dataclass(frozen=True, slots=True)
class CustomChartPaneConfig:
    chart: CustomChartConfig
    attachment_style: str | None = None
    attachment_theme: str | None = None


@dataclass(frozen=True, slots=True)
class AnimationPaneConfig:
    animation: AnimationSpec
    overlay: OverlayConfig = OverlayConfig()


@dataclass(frozen=True, slots=True)
class EmptyPaneConfig:
    pass


PaneConfig: TypeAlias = (
    ChartPaneConfig | CustomChartPaneConfig | AnimationPaneConfig | EmptyPaneConfig
)


@dataclass(frozen=True, slots=True)
class DashboardHostConfig:
    provider: str = "ccusage"
    ascii: bool = False
    demo_size: str | None = None
    demo_seed: int | None = None
    timezone: str | None = None
    grid: str = "2x2"
    layout: str | None = None
    column_weights: tuple[int, ...] | None = None
    row_weights: tuple[int, ...] | None = None
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
    launcher: str = "ccuv"

    def __post_init__(self) -> None:
        sources: dict[str, CustomCommandSource] = {}
        for pane in self.panes:
            if not isinstance(pane, CustomChartPaneConfig):
                continue
            previous = sources.setdefault(pane.chart.source.dataset_id, pane.chart.source)
            if previous != pane.chart.source:
                raise ValueError(
                    "custom dataset ID must use one command configuration across the dashboard"
                )

    def was_explicit(self, field: str) -> bool:
        return field in self.explicit


@dataclass(frozen=True, slots=True)
class AnimationLaunch:
    process: ProcessConfig
    host: StandaloneHostConfig
    animation: AnimationSpec
    explicit: frozenset[str] = frozenset()
    gallery: bool = False
    overlay: OverlayConfig = OverlayConfig()

    def was_explicit(self, field: str) -> bool:
        return field in self.explicit


LaunchConfig: TypeAlias = StandaloneLaunch | DashboardLaunch | AnimationLaunch


@dataclass(frozen=True, slots=True)
class StandaloneRoute:
    launch: StandaloneLaunch


@dataclass(frozen=True, slots=True)
class DashboardRoute:
    launch: DashboardLaunch


@dataclass(frozen=True, slots=True)
class AnimationRoute:
    launch: AnimationLaunch


LaunchRoute: TypeAlias = StandaloneRoute | DashboardRoute | AnimationRoute


def chart_kind(chart: ChartConfig) -> str:
    return chart.kind


def pane_kind(pane: PaneConfig) -> str:
    if isinstance(pane, EmptyPaneConfig):
        return "empty"
    if isinstance(pane, CustomChartPaneConfig):
        return "custom"
    if isinstance(pane, AnimationPaneConfig):
        return "animation"
    return "chart"


def compatible_styles(command: str, by: str | None) -> tuple[str, ...]:
    styles = COMMAND_STYLES[command]
    if command == "timeline" and by is not None:
        return tuple(style for style in styles if style != "area")
    if command == "monitor" and by is not None:
        return tuple(style for style in styles if style != "bars")
    return styles


def is_monitor_distribution(chart: MonitorConfig) -> bool:
    return chart.presentation.style == "cumulative-bars"


def monitor_shows_window_control(chart: MonitorConfig) -> bool:
    return chart.presentation.style not in {"ranking", "list"}


def _cycle(values: tuple[str, ...], current: str, step: int) -> str:
    return values[(values.index(current) + step) % len(values)]


def _adjust_period(date_range: DateRange, key: str, *, kind: str) -> DateRange:
    """Adjust a rolling time view without crossing its granularity boundary."""
    if not date_range.relative_until or date_range.period is None:
        return date_range
    if kind == "ranking" and date_range.period == "all":
        period = _cycle(
            RANKING_INTERACTIVE_PERIOD_PRESETS, "all", 1 if key == "p" else -1
        )
        return resolve_date_range(kind, period=period, since=None, until=None)
    _, unit = parse_period(date_range.period)
    granularity = UNIT_GRANULARITIES[unit]
    presets = (
        RANKING_INTERACTIVE_PERIOD_PRESETS if kind == "ranking" else INTERACTIVE_PERIOD_PRESETS
    )
    if date_range.period in presets:
        period = _cycle(
            presets, date_range.period, 1 if key == "p" else -1
        )
    else:
        period = DEFAULT_PERIODS[granularity]
    if kind == "ranking" and period == "all":
        return DateRange(ALL_PERIOD_START, date_range.until, relative_until=True, period="all")
    value, preset_unit = parse_period(period)
    return replace(
        date_range,
        since=natural_period_start(date_range.until, value, preset_unit),
        period=period,
    )


def _with_granularity_period(
    chart: TimelineConfig | StackConfig, key: str
) -> TimelineConfig | StackConfig:
    granularity = _cycle(GRANULARITIES, chart.granularity, 1 if key == "g" else -1)
    period = DEFAULT_PERIODS[granularity]
    value, unit = parse_period(period)
    return replace(
        chart,
        granularity=granularity,
        date_range=replace(
            chart.date_range,
            since=natural_period_start(chart.date_range.until, value, unit),
            period=period,
        ),
    )


def adjust_chart(chart: ChartConfig, key: str, *, demo: bool = False) -> ChartConfig:
    if key == "d":
        return replace(
            chart,
            presentation=replace(
                chart.presentation,
                density=_cycle(DENSITIES, chart.presentation.density, 1),
            ),
        )
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
        return replace(chart, date_range=_adjust_period(chart.date_range, key, kind=chart.kind))
    if key in {"g", "G"} and isinstance(chart, (TimelineConfig, StackConfig)):
        if not chart.date_range.relative_until:
            return chart
        return _with_granularity_period(chart, key)
    if key == "k" and isinstance(chart, (TimelineConfig, StackConfig)):
        return replace(chart, weekdays=_cycle(WEEKDAY_MODES, chart.weekdays, 1))
    if key == "l" and isinstance(chart, (TimelineConfig, StackConfig, MonitorConfig)):
        values = (
            ("below-title", "hidden")
            if isinstance(chart, StackConfig)
            else ("below-title", "inside", "values", "hidden")
            if isinstance(chart, MonitorConfig) and chart.presentation.style == "cumulative-bars"
            else ("below-title", "inside", "hidden")
        )
        return replace(
            chart,
            presentation=replace(
                chart.presentation, legend=_cycle(values, chart.presentation.legend, 1)
            ),
        )
    if key == "c" and isinstance(chart, StackConfig) and chart.by == "composition":
        return replace(chart, cache=_cycle(CACHE_MODES, chart.cache, 1))
    if key in {"b", "B"} and isinstance(
        chart, (TimelineConfig, StackConfig, RankingConfig, MonitorConfig)
    ):
        values: tuple[Dimension | None, ...] = (
            ("composition", "agent", "model", "project")
            if isinstance(chart, StackConfig)
            else (None, "agent", "model", "project", "composition")
            if isinstance(chart, TimelineConfig)
            else ("agent", "model", "composition", "project")
        )
        current = chart.by if chart.by in values else values[0]
        by = values[(values.index(current) + (1 if key == "b" else -1)) % len(values)]
        styles = compatible_styles(chart.kind, by)
        top = None if by is None else chart.top or (10 if isinstance(chart, StackConfig) else 3)
        presentation = (
            chart.presentation
            if chart.presentation.style in styles
            else replace(chart.presentation, style=styles[0])
        )
        return replace(chart, by=by, top=top, presentation=presentation)
    if (
        key in {"+", "="}
        and isinstance(chart, (TimelineConfig, StackConfig, RankingConfig, MonitorConfig))
        and chart.by is not None
    ):
        return replace(chart, top=(chart.top or 0) + 1)
    if (
        key in {"-", "_"}
        and isinstance(chart, (TimelineConfig, StackConfig, RankingConfig, MonitorConfig))
        and chart.by is not None
    ):
        return replace(chart, top=max(1, (chart.top or 1) - 1))
    if key == "o" and isinstance(chart, (TimelineConfig, StackConfig, RankingConfig)):
        return replace(chart, other=_cycle(OTHER_MODES, chart.other, 1))
    if key == "w" and isinstance(chart, MonitorConfig):
        if chart.presentation.style in {"ranking", "list"}:
            return chart
        if is_monitor_distribution(chart):
            values: tuple[MonitorDayWindow, ...] = ("today", "yesterday")
            return replace(chart, day_window=_cycle(values, chart.day_window, 1))
        values = (300, 900, 1800, 3600, 21600, 43200, 86400)
        nearest = min(values, key=lambda value: abs(value - chart.window_seconds))
        return replace(chart, window_seconds=values[(values.index(nearest) + 1) % len(values)])
    if key == "g" and isinstance(chart, MonitorConfig) and is_monitor_distribution(chart):
        values: tuple[MonitorDistributionGranularity, ...] = ("hour", "half-hour")
        return replace(
            chart,
            distribution_granularity=_cycle(values, chart.distribution_granularity, 1),
        )
    return chart


def adjust_custom_chart(chart: CustomChartConfig, key: str) -> CustomChartConfig:
    """Apply a local custom chart adjustment."""

    if key in {"p", "P"}:
        if chart.metric_periods:
            current = chart.date_range.period
            period = _cycle(
                chart.metric_periods,
                current if current in chart.metric_periods else chart.metric_periods[0],
                1 if key == "p" else -1,
            )
            return replace(
                chart,
                date_range=resolve_date_range(chart.kind, period=period, since=None, until=None),
            )
        return replace(chart, date_range=_adjust_period(chart.date_range, key, kind=chart.kind))
    if key == "d":
        return replace(
            chart,
            presentation=replace(
                chart.presentation,
                density=_cycle(DENSITIES, chart.presentation.density, 1),
            ),
        )
    if key in {"s", "S"}:
        styles = compatible_styles(chart.kind, chart.group_by)
        current = chart.presentation.style
        return replace(
            chart,
            presentation=replace(
                chart.presentation,
                style=_cycle(
                    styles, current if current in styles else styles[0], 1 if key == "s" else -1
                ),
            ),
        )
    if key in {"t", "T"}:
        from ccusage_viz.render.palette import COLOR_SCHEMES

        return replace(
            chart,
            presentation=replace(
                chart.presentation,
                theme=_cycle(COLOR_SCHEMES, chart.presentation.theme, 1 if key == "t" else -1),
            ),
        )
    if key == "k" and chart.kind in {"timeline", "stack"}:
        return replace(chart, weekdays=_cycle(WEEKDAY_MODES, chart.weekdays, 1))
    if key == "l" and chart.kind in {"timeline", "stack"}:
        return replace(
            chart,
            presentation=replace(
                chart.presentation,
                legend=_cycle(("below-title", "inside", "hidden"), chart.presentation.legend, 1),
            ),
        )
    if key == "o" and chart.group_by is not None:
        return replace(chart, other=_cycle(OTHER_MODES, chart.other, 1))
    if key in {"+", "="} and chart.group_by is not None:
        return replace(chart, top=(chart.top or 0) + 1)
    if key in {"-", "_"} and chart.group_by is not None:
        return replace(chart, top=max(1, (chart.top or 1) - 1))
    return chart


def replace_chart_filters(config: StandaloneLaunch, filters: Filters) -> StandaloneLaunch:
    return replace(config, chart=replace(config.chart, filters=filters))


def adjust_standalone(config: StandaloneLaunch, key: str) -> StandaloneLaunch:
    if key == "i" and isinstance(config.chart, MonitorConfig):
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
            detail="--period must be a positive integer followed by d, w, mo, q, or y",
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
    today: date | None = None,
    timezone: str | None = None,
) -> DateRange:
    current = local_today(today, timezone=timezone)
    if period is not None and (since is not None or until is not None):
        raise UsageError("error.date_conflict")
    if until is not None and since is None:
        raise UsageError("error.date_order")
    end = _parse_date(until) if until else current
    if command == "ranking" and period == "all":
        if since is not None or until is not None:
            raise UsageError("error.date_conflict")
        return DateRange(ALL_PERIOD_START, end, relative_until=True, period="all")
    if end > current:
        raise UsageError("error.future_until")
    if since is not None:
        start = _parse_date(since)
        if start > end:
            raise UsageError("error.date_order")
        return DateRange(start, end, fixed_bounds=True, implicit_until=until is None)
    canonical_period = period or COMMAND_DEFAULT_PERIODS[command]
    value, unit = parse_period(canonical_period)
    try:
        start = natural_period_start(end, value, unit)
    except (OverflowError, ValueError) as exc:
        raise UsageError("error.arguments", detail="--period is out of range") from exc
    return DateRange(start, end, relative_until=True, period=canonical_period)
