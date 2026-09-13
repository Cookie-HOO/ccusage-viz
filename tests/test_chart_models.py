from datetime import date

from ccusage_viz.chart_models import CalendarDay, CalendarModel, Series, TimelineModel
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
