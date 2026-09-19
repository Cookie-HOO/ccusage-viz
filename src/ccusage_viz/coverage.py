from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, order=True, slots=True)
class DateInterval:
    since: date
    until: date

    def __post_init__(self) -> None:
        if self.since > self.until:
            raise ValueError("coverage start must not be after end")

    def covers(self, other: DateInterval) -> bool:
        return self.since <= other.since and self.until >= other.until


@dataclass(frozen=True, slots=True)
class DateCoverage:
    intervals: tuple[DateInterval, ...] = ()

    def __post_init__(self) -> None:
        merged: list[DateInterval] = []
        for interval in sorted(self.intervals):
            if not merged or interval.since > merged[-1].until + timedelta(days=1):
                merged.append(interval)
            else:
                merged[-1] = DateInterval(
                    merged[-1].since,
                    max(merged[-1].until, interval.until),
                )
        object.__setattr__(self, "intervals", tuple(merged))

    @classmethod
    def from_interval(cls, since: date, until: date) -> DateCoverage:
        return cls((DateInterval(since, until),))

    def covers(self, interval: DateInterval) -> bool:
        return any(item.covers(interval) for item in self.intervals)

    def merge(self, other: DateCoverage) -> DateCoverage:
        return DateCoverage((*self.intervals, *other.intervals))

    def missing_coverage(self, required: DateCoverage) -> DateCoverage:
        """Return the normalized portions of required coverage not yet covered."""
        return DateCoverage(
            tuple(missing for interval in required.intervals for missing in self.missing(interval))
        )

    def missing(self, interval: DateInterval) -> tuple[DateInterval, ...]:
        """Return uncovered portions of an inclusive interval."""
        missing: list[DateInterval] = []
        cursor = interval.since
        for covered in self.intervals:
            if covered.until < cursor:
                continue
            if covered.since > interval.until:
                break
            if covered.since > cursor:
                missing.append(
                    DateInterval(cursor, min(interval.until, covered.since - timedelta(days=1)))
                )
            cursor = max(cursor, covered.until + timedelta(days=1))
            if cursor > interval.until:
                break
        if cursor <= interval.until:
            missing.append(DateInterval(cursor, interval.until))
        return tuple(missing)
