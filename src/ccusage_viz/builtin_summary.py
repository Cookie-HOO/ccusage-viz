from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ccusage_viz.chart_models import PeriodSummary
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import UsageRecord
from ccusage_viz.options import DateRange, HistoricalChartConfig
from ccusage_viz.processing.filtering import prepare_filtered_scope
from ccusage_viz.processing.summaries import (
    SummaryQueryPlan,
    build_period_summary,
    build_range_summary,
    summary_query_plan,
)


@dataclass(frozen=True, slots=True)
class BuiltinPaneSummary:
    """Accepted canonical records and derived summary for one built-in pane."""

    plan: SummaryQueryPlan
    records: tuple[UsageRecord, ...]
    coverage: DateCoverage
    summary: PeriodSummary | None
    accepted_at: datetime


def build_builtin_pane_summary(
    chart: HistoricalChartConfig,
    plan: SummaryQueryPlan,
    records: tuple[UsageRecord, ...],
    coverage: DateCoverage,
    *,
    accepted_at: datetime,
) -> BuiltinPaneSummary:
    """Derive a pane summary from canonical daily data and pane filters only."""
    _validate_summary_plan(chart, plan)
    summary_range = DateRange(
        min(interval.since for interval in plan.intervals),
        max(interval.until for interval in plan.intervals),
    )
    scope = prepare_filtered_scope(
        records,
        summary_range,
        agents=chart.filters.agents,
        models=chart.filters.models,
        projects=chart.filters.projects,
    )
    summary = (
        build_range_summary(
            scope.records,
            chart.date_range,
            coverage,
            filter_count=scope.filter_count,
        )
        if plan.scope == "range"
        else build_period_summary(
            scope.records,
            plan.current.until,
            plan.scope,
            coverage,
            filter_count=scope.filter_count,
        )
    )
    return BuiltinPaneSummary(plan, records, coverage, summary, accepted_at)


def _validate_summary_plan(chart: HistoricalChartConfig, plan: SummaryQueryPlan) -> None:
    """Fail clearly when a summary response cannot belong to this pane."""
    if plan.scope == "range":
        expected = (chart.date_range.since, chart.date_range.until)
        actual = (plan.current.since, plan.current.until)
        if actual != expected or plan.sequential is not None or plan.year_over_year is not None:
            raise ValueError("range summary plan must contain exactly the chart date range")
        return
    if chart.date_range.fixed_bounds:
        raise ValueError("fixed date-range panes require a range summary plan")
    expected = summary_query_plan(plan.current.until, plan.scope)
    if plan != expected:
        raise ValueError("summary plan intervals do not match its scope and current interval")
