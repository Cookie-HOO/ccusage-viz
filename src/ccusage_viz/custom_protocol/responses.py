from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomData,
    CustomDataset,
    CustomProbeDescriptor,
    CustomProtocolWarning,
    CustomSummary,
    V2MonitorObservation,
    V2ProbeDescriptor,
    V2RankingData,
    V2Runtime,
)


@dataclass(frozen=True, slots=True)
class CustomChartResponse:
    dataset: CustomDataset
    capabilities: CustomCapabilities
    data: CustomData
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

@dataclass(frozen=True, slots=True)
class CustomSummaryResponse:
    summary: CustomSummary
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

@dataclass(frozen=True, slots=True)
class CustomProbeResponse:
    dataset_id: str
    descriptor: CustomProbeDescriptor
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

@dataclass(frozen=True, slots=True)
class V2ProbeResponse:
    dataset_id: str
    descriptor: V2ProbeDescriptor
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

@dataclass(frozen=True, slots=True)
class V2ChartResponse:
    metric_id: str
    data: CustomData | V2RankingData
    descriptor: V2ProbeDescriptor
    runtime: V2Runtime
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

@dataclass(frozen=True, slots=True)
class V2MonitorResponse:
    metric_id: str
    observation: V2MonitorObservation
    descriptor: V2ProbeDescriptor | None = None
    runtime: V2Runtime = field(default_factory=lambda: V2Runtime(()))
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

@dataclass(frozen=True, slots=True)
class V2SummaryResponse:
    metric_id: str
    summary: CustomSummary
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)

CustomResponse: TypeAlias = (
    CustomChartResponse
    | CustomSummaryResponse
    | CustomProbeResponse
    | V2ChartResponse
    | V2MonitorResponse
    | V2SummaryResponse
    | V2ProbeResponse
)

@dataclass(frozen=True, slots=True)
class CustomPaneResponse(CustomChartResponse):
    """Legacy in-process chart fixture shape retained during the UI migration."""

    summary: object

CustomDashboardSummaryResponse = CustomSummaryResponse
