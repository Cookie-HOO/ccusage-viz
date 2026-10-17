from __future__ import annotations

from datetime import UTC, datetime

from ccusage_viz.core.time import DateRange
from ccusage_viz.options import (
    ChartPaneConfig,
    ChartPresentation,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    Filters,
    ProcessConfig,
    TimelineConfig,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)

RANGE = DateRange(
    __import__("datetime").date(2026, 9, 1),
    __import__("datetime").date(2026, 10, 8),
    relative_until=True,
    period="30d",
    fixed_bounds=True,
    implicit_until=True,
)

def _installed_source(dataset_id: str = "reading") -> CustomCommandSource:
    return CustomCommandSource(dataset_id, ("ccuv-dataset", dataset_id), "installed")

def _launch(*, panes: tuple[object, ...] | None = None) -> DashboardLaunch:
    resolved_panes = panes or (
        ChartPaneConfig(
            TimelineConfig(
                "timeline",
                RANGE,
                Filters(agents=("claude",), projects=("ccusage-viz",)),
                ChartPresentation(style="linear"),
                by="model",
                top=4,
            )
        ),
    )
    return DashboardLaunch(
        ProcessConfig("custom-ccusage", 9.5, 2048, (("API_TOKEN", "secret"),)),
        DashboardHostConfig(
            grid="1x1" if len(resolved_panes) == 1 else "3x3",
            timezone="Asia/Shanghai",
            demo_size="small",
            demo_seed=3,
            refresh_interval=11,
            sampling_interval=7,
            header_interval=5,
            column_weights=(1,) if len(resolved_panes) == 1 else (2, 3, 4),
            row_weights=(1,) if len(resolved_panes) == 1 else (2, 3, 4),
        ),
        resolved_panes,  # type: ignore[arg-type]
        explicit=frozenset({"demo"}),
        launcher="test",
    )
