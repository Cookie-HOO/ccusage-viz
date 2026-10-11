from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True, slots=True)
class LocalizedText:
    en: str
    zh_cn: str


@dataclass(frozen=True, slots=True)
class CustomUnit:
    id: str
    label: LocalizedText
    placement: Literal["prefix", "suffix"]
    decimal_places: int


@dataclass(frozen=True, slots=True)
class CustomDataset:
    title: LocalizedText
    description: LocalizedText
    unit: CustomUnit


@dataclass(frozen=True, slots=True)
class CustomPresentationDescriptor:
    """Validated metadata that may outlive a chart response's numeric facts."""

    dataset: CustomDataset
    group_labels: Mapping[str, LocalizedText]
    filter_labels: Mapping[str, LocalizedText] = field(default_factory=dict)
    filter_values: Mapping[tuple[str, str], LocalizedText] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_labels", MappingProxyType(dict(self.group_labels)))
        object.__setattr__(self, "filter_labels", MappingProxyType(dict(self.filter_labels)))
        object.__setattr__(self, "filter_values", MappingProxyType(dict(self.filter_values)))


@dataclass(frozen=True, slots=True)
class CustomDimension:
    id: str
    label: LocalizedText


@dataclass(frozen=True, slots=True)
class CustomFilterOption:
    id: str
    label: LocalizedText


@dataclass(frozen=True, slots=True)
class CustomFilter:
    id: str
    label: LocalizedText
    options: tuple[CustomFilterOption, ...]
    mode: Literal["multi_select"] = "multi_select"


@dataclass(frozen=True, slots=True)
class CustomChartCapability:
    granularities: tuple[str, ...]
    group_by: tuple[str | None, ...]
    filters: tuple[str, ...]
    max_items: int | None = None
    descriptions_default: Literal["expanded", "collapsed"] = "collapsed"
    periods: tuple[str, ...] = ()
    comparison: Literal["full", "rank", "none"] = "full"
    show_percentage: bool = True
    refresh_interval_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class CustomChartDefaults:
    period: str | None
    group_by: str | None
    top: int | None
    granularity: str | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    other: str | None = None
    style: str | None = None
    theme: str | None = None
    window_seconds: int | None = None
    declared: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CustomEnvironmentDeclaration:
    name: str
    required: bool
    sensitive: bool
    label: LocalizedText
    how_to_get: LocalizedText
    help_url: str | None = None


@dataclass(frozen=True, slots=True)
class CustomProbeDescriptor:
    revision: str
    version: str
    dataset: CustomDataset
    capabilities: CustomCapabilities
    defaults: Mapping[str, CustomChartDefaults]
    environment: tuple[CustomEnvironmentDeclaration, ...]
    source_timezone: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "defaults", MappingProxyType(dict(self.defaults)))


@dataclass(frozen=True, slots=True)
class CustomCapabilities:
    group_by: tuple[CustomDimension, ...]
    filters: tuple[CustomFilter, ...]
    charts: Mapping[str, CustomChartCapability]

    def __post_init__(self) -> None:
        object.__setattr__(self, "charts", MappingProxyType(dict(self.charts)))


Aggregation = Literal["sum", "value"]


@dataclass(frozen=True, slots=True)
class V2Dataset:
    title: LocalizedText
    description: LocalizedText


@dataclass(frozen=True, slots=True)
class V2HistoricalChartCapability:
    granularities: tuple[str, ...]
    group_by: tuple[str | None, ...]
    filters: tuple[str, ...]
    periods: tuple[str, ...] = ()
    max_items: int | None = None
    descriptions_default: Literal["expanded", "collapsed"] = "collapsed"
    comparison: Literal["full", "rank", "none"] = "full"
    show_percentage: bool = True
    refresh_interval_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class V2MonitorCapability:
    window_seconds: int
    refresh_interval_seconds: int | None
    group_by: tuple[str, ...]
    filters: tuple[str, ...]
    rate_label: LocalizedText | None = None


V2ChartCapability = V2HistoricalChartCapability | V2MonitorCapability


@dataclass(frozen=True, slots=True)
class V2MetricCapabilities:
    group_by: tuple[CustomDimension, ...]
    filters: tuple[CustomFilter, ...]
    charts: Mapping[str, V2ChartCapability]

    def __post_init__(self) -> None:
        object.__setattr__(self, "charts", MappingProxyType(dict(self.charts)))


@dataclass(frozen=True, slots=True)
class V2MetricGroup:
    id: str
    title: LocalizedText


@dataclass(frozen=True, slots=True)
class V2MetricDescriptor:
    id: str
    title: LocalizedText
    description: LocalizedText
    unit: CustomUnit
    aggregation: Aggregation
    capabilities: V2MetricCapabilities
    defaults: Mapping[str, CustomChartDefaults]
    summary: Literal["comparisons", "total", "none"] = "comparisons"
    group_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "defaults", MappingProxyType(dict(self.defaults)))


@dataclass(frozen=True, slots=True)
class V2ProbeDescriptor:
    revision: str
    version: str
    dataset: V2Dataset
    metrics: tuple[V2MetricDescriptor, ...]
    environment: tuple[CustomEnvironmentDeclaration, ...]
    source_timezone: str | None = None
    default_metric_id: str | None = None
    metric_groups: tuple[V2MetricGroup, ...] = ()


@dataclass(frozen=True, slots=True)
class V2MetricValue:
    id: str
    label: LocalizedText
    value: Decimal


@dataclass(frozen=True, slots=True)
class V2MonitorObservation:
    end_at: datetime
    total: Decimal
    groups: tuple[V2MetricValue, ...]


@dataclass(frozen=True, slots=True)
class V2Runtime:
    """Query-context controls accepted together with one V2 response."""

    filters: tuple[CustomFilter, ...]


@dataclass(frozen=True, slots=True)
class CustomPoint:
    date: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class CustomSeries:
    id: str
    label: LocalizedText
    points: tuple[CustomPoint, ...]
    description: LocalizedText | None = None
    display: LocalizedText | None = None
    comparison_display: LocalizedText | None = None
    link: str | None = None


@dataclass(frozen=True, slots=True)
class CustomData:
    series: tuple[CustomSeries, ...]


@dataclass(frozen=True, slots=True)
class CustomComparison:
    status: Literal["ready", "pending", "unavailable"]
    base_value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CustomSummaryCurrent:
    """A source-owned visible metric value plus its comparison-safe Decimal fact."""

    value: Decimal
    display: LocalizedText


@dataclass(frozen=True, slots=True)
class CustomSummaryMetric:
    id: str
    label: LocalizedText
    current: CustomSummaryCurrent
    sequential: CustomComparison
    year_over_year: CustomComparison


@dataclass(frozen=True, slots=True)
class CustomSummary:
    metric: CustomSummaryMetric


# Compatibility models remain for existing internal construction paths while
# chart responses migrate away from source-provided summaries.
@dataclass(frozen=True, slots=True)
class CustomMetric:
    id: str
    label: LocalizedText
    unit: CustomUnit
    value: Decimal
    sequential: CustomComparison
    year_over_year: CustomComparison


@dataclass(frozen=True, slots=True)
class CustomPaneSummary:
    metric: CustomMetric


@dataclass(frozen=True, slots=True)
class CustomProtocolWarning:
    code: str
    message: LocalizedText


@dataclass(frozen=True, slots=True)
class CustomProtocolFailure:
    code: str
    message: LocalizedText
    unsupported: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.unsupported is not None:
            object.__setattr__(self, "unsupported", MappingProxyType(dict(self.unsupported)))
