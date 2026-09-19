from __future__ import annotations

from datetime import date, timedelta

from ccusage_viz.core.time import today_for_timezone
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


def monitor_query_intent(
    options: StandaloneLaunch,
    definition: ProviderDefinition,
    *,
    owner_id: str,
    generation: int,
    trigger: QueryTrigger,
    sample_ordinal: int = 0,
    today: date | None = None,
) -> QueryIntent:
    """Compose one complete cumulative Monitor sample request."""
    chart = options.chart
    if not isinstance(chart, MonitorConfig):
        raise TypeError("monitor query planning requires a monitor configuration")
    provider = definition.provider
    current_day = today_for_timezone(options.host.timezone, today)
    scope_interval = DateInterval(current_day - timedelta(days=1), current_day)
    project_required = bool(chart.filters.projects) or chart.by == "project"
    available_options = {
        "chart_kind": chart.kind,
        "demo_size": options.host.demo_size,
        "sample_ordinal": sample_ordinal,
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
        scope=DataScope((scope_interval,), options.host.timezone),
        missing_intervals=(scope_interval,),
        resolution=DataResolution.DATE,
        dimensions=("project",) if project_required else ("agent",),
        execution_options=execution_options,
        execution_context=execution_context,
    )


def historical_query_intent(
    options: StandaloneLaunch,
    definition: ProviderDefinition,
    *,
    owner_id: str,
    generation: int,
    trigger: QueryTrigger,
    coverage: DateCoverage | None = None,
    required_coverage: DateCoverage | None = None,
) -> QueryIntent:
    """Compose one historical Host request into provider-neutral query intent."""
    chart = options.chart
    if isinstance(chart, MonitorConfig):
        raise TypeError("historical query planning does not support monitor configurations")
    provider = definition.provider
    scope_interval = DateInterval(chart.date_range.since, chart.date_range.until)
    required_coverage = required_coverage or DateCoverage((scope_interval,))
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
        scope=DataScope(required_coverage.intervals, chart.date_range.timezone),
        missing_intervals=coverage.missing_coverage(required_coverage).intervals,
        resolution=DataResolution.DATE,
        dimensions=("project",) if project_required else ("agent",),
        execution_options=execution_options,
        execution_context=execution_context,
    )
