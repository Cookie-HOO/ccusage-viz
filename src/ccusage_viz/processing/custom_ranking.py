"""Scalar projection for V2 command-backed Rankings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ccusage_viz.custom_models import (
    CustomDataset,
    CustomPresentationDescriptor,
    CustomRankingEntry,
    CustomUnit,
    LocalizedText,
    V2RankingData,
    V2RankingGroup,
)
from ccusage_viz.custom_protocol.responses import V2ChartResponse
from ccusage_viz.options import CustomChartConfig
from ccusage_viz.processing.custom_historical import CustomProjectionError, SortDirection


@dataclass(frozen=True, slots=True)
class CustomProjectedRankingEntry:
    id: str
    label: LocalizedText
    value: Decimal
    is_other: bool = False
    previous_total: Decimal | None = None
    comparison_ready: bool = False
    previous_rank: int | None = None
    description: LocalizedText | None = None
    display: LocalizedText | None = None
    comparison_display: LocalizedText | None = None
    link: str | None = None
    rank: int | None = None

    @property
    def total(self) -> Decimal:
        """Compatibility alias for shared Ranking presentation code."""
        return self.value


@dataclass(frozen=True, slots=True)
class CustomProjectedScalarRankingGroup:
    id: str
    label: LocalizedText
    series: tuple[CustomProjectedRankingEntry, ...]
    total: Decimal
    previous_total: Decimal | None
    comparison_ready: bool
    maximum: Decimal
    description: LocalizedText | None = None
    display: LocalizedText | None = None
    comparison_display: LocalizedText | None = None
    link: str | None = None


@dataclass(frozen=True, slots=True)
class CustomRankingProjection:
    kind: str
    series: tuple[CustomProjectedRankingEntry, ...]
    unit: CustomUnit
    config: CustomChartConfig
    presentation: CustomPresentationDescriptor
    comparison_available: bool = False
    show_percentage: bool = True
    groups: tuple[CustomProjectedScalarRankingGroup, ...] | None = None

    @property
    def total(self) -> Decimal:
        if self.groups is not None:
            return sum((group.total for group in self.groups), start=Decimal())
        return sum((entry.value for entry in self.series), start=Decimal())


def process_custom_ranking(
    response: V2ChartResponse,
    config: CustomChartConfig,
    *,
    comparison_response: V2ChartResponse | None = None,
    comparison_config: CustomChartConfig | None = None,
) -> CustomRankingProjection:
    """Project authoritative scalar values without constructing a time axis."""
    if config.kind != "ranking" or not isinstance(response.data, V2RankingData):
        raise CustomProjectionError("scalar ranking projection requires v2 ranking data")
    if comparison_response is not None:
        if comparison_config is None or not isinstance(comparison_response.data, V2RankingData):
            raise CustomProjectionError("scalar ranking comparison requires v2 ranking data")
        if (response.data.groups is None) != (comparison_response.data.groups is None):
            raise CustomProjectionError(
                "custom current and comparison responses have incompatible comparison shapes"
            )
    metric = next(item for item in response.descriptor.metrics if item.id == response.metric_id)
    capability = metric.capabilities.charts.get("ranking")
    if capability is None:
        raise CustomProjectionError("custom response does not support ranking")
    presentation = CustomPresentationDescriptor(
        dataset=CustomDataset(metric.title, metric.description, metric.unit),
        group_labels={item.id: item.label for item in metric.capabilities.group_by},
        filter_labels={item.id: item.label for item in response.runtime.filters},
        filter_values={
            (item.id, option.id): option.label
            for item in response.runtime.filters
            for option in item.options
        },
        partition_labels={
            item.id: item.label
            for item in (metric.capabilities.partition_by or metric.capabilities.group_by)
        },
    )
    direction = capability.sort_direction  # ty: ignore[unresolved-attribute]
    previous_data = comparison_response.data if comparison_response is not None else None
    if response.data.groups is not None:
        groups = _project_groups(
            response.data.groups,
            previous_data.groups if previous_data is not None else None,  # ty: ignore[invalid-argument-type]
            config,
            direction,
        )
        return CustomRankingProjection(
            "ranking",
            (),
            metric.unit,
            config,
            presentation,
            comparison_response is not None,
            capability.show_percentage,  # ty: ignore[unresolved-attribute]
            groups,
        )
    series, _, _ = _project_entries(
        response.data.series,
        config,
        direction,
        {item.id: item for item in previous_data.series} if previous_data is not None else None,  # ty: ignore[invalid-argument-type]
        include_rank=False,
    )
    return CustomRankingProjection(
        "ranking",
        series,
        metric.unit,
        config,
        presentation,
        comparison_response is not None,
        capability.show_percentage,  # ty: ignore[unresolved-attribute]
    )


def _key(value: Decimal, identifier: str, direction: SortDirection) -> tuple[Decimal, str]:
    return (value, identifier) if direction == "ascending" else (-value, identifier)


def _project_entries(
    entries: tuple[CustomRankingEntry, ...],
    config: CustomChartConfig,
    direction: SortDirection,
    previous: dict[str, CustomRankingEntry] | None,
    *,
    include_rank: bool,
) -> tuple[tuple[CustomProjectedRankingEntry, ...], Decimal, Decimal]:
    previous_values = {key: item.value for key, item in (previous or {}).items()}
    previous_ranks = {
        identifier: rank
        for rank, (identifier, value) in enumerate(
            sorted(previous_values.items(), key=lambda item: _key(item[1], item[0], direction)), 1
        )
    }
    ordered = sorted(entries, key=lambda item: _key(item.value, item.id, direction))
    projected = [
        CustomProjectedRankingEntry(
            item.id,
            item.label,
            item.value,
            previous_total=previous_values.get(item.id),
            comparison_ready=previous is not None and item.id in previous,
            previous_rank=previous_ranks.get(item.id),
            description=item.description,
            display=item.display,
            comparison_display=item.comparison_display,
            link=item.link,
            rank=rank if include_rank else None,
        )
        for rank, item in enumerate(ordered, 1)
    ]
    total = sum((item.value for item in projected), start=Decimal())
    maximum = max((item.value for item in projected), default=Decimal())
    discarded = projected[config.top :] if config.top is not None else []
    selected = projected[: config.top] if config.top is not None else projected
    if discarded and config.other == "show":
        selected.append(
            CustomProjectedRankingEntry(
                "other",
                LocalizedText("Other", "其他"),
                sum((item.value for item in discarded), start=Decimal()),
                is_other=True,
            )
        )
    return tuple(selected), total, maximum


def _project_groups(
    groups: tuple[V2RankingGroup, ...],
    previous: tuple[V2RankingGroup, ...] | None,
    config: CustomChartConfig,
    direction: SortDirection,
) -> tuple[CustomProjectedScalarRankingGroup, ...]:
    previous_by_id = {group.id: group for group in previous or ()}
    projected: list[CustomProjectedScalarRankingGroup] = []
    for group in groups:
        old = previous_by_id.get(group.id)
        series, total, maximum = _project_entries(
            group.series,
            config,
            direction,
            {item.id: item for item in old.series} if old is not None else None,
            include_rank=True,
        )
        projected.append(
            CustomProjectedScalarRankingGroup(
                group.id,
                group.label,
                series,
                total,
                sum((item.value for item in old.series), start=Decimal())
                if old is not None
                else None,
                old is not None,
                maximum,
                group.description,
                group.display,
                group.comparison_display,
                group.link,
            )
        )
    return tuple(projected)
