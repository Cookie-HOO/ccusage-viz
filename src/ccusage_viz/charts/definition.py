from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ccusage_viz.chart_models import CalendarModel, RankingModel, StackModel, TimelineModel
from ccusage_viz.options import CalendarConfig, RankingConfig, StackConfig, TimelineConfig
from ccusage_viz.processing.historical import HistoricalModel, process_historical
from ccusage_viz.render.base import RenderContext

HistoricalConfigType = (
    type[TimelineConfig] | type[CalendarConfig] | type[StackConfig] | type[RankingConfig]
)
HistoricalModelType = (
    type[TimelineModel] | type[CalendarModel] | type[StackModel] | type[RankingModel]
)
HistoricalRenderer = Callable[[HistoricalModel, RenderContext], str]


@dataclass(frozen=True, slots=True)
class ChartDefinition:
    """Stateless collaborators registered for one built-in chart kind."""

    chart_id: str
    config_type: HistoricalConfigType
    model_type: HistoricalModelType
    processor: Callable[..., HistoricalModel]
    renderer: HistoricalRenderer


__all__ = ("ChartDefinition", "HistoricalRenderer", "process_historical")
