from datetime import UTC, date, datetime, timedelta

from ccusage_viz.acquisition import custom_historical_query_intent
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_metric_switching import (
    cycle_switch_metric,
    normalization_category,
    normalize_switch_config,
    switch_candidates,
)
from ccusage_viz.custom_models import (
    CustomChartDefaults,
    CustomUnit,
    LocalizedText,
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_protocol import V2ChartRequest
from ccusage_viz.i18n import load_translator
from ccusage_viz.lifecycle import QueryTrigger
from ccusage_viz.options import CustomChartConfig, CustomCommandSource
from ccusage_viz.render.base import RenderContext, date_range_heading

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
    partition_by: tuple[str | None, ...] | None = None,
) -> V2HistoricalChartCapability:
    return V2HistoricalChartCapability(
        granularities, group_by, (), periods, partition_by=partition_by
    )


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

    assert [
        item.id for item in switch_candidates(source, current_metric_id="stars", kind="ranking")
    ] == [
        "stars",
        "updated_days",
    ]
    assert (
        cycle_switch_metric(source, current_metric_id="stars", kind="ranking", step=1).id
        == "updated_days"
    )  # type: ignore[union-attr]
    assert (
        cycle_switch_metric(source, current_metric_id="stars", kind="ranking", step=-1).id
        == "updated_days"
    )  # type: ignore[union-attr]


def test_returns_none_when_group_has_no_alternate_metric() -> None:
    source = descriptor(metric("stars", group_id="github", charts={"ranking": capability()}))

    assert cycle_switch_metric(source, current_metric_id="stars", kind="ranking", step=1) is None


def test_normalizes_target_period_and_filter_fields_from_metric_defaults() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities((), (), {"ranking": capability()}),
        {"ranking": CustomChartDefaults("all", None, None, filters=(("kind", ("tool",)),))},
        group_id="github",
    )
    current = config(filters=(("language", ("python",)),))

    assert normalization_category("range.period") == "period"
    assert normalize_switch_config(current, target, "period").date_range.period == "all"  # type: ignore[union-attr]
    assert normalization_category("query.filters.language") == "filters"
    assert normalize_switch_config(current, target, "filters").filters == (("kind", ("tool",)),)  # type: ignore[union-attr]


def test_metric_switch_subday_period_uses_shared_anchor_and_active_timezone() -> None:
    target = V2MetricDescriptor(
        "recent",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities((), (), {"ranking": capability(periods=("10m",))}),
        {"ranking": CustomChartDefaults("10m", None, None)},
        group_id="github",
    )
    anchor = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)

    normalized = normalize_switch_config(
        config(),
        target,
        "period",
        now=anchor,
        timezone="America/New_York",
    )

    assert normalized is not None
    assert isinstance(normalized.date_range, TimestampRange)
    assert normalized.date_range.end_at == anchor.astimezone(normalized.date_range.end_at.tzinfo)
    assert normalized.date_range.end_at.fold == 1
    assert normalized.date_range.end_at.astimezone(UTC) - normalized.date_range.start_at.astimezone(
        UTC
    ) == timedelta(minutes=10)


def test_metric_switch_all_period_remains_relative_and_hides_anchor_in_heading() -> None:
    all_metric = metric(
        "all_time", group_id="github", charts={"ranking": capability(periods=("all",))}
    )
    day_metric = metric("daily", group_id="github", charts={"ranking": capability(periods=("1d",))})
    initial = config(
        date_range=DateRange(
            date(1971, 1, 1),
            date(2026, 9, 30),
            relative_until=True,
            period="all",
        )
    )

    one_day = normalize_switch_config(initial, day_metric, "period")
    assert one_day is not None
    assert one_day.date_range.period == "1d"
    assert one_day.date_range.relative_until

    all_time = normalize_switch_config(one_day, all_metric, "period")
    assert all_time is not None
    assert all_time.date_range.since == date(1971, 1, 1)
    assert all_time.date_range.period == "all"
    assert all_time.date_range.relative_until
    heading = date_range_heading(
        "Ranking",
        all_time.date_range.since,
        all_time.date_range.until,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            period=all_time.date_range.period if all_time.date_range.relative_until else None,
        ),
    )
    assert heading == "Ranking · all"
    assert "1971-01-01" not in heading


def test_uses_the_only_declared_period_when_target_has_no_default() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities((), (), {"ranking": capability(periods=("all",))}),
        {},
        group_id="github",
    )

    assert normalize_switch_config(config(), target, "period").date_range.period == "all"  # type: ignore[union-attr]


def test_normalizes_partition_and_group_atomically_without_collisions() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {
                "ranking": capability(
                    group_by=("logical", "real", "provider"),
                    partition_by=(None, "logical"),
                )
            },
        ),
        {"ranking": CustomChartDefaults("14d", "real", None, partition_by="logical")},
        group_id="github",
    )
    current = config(group_by="logical", partition_by=None)

    assert normalization_category("query.partition_by") == "partition_by"
    partitioned = normalize_switch_config(current, target, "partition_by")
    assert partitioned is not None
    assert (partitioned.partition_by, partitioned.group_by) == ("logical", "real")


def test_switch_to_optional_partition_without_default_clears_active_partition_on_wire() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {
                "ranking": capability(
                    group_by=("logical", "real"),
                    partition_by=(None, "logical"),
                )
            },
        ),
        {},
        group_id="github",
    )
    current = config(metric_id="updated_days", partition_by="logical", group_by="real")

    normalized = normalize_switch_config(current, target, "partition_by")

    assert normalized is not None
    assert normalized.partition_by is None
    intent = custom_historical_query_intent(
        normalized,
        timezone="UTC",
        owner_id="pane",
        generation=1,
        trigger=QueryTrigger.REFRESH,
        partition_declared=True,
    )
    assert isinstance(intent.payload, V2ChartRequest)
    assert intent.payload.to_wire()["query"]["partition_by"] is None


def test_group_normalization_ignores_absent_null_default_and_preserves_legal_group() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {"ranking": capability(group_by=(None, "real_model"), partition_by=None)},
        ),
        {},
        group_id="github",
    )

    assert normalize_switch_config(config(group_by="real_model"), target, "group_by") is None


def test_declared_non_null_group_default_precedes_current_legal_group() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {"ranking": capability(group_by=(None, "real_model", "provider"))},
        ),
        {
            "ranking": CustomChartDefaults(
                None,
                "provider",
                None,
                declared=frozenset({"group_by"}),
            )
        },
        group_id="github",
    )

    normalized = normalize_switch_config(config(group_by="real_model"), target, "group_by")

    assert normalized is not None
    assert normalized.group_by == "provider"


def test_required_partition_without_defaults_chooses_first_legal_pair() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities(
            (),
            (),
            {
                "ranking": capability(
                    group_by=("logical", "real"),
                    partition_by=("logical",),
                )
            },
        ),
        {},
        group_id="github",
    )

    normalized = normalize_switch_config(config(), target, "partition_by")

    assert normalized is not None
    assert (normalized.partition_by, normalized.group_by) == ("logical", "real")


def test_v2_ranking_ignores_unsupported_granularity_during_metric_switch() -> None:
    current = config(granularity="legacy")
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities((), (), {"ranking": capability()}),
        {"ranking": CustomChartDefaults(None, None, None, granularity="month")},
        group_id="github",
    )

    assert normalization_category("query.granularity", config=current) is None
    assert normalize_switch_config(current, target, "granularity") is None


def test_unknown_or_unchanged_default_does_not_normalize() -> None:
    target = V2MetricDescriptor(
        "updated_days",
        TEXT,
        TEXT,
        UNIT,
        "sum",
        V2MetricCapabilities((), (), {"ranking": capability()}),
        {"ranking": CustomChartDefaults("14d", None, None)},
        group_id="github",
    )

    assert normalization_category("query.combination") is None
    assert normalize_switch_config(config(), target, "period") is None
