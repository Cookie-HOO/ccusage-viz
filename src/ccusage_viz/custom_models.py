from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_labels", MappingProxyType(dict(self.group_labels)))


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
    group_by: tuple[str, ...]
    filters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CustomChartDefaults:
    period: str | None
    group_by: str | None
    top: int | None


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
    capabilities: "CustomCapabilities"
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


@dataclass(frozen=True, slots=True)
class CustomPoint:
    date: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class CustomSeries:
    id: str
    label: LocalizedText
    points: tuple[CustomPoint, ...]


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
