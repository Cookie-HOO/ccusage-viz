"""Decimal-native local projection for command-backed historical charts.

This module deliberately does not adapt custom data into ``TokenUsage``.  The
custom protocol describes arbitrary additive measurements, so its values stay
``Decimal`` through ordering, Top/Other folding, and presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomPresentationDescriptor, CustomUnit, LocalizedText
from ccusage_viz.custom_protocol import CustomChartResponse
from ccusage_viz.options import CustomChartConfig
from ccusage_viz.processing.summaries import period_end, period_start


class CustomProjectionError(ValueError):
    """The command response cannot be represented by the selected chart."""


@dataclass(frozen=True, slots=True)
class CustomProjectedSeries:
    id: str
    label: LocalizedText
    values: tuple[Decimal, ...]
    is_other: bool = False
    previous_total: Decimal | None = None
    comparison_ready: bool = False
    previous_rank: int | None = None

    @property
    def total(self) -> Decimal:
        return sum(self.values, start=Decimal())


@dataclass(frozen=True, slots=True)
class CustomChartProjection:
    kind: Literal["timeline", "calendar", "stack", "ranking"]
    days: tuple[date, ...]
    series: tuple[CustomProjectedSeries, ...]
    unit: CustomUnit
    date_range: DateRange
    granularity: str
    config: CustomChartConfig | None = None
    presentation: CustomPresentationDescriptor | None = None

    @property
    def total(self) -> Decimal:
        return sum((series.total for series in self.series), start=Decimal())


def process_custom_historical(
    response: CustomChartResponse,
    config: CustomChartConfig,
    *,
    comparison_response: CustomChartResponse | None = None,
    comparison_config: CustomChartConfig | None = None,
) -> CustomChartProjection:
    """Apply local Decimal projection and optional raw ranking comparison facts."""
    _validate_capability(response, config)
    if config.kind == "calendar":
        _validate_calendar(response, config)
    if comparison_response is not None:
        if comparison_config is None:
            raise ValueError("comparison response requires its query configuration")
        _validate_capability(comparison_response, comparison_config)
        _validate_dates(comparison_response, comparison_config)

    days = _period_axis(config.date_range.since, config.date_range.until, config.granularity)
    indexes = {day: index for index, day in enumerate(days)}
    candidates: list[CustomProjectedSeries] = []
    for source in response.data.series:
        values = [Decimal()] * len(days)
        for point in source.points:
            bucket = _bucket_start(point.date, config.granularity)
            if not _bucket_overlaps(bucket, config):
                raise CustomProjectionError(
                    "custom response contains a point outside the requested range"
                )
            values[indexes[bucket]] += point.value
        candidates.append(CustomProjectedSeries(source.id, source.label, tuple(values)))

    previous_totals: dict[str, Decimal] = {}
    previous_ranks: dict[str, int] = {}
    if comparison_response is not None:
        previous_totals = {
            source.id: sum((point.value for point in source.points), start=Decimal())
            for source in comparison_response.data.series
        }
        previous_ranks = {
            series_id: rank
            for rank, (series_id, _) in enumerate(
                sorted(previous_totals.items(), key=lambda item: (-item[1], item[0])), start=1
            )
        }
        candidates = [
            CustomProjectedSeries(
                series.id,
                series.label,
                series.values,
                previous_total=previous_totals.get(series.id, Decimal()),
                comparison_ready=True,
                previous_rank=previous_ranks.get(series.id),
            )
            for series in candidates
        ]

    # Stable deterministic ranking by requested-range sum, with ID as tiebreaker.
    candidates.sort(key=lambda item: (-item.total, item.id))
    selected, discarded = _select_top(candidates, config.top)
    if discarded and config.other == "show":
        selected.append(_other(discarded, len(days)))
    return CustomChartProjection(
        config.kind,
        days,
        tuple(selected),
        response.dataset.unit,
        config.date_range,
        config.granularity,
        config,
        CustomPresentationDescriptor(
            response.dataset,
            {dimension.id: dimension.label for dimension in response.capabilities.group_by},
        ),
    )


def _validate_capability(response: CustomChartResponse, config: CustomChartConfig) -> None:
    capability = response.capabilities.charts.get(config.kind)
    if capability is None:
        raise CustomProjectionError(f"custom response does not support {config.kind}")
    if config.granularity not in capability.granularities:
        raise CustomProjectionError(
            f"custom response does not support {config.granularity} {config.kind}"
        )
    if config.group_by is not None and config.group_by not in capability.group_by:
        raise CustomProjectionError(
            f"custom response does not support grouping by {config.group_by}"
        )
    supported_filters = {
        item.id: {option.id for option in item.options}
        for item in response.capabilities.filters
        if item.id in capability.filters
    }
    for filter_id, option_ids in config.filters:
        if filter_id not in supported_filters:
            raise CustomProjectionError("custom response does not support selected filters")
        if any(option_id not in supported_filters[filter_id] for option_id in option_ids):
            raise CustomProjectionError("custom response does not support selected filter options")


def _validate_dates(response: CustomChartResponse, config: CustomChartConfig) -> None:
    for series in response.data.series:
        for point in series.points:
            if not _bucket_overlaps(_bucket_start(point.date, config.granularity), config):
                raise CustomProjectionError(
                    "custom response contains a point outside the requested range"
                )


def _bucket_start(day: date, granularity: str) -> date:
    return period_start(day, granularity)


def _bucket_overlaps(bucket: date, config: CustomChartConfig) -> bool:
    return (
        bucket <= config.date_range.until
        and period_end(bucket, config.granularity) >= config.date_range.since
    )


def _period_axis(start: date, end: date, granularity: str) -> tuple[date, ...]:
    return tuple(dict.fromkeys(_bucket_start(day, granularity) for day in _days(start, end)))


def _validate_calendar(response: CustomChartResponse, config: CustomChartConfig) -> None:
    if config.group_by is not None or config.granularity != "day":
        raise CustomProjectionError("calendar requires a single total series with daily buckets")
    series = response.data.series
    if len(series) != 1 or series[0].id != "total":
        raise CustomProjectionError("calendar requires a single total series with daily buckets")


def _days(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))


def _select_top(
    candidates: list[CustomProjectedSeries], top: int | None
) -> tuple[list[CustomProjectedSeries], list[CustomProjectedSeries]]:
    if top is None:
        return list(candidates), []
    return list(candidates[:top]), list(candidates[top:])


def _other(series: list[CustomProjectedSeries], count: int) -> CustomProjectedSeries:
    values = tuple(
        sum((item.values[index] for item in series), start=Decimal()) for index in range(count)
    )
    return CustomProjectedSeries("other", LocalizedText("Other", "其他"), values, is_other=True)
