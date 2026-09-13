from datetime import date

import pytest

from ccusage_viz.options import refresh_date_range, resolve_date_range


@pytest.mark.parametrize("days", [None, 7])
def test_watch_refresh_advances_unanchored_ranges(days: int | None) -> None:
    original = resolve_date_range(
        "timeline",
        days=days,
        since=None,
        until=None,
        timezone=None,
        today=date(2026, 9, 12),
    )

    refreshed = refresh_date_range(original, today=date(2026, 9, 13))

    assert refreshed.until == date(2026, 9, 13)
    assert refreshed.days == (14 if days is None else days)
    assert refreshed.since == original.since.replace(day=original.since.day + 1)


@pytest.mark.parametrize(
    ("days", "since", "until"),
    [
        (None, "2026-09-01", None),
        (7, None, "2026-09-10"),
        (None, "2026-09-01", "2026-09-10"),
    ],
)
def test_watch_refresh_preserves_explicit_ranges(
    days: int | None, since: str | None, until: str | None
) -> None:
    original = resolve_date_range(
        "timeline",
        days=days,
        since=since,
        until=until,
        timezone=None,
        today=date(2026, 9, 12),
    )

    assert refresh_date_range(original, today=date(2026, 9, 13)) is original
