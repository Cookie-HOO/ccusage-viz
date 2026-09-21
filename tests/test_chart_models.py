from datetime import date, datetime

import pytest

from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    MetricDescriptor,
    ObservedScope,
    RankingEntry,
    RankingModel,
    ScalarRankingEntry,
    ScalarSeries,
    Series,
    TimelineModel,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import TokenUsage


def usage(total: int) -> TokenUsage:
    return TokenUsage(total, total, 0, 0, 0)


def test_model_operations_sum_breakdowns_and_calendar_statistics() -> None:
    timeline = TimelineModel(
        (date(2026, 1, 1),), (Series("a", "a", (usage(4),)), Series("b", "b", (usage(6),)))
    )
    assert timeline.total.total == 10

    calendar = CalendarModel(
        tuple(
            CalendarDay(date(2026, 1, day), usage(total))
            for day, total in enumerate((1, 2, 0, 4), 1)
        )
    )
    assert calendar.total.total == 7
    assert calendar.active_days == 3
    assert calendar.longest_streak == 2
    assert calendar.current_streak == 1
    assert calendar.peak is not None
    assert calendar.peak.day == date(2026, 1, 4)


def test_observed_timeline_keeps_scalar_metrics_separate_from_token_breakdowns() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0)
    model = TimelineModel(
        (),
        (),
        observed_at=(timestamp,),
        observed_series=(ScalarSeries("Total", "Total", (1234.5,)),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "total"),
        y_axis_max=2000.0,
    )

    assert model.is_observed
    assert model.observed_series[0].values == (1234.5,)
    assert model.metric.unit == "tpm"
    assert model.total == TokenUsage.zero()


@pytest.mark.parametrize(
    ("top", "share", "denominator"),
    [
        (None, 0.5, 100),
        (1, -0.1, 100),
        (1, 1.1, 100),
        (1, 0.5, 0),
        (1, None, 100),
    ],
)
def test_ranking_hidden_coverage_requires_consistent_metadata(
    top: int | None,
    share: float | None,
    denominator: int,
) -> None:
    with pytest.raises(ValueError):
        RankingModel(
            (RankingEntry("a", "A", usage(50)),),
            DateRange(date(2026, 1, 1), date(2026, 1, 1), None),
            denominator=usage(denominator),
            top=top,
            top_share=share,
        )


def test_historical_timeline_rejects_monitor_start_boundary() -> None:
    with pytest.raises(ValueError, match="only observed axis"):
        TimelineModel(
            (date(2026, 1, 1),),
            (),
            monitor_started_at=datetime(2026, 1, 1, 12, 0),
        )


def test_observed_models_reject_historical_semantics() -> None:
    scope = ObservedScope(900, "model")
    with pytest.raises(ValueError, match="only observed axis"):
        TimelineModel(
            (date(2026, 1, 1),),
            (),
            observed_at=(datetime(2026, 1, 1, 12, 0),),
            observed_scope=scope,
        )

    with pytest.raises(ValueError, match="only observed entries"):
        RankingModel(
            (),
            DateRange(date(2026, 1, 1), date(2026, 1, 1), None),
            observed_entries=(ScalarRankingEntry("a", "A", 10.0),),
            observed_scope=scope,
        )
