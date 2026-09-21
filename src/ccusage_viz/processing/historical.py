from __future__ import annotations

from typing import TypeAlias

from ccusage_viz.chart_models import CalendarModel, RankingModel, StackModel, TimelineModel
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.options import HistoricalChartConfig
from ccusage_viz.processing.filtering import prepare_filtered_scope
from ccusage_viz.processing.projection import (
    build_calendar,
    build_ranking,
    build_stack,
    build_timeline,
)
from ccusage_viz.project_identity import ProjectLabelContext

HistoricalModel: TypeAlias = TimelineModel | CalendarModel | StackModel | RankingModel
_EMPTY_COVERAGE = DateCoverage()


def process_historical(
    chart: HistoricalChartConfig,
    records: tuple[UsageRecord, ...],
    *,
    notices: tuple[Notice, ...] = (),
    summary_notices: tuple[Notice, ...] = (),
    coverage: DateCoverage = _EMPTY_COVERAGE,
    include_summary: bool = True,
    project_label_context: ProjectLabelContext = 0,
) -> HistoricalModel:
    """Project accepted normalized records into one immutable chart model."""
    scope = prepare_filtered_scope(
        records,
        chart.date_range,
        agents=chart.filters.agents,
        models=chart.filters.models,
        projects=chart.filters.projects,
    )
    all_notices = (*notices, *scope.notices)
    if chart.kind == "timeline":
        return build_timeline(
            scope.records,
            chart.date_range,
            by=None if chart.by == "total" else chart.by,
            top=chart.top,
            show_other=chart.other == "show",
            include_summary=include_summary,
            notices=all_notices,
            aggregation=chart.granularity,
            coverage=coverage,
            filter_count=scope.filter_count,
            project_aggregation=chart.project_aggregation,
            project_label_context=project_label_context,
        )
    if chart.kind == "calendar":
        return build_calendar(
            scope.records,
            chart.date_range,
            include_summary=include_summary,
            notices=all_notices,
            coverage=coverage,
            filter_count=scope.filter_count,
        )
    if chart.kind == "stack":
        return build_stack(
            scope.records,
            chart.date_range,
            split_cache=chart.cache == "split",
            include_summary=include_summary,
            notices=all_notices,
            aggregation=chart.granularity,
            coverage=coverage,
            filter_count=scope.filter_count,
        )
    return build_ranking(
        scope.records,
        chart.date_range,
        by=chart.by,
        top=chart.top,
        show_other=chart.other == "show",
        include_summary=include_summary,
        notices=all_notices,
        summary_notices=summary_notices,
        coverage=coverage,
        filter_count=scope.filter_count,
        project_aggregation=chart.project_aggregation,
        project_label_context=project_label_context,
    )
