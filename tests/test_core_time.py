from datetime import date

import pytest

from ccusage_viz.core.time import (
    DateRange,
    natural_period_start,
    parse_period,
    refresh_date_range,
    today_for_timezone,
)


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("1d", (1, "d")),
        ("13mo", (13, "mo")),
        ("8q", (8, "q")),
        ("5y", (5, "y")),
    ],
)
def test_parse_period_accepts_supported_units(period: str, expected: tuple[int, str]) -> None:
    assert parse_period(period) == expected


@pytest.mark.parametrize("period", ["", "0d", "-1d", "1w", "1.5d", "d", " 1d"])
def test_parse_period_rejects_invalid_values(period: str) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        parse_period(period)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (7, "d", date(2026, 9, 7)),
        (3, "mo", date(2026, 7, 1)),
        (4, "q", date(2025, 10, 1)),
        (3, "y", date(2024, 1, 1)),
    ],
)
def test_natural_period_start_uses_calendar_boundaries(
    value: int, unit: str, expected: date
) -> None:
    assert natural_period_start(date(2026, 9, 13), value, unit) == expected


def test_natural_period_start_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="unsupported period unit"):
        natural_period_start(date(2026, 9, 13), 1, "w")


def test_today_override_does_not_resolve_timezone() -> None:
    expected = date(2026, 9, 13)

    assert today_for_timezone("Not/A-Timezone", expected) == expected


def test_refresh_date_range_advances_only_rolling_ranges() -> None:
    rolling = DateRange(
        date(2026, 9, 7),
        date(2026, 9, 13),
        None,
        relative_until=True,
        period="7d",
    )
    fixed = DateRange(
        date(2026, 9, 1),
        date(2026, 9, 7),
        None,
        fixed_bounds=True,
    )

    refreshed = refresh_date_range(rolling, today=date(2026, 9, 14))

    assert refreshed.since == date(2026, 9, 8)
    assert refreshed.until == date(2026, 9, 14)
    assert refresh_date_range(fixed, today=date(2026, 9, 14)) is fixed
