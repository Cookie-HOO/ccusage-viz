from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardPreset:
    panels: tuple[str, ...]
    grid: str
    layout: str | None = None
    refresh_interval: float = 60.0
    sampling_interval: float = 15.0
    style: str = "split"


DEFAULT_DASHBOARD_PANELS = (
    "timeline --style line-points --theme nord --density compact",
    "stack --style stacked-pattern --theme solarized --density compact",
    "ranking --style dot --theme gruvbox --density compact",
    "monitor --by model --style ranking --theme dracula --density compact",
)
DEFAULT_DASHBOARD_MONITOR_PANEL = DEFAULT_DASHBOARD_PANELS[-1]
DASHBOARD_PRESETS = {
    "wide": DashboardPreset(DEFAULT_DASHBOARD_PANELS, "2x2", style="framed"),
    "spotlight-wide": DashboardPreset(
        DEFAULT_DASHBOARD_PANELS[:3], "2x2", layout="spotlight-wide", style="framed"
    ),
    "spotlight-wide2": DashboardPreset(
        DEFAULT_DASHBOARD_PANELS, "2x2", layout="spotlight-wide2", style="framed"
    ),
    "narrow": DashboardPreset(
        (
            "timeline --period 14d --style line-points --theme nord --density compact",
            "ranking --period 14d --by project --style dot --theme gruvbox --density compact",
            "monitor --window 1h --by model --style ranking --theme dracula --density compact",
        ),
        "3x1",
        style="framed",
    ),
    "all": DashboardPreset(
        (
            "timeline --granularity day --style line-points --theme nord --density minimal",
            "timeline --period 13mo --granularity month --style stem --theme solarized --density minimal",
            "calendar --theme github --density minimal",
            "ranking --by project --style dots --theme gruvbox --density minimal",
            "stack --style stacked-pattern --theme dracula --density minimal",
            "stack --style grouped-thin --theme contrast --density minimal",
            "monitor --style points --theme github --density minimal",
            "monitor --by model --style ranking --theme nord --density minimal",
            "monitor --by agent --style ranking --theme gruvbox --density minimal",
            "monitor --by project --style ranking --theme solarized --density minimal",
        ),
        "5x2",
        style="split",
    ),
}
