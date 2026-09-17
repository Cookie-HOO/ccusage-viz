from datetime import date

import pytest

from ccusage_viz.coverage import DateCoverage, DateInterval


def test_interval_rejects_reversed_bounds() -> None:
    with pytest.raises(ValueError, match="coverage start"):
        DateInterval(date(2026, 1, 2), date(2026, 1, 1))


def test_coverage_coalesces_overlapping_and_adjacent_intervals() -> None:
    coverage = DateCoverage(
        (
            DateInterval(date(2026, 1, 5), date(2026, 1, 7)),
            DateInterval(date(2026, 1, 1), date(2026, 1, 3)),
            DateInterval(date(2026, 1, 3), date(2026, 1, 4)),
        )
    )

    assert coverage.intervals == (DateInterval(date(2026, 1, 1), date(2026, 1, 7)),)


def test_coverage_preserves_holes_and_requires_one_complete_interval() -> None:
    coverage = DateCoverage(
        (
            DateInterval(date(2026, 1, 1), date(2026, 1, 2)),
            DateInterval(date(2026, 1, 4), date(2026, 1, 5)),
        )
    )

    assert coverage.covers(DateInterval(date(2026, 1, 1), date(2026, 1, 2)))
    assert not coverage.covers(DateInterval(date(2026, 1, 2), date(2026, 1, 4)))


def test_coverage_reports_only_missing_subintervals() -> None:
    coverage = DateCoverage(
        (
            DateInterval(date(2026, 1, 2), date(2026, 1, 3)),
            DateInterval(date(2026, 1, 5), date(2026, 1, 6)),
        )
    )

    assert coverage.missing(DateInterval(date(2026, 1, 1), date(2026, 1, 7))) == (
        DateInterval(date(2026, 1, 1), date(2026, 1, 1)),
        DateInterval(date(2026, 1, 4), date(2026, 1, 4)),
        DateInterval(date(2026, 1, 7), date(2026, 1, 7)),
    )
    assert coverage.missing(DateInterval(date(2026, 1, 2), date(2026, 1, 3))) == ()


def test_coverage_merge_preserves_and_coalesces_both_sides() -> None:
    first = DateCoverage.from_interval(date(2026, 1, 1), date(2026, 1, 2))
    second = DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 4))

    assert first.merge(second) == DateCoverage.from_interval(date(2026, 1, 1), date(2026, 1, 4))
