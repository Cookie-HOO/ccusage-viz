from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from math import isfinite

from ccusage_viz.custom_models import (
    CustomUnit,
    LocalizedText,
    V2MonitorCapability,
    V2MonitorObservation,
)
from ccusage_viz.custom_protocol.responses import V2MonitorResponse
from ccusage_viz.options import CustomChartConfig

_MAX_DISPLAY_WINDOW_SECONDS = 86_400

def custom_monitor_y_axis_max(values: list[float]) -> float:
    """Return a non-degenerate upper bound for source-owned Monitor timelines."""

    maximum = max(values, default=0.0)
    if not isfinite(maximum) or maximum <= 0:
        return 1.0
    return maximum

def custom_monitor_styles(aggregation: str, group_by: str | None = None) -> tuple[str, ...]:
    """Return the complete source-safe Monitor style cycle for an aggregation."""
    styles = (
        "bars",
        "line",
        "step",
        "points",
        "line-points",
        "ranking",
        "ranking-dot",
        "list",
    )
    if group_by is not None:
        styles = tuple(style for style in styles if style != "bars")
    return (*styles, "cumulative-bars") if aggregation == "sum" else styles

def normalize_custom_monitor_style(
    config: CustomChartConfig, aggregation: str
) -> CustomChartConfig:
    """Normalize persisted presentation state against a metric's aggregation."""
    styles = custom_monitor_styles(aggregation, config.group_by)
    style = config.presentation.style
    if style in styles:
        return config
    # A value metric restored from a sum metric's state must not silently imply
    # accumulation; ranking is the nearest non-temporal presentation.
    fallback = "ranking" if style == "cumulative-bars" else styles[0]
    return replace(config, presentation=replace(config.presentation, style=fallback))

@dataclass(frozen=True, slots=True)
class CustomMonitorCompletion:
    generation: int
    config: CustomChartConfig
    response: V2MonitorResponse

@dataclass(frozen=True, slots=True)
class CustomMonitorPresentation:
    """Source-declared metadata needed to present Monitor observations."""

    title: LocalizedText
    description: LocalizedText
    unit: CustomUnit
    aggregation: str
    capability: V2MonitorCapability

@dataclass(frozen=True, slots=True)
class CustomMonitorHeadingMetadata:
    metric: str
    dimension: str | None
    window_seconds: int
    status: str | None = None

@dataclass(frozen=True, slots=True)
class CustomMonitorSeries:
    key: str
    label: LocalizedText | None
    values: tuple[Decimal | None, ...]

@dataclass(frozen=True, slots=True)
class CustomMonitorPoint:
    """One plotted source-window endpoint; ``None`` preserves an actual gap."""

    ended_at: datetime
    observation: V2MonitorObservation | None

@dataclass(frozen=True, slots=True)
class CustomMonitorTimeline:
    points: tuple[CustomMonitorPoint, ...]
    series: tuple[CustomMonitorSeries, ...]

@dataclass(frozen=True, slots=True)
class CustomMonitorRankingEntry:
    key: str
    label: LocalizedText | None
    value: Decimal
    description: LocalizedText | None = None
    display: LocalizedText | None = None

@dataclass(frozen=True, slots=True)
class CustomMonitorRanking:
    entries: tuple[CustomMonitorRankingEntry, ...]
