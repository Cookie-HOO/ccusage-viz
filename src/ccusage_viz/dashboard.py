from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DashboardPreset:
    panels: tuple[str, ...]
    grid: str
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
    "narrow": DashboardPreset(
        (
            "timeline --period 14d --style points --theme nord --density compact",
            "ranking --period 14d --by project --style dot --theme gruvbox --density compact",
            "monitor --window 1h --by model --style ranking --theme dracula --density compact",
        ),
        "3x1",
        style="framed",
    ),
    "all": DashboardPreset(
        (
            "timeline --granularity day --style line-points --theme nord --density compact",
            "timeline --period 13mo --granularity month --style stem --theme solarized --density compact",
            "calendar --theme github --density compact",
            "ranking --by project --style dots --theme gruvbox --density compact",
            "stack --style stacked-pattern --theme dracula --density compact",
            "stack --style grouped --theme catppuccin --density compact",
            "monitor --style points --theme github --density compact",
            "monitor --by model --style ranking --theme nord --density compact",
            "monitor --by agent --style ranking --theme gruvbox --density compact",
            "monitor --by project --style ranking --theme solarized --density compact",
        ),
        "5x2",
        style="framed",
    ),
}
