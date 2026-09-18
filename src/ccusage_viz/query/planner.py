from __future__ import annotations

from ccusage_viz.coverage import DateInterval
from ccusage_viz.options import MonitorConfig, StandaloneLaunch
from ccusage_viz.query.models import (
    DataResolution,
    DataScope,
    ExecutionContext,
    PhysicalPlan,
    QueryIntent,
    QueryTrigger,
)
from ccusage_viz.query.provider import ProviderCompiler


def plan_queries(options: StandaloneLaunch, compiler: ProviderCompiler) -> PhysicalPlan:
    """Compile provider-neutral intent through an injected provider compiler."""
    chart = options.chart
    if isinstance(chart, MonitorConfig):
        raise TypeError("historical query planning does not support monitor configurations")
    coverage = DateInterval(chart.date_range.since, chart.date_range.until)
    project_required = bool(chart.filters.projects) or getattr(chart, "by", None) == "project"
    available_options = {
        "chart_kind": chart.kind,
        "demo_size": options.host.demo_size,
    }
    execution_options = tuple(
        (key, available_options[key])
        for key in sorted(compiler.capabilities.execution_options)
        if available_options.get(key) is not None
    )
    execution_context = (
        None
        if compiler.capabilities.in_process
        else ExecutionContext(
            options.process.ccusage_bin,
            options.process.query_timeout,
            options.process.output_limit,
            options.process.environment,
        )
    )
    intent = QueryIntent(
        owner_id="legacy-standalone",
        generation=0,
        trigger=QueryTrigger.STARTUP,
        provider=compiler.provider,
        scope=DataScope((coverage,), chart.date_range.timezone),
        missing_intervals=(coverage,),
        resolution=DataResolution.DATE,
        dimensions=("project",) if project_required else ("agent",),
        execution_options=execution_options,
        execution_context=execution_context,
    )
    return compiler.compile(intent)
