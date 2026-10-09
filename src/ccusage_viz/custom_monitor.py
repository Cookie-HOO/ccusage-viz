"""Standalone runner for source-owned Dataset V2 Monitor Metrics."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from ccusage_viz.acquisition import custom_v2_monitor_query_intent, custom_v2_probe_query_intent
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.custom_filter_draft import run_custom_filter_editor
from ccusage_viz.custom_models import V2MonitorCapability
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
    apply_custom_monitor_defaults,
    resolve_metric,
)
from ccusage_viz.custom_protocol import V2MonitorResponse, V2ProbeResponse
from ccusage_viz.diagnostics import format_error
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import (
    FixedIntervalScheduler,
    LifecycleOperation,
    LifecycleTrigger,
    OperationToken,
    query_trigger,
)
from ccusage_viz.options import CustomChartConfig, StandaloneLaunch
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.render.base import RenderAudit, RenderContext, render_audit
from ccusage_viz.render.custom_monitor import render_custom_monitor
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import FramePainter, Terminal, compose_frame, inspect_terminal
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows, input_mode, read_key


def _metric_capability(descriptor: object, config: CustomChartConfig) -> V2MonitorCapability:
    if isinstance(descriptor, V2ProbeResponse):
        descriptor = descriptor.descriptor
    metric = next((item for item in getattr(descriptor, "metrics", ()) if item.id == config.metric_id), None)
    if metric is None:
        raise ValueError("runtime probe does not declare selected metric")
    capability = metric.capabilities.charts.get("monitor")
    if not isinstance(capability, V2MonitorCapability):
        raise ValueError("runtime probe does not support monitor for selected metric")
    return capability


def _render(
    component: CustomMonitorComponent,
    capability: V2MonitorCapability,
    translator: Translator,
    terminal: Terminal,
    interval: float,
) -> str:
    """Use the standalone Monitor renderer with Dataset-owned facts and headings."""

    config = component.candidate
    if component.accepted_response is None:
        detail = (
            format_error(component.error, translator, color=False)
            if component.error
            else translator.text("status.querying")
        )
        return f"{component.heading(language=translator.language)}\n{detail}"
    audit = RenderAudit(component.accepted_at, interval=interval, cadence="sample")
    context = RenderContext(
        terminal.width,
        max(1, terminal.height - int(config.presentation.density == "detailed")),
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=config.presentation.theme,
        style=config.presentation.style,
        legend_position=config.presentation.legend,
        density=config.presentation.density,
        audit=audit,
    )
    rendered = render_custom_monitor(component, context)
    audit_row = render_audit(context)
    notice = (
        f"{translator.text('status.refresh_every', seconds=f'{interval:g}')} · "
        f"Dataset {capability.refresh_interval_seconds}s"
        if capability.refresh_interval_seconds is not None
        and capability.refresh_interval_seconds != int(interval)
        else ""
    )
    return "\n".join(line for line in (rendered, audit_row, notice) if line)


def _adjust(component: CustomMonitorComponent, key: str) -> bool:
    """Apply standalone-native Monitor appearance/group/window shortcuts."""

    chart = component.candidate
    if key in {"s", "S"}:
        from ccusage_viz.custom_monitor_component import custom_monitor_styles

        styles = custom_monitor_styles(component.aggregation, chart.group_by)
        index = styles.index(chart.presentation.style) if chart.presentation.style in styles else 0
        updated = replace(
            chart,
            presentation=replace(
                chart.presentation, style=styles[(index + (1 if key == "s" else -1)) % len(styles)]
            ),
        )
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key in {"t", "T"}:
        index = COLOR_SCHEMES.index(chart.presentation.theme)
        updated = replace(
            chart,
            presentation=replace(
                chart.presentation,
                theme=COLOR_SCHEMES[(index + (1 if key == "t" else -1)) % len(COLOR_SCHEMES)],
            ),
        )
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key == "d":
        densities = ("minimal", "compact", "detailed")
        index = densities.index(chart.presentation.density)
        updated = replace(
            chart,
            presentation=replace(
                chart.presentation, density=densities[(index + 1) % len(densities)]
            ),
        )
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key == "l":
        legends = ("below-title", "inside", "hidden")
        index = (
            legends.index(chart.presentation.legend) if chart.presentation.legend in legends else 0
        )
        updated = replace(
            chart,
            presentation=replace(chart.presentation, legend=legends[(index + 1) % len(legends)]),
        )
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key == "w":
        if chart.presentation.style == "cumulative-bars":
            component.toggle_distribution_day_window()
            return True
        windows = (300, 900, 1800, 3600, 21600, 43200, 86400)
        current = min(windows, key=lambda value: abs(value - component.display_window_seconds))
        component.configure_display_window(windows[(windows.index(current) + 1) % len(windows)])
        return True
    if key in {"+", "="} and chart.group_by is not None:
        updated = replace(chart, top=(chart.top or 0) + 1)
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key in {"-", "_"} and chart.group_by is not None:
        updated = replace(chart, top=max(1, (chart.top or 1) - 1))
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key == "o" and chart.group_by is not None and component.aggregation == "sum":
        updated = replace(chart, other="hide" if chart.other == "show" else "show")
        component.configure(updated, data_affecting=False)
        return updated != chart
    if key in {"b", "B"}:
        groups = (
            component.monitor_capability.group_by
            if component.monitor_capability is not None
            else ()
        )
        values = (None, *groups)
        current = chart.group_by if chart.group_by in values else values[0]
        updated = replace(
            chart,
            group_by=values[(values.index(current) + (1 if key == "b" else -1)) % len(values)],
        )
        component.configure(updated, data_affecting=True)
        return updated != chart
    return False


def _custom_monitor_actions(
    component: CustomMonitorComponent, page: Literal["quick", "advanced"]
) -> tuple[tuple[str, str], ...]:
    """Expose the standalone native Monitor action split with Dataset capabilities."""

    if page == "advanced":
        filters = (("f", "filters"),) if component.runtime is not None and component.runtime.filters else ()
        return (
            (*filters, *(("o", "other"), ("l", "legend")))
            if component.aggregation == "sum"
            else (*filters, ("l", "legend"))
        )
    actions: list[tuple[str, str]] = [("w", "window")]
    if component.monitor_capability is not None and component.monitor_capability.group_by:
        actions.append(("b/B", "grouping"))
    if component.candidate.group_by is not None:
        actions.append(("+/-", "top"))
    actions.extend((("d", "density"), ("t/T", "theme"), ("s/S", "style")))
    return tuple(actions)


def run_custom_monitor(options: StandaloneLaunch, translator: Translator) -> int:
    if not isinstance(options.chart, CustomChartConfig) or options.chart.kind != "monitor":
        raise TypeError("custom monitor runner requires a custom monitor chart")
    if options.host.timezone is None:
        raise RuntimeError("custom monitor requires a resolved timezone")
    runtime = build_query_runtime()
    component = CustomMonitorComponent(options.chart)
    component.configure_display_timezone(ZoneInfo(options.host.timezone))
    component.start_monitoring(datetime.now(ZoneInfo(options.host.timezone)))
    lifecycle: LifecycleOperation = LifecycleOperation("standalone:custom-monitor")
    scheduler = FixedIntervalScheduler(options.host.interval, now=time.monotonic())
    screen = FramePainter(sys.stdout)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-custom-monitor")
    probe: V2ProbeResponse | None = None
    capability: V2MonitorCapability | None = None

    def submit(operation: OperationToken):
        nonlocal probe, capability
        if probe is None:
            intent = custom_v2_probe_query_intent(
                component.candidate.source,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=options.process,
            )
        else:
            intent = custom_v2_monitor_query_intent(
                component.candidate,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                end_at=datetime.now().astimezone(),
                process=options.process,
            )
        handle = runtime.submit(intent)
        return executor.submit(lambda: handle.result()), handle.cancel

    def complete(operation: OperationToken, future) -> None:
        nonlocal probe, capability
        try:
            result: ProviderResult = future.result()
            response = result.custom_response
            if probe is None:
                if not isinstance(response, V2ProbeResponse):
                    raise RuntimeError("custom monitor requires a V2 probe response")
                probe = response
                resolved = resolve_metric(component.candidate, probe.descriptor)
                metric = next(
                    item
                    for item in probe.descriptor.metrics
                    if item.id == resolved.metric_id
                )
                resolved, display_window = apply_custom_monitor_defaults(resolved, metric)
                component.configure(resolved, data_affecting=False)
                component.set_metric(metric)
                if display_window is not None:
                    component.configure_display_window(display_window)
                capability = _metric_capability(probe, component.candidate)
                lifecycle.complete(operation, generation=operation.generation)
                lifecycle.request(
                    LifecycleTrigger.STARTUP,
                    generation=component.generation,
                    now=time.monotonic(),
                    start=submit,
                )
                return
            if not isinstance(response, V2MonitorResponse):
                raise RuntimeError("custom monitor query did not return an observation")
            component.accept(
                CustomMonitorCompletion(operation.generation, component.candidate, response),
                accepted_at=datetime.now().astimezone(),
            )
            capability = _metric_capability(response.descriptor, component.candidate)
            lifecycle.complete(operation, generation=operation.generation)
        except BaseException as error:
            component.fail(error, generation=operation.generation)
            lifecycle.complete(operation, generation=operation.generation)

    try:
        lifecycle.request(
            LifecycleTrigger.STARTUP, generation=0, now=time.monotonic(), start=submit
        )
        while True:
            completed = lifecycle.take_completed(lambda future: future.done())
            if completed is not None:
                complete(*completed)
            if probe is not None and scheduler.due(now=time.monotonic()):
                component.generation += 1
                lifecycle.request(
                    LifecycleTrigger.PERIODIC,
                    generation=component.generation,
                    now=time.monotonic(),
                    start=submit,
                )
            terminal = inspect_terminal("monitor", stream=sys.stdout, ascii=options.host.ascii)
            body = (
                _render(component, capability, translator, terminal, options.host.interval)
                if capability is not None
                else translator.text("status.querying")
            )
            controls = "r refresh · m adjust · Ctrl-C exit"
            screen.paint(compose_frame(body, "ccuv", controls, (), height=terminal.height))
            with input_mode():
                key = read_key(0.1)
            if key == "\x03":
                return 0
            if key == "r" and probe is not None:
                component.generation += 1
                lifecycle.request(
                    LifecycleTrigger.MANUAL,
                    generation=component.generation,
                    now=time.monotonic(),
                    replace_active=True,
                    start=submit,
                )
            if key == "m" and probe is not None:
                page: Literal["quick", "advanced"] = "quick"
                while True:
                    action_rows = _custom_monitor_actions(component, page)
                    screen.paint(
                        compose_frame(
                            body,
                            translator.text("status.tui_adjust_monitor"),
                            adjustment_rows(
                                component.heading(language=translator.language),
                                translator.text(f"adjustment.page_{page}"),
                                tuple(
                                    AdjustmentAction(
                                        action_key,
                                        translator.text(f"adjustment.{label}"),
                                        priority,
                                    )
                                    for priority, (action_key, label) in enumerate(action_rows)
                                ),
                                width=terminal.width,
                                color=terminal.color,
                                switch_action=translator.text(
                                    "adjustment.switch_advanced"
                                    if page == "quick"
                                    else "adjustment.switch_quick"
                                ),
                                finish_action=translator.text("adjustment.finish"),
                            ),
                            height=terminal.height,
                        )
                    )
                    adjusted = read_key(5)
                    if adjusted in {None, "\x1b", "\r", "\n"}:
                        break
                    if adjusted == "a":
                        page = "advanced" if page == "quick" else "quick"
                        continue
                    if (
                        adjusted == "f"
                        and page == "advanced"
                        and component.runtime is not None
                        and component.runtime.filters
                    ):
                        filter_height = terminal.height

                        def paint_filter_editor(
                            body: str, controls: str, *, height: int = filter_height
                        ) -> None:
                            screen.paint(
                                compose_frame(
                                    body,
                                    translator.text("label.adjust_filters"),
                                    controls,
                                    height=height,
                                )
                            )

                        edited = run_custom_filter_editor(
                            component.candidate.filters,
                            component.runtime.filters,
                            translator,
                            width=terminal.width,
                            paint=paint_filter_editor,
                            read_key=lambda: read_key(5),
                        )
                        if edited is not None and edited != component.candidate.filters:
                            component.configure(
                                replace(component.candidate, filters=edited), data_affecting=True
                            )
                            lifecycle.request(
                                LifecycleTrigger.CONFIGURATION,
                                generation=component.generation,
                                now=time.monotonic(),
                                replace_active=True,
                                start=submit,
                            )
                        continue
                    if adjusted in {"b", "B"} and _adjust(component, adjusted):
                        lifecycle.request(
                            LifecycleTrigger.CONFIGURATION,
                            generation=component.generation,
                            now=time.monotonic(),
                            replace_active=True,
                            start=submit,
                        )
                    elif adjusted in {key for binding, _label in action_rows for key in binding}:
                        _adjust(component, adjusted)
    finally:
        lifecycle.shutdown()
        scheduler.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)
        runtime.cancel()
        screen.finish()
