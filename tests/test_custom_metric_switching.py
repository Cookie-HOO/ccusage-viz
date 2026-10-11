from datetime import date

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_metric_switching import (
    MetricSwitchRejection,
    cycle_switch_metric,
    switch_candidates,
    validate_metric_switch,
)
from ccusage_viz.custom_models import (
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2ProbeDescriptor,
)
from ccusage_viz.options import CustomChartConfig, CustomCommandSource

TEXT = LocalizedText("Text", "文本")
UNIT = CustomUnit("count", TEXT, "suffix", 0)
SOURCE = CustomCommandSource("example", ("example",))


def date_range(period: str) -> DateRange:
    return DateRange(date(2026, 9, 17), date(2026, 9, 30), period=period)


def metric(
    identifier: str,
    *,
    group_id: str | None,
    charts: dict[str, V2HistoricalChartCapability],
) -> V2MetricDescriptor:
    return V2MetricDescriptor(
        identifier,
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities((), (), charts),
        {},
        group_id=group_id,
    )


def descriptor(*metrics: V2MetricDescriptor) -> V2ProbeDescriptor:
    return V2ProbeDescriptor(
        "revision",
        "1",
        V2Dataset(TEXT, TEXT),
        metrics,
        (),
        metric_groups=(V2MetricGroup("github", TEXT), V2MetricGroup("ci", TEXT)),
    )


def capability(
    *,
    periods: tuple[str, ...] = (),
    group_by: tuple[str | None, ...] = (None,),
    granularities: tuple[str, ...] = ("day",),
) -> V2HistoricalChartCapability:
    return V2HistoricalChartCapability(granularities, group_by, (), periods)


def config(**changes: object) -> CustomChartConfig:
    values: dict[str, object] = {
        "kind": "ranking",
        "source": SOURCE,
        "date_range": date_range("14d"),
        "group_by": None,
        "granularity": "day",
        "metric_id": "stars",
    }
    values.update(changes)
    return CustomChartConfig(**values)  # type: ignore[arg-type]


def test_cycles_only_same_group_metrics_that_support_the_active_kind() -> None:
    source = descriptor(
        metric("stars", group_id="github", charts={"ranking": capability()}),
        metric("updated_days", group_id="github", charts={"ranking": capability()}),
        metric("issues", group_id="github", charts={"timeline": capability()}),
        metric("builds", group_id="ci", charts={"ranking": capability()}),
        metric("forks", group_id=None, charts={"ranking": capability()}),
    )

    assert [item.id for item in switch_candidates(source, current_metric_id="stars", kind="ranking")] == [
        "stars",
        "updated_days",
    ]
    assert cycle_switch_metric(source, current_metric_id="stars", kind="ranking", step=1).id == "updated_days"  # type: ignore[union-attr]
    assert cycle_switch_metric(source, current_metric_id="stars", kind="ranking", step=-1).id == "updated_days"  # type: ignore[union-attr]


def test_returns_none_when_group_has_no_alternate_metric() -> None:
    source = descriptor(metric("stars", group_id="github", charts={"ranking": capability()}))

    assert cycle_switch_metric(source, current_metric_id="stars", kind="ranking", step=1) is None


def test_rejects_only_declared_period_group_and_granularity_mismatches() -> None:
    target = metric(
        "updated_days",
        group_id="github",
        charts={"ranking": capability(periods=("30d",), group_by=("repo",), granularities=("week",))},
    )

    assert validate_metric_switch(config(), target) == MetricSwitchRejection("range.period", "14d")
    assert validate_metric_switch(config(date_range=date_range("30d")), target) == MetricSwitchRejection("query.group_by", None)
    assert validate_metric_switch(
        config(date_range=date_range("30d"), group_by="repo"), target
    ) == MetricSwitchRejection("query.granularity", "day")


def test_does_not_validate_runtime_filters_or_cross_field_rules() -> None:
    target = metric("updated_days", group_id="github", charts={"ranking": capability()})

    assert validate_metric_switch(config(filters=(("unknown", ("x",)),)), target) is None
