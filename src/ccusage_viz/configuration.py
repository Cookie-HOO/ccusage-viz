from __future__ import annotations

from dataclasses import replace

from ccusage_viz.custom_models import CustomProbeDescriptor
from ccusage_viz.custom_protocol import CustomProtocolError
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


def apply_custom_probe_defaults(
    config: CustomChartConfig,
    descriptor: CustomProbeDescriptor,
    *,
    timezone: str,
) -> CustomChartConfig:
    """Merge a Dataset's initial chart defaults into an uncustomized chart.

    Probe data is source metadata, rather than a preference store: callers apply
    it exactly once before their first chart request.  A malformed or
    contradictory descriptor is rejected here instead of falling back to the
    host's unrelated generic defaults.
    """
    defaults = descriptor.defaults.get(config.kind)
    capability = descriptor.capabilities.charts.get(config.kind)
    if defaults is None or capability is None:
        raise CustomProtocolError(f"probe descriptor does not support {config.kind} charts")

    explicit = config.initial_explicit
    group_by = config.group_by if "group_by" in explicit else defaults.group_by
    top = config.top if "top" in explicit else defaults.top
    if group_by is not None and group_by not in capability.group_by:
        raise CustomProtocolError(
            f"probe default group_by {group_by!r} is not supported by {config.kind}"
        )
    if top is not None and group_by is None:
        raise CustomProtocolError("probe default top requires a group_by value")

    date_range = config.date_range
    if not explicit & {"period", "since", "until"} and defaults.period is not None:
        date_range = resolve_date_range(
            config.kind,
            period=defaults.period,
            since=None,
            until=None,
            timezone=timezone,
        )
    return replace(config, date_range=date_range, group_by=group_by, top=top)


def default_custom_pane(
    kind: str, *, source: CustomCommandSource, dashboard: DashboardLaunch, metric_id: str | None = None
) -> CustomChartPaneConfig:
    """Create a default custom historical pane from a declared command source."""
    if kind not in {"timeline", "calendar", "stack", "ranking", "monitor"}:
        raise ValueError(f"unknown custom chart kind: {kind}")
    presentation = _default_dashboard_chart_presentation(kind)
    date_range = resolve_date_range("timeline" if kind == "monitor" else kind, period=None, since=None, until=None)
    return CustomChartPaneConfig(
        CustomChartConfig(kind, source, date_range, presentation=presentation, metric_id=metric_id)
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
