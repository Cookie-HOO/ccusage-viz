from datetime import date, timedelta

import pytest

from ccusage_viz.chart_models import ChangeDirection
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.demo import generate_demo
from ccusage_viz.domain import ModelBreakdown, Notice, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.options import Filters, TimelineConfig
from ccusage_viz.processing import (
    build_calendar,
    build_ranking,
    build_stack,
    build_timeline,
    filter_records,
)
from ccusage_viz.project_identity import make_project_ref


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


def test_demo_stack_has_no_other_component() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 8))

    combined = build_stack(generate_demo("small", period), period, split_cache=False)
    split = build_stack(generate_demo("small", period), period, split_cache=True)

    assert [component.label for component in combined.components] == ["input", "output", "cache"]
    assert [component.label for component in split.components] == [
        "input",
        "output",
        "cache_read",
        "cache_creation",
    ]


def test_filters_or_within_dimension_and_and_across_dimensions() -> None:
    records = (
        record(1, "claude", "/a/app", "sonnet", 10),
        record(1, "codex", "/b/app", "codex", 20),
        record(1, "claude", "/a/tool", "opus", 30),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2))
    filtered, _ = filter_records(
        records,
        period,
        agents=("claude", "codex"),
        projects=("app (claude)", "app (codex)"),
        models=("sonnet", "codex"),
    )
    assert [item.usage.total for item in filtered] == [10, 20]


def test_filter_candidates_are_independent_across_dimensions() -> None:
    records = (
        record(1, "claude", "/a/app", "sonnet", 10),
        record(1, "codex", "/b/tool", "codex", 20),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2))

    filtered, notices = filter_records(records, period, agents=("claude",), models=("codex",))
    assert filtered == ()
    assert notices[-1].values == {"dimension": "model", "values": "codex"}

    filtered, notices = filter_records(records, period, agents=("claude",), projects=("tool",))
    assert filtered == ()
    assert notices[-1].values == {"dimension": "project", "values": "tool"}


def test_filters_remain_and_across_independently_resolved_dimensions() -> None:
    records = (
        record(1, "claude", "/a/app", "sonnet", 10),
        record(1, "codex", "/b/tool", "codex", 20),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2))

    filtered, _ = filter_records(
        records, period, agents=("claude",), projects=("app",), models=("sonnet",)
    )
    assert [item.usage.total for item in filtered] == [10]


def test_process_historical_carries_filter_dimension_count_into_summary() -> None:
    from ccusage_viz.processing import process_historical

    records = (
        record(1, "claude", "/a/app", "sonnet", 10),
        record(1, "codex", "/b/tool", "codex", 20),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))
    chart = TimelineConfig(
        "timeline",
        period,
        filters=Filters(agents=("claude", "other"), models=("sonnet",), projects=("app",)),
    )
    model = process_historical(
        chart,
        records,
        coverage=DateCoverage.from_interval(period.since - timedelta(days=7), period.until),
    )

    assert model.summary is not None
    assert model.summary.total == 10
    assert model.summary.filter_count == 3


def test_project_aggregation_merges_only_unambiguous_cross_agent_names() -> None:
    records = (
        record(1, "claude", "-home-me-projects-app", "sonnet", 30),
        record(1, "codex", "/work/app", "gpt", 20),
        record(1, "codex", "/work/tool", "gpt", 10),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

    named = build_ranking(records, period, by="project", project_aggregation="name")
    exact = build_ranking(records, period, by="project", project_aggregation="exact")

    assert [(entry.label, entry.usage.total) for entry in named.entries] == [
        ("app", 50),
        ("tool", 10),
    ]
    assert [(entry.label, entry.usage.total) for entry in exact.entries] == [
        ("claude · -home-me-projects-app", 30),
        ("codex · app", 20),
        ("codex · tool", 10),
    ]
    assert [entry.key for entry in exact.entries[:2]] == [
        ("project", "exact", "claude", "-home-me-projects-app"),
        ("project", "exact", "codex", "/work/app"),
    ]


def test_project_aggregation_uses_parent_aliases_without_merging_codex_projects() -> None:
    records = (
        record(1, "claude", "-a-b-c-e", "sonnet", 30),
        record(1, "codex", "/a/b/c/e", "gpt", 20),
        record(1, "codex", "/a/b/d/e", "gpt", 10),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

    named_ranking = build_ranking(records, period, by="project", project_aggregation="name")
    named_timeline = build_timeline(records, period, by="project", project_aggregation="name")
    exact = build_ranking(records, period, by="project", project_aggregation="exact")

    assert [(entry.key, entry.usage.total) for entry in named_ranking.entries] == [
        (("project", "name", "c-e"), 50),
        (("project", "exact", "codex", "/a/b/d/e"), 10),
    ]
    assert [(series.key, series.total.total) for series in named_timeline.series] == [
        (("project", "name", "c-e"), 50),
        (("project", "exact", "codex", "/a/b/d/e"), 10),
    ]
    assert [(entry.key, entry.usage.total) for entry in exact.entries] == [
        (("project", "exact", "claude", "-a-b-c-e"), 30),
        (("project", "exact", "codex", "/a/b/c/e"), 20),
        (("project", "exact", "codex", "/a/b/d/e"), 10),
    ]


def test_project_aggregation_does_not_merge_ambiguous_same_agent_names() -> None:
    records = (
        record(1, "claude", "-home-me-projects-app", "sonnet", 30),
        record(1, "codex", "/work/app", "gpt", 20),
        record(1, "codex", "/archive/app", "gpt", 10),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

    model = build_timeline(records, period, by="project", project_aggregation="name")

    assert [(series.label, series.total.total) for series in model.series] == [
        ("-home-me-projects-app", 30),
        ("app 2", 20),
        ("app 1", 10),
    ]


def test_timeline_zero_fills_and_other_is_final() -> None:
    records = (
        record(1, "claude", "/a", "a", 30),
        record(1, "codex", "/b", "b", 20),
        record(1, "claude", "/c", "c", 10),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 2))
    model = build_timeline(records, period, by="project", top=1, show_other=True)
    assert [series.label for series in model.series] == ["a", "Other"]
    assert [value.total for value in model.series[1].values] == [30, 0]


def test_summary_uses_the_single_rendered_series() -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, 15))
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
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
    period = DateRange(date(2026, 1, 1), date(2026, 1, days))

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


def test_explicit_start_and_end_keep_total_without_comparisons() -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, 15))
    period = DateRange(
        date(2026, 1, 1),
        date(2026, 1, 14),
        None,
        fixed_bounds=True,
    )

    coverage = DateCoverage.from_interval(period.since, period.until)
    summaries = (
        build_timeline(records, period, coverage=coverage).summary,
        build_calendar(records, period, coverage=coverage).summary,
        build_stack(records, period, coverage=coverage).summary,
    )

    assert all(summary is not None for summary in summaries)
    for summary in summaries:
        assert summary is not None
        assert summary.period == "range"
        assert summary.total == 1_050
        assert summary.sequential is None
        assert summary.year_over_year is None


def test_summary_can_be_disabled_for_supported_charts() -> None:
    records = tuple(record(day, "claude", "/a", "sonnet", day * 10) for day in range(1, 15))
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))

    assert build_timeline(records, period, include_summary=False).summary is None
    assert build_calendar(records, period, include_summary=False).summary is None
    assert build_stack(records, period, include_summary=False).summary is None


def test_summary_aggregates_visible_timeline_series() -> None:
    records = tuple(
        record(day, agent, f"/{agent}", agent, day * 10)
        for day in range(1, 15)
        for agent in ("claude", "codex")
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))

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
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))

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
    assert with_other.summary is not None
    assert with_other.summary.total == 60


def test_summary_handles_zero_and_equal_baselines() -> None:
    records = (
        record(7, "claude", "/a", "sonnet", 0),
        record(13, "claude", "/a", "sonnet", 40),
        record(14, "claude", "/a", "sonnet", 40),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
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
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
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
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
    summary = build_calendar(
        records, period, coverage=DateCoverage.from_interval(date(2025, 12, 25), period.until)
    ).summary

    assert summary is not None
    assert summary.week_over_week is not None
    assert summary.week_over_week.direction == ChangeDirection.DECREASE
    assert summary.week_over_week.percent == 100.0


def test_show_other_without_excluded_groups_is_silent() -> None:
    records = tuple(
        record(1, "claude", f"/{name}", name, total)
        for name, total in (("a", 30), ("b", 20), ("c", 10))
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
    timeline = build_timeline(records, period, by="project", top=3, show_other=True)
    ranking = build_ranking(records, period, by="project", top=3, show_other=True)

    assert [series.label for series in timeline.series] == ["a", "b", "c"]
    assert [entry.label for entry in ranking.entries] == ["a", "b", "c"]
    assert timeline.notices == ranking.notices == ()


def test_show_other_does_not_emit_a_zero_group_notice() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
    model = build_timeline((), period, by="project", top=3, show_other=True)

    assert model.notices == ()


def test_ranking_uses_model_breakdowns_and_stack_components_sum() -> None:
    records = (record(1, "claude", "/a", "sonnet", 20), record(1, "codex", "/b", "codex", 10))
    period = DateRange(date(2026, 1, 1), date(2026, 1, 14))
    ranking = build_ranking(records, period, by="model", top=1, show_other=True)
    assert ranking.date_range == period
    assert [(item.label, item.usage.total) for item in ranking.entries] == [
        ("sonnet", 20),
        ("Other", 10),
    ]
    stack = build_stack(records, DateRange(date(2026, 1, 1), date(2026, 1, 1)))
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
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

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
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

    model = build_timeline(records, period, by="model")

    assert [(item.label, item.total.total) for item in model.series] == [("sonnet", 15)]
    assert [notice.key for notice in model.notices] == ["notice.model_overattributed"]


def test_model_ranking_top_share_excludes_authoritative_residual_other() -> None:
    records = (
        UsageRecord(
            date(2026, 1, 1),
            "claude",
            usage(100),
            SourceKind.UNIFIED_DAILY,
            make_project_ref("claude", "/a"),
            (ModelBreakdown("a", usage(60)), ModelBreakdown("b", usage(30))),
        ),
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

    ranking = build_ranking(records, period, by="model", top=1)

    assert [(entry.label, entry.usage.total) for entry in ranking.entries] == [
        ("a", 60),
        ("Other", 10),
    ]
    assert ranking.top == 1
    assert ranking.top_share == pytest.approx(0.6)


def test_ranking_summary_uses_only_daily_records_and_marks_session_omission() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))
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
    assert ranking.summary_notices == (scope_notice,)
    assert scope_notice not in ranking.notices


def test_ranking_summary_warning_is_hidden_with_the_summary() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))
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
    assert ranking.summary_notices == ()
    assert scope_notice not in ranking.notices


def test_ranking_percentage_uses_full_filtered_total() -> None:
    records = tuple(
        record(1, "claude", f"/{name}", name, total)
        for name, total in (("a", 60), ("b", 30), ("c", 10))
    )
    period = DateRange(date(2026, 1, 1), date(2026, 1, 1))

    ranking = build_ranking(records, period, by="model", top=1)

    assert ranking.total.total == 60
    assert ranking.percentage_total.total == 100
    assert ranking.top == 1
    assert ranking.top_share == pytest.approx(0.6)

    with_other = build_ranking(records, period, by="model", top=1, show_other=True)
    assert with_other.top_share is None
    assert with_other.top is None
