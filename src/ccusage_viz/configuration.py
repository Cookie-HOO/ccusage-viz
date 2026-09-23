from __future__ import annotations

from dataclasses import replace

from ccusage_viz.options import (
    CalendarConfig,
    ChartPresentation,
    DashboardLaunch,
    MonitorConfig,
    PaneConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    resolve_date_range,
)


def default_pane(kind: str, *, dashboard: DashboardLaunch) -> PaneConfig:
    """Create a default Pane without interpreting command-line syntax."""
    presentation = ChartPresentation(
        style={
            "timeline": "linear",
            "calendar": "relative",
            "stack": "stacked",
            "ranking": "bar",
            "monitor": "bars",
        }[kind],
        density="compact",
    )
    if kind == "monitor":
        chart = MonitorConfig("monitor", 3600, presentation=presentation)
    else:
        date_range = resolve_date_range(kind, period=None, since=None, until=None)
        if kind == "timeline":
            chart = TimelineConfig("timeline", date_range, presentation=presentation)
        elif kind == "calendar":
            chart = CalendarConfig("calendar", date_range, presentation=presentation)
        elif kind == "stack":
            chart = StackConfig("stack", date_range, presentation=presentation)
        elif kind == "ranking":
            chart = RankingConfig("ranking", date_range, presentation=presentation)
        else:
            raise ValueError(f"unknown chart kind: {kind}")
    return PaneConfig(chart)


def standalone_from_pane(dashboard: DashboardLaunch, pane: PaneConfig) -> StandaloneLaunch:
    """Materialize Dashboard-owned Host context for one reusable chart payload."""
    interval = (
        dashboard.host.sampling_interval
        if pane.chart.kind == "monitor"
        else dashboard.host.refresh_interval
    )
    host = StandaloneHostConfig(
        provider=dashboard.host.provider,
        ascii=dashboard.host.ascii,
        demo_size=dashboard.host.demo_size,
        watch=True,
        interval=interval,
    )
    chart = pane.chart
    if dashboard.host.ascii:
        chart = replace(chart, presentation=replace(chart.presentation, theme="classic"))
    return StandaloneLaunch(dashboard.process, host, chart)
