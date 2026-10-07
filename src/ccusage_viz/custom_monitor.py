"""Standalone runner for source-owned Dataset V2 Monitor Metrics."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ccusage_viz.acquisition import custom_v2_monitor_query_intent, custom_v2_probe_query_intent
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.custom_models import V2MonitorCapability
from ccusage_viz.custom_monitor_component import CustomMonitorCompletion, CustomMonitorComponent, resolve_metric
from ccusage_viz.custom_protocol import V2MonitorResponse, V2ProbeResponse
from ccusage_viz.diagnostics import format_error
from ccusage_viz.formatting import center_text, format_tokens
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation, LifecycleTrigger, OperationToken, query_trigger
from ccusage_viz.options import CustomChartConfig, StandaloneLaunch
from ccusage_viz.query.models import ProviderResult
from ccusage_viz.terminal import FramePainter, Terminal, compose_frame, inspect_terminal
from ccusage_viz.terminal_ui import read_key


def _metric_capability(probe: V2ProbeResponse, config: CustomChartConfig) -> V2MonitorCapability:
    metric = next((item for item in probe.descriptor.metrics if item.id == config.metric_id), None)
    if metric is None:
        raise ValueError("runtime probe does not declare selected metric")
    capability = metric.capabilities.charts.get("monitor")
    if not isinstance(capability, V2MonitorCapability):
        raise ValueError("runtime probe does not support monitor for selected metric")
    return capability


def _render(component: CustomMonitorComponent, capability: V2MonitorCapability, translator: Translator, terminal: Terminal, interval: float) -> str:
    config = component.candidate
    response = component.accepted_response
    title = config.metric_id or config.source.dataset_id
    heading = center_text(f"{title} · {capability.window_seconds}s", terminal.width)
    if response is None:
        detail = format_error(component.error, translator, color=False) if component.error else translator.text("status.querying")
        return f"{heading}\n{detail}"
    observation = response.observation
    rows = [heading, f"Total  {format_tokens(round(float(observation.total)))}"]
    for group in sorted(observation.groups, key=lambda item: (-item.value, item.id)):
        label = group.label.zh_cn if translator.language == "zh" else group.label.en
        rows.append(f"{label}  {format_tokens(round(float(group.value)))}")
    if capability.refresh_interval_seconds is not None and capability.refresh_interval_seconds != int(interval):
        rows.append(
            f"{translator.text('status.refresh_every', seconds=f'{interval:g}')} · "
            f"Dataset {capability.refresh_interval_seconds}s"
        )
    return "\n".join(rows)


def run_custom_monitor(options: StandaloneLaunch, translator: Translator) -> int:
    if not isinstance(options.chart, CustomChartConfig) or options.chart.kind != "monitor":
        raise TypeError("custom monitor runner requires a custom monitor chart")
    if options.host.timezone is None:
        raise RuntimeError("custom monitor requires a resolved timezone")
    runtime = build_query_runtime()
    component = CustomMonitorComponent(options.chart)
    lifecycle: LifecycleOperation = LifecycleOperation("standalone:custom-monitor")
    scheduler = FixedIntervalScheduler(options.host.interval, now=time.monotonic())
    screen = FramePainter(sys.stdout)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccusage-viz-custom-monitor")
    probe: V2ProbeResponse | None = None
    capability: V2MonitorCapability | None = None

    def submit(operation: OperationToken):
        nonlocal probe, capability
        if probe is None:
            intent = custom_v2_probe_query_intent(component.candidate.source, owner_id=operation.owner_id, generation=operation.generation, trigger=query_trigger(operation.trigger), process=options.process)
        else:
            intent = custom_v2_monitor_query_intent(component.candidate, timezone=options.host.timezone, owner_id=operation.owner_id, generation=operation.generation, trigger=query_trigger(operation.trigger), end_at=datetime.now().astimezone(), process=options.process)
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
                component.configure(resolve_metric(component.candidate, probe.descriptor), data_affecting=False)
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
            component.accept(CustomMonitorCompletion(operation.generation, component.candidate, response), accepted_at=datetime.now().astimezone())
            lifecycle.complete(operation, generation=operation.generation)
        except BaseException as error:
            component.fail(error, generation=operation.generation)
            lifecycle.complete(operation, generation=operation.generation)

    try:
        lifecycle.request(LifecycleTrigger.STARTUP, generation=0, now=time.monotonic(), start=submit)
        while True:
            completed = lifecycle.take_completed(lambda future: future.done())
            if completed is not None:
                complete(*completed)
            if probe is not None and scheduler.due(now=time.monotonic()):
                component.generation += 1
                lifecycle.request(LifecycleTrigger.PERIODIC, generation=component.generation, now=time.monotonic(), start=submit)
            terminal = inspect_terminal("monitor", stream=sys.stdout, ascii=options.host.ascii)
            body = _render(component, capability, translator, terminal, options.host.interval) if capability is not None else translator.text("status.querying")
            screen.paint(compose_frame(body, "ccuv", "Ctrl-C exit · r refresh", (), height=terminal.height))
            key = read_key(0.1)
            if key == "\x03":
                return 0
            if key == "r" and probe is not None:
                component.generation += 1
                lifecycle.request(LifecycleTrigger.MANUAL, generation=component.generation, now=time.monotonic(), replace_active=True, start=submit)
    finally:
        lifecycle.shutdown()
        scheduler.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)
        runtime.cancel()
        screen.finish()
