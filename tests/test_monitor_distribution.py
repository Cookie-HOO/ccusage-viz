from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ccusage_viz.chart_models import DistributionCoverage
from ccusage_viz.domain import TokenUsage
from ccusage_viz.processing.monitor import CounterSnapshot, ObservedTPM
from ccusage_viz.project_identity import ExactProjectDisplayKey


def usage(total: int) -> TokenUsage:
    return TokenUsage.from_parts(total=total, input=total, output=0, cache_read=0, cache_creation=0)


def snapshot(total: int, **models: int) -> CounterSnapshot:
    return CounterSnapshot(usage(total), {name: usage(value) for name, value in models.items()})


def test_distribution_splits_intervals_at_half_hour_boundaries() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    wall = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    observer.add(snapshot(0), 0.0, wall)
    observer.add(snapshot(120), 120 * 60.0, wall + timedelta(hours=2))

    model = observer.time_of_day_distribution(120 * 60.0, wall=wall + timedelta(hours=2))

    values = [
        bucket.values["Total"]
        for bucket in model.buckets
        if bucket.coverage is not DistributionCoverage.UNOBSERVED
    ]
    assert values == [45.0, 60.0, 15.0]


def test_distribution_preserves_unobserved_partial_and_observed_zero() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    wall = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    observer.add(snapshot(0), 0.0, wall)
    observer.add(snapshot(0), 45 * 60.0, wall + timedelta(minutes=45))

    model = observer.time_of_day_distribution(45 * 60.0, wall=wall + timedelta(minutes=45))

    assert model.buckets[8].coverage is DistributionCoverage.UNOBSERVED
    assert model.buckets[9].coverage is DistributionCoverage.PARTIAL
    assert model.buckets[9].values["Total"] == 0.0


def test_distribution_groups_top_names_over_full_day() -> None:
    observer = ObservedTPM(window_seconds=3600, by="model", top=1)
    wall = datetime(2026, 1, 1, tzinfo=UTC)
    observer.add(snapshot(0, alpha=0, beta=0), 0.0, wall)
    observer.add(snapshot(100, alpha=60, beta=40), 3600.0, wall + timedelta(hours=1))

    model = observer.time_of_day_distribution(3600.0, wall=wall + timedelta(hours=1))

    assert tuple(series.key for series in model.series) == ("alpha", "Other")
    assert model.buckets[0].values == {"alpha": 60.0, "Other": 40.0}


def test_distribution_uses_safe_project_display_labels() -> None:
    observer = ObservedTPM(window_seconds=3600, by="project", top=None)
    project = ExactProjectDisplayKey("claude", "/safe/private/path", "app")
    wall = datetime(2026, 1, 1, tzinfo=UTC)
    observer.add(CounterSnapshot(usage(0), projects={project: usage(0)}), 0.0, wall)
    observer.add(
        CounterSnapshot(usage(10), projects={project: usage(10)}), 60.0, wall + timedelta(minutes=1)
    )

    model = observer.time_of_day_distribution(60.0, wall=wall + timedelta(minutes=1))

    assert model.series[0].label == "app"
    assert "/safe" not in model.series[0].label


def test_distribution_spring_forward_day_has_aware_monotonic_twenty_three_hour_buckets() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    zone = ZoneInfo("America/New_York")
    wall = datetime(2026, 3, 9, 0, 30, tzinfo=zone)

    model = observer.time_of_day_distribution(0.0, wall=wall, day_window="yesterday")

    assert len(model.buckets) == 23
    assert all(bucket.started_at.tzinfo is not None for bucket in model.buckets)
    assert all(
        earlier.ended_at.timestamp() == later.started_at.timestamp()
        for earlier, later in zip(model.buckets, model.buckets[1:], strict=False)
    )
    assert [bucket.started_at.timestamp() for bucket in model.buckets] == sorted(
        bucket.started_at.timestamp() for bucket in model.buckets
    )
    assert (
        model.buckets[-1].ended_at.timestamp() - model.buckets[0].started_at.timestamp()
        == 23 * 3600
    )


def test_distribution_fall_back_day_has_monotonic_twenty_five_hour_buckets() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    zone = ZoneInfo("America/New_York")
    wall = datetime(2026, 11, 2, 0, 30, tzinfo=zone)

    model = observer.time_of_day_distribution(0.0, wall=wall, day_window="yesterday")

    assert len(model.buckets) == 25
    assert all(bucket.started_at.tzinfo is not None for bucket in model.buckets)
    assert all(
        earlier.ended_at.timestamp() == later.started_at.timestamp()
        for earlier, later in zip(model.buckets, model.buckets[1:], strict=False)
    )
    assert (
        model.buckets[-1].ended_at.timestamp() - model.buckets[0].started_at.timestamp()
        == 25 * 3600
    )


def test_distribution_allocates_increments_across_fall_back_repeated_hour() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    zone = ZoneInfo("America/New_York")
    started_wall = datetime(2026, 11, 1, tzinfo=zone)
    ended_wall = datetime.fromtimestamp(started_wall.timestamp() + 25 * 3600, zone)
    observer.add(snapshot(0), 0.0, started_wall)
    observer.add(snapshot(250), 25 * 3600.0, ended_wall)

    model = observer.time_of_day_distribution(25 * 3600.0, wall=ended_wall, day_window="yesterday")

    assert [bucket.values["Total"] for bucket in model.buckets] == pytest.approx([10.0] * 25)
    assert all(bucket.coverage is DistributionCoverage.FULL for bucket in model.buckets)


def test_rollup_coverage_spans_preserve_gap_and_retention_is_fifty_hours() -> None:
    observer = ObservedTPM(window_seconds=3600, by=None, top=None)
    observer.add(snapshot(0), 0.0)
    observer.add(snapshot(10), 10.0)
    observer.add(snapshot(0), 30.0)  # rejected reset leaves an unobserved gap
    observer.add(snapshot(10), 40.0)

    observer.rates(3661.0)

    assert observer.rollups[0].coverage_spans[0].started_at == 0.0
    assert observer.rollups[0].coverage_spans[-1].ended_at == 40.0
    observer.rates(50 * 3600 + 41.0)
    assert not observer.rollups
