from dataclasses import replace
from datetime import date
from decimal import Decimal

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomComparison,
    CustomData,
    CustomDataset,
    CustomFilter,
    CustomFilterOption,
    CustomMetric,
    CustomPaneSummary,
    CustomPoint,
    CustomRankingGroup,
    CustomSeries,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_protocol.responses import (
    CustomPaneResponse,
    V2ChartResponse,
)
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource

SOURCE = CustomCommandSource("reading", ("reader", "ccuv"))

RANGE = DateRange(date(2026, 9, 1), date(2026, 9, 2))

UNIT = CustomUnit("page", LocalizedText("pages", "页"), "suffix", 2)

def config(**changes: object) -> CustomChartConfig:
    values: dict[str, object] = {
        "kind": "timeline",
        "source": SOURCE,
        "date_range": RANGE,
        "presentation": ChartPresentation(theme="no-color"),
        "group_by": "book",
        "top": 2,
    }
    values.update(changes)
    return CustomChartConfig(**values)  # type: ignore[arg-type]

def response(
    values: tuple[tuple[str, str], ...] = (("a", "10"), ("b", "5"), ("c", "2")),
    *,
    point_date: date = date(2026, 9, 1),
) -> CustomPaneResponse:
    capability = CustomChartCapability(("day",), ("book",), ("genre",))
    capabilities = CustomCapabilities(
        (),
        (
            CustomFilter(
                "genre",
                LocalizedText("Genre", "类型"),
                (CustomFilterOption("fiction", LocalizedText("Fiction", "小说")),),
            ),
        ),
        {kind: capability for kind in ("timeline", "calendar", "stack", "ranking")},
    )
    data = CustomData(
        tuple(
            CustomSeries(
                series_id,
                LocalizedText(series_id, series_id),
                (CustomPoint(point_date, Decimal(value)),),
            )
            for series_id, value in values
        )
    )
    metric = CustomMetric(
        "read",
        LocalizedText("Read", "阅读"),
        UNIT,
        Decimal("3.5"),
        CustomComparison("ready", Decimal("2")),
        CustomComparison("unavailable"),
    )
    return CustomPaneResponse(
        CustomDataset(LocalizedText("Reading", "阅读"), LocalizedText("Daily", "每日"), UNIT),
        capabilities,
        data,
        CustomPaneSummary(metric),
    )

def _grouped_response(
    groups: tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
    *,
    point_date: date = date(2026, 9, 1),
    ascending: bool = False,
) -> CustomPaneResponse:
    source = response(())
    capability = replace(
        source.capabilities.charts["ranking"],
        group_by=("real_model",),
        partition_by=("logical_model",),
        sort_direction="ascending" if ascending else "descending",
    )
    return replace(
        source,
        capabilities=replace(source.capabilities, charts={"ranking": capability}),
        data=CustomData(
            groups=tuple(
                CustomRankingGroup(
                    group_id,
                    LocalizedText(group_id, group_id),
                    tuple(
                        CustomSeries(
                            series_id,
                            LocalizedText(series_id, series_id),
                            (CustomPoint(point_date, Decimal(value)),),
                        )
                        for series_id, value in values
                    ),
                    description=LocalizedText(f"About {group_id}", f"关于 {group_id}"),
                    display=LocalizedText(f"Total {group_id}", f"总计 {group_id}"),
                    comparison_display=LocalizedText(f"Delta {group_id}", f"变化 {group_id}"),
                    link=f"https://example.com/{group_id}",
                )
                for group_id, values in groups
            )
        ),
    )

def v2_chart_response(metric_id: str, *, periods: tuple[str, ...] = ()) -> V2ChartResponse:
    text = LocalizedText("Reading", "阅读")
    capability = V2HistoricalChartCapability(("day",), ("book",), (), periods)

    def metric(identifier: str) -> V2MetricDescriptor:
        return V2MetricDescriptor(
            identifier,
            LocalizedText(identifier, identifier),
            text,
            UNIT,
            "sum",
            V2MetricCapabilities(
                (),
                (),
                {kind: capability for kind in ("timeline", "ranking")},
            ),
            {},
        )

    return V2ChartResponse(
        metric_id,
        response().data,
        V2ProbeDescriptor(
            "reading-1",
            "0.1.0",
            V2Dataset(text, text),
            (metric("stars"), metric("updated_days")),
            (),
        ),
        V2Runtime(()),
    )
