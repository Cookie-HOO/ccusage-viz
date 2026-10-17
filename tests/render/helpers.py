




from datetime import date, datetime
from decimal import Decimal

from ccusage_viz.chart_models import (
    DistributionCoverage,
    TimeOfDayBucket,
    TimeOfDayDistributionModel,
    TimeOfDaySeries,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomDataset,
    CustomPresentationDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.domain import TokenUsage
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomChartConfig, CustomCommandSource
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
    CustomProjectedRankingGroup,
    CustomProjectedSeries,
)
from ccusage_viz.render.base import RenderContext


def _grouped_ranking_projection(
    *,
    groups: tuple[CustomProjectedRankingGroup, ...] | None = None,
    period: str = "14d",
    show_percentage: bool = True,
    comparison_available: bool = True,
) -> CustomChartProjection:
    unit = CustomUnit("request", LocalizedText("requests", "次请求"), "suffix", 0)
    dataset = CustomDataset(LocalizedText("Router", "路由"), LocalizedText("", ""), unit)
    source = CustomCommandSource("router", ("router-dataset",))
    date_range = DateRange(date(2026, 10, 1), date(2026, 10, 14), period=period)
    config = CustomChartConfig(
        "ranking",
        source,
        date_range,
        group_by="real_model",
        partition_by="logical_model",
    )
    presentation = CustomPresentationDescriptor(
        dataset,
        {"real_model": LocalizedText("Real Model", "真实模型")},
        partition_labels={"logical_model": LocalizedText("Logical Model", "逻辑模型")},
    )
    if groups is None:
        groups = (
            CustomProjectedRankingGroup(
                "coding",
                LocalizedText("Coding Model", "代码模型"),
                (
                    CustomProjectedSeries(
                        "coding-a",
                        LocalizedText("coding-a", "编码-a"),
                        (Decimal("8"),),
                        rank=1,
                        description=LocalizedText(
                            "Read [safe docs](https://example.com/coding)",
                            "阅读文档",
                        ),
                    ),
                    CustomProjectedSeries(
                        "coding-b", LocalizedText("coding-b", "编码-b"), (Decimal("-2"),), rank=2
                    ),
                ),
                Decimal("6"),
                Decimal("4"),
                True,
                Decimal("8"),
                description=LocalizedText("Routes coding workloads", "路由编码工作负载"),
                display=LocalizedText("source-owned total", "来源总计"),
                comparison_display=LocalizedText("+2 requests", "+2 次请求"),
                link="https://example.com/groups/coding",
            ),
            CustomProjectedRankingGroup(
                "general",
                LocalizedText("General Model", "通用模型"),
                (
                    CustomProjectedSeries(
                        "general-a", LocalizedText("general-a", "通用-a"), (Decimal("800"),), rank=1
                    ),
                ),
                Decimal("800"),
                None,
                False,
                Decimal("800"),
            ),
        )
    return CustomChartProjection(
        "ranking",
        (date(2026, 10, 1),),
        (),
        unit,
        date_range,
        "day",
        config,
        presentation,
        comparison_available,
        show_percentage,
        groups,
    )

def usage(total: int) -> TokenUsage:
    return TokenUsage(total, total, 0, 0, 0)

def context(ascii: bool = False) -> RenderContext:
    return RenderContext(80, 24, load_translator("en"), color=False, ascii=ascii)

def period() -> DateRange:
    return DateRange(date(2026, 1, 1), date(2026, 1, 14))

def _distribution_model() -> TimeOfDayDistributionModel:
    started = datetime(2026, 9, 22, 9, 0).astimezone()
    first_end = datetime(2026, 9, 22, 10, 0).astimezone()
    second_end = datetime(2026, 9, 22, 11, 0).astimezone()
    third_end = datetime(2026, 9, 22, 12, 0).astimezone()
    return TimeOfDayDistributionModel(
        (
            TimeOfDayBucket(started, first_end, DistributionCoverage.UNOBSERVED),
            TimeOfDayBucket(
                first_end,
                second_end,
                DistributionCoverage.PARTIAL,
                {"alpha": 60.0, "beta": 40.0},
            ),
            TimeOfDayBucket(
                second_end,
                third_end,
                DistributionCoverage.FULL,
                {"alpha": 0.0, "beta": 0.0},
            ),
        ),
        (TimeOfDaySeries("alpha", "Alpha"), TimeOfDaySeries("beta", "Beta")),
        datetime(2026, 9, 22, 9, 18).astimezone(),
        "today",
        "hour",
    )
