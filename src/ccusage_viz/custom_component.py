"""Accepted/candidate lifecycle for command-backed custom historical charts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomDataset,
    CustomPresentationDescriptor,
    CustomProtocolFailure,
    V2HistoricalChartCapability,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_protocol import CustomChartResponse, V2ChartResponse
from ccusage_viz.errors import QueryError
from ccusage_viz.options import CustomChartConfig, has_complete_content
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
    process_custom_historical,
)
from ccusage_viz.processing.summaries import ranking_comparison_interval


def custom_replacement_required(current: CustomChartConfig, updated: CustomChartConfig) -> bool:
    """Return whether an adjustment requires the command to produce new data."""

    return (
        current.source != updated.source
        or current.kind != updated.kind
        or current.date_range != updated.date_range
        or current.filters != updated.filters
        or current.group_by != updated.group_by
        or current.granularity != updated.granularity
    )


def custom_summary_replacement_required(
    current: CustomChartConfig, updated: CustomChartConfig
) -> bool:
    """Return whether a Pane-owned summary needs fresh source facts."""

    return (
        current.source != updated.source
        or current.filters != updated.filters
        or current.granularity != updated.granularity
        or current.date_range.fixed_bounds != updated.date_range.fixed_bounds
        or (current.date_range.fixed_bounds and current.date_range != updated.date_range)
    )


CustomPurpose = Literal["primary", "comparison"]


def _invalidates_accepted_chart(error: BaseException) -> bool:
    """Whether a Dataset rejected the selected rolling-period semantic."""

    if not isinstance(error, QueryError):
        return False
    failure = error.values.get("custom_failure")
    return (
        isinstance(failure, CustomProtocolFailure)
        and failure.code == "unsupported_query"
        and failure.unsupported is not None
        and failure.unsupported.get("field") == "range.period"
    )


def _query_identity(config: CustomChartConfig) -> tuple[object, ...]:
    """Return the data-affecting portion of a custom query configuration."""

    return (
        config.source,
        config.kind,
        config.date_range,
        config.filters,
        config.group_by,
        config.granularity,
    )


@dataclass(frozen=True, slots=True)
class CustomCompletion:
    generation: int
    config: CustomChartConfig
    response: CustomChartResponse
    purpose: CustomPurpose = "primary"


class CustomHistoricalComponent:
    """Keep accepted custom facts visible until a newer source query succeeds.

    Query execution belongs to the custom provider.  This component deliberately
    accepts its typed protocol payload directly instead of passing it through
    token ``UsageRecord`` models.
    """

    __slots__ = (
        "candidate",
        "capability",
        "accepted_config",
        "accepted_response",
        "accepted_at",
        "comparison_config",
        "comparison_error",
        "comparison_response",
        "comparison_pending_generation",
        "error",
        "generation",
        "model",
        "pending_generation",
        "presentation",
        "render_revision",
        "retrieval_top",
        "runtime",
        "v2_descriptor",
    )

    def __init__(self, config: CustomChartConfig) -> None:
        self.candidate = config
        self.capability: CustomChartCapability | None = None
        self.accepted_config: CustomChartConfig | None = None
        self.accepted_response: CustomChartResponse | None = None
        self.accepted_at: datetime | None = None
        self.comparison_config: CustomChartConfig | None = None
        self.comparison_error: BaseException | None = None
        self.comparison_response: CustomChartResponse | None = None
        self.comparison_pending_generation: int | None = None
        self.error: BaseException | None = None
        self.generation = 0
        self.model: CustomChartProjection | None = None
        self.pending_generation: int | None = None
        self.presentation: CustomPresentationDescriptor | None = None
        self.render_revision = 0
        self.retrieval_top: int | None = None
        self.runtime: V2Runtime | None = None
        self.v2_descriptor: V2ProbeDescriptor | None = None

    @property
    def is_pending(self) -> bool:
        return self.pending_generation == self.generation

    @property
    def comparison_is_pending(self) -> bool:
        return self.comparison_pending_generation == self.generation

    def comparison_request_config(self) -> CustomChartConfig | None:
        """Return the ordinary prior-range request required by complete-content Ranking."""
        if (
            self.candidate.kind != "ranking"
            or not has_complete_content(self.candidate.presentation.density)
            or self.candidate.date_range.fixed_bounds
            or self.candidate.date_range.period == "all"
            or self.candidate.ranking_comparison == "none"
        ):
            return None
        interval = ranking_comparison_interval(self.candidate.date_range)
        return replace(
            self.candidate,
            date_range=DateRange(interval.since, interval.until, fixed_bounds=True),
        )

    def _reproject(self) -> None:
        if self.accepted_config is None or self.accepted_response is None:
            return
        comparison = (
            self.comparison_response
            if self.comparison_config == self.comparison_request_config()
            else None
        )
        self.model = process_custom_historical(
            self.accepted_response,
            self.accepted_config,
            comparison_response=comparison,
            comparison_config=self.comparison_config if comparison is not None else None,
        )

    def configure(self, config: CustomChartConfig, *, data_affecting: bool) -> None:
        if config == self.candidate:
            return
        self.candidate = config
        if data_affecting:
            if self.accepted_config is not None and self.accepted_config.source != config.source:
                self.capability = None
            self.generation += 1
            self.pending_generation = self.generation if self.model is not None else None
            self.comparison_config = None
            self.comparison_error = None
            self.comparison_response = None
            self.comparison_pending_generation = None
            return
        self.render_revision += 1
        if (
            self.accepted_response is not None
            and self.accepted_config is not None
            and not self.is_pending
            and not custom_replacement_required(self.accepted_config, config)
        ):
            self.accepted_config = config
            self._reproject()

    def set_capability(self, capability: CustomChartCapability) -> None:
        """Keep Probe-declared controls available across rejected chart queries."""

        if capability == self.capability:
            return
        self.capability = capability
        if self.candidate.kind == "ranking":
            self.candidate = replace(self.candidate, ranking_comparison=capability.comparison)
        self.render_revision += 1

    def adjust(self, config: CustomChartConfig, *, data_affecting: bool) -> None:
        """Scheduler-facing alias matching the custom pane adjustment path."""
        self.configure(config, data_affecting=data_affecting)

    def apply_result(
        self, completion: CustomCompletion, *, accepted_at: datetime | None = None
    ) -> bool:
        if completion.generation != self.generation:
            return False
        if completion.purpose == "comparison":
            if completion.config != self.comparison_request_config():
                return False
            self.comparison_config = completion.config
            self.comparison_response = completion.response
            self.comparison_pending_generation = None
            self.comparison_error = None
            self._reproject()
            self.render_revision += 1
            return True
        if completion.config != self.candidate:
            return False
        if self.capability is not None:
            self.candidate = replace(self.candidate, ranking_comparison=self.capability.comparison)
        self.accepted_config = self.candidate
        self.accepted_response = completion.response
        self.retrieval_top = completion.config.top
        self.presentation = CustomPresentationDescriptor(
            completion.response.dataset,
            {
                dimension.id: dimension.label
                for dimension in completion.response.capabilities.group_by
            },
            {filter.id: filter.label for filter in completion.response.capabilities.filters},
            {
                (filter.id, option.id): option.label
                for filter in completion.response.capabilities.filters
                for option in filter.options
            },
        )
        self.capability = completion.response.capabilities.charts.get(self.candidate.kind)
        self.comparison_config = None
        self.comparison_response = None
        self.comparison_error = None
        self._reproject()
        self.accepted_at = accepted_at or datetime.now().astimezone()
        self.pending_generation = None
        self.error = None
        self.render_revision += 1
        return True

    def accept_response(
        self,
        response: CustomChartResponse,
        *,
        purpose: CustomPurpose = "primary",
        accepted_at: datetime | None = None,
    ) -> bool:
        config = self.candidate if purpose == "primary" else self.comparison_request_config()
        if config is None:
            return False
        return self.apply_result(
            CustomCompletion(self.generation, config, response, purpose), accepted_at=accepted_at
        )

    def start_comparison(self) -> CustomChartConfig | None:
        """Mark and return the prior range after the current response is accepted."""
        config = self.comparison_request_config()
        if self.accepted_response is None or config is None:
            return None
        self.comparison_pending_generation = self.generation
        self.comparison_error = None
        return config

    def apply_provider_result(
        self,
        result: Any,
        *,
        purpose: CustomPurpose = "primary",
        accepted_at: datetime | None = None,
    ) -> bool:
        """Apply the provider's typed optional custom payload when available."""
        payload = getattr(result, "custom_response", None)
        descriptor: V2ProbeDescriptor | None = None
        runtime: V2Runtime | None = None
        if isinstance(payload, V2ChartResponse):
            metric = next(
                item for item in payload.descriptor.metrics if item.id == payload.metric_id
            )
            capability = metric.capabilities.charts.get(self.candidate.kind)
            if not isinstance(capability, V2HistoricalChartCapability):
                raise TypeError("v2 chart response does not describe the selected historical chart")
            descriptor = payload.descriptor
            runtime = payload.runtime
            self.candidate = replace(self.candidate, ranking_comparison=capability.comparison)
            payload = CustomChartResponse(
                CustomDataset(metric.title, metric.description, metric.unit),
                CustomCapabilities(
                    metric.capabilities.group_by,
                    payload.runtime.filters,
                    {
                        self.candidate.kind: CustomChartCapability(
                            capability.granularities,
                            capability.group_by,
                            tuple(item.id for item in payload.runtime.filters),
                            capability.max_items,
                            capability.descriptions_default,
                            comparison=capability.comparison,
                            show_percentage=capability.show_percentage,
                            refresh_interval_seconds=capability.refresh_interval_seconds,
                        )
                    },
                ),
                payload.data,
                warnings=payload.warnings,
            )
        if not isinstance(payload, CustomChartResponse):
            raise TypeError("custom provider result does not contain a chart response")
        accepted = self.accept_response(payload, purpose=purpose, accepted_at=accepted_at)
        if accepted and purpose == "primary" and descriptor is not None and runtime is not None:
            self.v2_descriptor = descriptor
            self.runtime = runtime
        return accepted

    def fail(
        self, error: BaseException, *, generation: int, purpose: CustomPurpose = "primary"
    ) -> bool:
        if generation != self.generation:
            return False
        if purpose == "comparison":
            self.comparison_pending_generation = None
            self.comparison_error = error
            return True
        self.pending_generation = None
        replacement_failed = self.accepted_config is not None and _query_identity(
            self.accepted_config
        ) != _query_identity(self.candidate)
        if _invalidates_accepted_chart(error) or replacement_failed:
            self.model = None
            self.accepted_config = None
            self.accepted_response = None
            self.accepted_at = None
            self.comparison_config = None
            self.comparison_error = None
            self.comparison_response = None
            self.comparison_pending_generation = None
        self.error = error
        return True
