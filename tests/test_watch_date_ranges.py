from datetime import date

import pytest

from ccusage_viz.core.time import refresh_date_range
from ccusage_viz.options import resolve_date_range


@pytest.mark.parametrize("period", [None, "7d"])
def test_watch_refresh_advances_rolling_periods(period: str | None) -> None:
    original = resolve_date_range(
        "timeline",
        period=period,
        since=None,
        until=None,
        today=date(2026, 9, 12),
    )

    refreshed = refresh_date_range(original, today=date(2026, 9, 13))

    assert refreshed.until == date(2026, 9, 13)
    assert refreshed.days == (14 if period is None else 7)
    assert refreshed.since == original.since.replace(day=original.since.day + 1)


@pytest.mark.parametrize("until", [None, "2026-09-10"])
def test_watch_refresh_preserves_explicit_ranges(until: str | None) -> None:
    original = resolve_date_range(
        "timeline",
        period=None,
        since="2026-09-01",
        until=until,
        today=date(2026, 9, 12),
    )

    assert refresh_date_range(original, today=date(2026, 9, 13)) is original
