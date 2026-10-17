from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ccusage_viz.core.custom_ranking_time import (
    TimestampRange,
    parse_subday_period,
    previous_custom_ranking_range,
    refresh_custom_ranking_range,
    resolve_custom_ranking_range,
)
from ccusage_viz.core.time import DateRange


@pytest.mark.parametrize(
    ("period", "seconds"),
    (("15s", 15), ("90s", 90), ("10m", 600), ("45m", 2700), ("1h", 3600), ("6h", 21600)),
)
def test_subday_period_duration(period: str, seconds: int) -> None:
    assert parse_subday_period(period) == timedelta(seconds=seconds)


@pytest.mark.parametrize("period", ("0s", "-1m", "1.5h", "1d", "all", " 1h"))
def test_subday_period_rejects_non_positive_or_non_subday_values(period: str) -> None:
    with pytest.raises(ValueError):
        parse_subday_period(period)


def test_hour_uses_elapsed_time_at_dst_transition() -> None:
    now = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1)

    interval = resolve_custom_ranking_range("1h", now=now, timezone="America/New_York")

    assert isinstance(interval, TimestampRange)
    assert interval.end_at.astimezone(UTC) - interval.start_at.astimezone(UTC) == timedelta(hours=1)
    assert interval.start_at.fold == 0
    assert interval.end_at.fold == 1


def test_subday_range_is_half_open_and_can_cross_midnight() -> None:
    interval = resolve_custom_ranking_range(
        "90m", now=datetime(2026, 10, 15, 0, 30, tzinfo=UTC), timezone="UTC"
    )

    assert isinstance(interval, TimestampRange)
    assert interval.start_at == datetime(2026, 10, 14, 23, 0, tzinfo=UTC)
    assert interval.end_at == datetime(2026, 10, 15, 0, 30, tzinfo=UTC)


def test_timestamp_range_rejects_naive_and_same_instant_bounds() -> None:
    with pytest.raises(ValueError, match="aware"):
        TimestampRange(datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="after"):
        TimestampRange(
            datetime(2026, 1, 1, 0, tzinfo=UTC),
            datetime(2025, 12, 31, 19, tzinfo=ZoneInfo("America/New_York")),
        )


def test_timestamp_range_rejects_fixed_relative_shape() -> None:
    with pytest.raises(ValueError, match="fixed timestamp range cannot be relative"):
        TimestampRange(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 1, tzinfo=UTC),
            relative_until=True,
            period="1h",
            fixed_bounds=True,
        )


def test_date_period_retains_natural_day_semantics() -> None:
    interval = resolve_custom_ranking_range(
        "1d", now=datetime(2026, 10, 15, 12, tzinfo=UTC), timezone="America/New_York"
    )

    assert isinstance(interval, DateRange)
    assert interval.since == interval.until


def test_previous_range_uses_accepted_interval_not_current_clock() -> None:
    accepted = TimestampRange(
        datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0),
        datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1),
        relative_until=True,
        period="1h",
    )

    previous = previous_custom_ranking_range(accepted)

    assert previous.end_at.astimezone(UTC) == accepted.start_at.astimezone(UTC)
    assert previous.end_at.astimezone(UTC) - previous.start_at.astimezone(UTC) == timedelta(hours=1)
    assert previous.fixed_bounds
    assert not previous.relative_until


def test_refresh_preserves_fixed_timestamp_bounds() -> None:
    fixed = TimestampRange(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 1, tzinfo=UTC),
        fixed_bounds=True,
    )

    assert (
        refresh_custom_ranking_range(fixed, now=datetime(2026, 2, 1, tzinfo=UTC), timezone="UTC")
        is fixed
    )
