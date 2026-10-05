from __future__ import annotations

import time
from datetime import date, timedelta
from typing import cast

from ccusage_viz.core.time import local_today
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.custom_protocol import CustomChartRequest, CustomSummaryRequest
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
    DashboardLaunch,
    MonitorConfig,
    ProcessConfig,
    StandaloneLaunch,
)
from ccusage_viz.processing.summaries import SummaryQueryPlan, SummaryScope, summary_query_plan
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ExecutionContext,
    ProviderRef,
    QueryIntent,
    QueryTrigger,
)
from ccusage_viz.query.provider import ProviderDefinition


def historical_provider_id(options: StandaloneLaunch) -> str:
    """Resolve the configured historical data mode to its Provider ID."""
    return "demo" if options.host.demo_size is not None else options.host.provider


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
    current_day = local_today(today)
    scope_interval = DateInterval(current_day - timedelta(days=1), current_day)
    project_required = bool(chart.filters.projects) or chart.by == "project"
    available_options = {
        "chart_kind": chart.kind,
        "demo_size": options.host.demo_size,
        "demo_seed": options.host.demo_seed,
        "demo_report_time": time.monotonic() if options.host.demo_size is not None else None,
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
        scope=DataScope((scope_interval,)),
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
    if isinstance(chart, (MonitorConfig, CustomChartConfig)):
        raise TypeError(
            "historical query planning only supports built-in historical configurations"
        )
    provider = definition.provider
    scope_interval = DateInterval(chart.date_range.since, chart.date_range.until)
    required_coverage = (
        required_coverage if required_coverage is not None else DateCoverage((scope_interval,))
    )
    coverage = coverage or DateCoverage()
    project_required = bool(chart.filters.projects) or getattr(chart, "by", None) == "project"
    available_options = {
        "chart_kind": chart.kind,
        "demo_size": options.host.demo_size,
        "demo_seed": options.host.demo_seed,
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
        scope=DataScope(required_coverage.intervals),
        missing_intervals=coverage.missing_coverage(required_coverage).intervals,
        resolution=DataResolution.DATE,
        dimensions=("project",) if project_required else ("agent",),
        execution_options=execution_options,
        execution_context=execution_context,
    )


def custom_historical_query_intent(
    config: CustomChartConfig,
    *,
    timezone: str,
    owner_id: str,
    generation: int,
    trigger: QueryTrigger,
    process: ProcessConfig | None = None,
    request_id_suffix: str = "",
) -> QueryIntent:
    """Plan one command-backed custom pane request without display-only fields."""
    process = process or ProcessConfig()
    interval = DateInterval(config.date_range.since, config.date_range.until)
    request = CustomChartRequest(
        request_id=f"{owner_id}:{generation}{request_id_suffix}",
        dataset_id=config.source.dataset_id,
        timezone=timezone,
        start_date=interval.since,
        end_date=interval.until,
        period=config.date_range.period if config.date_range.relative_until else None,
        filters=config.filters,
        group_by=config.group_by,
        granularity=config.granularity,
        command_argv=config.source.command_argv,
    )
    return QueryIntent(
        owner_id=owner_id,
        generation=generation,
        trigger=trigger,
        provider=ProviderRef("custom-command", config.source.dataset_id),
        scope=DataScope((interval,)),
        missing_intervals=(interval,),
        resolution=DataResolution.DATE,
        execution_context=ExecutionContext(
            config.source.command_argv[0],
            process.query_timeout,
            process.output_limit,
            process.environment,
        ),
        payload=request,
    )


def custom_summary_query_intent(
    source: CustomCommandSource,
    plan: SummaryQueryPlan,
    *,
    filters: tuple[tuple[str, tuple[str, ...]], ...] = (),
    timezone: str,
    owner_id: str,
    generation: int,
    trigger: QueryTrigger,
    process: ProcessConfig | None = None,
) -> QueryIntent:
    """Plan one source summary from a ccuv-resolved set of intervals."""
    process = process or ProcessConfig()
    request = CustomSummaryRequest(
        request_id=f"{owner_id}:{generation}",
        dataset_id=source.dataset_id,
        timezone=timezone,
        scope=plan.scope,
        current=plan.current,
        sequential=plan.sequential,
        year_over_year=plan.year_over_year,
        filters=filters,
        command_argv=source.command_argv,
    )
    return QueryIntent(
        owner_id=owner_id,
        generation=generation,
        trigger=trigger,
        provider=ProviderRef("custom-command", source.dataset_id),
        scope=DataScope(plan.intervals),
        missing_intervals=plan.intervals,
        resolution=DataResolution.DATE,
        execution_context=ExecutionContext(
            source.command_argv[0],
            process.query_timeout,
            process.output_limit,
            process.environment,
        ),
        payload=request,
    )


def custom_dashboard_summary_query_intent(
    source: CustomCommandSource,
    dashboard: DashboardLaunch,
    *,
    owner_id: str,
    generation: int,
    trigger: QueryTrigger,
    as_of_date: date | None = None,
) -> QueryIntent:
    """Compatibility wrapper for Dashboard callers during the protocol migration."""
    period = dashboard.host.header_summary
    if period not in {"day", "week", "month", "quarter", "year"}:
        raise ValueError("custom Dashboard summary requires a supported scope")

    timezone = dashboard.host.timezone
    if timezone is None:
        raise ValueError("custom Dashboard summary requires a timezone")
    return custom_summary_query_intent(
        source,
        summary_query_plan(local_today(as_of_date, timezone=timezone), cast(SummaryScope, period)),
        timezone=timezone,
        owner_id=owner_id,
        generation=generation,
        trigger=trigger,
        process=dashboard.process,
    )
