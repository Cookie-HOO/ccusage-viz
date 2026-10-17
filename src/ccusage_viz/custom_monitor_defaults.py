from __future__ import annotations

from dataclasses import replace

from ccusage_viz.custom_models import (
    V2HistoricalChartCapability,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.options import CustomChartConfig, compatible_styles
from ccusage_viz.render.palette import COLOR_SCHEMES


def resolve_metric(config: CustomChartConfig, descriptor: V2ProbeDescriptor) -> CustomChartConfig:
    """Resolve an omitted Metric from a V2 Probe without guessing ambiguous sources."""
    if config.metric_id is not None:
        metric = next(
            (metric for metric in descriptor.metrics if metric.id == config.metric_id), None
        )
        if metric is None:
            raise ValueError("selected metric is not declared by runtime probe")
        chart_capability = metric.capabilities.charts.get(config.kind)
        periods = (
            chart_capability.periods
            if isinstance(chart_capability, V2HistoricalChartCapability)
            else ()
        )
        comparison = (
            chart_capability.comparison
            if isinstance(chart_capability, V2HistoricalChartCapability)
            else "full"
        )
        return replace(
            config,
            metric_summary=metric.summary,
            metric_periods=periods,
            metric_titles=(metric.title.en, metric.title.zh_cn),
            ranking_comparison=comparison,
        )
    selected = descriptor.default_metric_id
    if selected is None and len(descriptor.metrics) == 1:
        selected = descriptor.metrics[0].id
    if selected is None:
        raise ValueError("dataset declares multiple metrics; specify --metric")
    metric = next(metric for metric in descriptor.metrics if metric.id == selected)
    chart_capability = metric.capabilities.charts.get(config.kind)
    periods = (
        chart_capability.periods
        if isinstance(chart_capability, V2HistoricalChartCapability)
        else ()
    )
    comparison = (
        chart_capability.comparison
        if isinstance(chart_capability, V2HistoricalChartCapability)
        else "full"
    )
    return replace(
        config,
        metric_id=selected,
        metric_summary=metric.summary,
        metric_periods=periods,
        metric_titles=(metric.title.en, metric.title.zh_cn),
        ranking_comparison=comparison,
    )

def apply_custom_monitor_defaults(
    config: CustomChartConfig, metric: V2MetricDescriptor
) -> tuple[CustomChartConfig, int | None]:
    """Merge safe Dataset Monitor suggestions after Metric selection."""
    defaults = metric.defaults.get("monitor")
    capability = metric.capabilities.charts.get("monitor")
    if defaults is None or not isinstance(capability, V2MonitorCapability):
        return config, None
    explicit = config.initial_explicit
    group_by = config.group_by
    if (
        "group_by" not in explicit
        and (not defaults.declared or "group_by" in defaults.declared)
        and defaults.group_by in capability.group_by
    ):
        group_by = defaults.group_by
    top = config.top
    if "top" not in explicit and defaults.top is not None and group_by is not None:
        top = defaults.top
    presentation = config.presentation
    if "color_scheme" not in explicit and defaults.theme in COLOR_SCHEMES:
        presentation = replace(presentation, theme=defaults.theme)
    if "style" not in explicit and defaults.style in compatible_styles("monitor", group_by):
        presentation = replace(presentation, style=defaults.style)
    other = (
        defaults.other
        if "other" not in explicit and defaults.other is not None and metric.aggregation == "sum"
        else config.other
    )
    window = defaults.window_seconds if "window" not in explicit else None
    return (
        replace(
            config,
            filters=config.filters,
            presentation=presentation,
            group_by=group_by,
            top=top,
            other=other,
        ),
        window,
    )
