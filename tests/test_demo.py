from datetime import date

from ccusage_viz.core.time import DateRange
from ccusage_viz.demo import generate_demo
from ccusage_viz.domain import UsageRecord


def record_identity(record: UsageRecord) -> tuple[date, str, tuple[str, str], str]:
    assert record.day is not None
    assert record.project is not None
    return record.day, record.agent, record.project.key, record.models[0].model


def test_demo_sizes_only_change_magnitude() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 8), None)
    small = generate_demo("small", period)
    medium = generate_demo("medium", period)
    large = generate_demo("large", period)
    assert [record_identity(record) for record in small] == [
        record_identity(record) for record in medium
    ]
    assert [r.usage.total * 1_000 for r in small] == [r.usage.total for r in medium]
    assert [r.usage.total * 1_000_000 for r in small] == [r.usage.total for r in large]
    assert max(r.usage.total for r in small) >= 1_000
    assert max(r.usage.total for r in medium) >= 1_000_000
    assert max(r.usage.total for r in large) >= 1_000_000_000
    since = period.since
    until = period.until
    assert since is not None
    assert until is not None
    assert all(since <= record_identity(record)[0] <= until for record in small)
    assert all(record.usage.other == 0 for record in (*small, *medium, *large))
