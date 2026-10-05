from __future__ import annotations

from dataclasses import replace

from ccusage_viz.options import (
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardLaunch,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    resolve_date_range,
)


def _default_dashboard_chart_presentation(kind: str) -> ChartPresentation:
    """Return the shared starting presentation for Dashboard chart panes."""
    return ChartPresentation(
        style={
            "timeline": "linear",
            "calendar": "relative",
            "stack": "stacked",
            "ranking": "dot",
            "monitor": "bars",
        }[kind],
        density="compact",
    )


def default_pane(kind: str, *, dashboard: DashboardLaunch) -> ChartPaneConfig:
    """Create a default Pane without interpreting command-line syntax."""
    presentation = _default_dashboard_chart_presentation(kind)
    if kind == "monitor":
        chart = MonitorConfig("monitor", 3600, presentation=presentation)
    else:
        date_range = resolve_date_range(
            kind, period=None, since=None, until=None, timezone=dashboard.host.timezone
        )
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
    return ChartPaneConfig(chart)


def default_custom_pane(
    kind: str, *, source: CustomCommandSource, dashboard: DashboardLaunch
) -> CustomChartPaneConfig:
    """Create a default custom historical pane from a declared command source."""
    if kind not in {"timeline", "calendar", "stack", "ranking"}:
        raise ValueError(f"unknown custom chart kind: {kind}")
    presentation = _default_dashboard_chart_presentation(kind)
    date_range = resolve_date_range(kind, period=None, since=None, until=None)
    return CustomChartPaneConfig(
        CustomChartConfig(kind, source, date_range, presentation=presentation)
    )


def standalone_from_chart_pane(
    dashboard: DashboardLaunch, pane: ChartPaneConfig | CustomChartPaneConfig
) -> StandaloneLaunch:
    """Materialize Dashboard-owned Host context for one reusable chart payload."""
    interval = (
        dashboard.host.sampling_interval
        if pane.chart.kind == "monitor"
        else dashboard.host.refresh_interval
    )
    host = StandaloneHostConfig(
        provider=dashboard.host.provider,
        timezone=dashboard.host.timezone,
        ascii=dashboard.host.ascii,
        demo_size=dashboard.host.demo_size,
        demo_seed=dashboard.host.demo_seed,
        watch=True,
        interval=interval,
    )
    chart = pane.chart
    if dashboard.host.ascii:
        chart = replace(chart, presentation=replace(chart.presentation, theme="classic"))
    return StandaloneLaunch(dashboard.process, host, chart)
