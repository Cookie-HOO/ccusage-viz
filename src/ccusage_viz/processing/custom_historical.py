"""Decimal-native local projection for command-backed historical charts.

This module deliberately does not adapt custom data into ``TokenUsage``.  The
custom protocol describes arbitrary additive measurements, so its values stay
``Decimal`` through ordering, Top/Other folding, and presentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomPresentationDescriptor,
    CustomRankingGroup,
    CustomSeries,
    CustomUnit,
    LocalizedText,
)
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
    description: LocalizedText | None = None
    display: LocalizedText | None = None
    comparison_display: LocalizedText | None = None
    link: str | None = None
    rank: int | None = None
    total_value: Decimal = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_value", sum(self.values, start=Decimal()))

    @property
    def total(self) -> Decimal:
        return self.total_value


@dataclass(frozen=True, slots=True)
class CustomProjectedRankingGroup:
    id: str
    label: LocalizedText
    series: tuple[CustomProjectedSeries, ...]
    total: Decimal
    previous_total: Decimal | None
    comparison_ready: bool
    maximum: Decimal
    description: LocalizedText | None = None
    display: LocalizedText | None = None
    comparison_display: LocalizedText | None = None
    link: str | None = None


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
    comparison_available: bool = False
    show_percentage: bool = True
    groups: tuple[CustomProjectedRankingGroup, ...] | None = None

    @property
    def total(self) -> Decimal:
        if self.groups is not None:
            return sum((group.total for group in self.groups), start=Decimal())
        return sum((series.total for series in self.series), start=Decimal())


def process_custom_historical(
    response: CustomChartResponse,
    config: CustomChartConfig,
    *,
    comparison_response: CustomChartResponse | None = None,
    comparison_config: CustomChartConfig | None = None,
) -> CustomChartProjection:
    """Apply local Decimal projection and optional raw ranking comparison facts."""
    if config.kind == "monitor":
        raise CustomProjectionError("custom historical projection does not support monitor")
    if response.data.groups is not None and config.kind != "ranking":
        raise CustomProjectionError("custom grouped data is supported only by ranking")
    _validate_capability(response, config)
    if config.kind != "ranking" and any(
        source.description is not None or source.display is not None or source.link is not None
        for source in response.data.series
    ):
        raise CustomProjectionError(
            "custom series presentation fields are supported only by ranking"
        )
    if config.kind == "calendar":
        _validate_calendar(response, config)
    if comparison_response is not None:
        if comparison_config is None:
            raise ValueError("comparison response requires its query configuration")
        _validate_capability(comparison_response, comparison_config)
        _validate_dates(comparison_response, comparison_config)

    days = _period_axis(config.date_range.since, config.date_range.until, config.granularity)
    if response.data.groups is not None:
        return _process_grouped_ranking(
            response,
            config,
            days,
            comparison_response=(
                None if config.date_range.period == "all" else comparison_response
            ),
        )

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
        candidates.append(
            CustomProjectedSeries(
                source.id,
                source.label,
                tuple(values),
                description=source.description,
                display=source.display,
                comparison_display=source.comparison_display,
                link=source.link,
            )
        )

    sort_direction = response.capabilities.charts[config.kind].sort_direction
    ranking_key = (
        (lambda item: (item.total, item.id))
        if sort_direction == "ascending"
        else (lambda item: (-item.total, item.id))
    )
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
                sorted(
                    previous_totals.items(),
                    key=(
                        (lambda item: (item[1], item[0]))
                        if sort_direction == "ascending"
                        else (lambda item: (-item[1], item[0]))
                    ),
                ),
                start=1,
            )
        }
        candidates = [
            CustomProjectedSeries(
                series.id,
                series.label,
                series.values,
                previous_total=previous_totals.get(series.id),
                comparison_ready=series.id in previous_totals,
                previous_rank=previous_ranks.get(series.id),
                description=series.description,
                display=series.display,
                comparison_display=series.comparison_display,
                link=series.link,
            )
            for series in candidates
        ]

    # Stable deterministic ranking by requested-range sum, with ID as tiebreaker.
    candidates.sort(key=ranking_key)
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
            {filter.id: filter.label for filter in response.capabilities.filters},
            {
                (filter.id, option.id): option.label
                for filter in response.capabilities.filters
                for option in filter.options
            },
        ),
        comparison_response is not None,
        response.capabilities.charts[config.kind].show_percentage
        if config.kind == "ranking"
        else True,
    )


def _process_grouped_ranking(
    response: CustomChartResponse,
    config: CustomChartConfig,
    days: tuple[date, ...],
    *,
    comparison_response: CustomChartResponse | None,
) -> CustomChartProjection:
    current = response.data.groups
    assert current is not None
    previous = comparison_response.data.groups if comparison_response is not None else None
    sort_direction = response.capabilities.charts["ranking"].sort_direction
    groups = _project_groups(current, previous, config, sort_direction=sort_direction)
    return CustomChartProjection(
        "ranking",
        days,
        (),
        response.dataset.unit,
        config.date_range,
        config.granularity,
        config,
        CustomPresentationDescriptor(
            response.dataset,
            {dimension.id: dimension.label for dimension in response.capabilities.group_by},
            {filter.id: filter.label for filter in response.capabilities.filters},
            {
                (filter.id, option.id): option.label
                for filter in response.capabilities.filters
                for option in filter.options
            },
        ),
        comparison_response is not None,
        response.capabilities.charts["ranking"].show_percentage,
        groups,
    )


def _project_source_series(
    sources: tuple[CustomSeries, ...],
    config: CustomChartConfig,
    *,
    sort_direction: str,
    previous: dict[str, CustomSeries] | None,
) -> tuple[tuple[CustomProjectedSeries, ...], Decimal, Decimal]:
    """Return visible Top/Other entries, full returned total, and full returned maximum."""
    days = _period_axis(config.date_range.since, config.date_range.until, config.granularity)
    indexes = {day: index for index, day in enumerate(days)}

    def values_for(source: CustomSeries) -> tuple[Decimal, ...]:
        values = [Decimal()] * len(days)
        for point in source.points:
            bucket = _bucket_start(point.date, config.granularity)
            if not _bucket_overlaps(bucket, config):
                raise CustomProjectionError(
                    "custom response contains a point outside the requested range"
                )
            values[indexes[bucket]] += point.value
        return tuple(values)

    previous_totals = (
        {
            source.id: sum((point.value for point in source.points), start=Decimal())
            for source in previous.values()
        }
        if previous is not None
        else {}
    )
    previous_ranks = {
        series_id: rank
        for rank, (series_id, _) in enumerate(
            sorted(
                previous_totals.items(),
                key=(
                    (lambda item: (item[1], item[0]))
                    if sort_direction == "ascending"
                    else (lambda item: (-item[1], item[0]))
                ),
            ),
            start=1,
        )
    }
    candidates = [
        CustomProjectedSeries(
            source.id,
            source.label,
            values_for(source),
            previous_total=previous_totals.get(source.id),
            comparison_ready=previous is not None and source.id in previous,
            previous_rank=previous_ranks.get(source.id),
            description=source.description,
            display=source.display,
            comparison_display=source.comparison_display,
            link=source.link,
        )
        for source in sources
    ]
    ranking_key = (
        (lambda item: (item.total, item.id))
        if sort_direction == "ascending"
        else (lambda item: (-item.total, item.id))
    )
    candidates.sort(key=ranking_key)
    ranked = [
        CustomProjectedSeries(
            item.id,
            item.label,
            item.values,
            previous_total=item.previous_total,
            comparison_ready=item.comparison_ready,
            previous_rank=item.previous_rank,
            description=item.description,
            display=item.display,
            comparison_display=item.comparison_display,
            link=item.link,
            rank=rank,
        )
        for rank, item in enumerate(candidates, start=1)
    ]
    total = sum((item.total for item in ranked), start=Decimal())
    maximum = max((item.total for item in ranked), default=Decimal())
    selected, discarded = _select_top(ranked, config.top)
    if discarded and config.other == "show":
        selected.append(_other(discarded, len(days)))
    return tuple(selected), total, maximum


def _project_groups(
    current: tuple[CustomRankingGroup, ...],
    previous: tuple[CustomRankingGroup, ...] | None,
    config: CustomChartConfig,
    *,
    sort_direction: str,
) -> tuple[CustomProjectedRankingGroup, ...]:
    """Preserve current group order and independently project every group."""
    previous_by_id = {group.id: group for group in previous or ()}
    projected: list[CustomProjectedRankingGroup] = []
    for group in current:
        previous_group = previous_by_id.get(group.id)
        previous_series = (
            {series.id: series for series in previous_group.series}
            if previous_group is not None
            else None
        )
        series, total, maximum = _project_source_series(
            group.series,
            config,
            sort_direction=sort_direction,
            previous=previous_series,
        )
        projected.append(
            CustomProjectedRankingGroup(
                group.id,
                group.label,
                series,
                total,
                (
                    sum(
                        (
                            point.value
                            for source in previous_group.series
                            for point in source.points
                        ),
                        start=Decimal(),
                    )
                    if previous_group is not None
                    else None
                ),
                previous_group is not None,
                maximum,
                group.description,
                group.display,
                group.comparison_display,
                group.link,
            )
        )
    return tuple(projected)


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
    series_sources = response.data.series
    if response.data.groups is not None:
        series_sources = tuple(series for group in response.data.groups for series in group.series)
    for series in series_sources:
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
