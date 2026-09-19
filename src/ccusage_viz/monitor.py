from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from shutil import get_terminal_size

from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    wrap_command,
)
from ccusage_viz.data_view import BodyView, next_body_view, render_monitor_data
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import (
    FixedIntervalScheduler,
    LifecycleOperation,
    LifecycleTrigger,
    OperationToken,
    QueryTrigger,
    query_trigger,
)
from ccusage_viz.monitor_component import MonitorComponent, MonitorSubmission
from ccusage_viz.options import MonitorConfig, StandaloneLaunch, adjust_standalone
from ccusage_viz.render.base import RenderContext
from ccusage_viz.terminal import FramePainter, Terminal, compose_frame, inspect_terminal
from ccusage_viz.terminal_ui import controls_line, input_mode, read_key


def run_monitor(options: StandaloneLaunch, translator: Translator) -> int:
    if not isinstance(options.chart, MonitorConfig):
        raise TypeError("monitor runtime requires a monitor configuration")
    if options.chart.window_seconds is None or options.host.interval is None:
        raise UsageError(
            "error.arguments", detail="monitor requires an observation window and interval"
        )

    runtime = build_query_runtime()
    component = MonitorComponent(
        options,
        registry=build_chart_registry(),
        owner_id="standalone:monitor",
        runtime=runtime,
    )
    screen = FramePainter()
    started_at = time.monotonic()
    scheduler = FixedIntervalScheduler(options.host.interval, now=started_at)
    lifecycle: LifecycleOperation[MonitorSubmission] = LifecycleOperation("standalone:monitor")
    controls_hidden = False
    body_view: BodyView = "chart"
    demo_ordinal = 0
    status = translator.text("status.loading")
    last_size: tuple[int, int] | None = None

    def monitor_chart(config: StandaloneLaunch) -> MonitorConfig:
        if not isinstance(config.chart, MonitorConfig):
            raise TypeError("monitor runtime requires a monitor configuration")
        return config.chart

    def terminal_for(config: StandaloneLaunch) -> Terminal:
        return inspect_terminal(
            config.chart.kind,
            no_color=config.chart.presentation.theme == "no-color",
            ascii=config.host.ascii,
            size=get_terminal_size(),
        )

    def buckets(now: float, terminal: Terminal):
        return component.observer.buckets(
            component.observer.display_now(now),
            max(8, min(32, terminal.width // 4)),
            datetime.now().astimezone(),
        )

    def render_component(
        target: MonitorComponent,
        config: StandaloneLaunch,
        terminal: Terminal,
        *,
        control_rows: int,
    ) -> str:
        context = RenderContext(
            terminal.width,
            max(1, terminal.height - control_rows),
            translator,
            color=terminal.color,
            ascii=terminal.ascii,
            color_scheme=config.chart.presentation.theme,
            style=config.chart.presentation.style,
            legend_position=config.chart.presentation.legend,
            deltas=target.deltas,
            rank_deltas=target.rank_deltas,
            title_content=translator.text(f"label.{monitor_chart(config).by or 'total'}"),
        )
        return target.render(
            context,
            now=time.monotonic(),
            count=max(8, min(32, terminal.width // 4)),
            wall=datetime.now().astimezone(),
        )

    def paint(*, force: bool = False) -> None:
        nonlocal last_size
        config = component.accepted_options or component.candidate
        terminal = terminal_for(config)
        last_size = (terminal.width, terminal.height)
        controls = (
            ()
            if controls_hidden
            else controls_line(
                translator.text(
                    {
                        "chart": "status.monitor_controls",
                        "command": "status.monitor_command_controls",
                        "full-command": "status.monitor_full_command_controls",
                        "data-table": "status.monitor_data_table_controls",
                        "data-json": "status.monitor_data_json_controls",
                    }[body_view]
                ),
                width=terminal.width,
                color=terminal.color,
            )
        )
        now = time.monotonic()
        try:
            if component.error is not None:
                body = (
                    format_error(
                        component.error,
                        translator,
                        color=terminal.color,
                        color_scheme=config.chart.presentation.theme,
                    )
                    if isinstance(component.error, UsageError)
                    else str(component.error)
                )
            elif body_view == "chart":
                body = render_component(
                    component,
                    config,
                    terminal,
                    control_rows=0 if controls_hidden else 2,
                )
            elif body_view == "command":
                body = wrap_command(format_command(config), terminal.width)
            elif body_view == "full-command":
                body = format_full_command_display(format_full_command(config), terminal.width)
            else:
                body = render_monitor_data(
                    buckets(now, terminal),
                    by=monitor_chart(config).by,
                    translator=translator,
                    terminal=terminal,
                    view=body_view,
                )
            screen.paint(compose_frame(body, status, controls, height=terminal.height), force=force)
        except UsageError as exc:
            screen.paint(
                compose_frame(
                    format_error(
                        exc,
                        translator,
                        color=False,
                        color_scheme=config.chart.presentation.theme,
                    ),
                    status,
                    controls,
                    height=terminal.height,
                ),
                force=force,
            )

    def pick_appearance() -> bool:
        current = component.candidate
        candidate = current
        adjustment_page = "quick"
        copied_status: str | None = None

        def paint_picker() -> None:
            preview = component.preview(candidate)
            terminal = terminal_for(candidate)
            chart = monitor_chart(candidate)
            mode = translator.text(
                {
                    None: "label.monitor_total_mode",
                    "agent": "label.monitor_agent_mode",
                    "model": "label.monitor_model_mode",
                    "project": "label.monitor_project_mode",
                }[chart.by]
            )
            top = str(chart.top) if chart.top is not None else translator.text("label.monitor_all")
            window = (
                f"{chart.window_seconds // 3600}h"
                if chart.window_seconds % 3600 == 0
                else f"{chart.window_seconds // 60}m"
            )
            values = (
                {
                    "window": window,
                    "interval": f"{candidate.host.interval:g}",
                    "mode": mode,
                    "top": top,
                    "theme": chart.presentation.theme,
                    "style": chart.presentation.style,
                }
                if adjustment_page == "quick"
                else {
                    "legend_position": translator.text(
                        f"label.legend_{chart.presentation.legend.replace('-', '_')}"
                    )
                }
            )
            adjustment_state = controls_line(
                " · ".join(
                    part
                    for part in (
                        translator.text(f"status.monitor_adjust_{adjustment_page}", **values),
                        copied_status,
                    )
                    if part is not None
                ),
                width=terminal.width,
                color=terminal.color,
            )
            key_help = controls_line(
                translator.text(f"status.monitor_adjust_{adjustment_page}_keys"),
                width=terminal.width,
                color=terminal.color,
            )
            screen.paint(
                compose_frame(
                    render_component(preview, candidate, terminal, control_rows=2),
                    translator.text("status.tui_adjust_monitor"),
                    (adjustment_state, key_help),
                    height=terminal.height,
                )
            )

        paint_picker()
        while True:
            key = read_key(0.1)
            if key == "\x03":
                raise KeyboardInterrupt
            if key == "\x1b":
                return False
            if key in {"y", "Y"}:
                copied_status = (
                    translator.text("status.command_copied")
                    if copy_command(format_command(candidate))
                    else translator.text("status.command_copy_failed")
                )
            elif key in {"\r", "\n"}:
                current_chart = monitor_chart(current)
                candidate_chart = monitor_chart(candidate)
                data_affecting = (
                    current_chart.by,
                    current_chart.filters,
                    current_chart.window_seconds,
                    current.host.interval,
                ) != (
                    candidate_chart.by,
                    candidate_chart.filters,
                    candidate_chart.window_seconds,
                    candidate.host.interval,
                )
                component.configure(candidate, data_affecting=data_affecting)
                return data_affecting
            elif key in {"a", "A"}:
                adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
            elif (
                adjustment_page == "quick"
                and key
                in {
                    "s",
                    "S",
                    "t",
                    "T",
                    "b",
                    "B",
                    "w",
                    "W",
                    "i",
                    "I",
                    "+",
                    "=",
                    "-",
                    "_",
                }
                or adjustment_page == "advanced"
                and key in {"l", "L"}
            ):
                candidate = adjust_standalone(candidate, key)
            else:
                continue
            paint_picker()

    def start(operation: OperationToken) -> tuple[MonitorSubmission, Callable[[], None]]:
        submission = component.submit(
            query_trigger(operation.trigger),
            sample_ordinal=demo_ordinal + 1,
        )
        return submission, submission.cancel

    def report_start_failure(exc: BaseException) -> None:
        nonlocal status
        component.fail(exc, generation=component.generation)
        status = translator.text(
            "status.monitor_source",
            source=str(exc),
            interval=f"{component.candidate.host.interval:g}",
            state=(f" · {translator.text('status.paused')}" if lifecycle.paused else ""),
        ).rstrip(" ·")

    def start_ready(now: float) -> bool:
        try:
            return lifecycle.start_ready(now=now, start=start)
        except BaseException as exc:
            report_start_failure(exc)
            return False

    def request(
        trigger: LifecycleTrigger,
        *,
        now: float,
        replace_active: bool = False,
    ) -> bool:
        try:
            return lifecycle.request(
                trigger,
                generation=component.generation,
                now=now,
                replace_active=replace_active,
                start=start,
            )
        except BaseException as exc:
            report_start_failure(exc)
            return False

    try:
        if options.host.demo_size:
            demo_steps = min(24, max(8, options.chart.window_seconds))
            demo_now = time.monotonic()
            demo_wall = datetime.now().astimezone()
            demo_seconds = options.chart.window_seconds / max(1, demo_steps - 1)
            for ordinal in range(1, demo_steps + 1):
                submission = component.submit(QueryTrigger.STARTUP, sample_ordinal=ordinal)
                completion = submission.result()
                component.accept(
                    completion,
                    now=demo_now - (demo_steps - ordinal) * demo_seconds,
                    wall=demo_wall - timedelta(seconds=(demo_steps - ordinal) * demo_seconds),
                    detect_gap=False,
                )
                demo_ordinal = ordinal
            scheduler.rebuild(component.candidate.host.interval, now=demo_now)
        else:
            request(LifecycleTrigger.STARTUP, now=started_at)

        with input_mode():
            paint()
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                now = time.monotonic()
                if scheduler.due(now=now):
                    started = request(LifecycleTrigger.PERIODIC, now=now)
                    if started:
                        status = translator.text(
                            "status.monitor_sampling",
                            seconds=(
                                f"{component.last_elapsed:.2f}"
                                if component.last_elapsed is not None
                                else "…"
                            ),
                            interval=f"{component.candidate.host.interval:g}",
                        )
                    if started or component.error is not None:
                        paint()
                completed = lifecycle.take_completed(lambda submission: submission.handle.done())
                if completed is not None:
                    operation, submission = completed
                    current = lifecycle.accepts(
                        operation,
                        generation=submission.generation,
                    )
                    try:
                        completion = submission.result()
                        accepted = current and component.accept(
                            completion,
                            now=time.monotonic(),
                            wall=datetime.now().astimezone(),
                        )
                        if accepted:
                            lifecycle.complete(
                                operation,
                                generation=submission.generation,
                            )
                            demo_ordinal += 1
                            source = (
                                "DEMO DATA"
                                if completion.options.host.demo_size
                                else f"ccusage {completion.elapsed:.2f}s"
                            )
                            status = translator.text(
                                "status.monitor_source",
                                source=source,
                                interval=f"{component.candidate.host.interval:g}",
                                state=(
                                    f" · {translator.text('status.paused')}"
                                    if lifecycle.paused
                                    else ""
                                ),
                            ).rstrip(" ·")
                        elif current:
                            lifecycle.abandon(operation)
                    except BaseException as exc:
                        if current:
                            lifecycle.abandon(operation)
                            component.fail(exc, generation=submission.generation)
                            status = translator.text(
                                "status.monitor_source",
                                source=str(exc),
                                interval=f"{component.candidate.host.interval:g}",
                                state=(
                                    f" · {translator.text('status.paused')}"
                                    if lifecycle.paused
                                    else ""
                                ),
                            ).rstrip(" ·")
                    paint()
                    start_ready(time.monotonic())
                key = read_key(0.05)
                if key == "\x03":
                    raise KeyboardInterrupt
                if key == "r":
                    if not request(
                        LifecycleTrigger.MANUAL,
                        now=time.monotonic(),
                        replace_active=True,
                    ):
                        paint()
                elif key in {"h", "H"}:
                    controls_hidden = not controls_hidden
                    paint(force=True)
                elif key in {"v", "V"}:
                    body_view = next_body_view(body_view)
                    paint(force=True)
                elif key in {"y", "Y"} and body_view != "chart":
                    config = component.accepted_options or component.candidate
                    terminal = terminal_for(config)
                    copied = (
                        format_command(config)
                        if body_view == "command"
                        else format_full_command(config)
                        if body_view == "full-command"
                        else render_monitor_data(
                            buckets(time.monotonic(), terminal),
                            by=monitor_chart(config).by,
                            translator=translator,
                            terminal=terminal,
                            view=body_view,
                            complete=True,
                        )
                    )
                    copied_successfully = copy_command(copied)
                    status = translator.text(
                        "status.command_copied"
                        if copied_successfully and body_view in {"command", "full-command"}
                        else "status.data_copied"
                        if copied_successfully
                        else "status.command_copy_failed"
                    )
                    paint()
                elif key in {"m", "M"} and body_view == "chart":
                    previous_interval = component.candidate.host.interval
                    data_affecting = pick_appearance()
                    if data_affecting:
                        now = time.monotonic()
                        if component.candidate.host.interval != previous_interval:
                            scheduler.rebuild(component.candidate.host.interval, now=now)
                        request(LifecycleTrigger.CONFIGURATION, now=now)
                    paint()
                elif key == " ":
                    resumed = False
                    if not lifecycle.paused:
                        scheduler.pause()
                        lifecycle.pause()
                        component.pause()
                    else:
                        now = time.monotonic()
                        lifecycle.resume()
                        scheduler.resume(now=now)
                        component.resume(now=now, wall=datetime.now().astimezone())
                        resumed = request(LifecycleTrigger.RESUME, now=now)
                    if lifecycle.paused or resumed:
                        status = translator.text(
                            "status.monitor_paused",
                            source=(
                                f"ccusage {component.last_elapsed:.2f}s"
                                if component.last_elapsed is not None
                                else "ccusage …"
                            ),
                            interval=f"{component.candidate.host.interval:g}",
                            state=(
                                f" · {translator.text('status.paused')}" if lifecycle.paused else ""
                            ),
                        )
                    paint()
    except KeyboardInterrupt:
        return 0
    finally:
        scheduler.shutdown()
        lifecycle.shutdown()
        runtime.cancel()
        screen.finish()
