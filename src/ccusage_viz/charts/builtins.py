from __future__ import annotations

from typing import cast

from ccusage_viz.chart_models import CalendarModel, RankingModel, StackModel, TimelineModel
from ccusage_viz.charts.definition import ChartDefinition, HistoricalRenderer
from ccusage_viz.options import CalendarConfig, RankingConfig, StackConfig, TimelineConfig
from ccusage_viz.processing import process_historical
from ccusage_viz.render import render_calendar, render_ranking, render_stack, render_timeline

TIMELINE_DEFINITION = ChartDefinition(
    "timeline",
    TimelineConfig,
    TimelineModel,
    process_historical,
    cast(HistoricalRenderer, render_timeline),
)
CALENDAR_DEFINITION = ChartDefinition(
    "calendar",
    CalendarConfig,
    CalendarModel,
    process_historical,
    cast(HistoricalRenderer, render_calendar),
)
STACK_DEFINITION = ChartDefinition(
    "stack",
    StackConfig,
    StackModel,
    process_historical,
    cast(HistoricalRenderer, render_stack),
)
RANKING_DEFINITION = ChartDefinition(
    "ranking",
    RankingConfig,
    RankingModel,
    process_historical,
    cast(HistoricalRenderer, render_ranking),
)
