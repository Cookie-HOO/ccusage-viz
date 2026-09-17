from datetime import date, timedelta

import pytest

from ccusage_viz.chart_models import ChangeDirection
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import ModelBreakdown, Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.options import DateRange
from ccusage_viz.project_identity import make_project_ref
from ccusage_viz.transform import (
    build_calendar,
    build_ranking,
    build_stack,
    build_timeline,
    filter_records,
)


def usage(total: int) -> TokenUsage:
    return TokenUsage.from_parts(
        total=total, input=total // 2, output=total // 4, cache_read=total // 4, cache_creation=0
    )


def record(day: int, agent: str, project: str, model: str, total: int) -> UsageRecord:
    value = usage(total)
    return UsageRecord(
        date(2026, 1, day),
        agent,
        value,
        SourceKind.UNIFIED_DAILY,
        make_project_ref(agent, project),
        (ModelBreakdown(model, value),),
    )


def test_filters_or_within_dimension_and_and_across_dimensions() -> None:
    records = (
        record(1, "claude", "/a/app", "sonnet", 10),
        record(1, "codex", "/b/app", "codex", 20),
        record(1, "claude", "/a/tool", "opus", 30),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2), None)
    filtered, _ = filter_records(
        records, period, agents=("claude", "codex"), projects=("app",), models=("son", "cod")
    )
    assert [item.usage.total for item in filtered] == [10, 20]


def test_model_candidates_respect_agent_and_project_filters() -> None:
    records = (
        record(1, "claude", "/a/app", "sonnet", 10),
        record(1, "codex", "/b/tool", "codex", 20),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2), None)

    filtered, _ = filter_records(records, period, agents=("claude",), models=("son",))
    assert [item.usage.total for item in filtered] == [10]

    filtered, _ = filter_records(records, period, projects=("app",), models=("son",))
    assert [item.usage.total for item in filtered] == [10]


def test_timeline_zero_fills_and_other_is_final() -> None:
    records = (
        record(1, "claude", "/a", "a", 30),
        record(1, "codex", "/b", "b", 20),
        record(1, "claude", "/c", "c", 10),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2), None)
    model = build_timeline(records, period, by="project", top=1, show_other=True)
    assert [series.label for series in model.series] == ["a", "Other"]
    assert [value.total for value in model.series[1].values] == [30, 0]


def test_summary_uses_the_single_rendered_series() -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, 15))
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    model = build_timeline(
        records, period, coverage=DateCoverage.from_interval(date(2025, 12, 25), period.until)
    )

    assert model.summary is not None
    assert model.summary.total == 140
    assert model.summary.day_over_day is not None
    assert model.summary.day_over_day.percent == pytest.approx(100 / 13)
    assert model.summary.week_over_week is not None
    assert model.summary.week_over_week.percent == 100.0


@pytest.mark.parametrize("days", [1, 13])
def test_relative_summary_zero_fills_comparisons_outside_the_range(days: int) -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, days + 1))
    period = DateRange(date(2026, 1, 1), date(2026, 1, days), None)

    coverage = DateCoverage.from_interval(period.until - timedelta(days=7), period.until)
    timeline = build_timeline(records, period, coverage=coverage).summary
    calendar = build_calendar(records, period, coverage=coverage).summary

    assert timeline is not None
    assert calendar is not None
    if days == 1:
        assert timeline.day_over_day is not None
        assert timeline.week_over_week is not None
        assert timeline.day_over_day.direction == ChangeDirection.FROM_ZERO
        assert timeline.week_over_week.direction == ChangeDirection.FROM_ZERO


def test_explicit_start_and_end_hide_summary() -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, 15))
    period = DateRange(
        date(2026, 1, 1),
        date(2026, 1, 14),
        None,
        fixed_bounds=True,
    )

    assert build_timeline(records, period).summary is None
    assert build_calendar(records, period).summary is None
    assert build_stack(records, period).summary is None


def test_summary_can_be_disabled_for_supported_charts() -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, 15))
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)

    assert build_timeline(records, period, include_summary=False).summary is None
    assert build_calendar(records, period, include_summary=False).summary is None
    assert build_stack(records, period, include_summary=False).summary is None


def test_summary_aggregates_visible_timeline_series() -> None:
    records = tuple(
        record(day, agent, f"/{agent}", agent, day * 10)
        for day in range(1, 15)
        for agent in ("claude", "codex")
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)

    grouped = build_timeline(
        records,
        period,
        by="agent",
        coverage=DateCoverage.from_interval(date(2025, 12, 25), period.until),
    )
    assert grouped.summary is not None
    assert grouped.summary.total == 280


def test_timeline_summary_uses_full_filter_scope_when_top_hides_groups() -> None:
    records = tuple(
        record(day, "claude", f"/{name}", name, amount if day == 14 else 0)
        for day in range(1, 15)
        for name, amount in (("a", 30), ("b", 20), ("c", 10))
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)

    coverage = DateCoverage.from_interval(date(2025, 12, 25), period.until)
    top_only = build_timeline(records, period, by="project", top=1, coverage=coverage)
    with_other = build_timeline(
        records,
        period,
        by="project",
        top=1,
        show_other=True,
        coverage=coverage,
    )

    assert top_only.summary is not None
    assert top_only.summary.total == 60
    assert top_only.summary.current_filter_total
    assert top_only.summary.chart_top == 1
    assert with_other.summary is not None
    assert with_other.summary.total == 60
    assert not with_other.summary.current_filter_total
    assert with_other.summary.chart_top is None


def test_summary_handles_zero_and_equal_baselines() -> None:
    records = (
        record(7, "claude", "/a", "sonnet", 0),
        record(13, "claude", "/a", "sonnet", 40),
        record(14, "claude", "/a", "sonnet", 40),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    summary = build_timeline(
        records, period, coverage=DateCoverage.from_interval(date(2025, 12, 25), period.until)
    ).summary

    assert summary is not None
    assert summary.day_over_day is not None
    assert summary.week_over_week is not None
    assert summary.day_over_day.direction == ChangeDirection.UNCHANGED
    assert summary.day_over_day.percent is None
    assert summary.week_over_week.direction == ChangeDirection.FROM_ZERO
    assert summary.week_over_week.percent is None


def test_calendar_summary_uses_aggregate_daily_totals() -> None:
    records = tuple(
        record(day, agent, f"/{agent}", agent, day * amount)
        for day in range(1, 15)
        for agent, amount in (("claude", 10), ("codex", 5))
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    summary = build_calendar(
        records, period, coverage=DateCoverage.from_interval(date(2025, 12, 25), period.until)
    ).summary

    assert summary is not None
    assert summary.total == 210
    assert summary.day_over_day is not None
    assert summary.week_over_week is not None
    assert summary.day_over_day.percent == pytest.approx(100 / 13)
    assert summary.week_over_week.percent == 100.0


def test_summary_reports_full_decrease_to_zero() -> None:
    records = (record(7, "claude", "/a", "sonnet", 100),)
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    summary = build_calendar(
        records, period, coverage=DateCoverage.from_interval(date(2025, 12, 25), period.until)
    ).summary

    assert summary is not None
    assert summary.week_over_week is not None
    assert summary.week_over_week.direction == ChangeDirection.DECREASE
    assert summary.week_over_week.percent == 100.0


def test_show_other_notice_preserves_filter_before_top_semantics() -> None:
    records = tuple(
        record(1, "claude", f"/{name}", name, total)
        for name, total in (("a", 30), ("b", 20), ("c", 10))
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    model = build_timeline(records, period, by="project", top=3, show_other=True)

    assert [series.label for series in model.series] == ["a", "b", "c"]
    assert model.notices[-1].key == "notice.other_not_needed"
    assert model.notices[-1].values == {"count": 3, "top": 3}


def test_show_other_does_not_emit_a_zero_group_notice() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    model = build_timeline((), period, by="project", top=3, show_other=True)

    assert model.notices == ()


def test_ranking_uses_model_breakdowns_and_stack_components_sum() -> None:
    records = (record(1, "claude", "/a", "sonnet", 20), record(1, "codex", "/b", "codex", 10))
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    ranking = build_ranking(records, period, by="model", top=1, show_other=True)
    assert ranking.date_range == period
    assert [(item.label, item.usage.total) for item in ranking.entries] == [
        ("sonnet", 20),
        ("Other", 10),
    ]
    stack = build_stack(records, DateRange(date(2026, 1, 1), date(2026, 1, 1), None))
    assert stack.total.total == 30


def test_model_grouping_adds_authoritative_residual_other() -> None:
    full_usage = usage(20)
    partial_usage = usage(15)
    records = (
        UsageRecord(
            date(2026, 1, 1),
            "claude",
            full_usage,
            SourceKind.UNIFIED_DAILY,
            make_project_ref("claude", "/a"),
            (ModelBreakdown("sonnet", partial_usage),),
        ),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)

    timeline = build_timeline(records, period, by="model")
    ranking = build_ranking(records, period, by="model")

    assert [(item.label, item.total.total) for item in timeline.series] == [
        ("sonnet", 15),
        ("Other", 5),
    ]
    assert [(item.label, item.usage.total) for item in ranking.entries] == [
        ("sonnet", 15),
        ("Other", 5),
    ]
    assert ranking.percentage_total.total == 20


def test_model_grouping_notices_invalid_overattribution_without_negative_other() -> None:
    records = (
        UsageRecord(
            date(2026, 1, 1),
            "claude",
            usage(10),
            SourceKind.UNIFIED_DAILY,
            make_project_ref("claude", "/a"),
            (ModelBreakdown("sonnet", usage(15)),),
        ),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)

    model = build_timeline(records, period, by="model")

    assert [(item.label, item.total.total) for item in model.series] == [("sonnet", 15)]
    assert [notice.key for notice in model.notices] == ["notice.model_overattributed"]


def test_ranking_summary_uses_only_daily_records_and_marks_session_omission() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)
    dated = record(1, "claude", "/daily", "sonnet", 10)
    session = UsageRecord(
        None,
        "codex",
        usage(90),
        SourceKind.CODEX_SESSIONS,
        make_project_ref("codex", "/session"),
    )
    scope_notice = Notice("notice.summary_excludes_session_agent", {"agent": "Codex"})

    ranking = build_ranking(
        (dated, session),
        period,
        by="project",
        coverage=DateCoverage.from_interval(period.since, period.until),
        summary_notices=(scope_notice,),
    )

    assert ranking.summary is not None
    assert ranking.summary.total == 10
    assert ranking.percentage_total.total == 100
    assert sum(entry.usage.total for entry in ranking.entries) == 100
    assert ranking.notices[-1] == scope_notice


def test_ranking_summary_warning_is_hidden_with_the_summary() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)
    scope_notice = Notice("notice.summary_excludes_session_agent", {"agent": "Codex"})

    ranking = build_ranking(
        (record(1, "claude", "/daily", "sonnet", 10),),
        period,
        by="project",
        include_summary=False,
        coverage=DateCoverage.from_interval(period.since, period.until),
        summary_notices=(scope_notice,),
    )

    assert ranking.summary is None
    assert scope_notice not in ranking.notices


def test_ranking_percentage_uses_full_filtered_total() -> None:
    records = tuple(
        record(1, "claude", f"/{name}", name, total)
        for name, total in (("a", 60), ("b", 30), ("c", 10))
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)

    ranking = build_ranking(records, period, by="model", top=1)

    assert ranking.total.total == 60
    assert ranking.percentage_total.total == 100
