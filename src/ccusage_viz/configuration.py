from __future__ import annotations

from contextlib import suppress
from dataclasses import replace

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomDataset,
    CustomProbeDescriptor,
    V2HistoricalChartCapability,
    V2ProbeDescriptor,
)
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
    compatible_styles,
    is_v2_custom_ranking,
    resolve_date_range,
)
from ccusage_viz.render.palette import COLOR_SCHEMES


def _default_dashboard_chart_presentation(kind: str) -> ChartPresentation:
    """Return the shared starting presentation for Dashboard chart panes."""
    return ChartPresentation(
        style={
            "timeline": "linear",
            "calendar": "relative",
            "stack": "stacked",
            "ranking": "dot",
            "monitor": "points",
        }[kind],
        density="full" if kind == "ranking" else "compact",
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
    """Apply compatible Dataset suggestions to an initial historical chart."""
    defaults = descriptor.defaults.get(config.kind)
    capability = descriptor.capabilities.charts.get(config.kind)
    if capability is None:
        return config

    explicit = config.initial_explicit
    partition_choices = getattr(capability, "partition_by", None)
    if "partition_by" in explicit:
        partition_candidates = (config.partition_by,)
    elif partition_choices is None:
        partition_candidates = (None,)
    else:
        preferred_partition = (
            defaults.partition_by
            if defaults is not None
            and defaults.partition_by is not None
            and _declared(defaults, "partition_by")
            else None
        )
        partition_preferences = (
            *((preferred_partition,) if preferred_partition is not None else ()),
            config.partition_by,
            *partition_choices,
        )
        partition_candidates = tuple(
            dict.fromkeys(choice for choice in partition_preferences if choice in partition_choices)
        )
    if "group_by" in explicit:
        group_candidates = (config.group_by,)
    else:
        preferred_group = (
            defaults.group_by
            if defaults is not None
            and defaults.group_by is not None
            and _declared(defaults, "group_by")
            else None
        )
        fallback_groups = (
            capability.group_by
            if any(choice is not None for choice in partition_candidates)
            else ()
        )
        group_preferences = (
            *((preferred_group,) if preferred_group is not None else ()),
            config.group_by,
            *fallback_groups,
        )
        group_candidates = tuple(
            dict.fromkeys(choice for choice in group_preferences if choice in capability.group_by)
        )
    partition_by, group_by = next(
        (
            (partition, group)
            for partition in partition_candidates
            for group in group_candidates
            if (partition is None or partition != group)
            and (partition is None or group is not None)
        ),
        (config.partition_by, config.group_by),
    )
    top = config.top
    if (
        defaults is not None
        and "top" not in explicit
        and _declared(defaults, "top")
        and defaults.top is not None
        and group_by is not None
    ):
        top = defaults.top

    date_range = config.date_range
    supported_periods = getattr(capability, "periods", ())
    if (
        defaults is not None
        and not explicit & {"period", "since", "until"}
        and defaults.period is not None
        and (defaults.period != "all" or defaults.period in supported_periods)
        and (not supported_periods or defaults.period in supported_periods)
    ):
        with suppress(ValueError):
            date_range = resolve_date_range(
                config.kind,
                period=defaults.period,
                since=None,
                until=None,
                timezone=timezone,
            )
    granularity = "day" if is_v2_custom_ranking(config) else config.granularity
    if (
        not is_v2_custom_ranking(config)
        and defaults is not None
        and "granularity" not in explicit
        and _declared(defaults, "granularity")
        and defaults.granularity in capability.granularities
    ):
        granularity = defaults.granularity
    other = config.other
    if (
        defaults is not None
        and config.kind in {"timeline", "stack", "ranking"}
        and "other" not in explicit
        and _declared(defaults, "other")
        and defaults.other is not None
    ):
        other = defaults.other
    theme = config.presentation.theme
    if (
        defaults is not None
        and "color_scheme" not in explicit
        and _declared(defaults, "theme")
        and defaults.theme in COLOR_SCHEMES
    ):
        theme = defaults.theme
    style = config.presentation.style
    if (
        defaults is not None
        and "style" not in explicit
        and _declared(defaults, "style")
        and defaults.style in compatible_styles(config.kind, group_by)
    ):
        style = defaults.style
    return replace(
        config,
        date_range=date_range,
        filters=config.filters,
        presentation=replace(config.presentation, theme=theme, style=style),
        group_by=group_by,
        top=top,
        partition_by=partition_by,
        other=other,
        granularity=granularity,
    )


def _declared(defaults, field: str) -> bool:
    return not defaults.declared or field in defaults.declared


def v2_metric_probe_descriptor(
    descriptor: V2ProbeDescriptor, metric_id: str | None
) -> CustomProbeDescriptor:
    """Project one V2 historical Metric into the mature V1 historical surface."""

    from ccusage_viz.custom_monitor_component import resolve_metric

    resolved = resolve_metric(
        CustomChartConfig(
            "timeline",
            CustomCommandSource("probe", ("probe",)),
            resolve_date_range("timeline", period="14d", since=None, until=None),
            metric_id=metric_id,
        ),
        descriptor,
    )
    metric = next(item for item in descriptor.metrics if item.id == resolved.metric_id)
    charts: dict[str, CustomChartCapability] = {}
    for kind, capability in metric.capabilities.charts.items():
        if isinstance(capability, V2HistoricalChartCapability):
            charts[kind] = CustomChartCapability(
                capability.granularities,
                capability.group_by,
                capability.filters,
                capability.max_items,
                capability.descriptions_default,
                capability.periods,
                capability.comparison,
                capability.show_percentage,
                capability.refresh_interval_seconds,
                capability.sort_direction,
                capability.partition_by,
            )
    return CustomProbeDescriptor(
        descriptor.revision,
        descriptor.version,
        CustomDataset(metric.title, metric.description, metric.unit),
        CustomCapabilities(
            metric.capabilities.group_by,
            (),
            charts,
            metric.capabilities.partition_by,
        ),
        metric.defaults,
        descriptor.environment,
        descriptor.source_timezone,
    )


def default_custom_pane(
    kind: str,
    *,
    source: CustomCommandSource,
    dashboard: DashboardLaunch,
    metric_id: str | None = None,
    metric_summary: str = "comparisons",
    metric_periods: tuple[str, ...] = (),
    metric_titles: tuple[str, str] | None = None,
) -> CustomChartPaneConfig:
    """Create a default custom historical pane from a declared command source."""
    if kind not in {"timeline", "calendar", "stack", "ranking", "monitor"}:
        raise ValueError(f"unknown custom chart kind: {kind}")
    presentation = _default_dashboard_chart_presentation(kind)
    date_range = resolve_date_range(
        "timeline" if kind == "monitor" else kind, period=None, since=None, until=None
    )
    return CustomChartPaneConfig(
        CustomChartConfig(
            kind,
            source,
            date_range,
            presentation=presentation,
            metric_id=metric_id,
            metric_summary=metric_summary,  # type: ignore[arg-type]
            metric_periods=metric_periods,
            metric_titles=metric_titles,
        )
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
