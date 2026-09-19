from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardPreset:
    panels: tuple[str, ...]
    grid: str
    refresh_interval: float = 60.0
    sampling_interval: float = 15.0
    style: str = "split"


DEFAULT_DASHBOARD_PANELS = ("timeline", "stack", "ranking", "monitor --by model")
DEFAULT_DASHBOARD_MONITOR_PANEL = DEFAULT_DASHBOARD_PANELS[-1]
DASHBOARD_PRESETS = {
    "wide": DashboardPreset(DEFAULT_DASHBOARD_PANELS, "2x2"),
    "narrow": DashboardPreset(
        (
            "timeline --period 14d",
            "ranking --by project --top 5",
            "monitor --by model --top 3 --style ranking",
        ),
        "3x1",
    ),
    "all": DashboardPreset(
        (
            "timeline --granularity day",
            "timeline --period 13mo --granularity month",
            "calendar",
            "ranking",
            "stack --style stacked",
            "stack --style grouped",
            "monitor",
            "monitor --by model --top 3 --style ranking",
            "monitor --by agent --top 3 --style ranking",
            "monitor --by project --top 3 --style ranking",
        ),
        "5x2",
        style="framed",
    ),
}
