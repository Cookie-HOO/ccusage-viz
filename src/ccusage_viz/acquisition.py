from __future__ import annotations

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.options import MonitorConfig, StandaloneLaunch
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ExecutionContext,
    QueryIntent,
    QueryTrigger,
)
from ccusage_viz.query.provider import ProviderDefinition


def historical_provider_id(options: StandaloneLaunch) -> str:
    """Resolve the configured historical data mode to its Provider ID."""
    return "demo" if options.host.demo_size else options.host.provider


def historical_query_intent(
    options: StandaloneLaunch,
    definition: ProviderDefinition,
    *,
    owner_id: str,
    generation: int,
    trigger: QueryTrigger,
    coverage: DateCoverage | None = None,
) -> QueryIntent:
    """Compose one historical Host request into provider-neutral query intent."""
    chart = options.chart
    if isinstance(chart, MonitorConfig):
        raise TypeError("historical query planning does not support monitor configurations")
    provider = definition.provider
    scope_interval = DateInterval(chart.date_range.since, chart.date_range.until)
    coverage = coverage or DateCoverage()
    project_required = bool(chart.filters.projects) or getattr(chart, "by", None) == "project"
    available_options = {
        "chart_kind": chart.kind,
        "demo_size": options.host.demo_size,
    }
    execution_options = tuple(
        (key, available_options[key])
        for key in sorted(provider.capabilities.execution_options)
        if available_options.get(key) is not None
    )
    execution_context = (
        None
        if provider.capabilities.in_process
        else ExecutionContext(
            options.process.ccusage_bin,
            options.process.query_timeout,
            options.process.output_limit,
            options.process.environment,
        )
    )
    return QueryIntent(
        owner_id=owner_id,
        generation=generation,
        trigger=trigger,
        provider=provider.provider,
        scope=DataScope((scope_interval,), chart.date_range.timezone),
        missing_intervals=coverage.missing(scope_interval),
        resolution=DataResolution.DATE,
        dimensions=("project",) if project_required else ("agent",),
        execution_options=execution_options,
        execution_context=execution_context,
    )
