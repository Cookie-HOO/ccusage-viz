from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, replace
from shutil import get_terminal_size

from ccusage_viz.bootstrap import build_chart_registry, build_query_runtime
from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    wrap_command,
)
from ccusage_viz.core.time import refresh_date_range
from ccusage_viz.data_view import BodyView, next_body_view, render_snapshot_data
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.errors import QueryError, UsageError
from ccusage_viz.filter_draft import discover_filter_choices, run_filter_editor
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalPurpose,
    HistoricalSubmission,
    UsageSnapshot,
)
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import (
    FixedIntervalScheduler,
    LifecycleOperation,
    LifecycleTrigger,
    OperationToken,
    query_trigger,
)
from ccusage_viz.options import (
    HistoricalChartConfig,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
    compatible_styles,
    replace_chart_filters,
)
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import FramePainter, Terminal, compose_frame, inspect_terminal
from ccusage_viz.terminal_ui import controls_line, dimmed, input_mode, notice_lines, read_key
from ccusage_viz.tui_input import InputDecoder, KeyEvent, read_event


@dataclass(frozen=True, slots=True)
class RefreshResult:
    chart: str
    notices: tuple[str, ...]
    elapsed: float
    snapshot: UsageSnapshot | None = None
    options: StandaloneLaunch | None = None


@dataclass(frozen=True, slots=True)
class RuntimeAdjustmentResult:
    options: StandaloneLaunch
    seed: RefreshResult


_ADJUSTMENT_QUICK_KEYS = {
    "timeline": frozenset("dpPgbB+-=tTsS"),
    "calendar": frozenset("dpPtTsS"),
    "stack": frozenset("dpPgtTsS"),
    "ranking": frozenset("dpPbB+-=tTsS"),
}
_ADJUSTMENT_ADVANCED_KEYS = {
    "timeline": frozenset("olkOLK"),
    "calendar": frozenset(),
    "stack": frozenset("clkCLK"),
    "ranking": frozenset("oO"),
}


def _adjustment_key_supported(command: str, page: str, key: str) -> bool:
    keys = _ADJUSTMENT_QUICK_KEYS if page == "quick" else _ADJUSTMENT_ADVANCED_KEYS
    return key in keys[command]


def _require_complete_coverage(submission: HistoricalSubmission, snapshot: UsageSnapshot) -> None:
    if snapshot.coverage.missing_coverage(submission.requested_coverage).intervals:
        raise QueryError("error.incomplete_coverage")


def render_component(
    component: HistoricalChartComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
    hide_upper_right_axes: bool = False,
    ranking_deltas: Mapping[Hashable, float] | None = None,
    ranking_rank_deltas: Mapping[Hashable, int] | None = None,
    normalize_titles: bool = False,
) -> RefreshResult:
    snapshot = component.snapshot
    options = component.accepted_options
    if snapshot is None or options is None:
        raise RuntimeError("historical component has no accepted snapshot")
    rendered = render_historical_component(
        component,
        translator,
        terminal,
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
        hide_upper_right_axes=hide_upper_right_axes,
        ranking_deltas=ranking_deltas,
        ranking_rank_deltas=ranking_rank_deltas,
        normalize_titles=normalize_titles,
        interval=options.host.interval,
    )
    return RefreshResult(
        rendered.chart,
        rendered.notices,
        snapshot.elapsed,
        snapshot,
        options,
    )


def _paint(
    body: str,
    status: str,
    controls: str | tuple[str, ...],
    notices: tuple[str, ...] = (),
    *,
    height: int | None = None,
) -> None:
    FramePainter(sys.stdout).paint(compose_frame(body, status, controls, notices, height=height))


def _refreshing_status(status: str, translator: Translator, *, color: bool) -> str:
    refreshing = dimmed(translator.text("status.refreshing"), color=color)
    return f"{status} · {refreshing}"


def _watch_status(
    base: str,
    translator: Translator,
    *,
    interval: float,
    paused: bool,
    running: bool,
    color: bool,
) -> str:
    suffix = (
        translator.text("status.paused")
        if paused
        else translator.text("status.refresh_every", seconds=f"{interval:g}")
    )
    parts = [base, suffix]
    if running:
        parts.append(dimmed(translator.text("status.refreshing"), color=color))
    return " · ".join(parts)


def run_runtime_adjustment(
    options: StandaloneLaunch,
    translator: Translator,
    snapshot: UsageSnapshot,
    screen: FramePainter,
) -> RuntimeAdjustmentResult | None:
    theme_index = COLOR_SCHEMES.index(options.chart.presentation.theme)
    last_size: os.terminal_size | None = None
    current = options
    component = HistoricalChartComponent(
        current,
        owner_id="standalone:adjustment",
        runtime=None,
        registry=build_chart_registry(),
    )
    component.seed(current, snapshot)
    rendered: RefreshResult | None = None
    rendered_options: StandaloneLaunch | None = None
    render_warning: str | None = None
    copied_status: str | None = None
    adjustment_page = "quick"

    def grouping_choices() -> tuple[str, ...]:
        if current.chart.kind == "timeline":
            return ("total", "agent", "model", "project")
        if current.chart.kind == "ranking":
            return ("agent", "model", "project")
        return ()

    def paint() -> None:
        nonlocal current, last_size, rendered, rendered_options, render_warning
        theme = COLOR_SCHEMES[theme_index]
        styles = compatible_styles(current.chart.kind, getattr(current.chart, "by", None))
        style = (
            current.chart.presentation.style
            if current.chart.presentation.style in styles
            else styles[0]
        )
        current = replace(
            current,
            chart=replace(
                current.chart,
                presentation=replace(current.chart.presentation, theme=theme, style=style),
            ),
        )
        last_size = get_terminal_size()
        terminal = Terminal(
            last_size.columns,
            last_size.lines,
            current.chart.presentation.theme != "no-color",
            current.host.ascii,
        )
        try:
            terminal = inspect_terminal(
                current.chart.kind,
                no_color=current.chart.presentation.theme == "no-color",
                ascii=current.host.ascii,
                size=last_size,
            )
            component.configure(current, data_affecting=False)
            candidate = render_component(
                component,
                translator,
                terminal,
                control_rows=2,
            )
        except UsageError as exc:
            render_warning = format_error(
                exc, translator, color=terminal.color, color_scheme=current.chart.presentation.theme
            )
        else:
            rendered = candidate
            rendered_options = current
            render_warning = None
        visible = rendered
        chart = visible.chart if visible is not None else render_warning or ""
        notices = (
            (*visible.notices, render_warning)
            if visible is not None and render_warning is not None
            else visible.notices
            if visible is not None
            else ()
        )
        common = {
            "density": current.chart.presentation.density,
            "theme_index": theme_index + 1,
            "theme_count": len(COLOR_SCHEMES),
            "theme": theme,
            "style_index": styles.index(style) + 1,
            "style_count": len(styles),
            "style": style,
        }
        status_key = f"status.runtime_adjustment_{current.chart.kind}_{adjustment_page}"
        key_key = f"status.tui_adjust_{current.chart.kind}_{adjustment_page}_controls"
        state_values = dict(common)
        if isinstance(current.chart, (TimelineConfig, RankingConfig)):
            state_values.update(
                grouping=current.chart.by or translator.text("label.all"),
                top=current.chart.top
                if current.chart.top is not None
                else translator.text("label.all"),
                other=translator.text("label.on" if current.chart.other == "show" else "label.off"),
            )
        if isinstance(current.chart, (TimelineConfig, StackConfig)):
            state_values["weekday"] = translator.text(f"label.weekday_{current.chart.weekdays}")
            state_values["legend_position"] = translator.text(
                f"label.legend_{current.chart.presentation.legend.replace('-', '_')}"
            )
        if isinstance(current.chart, StackConfig):
            state_values["cache"] = translator.text(
                "label.on" if current.chart.cache == "split" else "label.off"
            )
        state = translator.messages[status_key].format(**state_values)
        project_preview_missing = (
            isinstance(current.chart, (TimelineConfig, RankingConfig))
            and current.chart.by == "project"
            and not snapshot.includes_project_attribution
        )
        preview_notice = (
            translator.text("status.project_preview_missing") if project_preview_missing else None
        )
        controls: str | tuple[str, ...] = (
            controls_line(
                " · ".join(part for part in (state, copied_status) if part is not None),
                width=terminal.width,
                color=terminal.color,
            ),
            controls_line(
                f"{translator.text(f'status.tui_adjust_{adjustment_page}')} · "
                f"{translator.messages[key_key]}",
                width=terminal.width,
                color=terminal.color,
            ),
        )
        status = " · ".join(
            part for part in (translator.text("status.tui_adjust_history"), preview_notice) if part
        )
        screen.paint(
            compose_frame(
                chart,
                status,
                controls,
                notice_lines(
                    notices,
                    width=terminal.width,
                    color=terminal.color,
                    ascii=terminal.ascii,
                    translator=translator,
                    color_scheme=theme,
                ),
                height=terminal.height,
            )
        )

    try:
        with input_mode():
            paint()
            while True:
                key = read_key(0.1)
                if get_terminal_size() != last_size:
                    paint()
                if key == "\x03":
                    raise KeyboardInterrupt
                if key == "\x1b":
                    return None
                if key in {"\r", "\n"} and rendered is not None and rendered_options == current:
                    return RuntimeAdjustmentResult(current, rendered)
                if key in {"y", "Y"}:
                    copied_status = (
                        translator.text("status.command_copied")
                        if copy_command(format_command(current))
                        else translator.text("status.command_copy_failed")
                    )
                    paint()
                elif key in {"a", "A"}:
                    adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                    paint()
                elif key is not None and _adjustment_key_supported(
                    current.chart.kind, adjustment_page, key
                ):
                    updated = adjust_standalone(current, key)
                    if updated != current:
                        current = updated
                        theme_index = COLOR_SCHEMES.index(current.chart.presentation.theme)
                        paint()
    except KeyboardInterrupt:
        return None


def run_watch(options: StandaloneLaunch, translator: Translator) -> int:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical watch mode does not support monitor configurations")
    active_screen = FramePainter(sys.stdout)
    interval = options.host.interval or 10.0
    runtime = build_query_runtime()
    current = options
    component = HistoricalChartComponent(
        current,
        owner_id="standalone",
        runtime=runtime,
        registry=build_chart_registry(),
    )
    started_at = time.monotonic()
    scheduler = FixedIntervalScheduler(interval, now=started_at)
    lifecycle: LifecycleOperation[HistoricalSubmission] = LifecycleOperation("standalone")
    controls_hidden = False
    body_view: BodyView = "chart"
    last_chart = ""
    last_notices: tuple[str, ...] = ()
    last_snapshot: UsageSnapshot | None = None
    terminal_error: UsageError | None = None
    render_warning: str | None = None
    last_size: tuple[int, int] | None = None
    base_status = translator.text("status.loading")

    def historical_chart(config: StandaloneLaunch) -> HistoricalChartConfig:
        if isinstance(config.chart, MonitorConfig):
            raise TypeError("historical watch mode does not support monitor configurations")
        return config.chart

    historical_chart(current)
    ranking_deltas = RefreshDeltas()
    ranking_ranks = RefreshRanks()
    if current.chart.kind == "ranking" and component.model is not None:
        ranking_deltas.accept(component.ranking_values())
        ranking_ranks.accept(component.ranking_keys())

    def style_enabled() -> bool:
        return color_enabled(sys.stdout, no_color=current.chart.presentation.theme == "no-color")

    def terminal_size() -> os.terminal_size:
        return get_terminal_size()

    def status() -> str:
        return _watch_status(
            base_status,
            translator,
            interval=interval,
            paused=lifecycle.paused,
            running=lifecycle.submission is not None,
            color=style_enabled(),
        )

    def controls() -> str:
        if controls_hidden:
            return ""
        keys = translator.text(
            {
                "chart": "status.keys",
                "command": "status.command_keys",
                "full-command": "status.full_command_keys",
                "data-table": "status.data_table_keys",
                "data-json": "status.data_json_keys",
            }[body_view]
        )
        if current.host.demo_size:
            keys = f"{keys} · {translator.text('status.demo_keys')}"
        return keys

    def paint(*, force: bool = False) -> None:
        nonlocal last_chart, last_notices, last_snapshot, terminal_error, render_warning, last_size
        size = terminal_size()
        last_size = (size.columns, size.lines)
        color = style_enabled()
        try:
            terminal = inspect_terminal(
                current.chart.kind,
                no_color=current.chart.presentation.theme == "no-color",
                ascii=current.host.ascii,
                size=size,
            )
        except UsageError as exc:
            terminal_error = exc
            warning = format_error(
                exc, translator, color=False, color_scheme=current.chart.presentation.theme
            )
            active_screen.paint(
                compose_frame(
                    last_chart or warning,
                    status(),
                    ()
                    if controls_hidden
                    else controls_line(controls(), width=size.columns, color=False),
                    notice_lines(
                        (*last_notices, warning) if last_chart else (),
                        width=size.columns,
                        color=False,
                        ascii=current.host.ascii,
                        translator=translator,
                        color_scheme=current.chart.presentation.theme,
                    ),
                    height=size.lines,
                ),
                force=force,
            )
            return
        terminal_error = None
        if last_snapshot is not None:
            try:
                rendered = render_component(
                    component,
                    translator,
                    terminal,
                    control_rows=0 if controls_hidden else 1,
                    ranking_deltas=ranking_deltas.current
                    if current.chart.kind == "ranking"
                    else None,
                    ranking_rank_deltas=(
                        ranking_ranks.current if current.chart.kind == "ranking" else None
                    ),
                    normalize_titles=True,
                )
            except UsageError as exc:
                render_warning = format_error(
                    exc, translator, color=color, color_scheme=current.chart.presentation.theme
                )
            else:
                last_chart = rendered.chart
                last_notices = rendered.notices
                render_warning = None
        footer = controls()
        body = (
            last_chart
            if body_view == "chart"
            else wrap_command(format_command(current), size.columns)
            if body_view == "command"
            else format_full_command_display(format_full_command(current), size.columns)
            if body_view == "full-command"
            else render_snapshot_data(
                current,
                last_snapshot,
                translator,
                terminal,
                view=body_view,
            )
        )
        active_screen.paint(
            compose_frame(
                body,
                status(),
                () if not footer else controls_line(footer, width=size.columns, color=color),
                notice_lines(
                    (*last_notices, render_warning) if render_warning is not None else last_notices,
                    width=size.columns,
                    color=color,
                    ascii=current.host.ascii,
                    translator=translator,
                    color_scheme=current.chart.presentation.theme,
                ),
                height=size.lines,
            ),
            force=force,
        )

    def operation_purpose(operation: OperationToken) -> HistoricalPurpose:
        if (
            operation.trigger is LifecycleTrigger.CONFIGURATION
            and component.snapshot is not None
            and component.accepted_generation == component.generation
            and component.missing_comparison_coverage().intervals
        ):
            return HistoricalPurpose.SUPPLEMENTAL
        return HistoricalPurpose.PRIMARY

    def start(operation: OperationToken) -> tuple[HistoricalSubmission, Callable[[], None]]:
        purpose = operation_purpose(operation)
        try:
            submission = component.submit(
                query_trigger(operation.trigger),
                coverage=(
                    component.snapshot.coverage
                    if purpose is HistoricalPurpose.SUPPLEMENTAL and component.snapshot is not None
                    else None
                ),
                purpose=purpose,
                required_coverage=(
                    component.required_coverage()
                    if not options.host.watch and purpose is HistoricalPurpose.PRIMARY
                    else None
                ),
            )
        except BaseException as exc:
            component.fail(
                exc,
                generation=component.generation,
                purpose=purpose,
            )
            raise
        return submission, submission.cancel

    def start_ready(now: float) -> bool:
        nonlocal base_status, terminal_error
        try:
            return lifecycle.start_ready(now=now, start=start)
        except BaseException as exc:
            base_status = format_error(
                exc,
                translator,
                color=style_enabled(),
                color_scheme=current.chart.presentation.theme,
            )
            if isinstance(exc, UsageError):
                terminal_error = exc
            return False

    def request(
        trigger: LifecycleTrigger,
        *,
        now: float,
        replace_active: bool = False,
        data_affecting: bool = True,
    ) -> bool:
        nonlocal base_status, terminal_error
        if data_affecting:
            candidate = component.candidate
            chart = historical_chart(candidate)
            refreshed = replace(
                candidate,
                chart=replace(chart, date_range=refresh_date_range(chart.date_range)),
            )
            component.configure(refreshed, data_affecting=True)
        try:
            return lifecycle.request(
                trigger,
                generation=component.generation,
                now=now,
                replace_active=replace_active,
                start=start,
            )
        except BaseException as exc:
            base_status = format_error(
                exc,
                translator,
                color=style_enabled(),
                color_scheme=current.chart.presentation.theme,
            )
            if isinstance(exc, UsageError):
                terminal_error = exc
            return False

    try:
        request(LifecycleTrigger.STARTUP, now=started_at)
        if not options.host.watch:
            operation = lifecycle.operation
            submission = lifecycle.submission
            if operation is None or submission is None:
                paint()
                return 1
            try:
                completion = submission.result()
                if not lifecycle.accepts(operation, generation=submission.generation):
                    return 1
                _require_complete_coverage(submission, completion.snapshot)
                if not component.accept(completion):
                    return 1
                lifecycle.complete(operation, generation=submission.generation)
                current = component.candidate
                terminal = inspect_terminal(
                    current.chart.kind,
                    no_color=current.chart.presentation.theme == "no-color",
                    ascii=current.host.ascii,
                )
                result = render_component(
                    component,
                    translator,
                    terminal,
                    reserve_prompt=True,
                    normalize_titles=True,
                )
                base_status = (
                    translator.text("status.demo", size=current.host.demo_size)
                    if current.host.demo_size
                    else translator.text("status.query_time", seconds=f"{result.elapsed:.2f}")
                )
                active_screen.paint(
                    compose_frame(
                        result.chart,
                        base_status,
                        "",
                        notice_lines(
                            result.notices,
                            width=terminal.width,
                            color=terminal.color,
                            ascii=terminal.ascii,
                            translator=translator,
                            color_scheme=current.chart.presentation.theme,
                        ),
                        height=terminal.height,
                    )
                )
                return 0
            finally:
                lifecycle.abandon(operation)

        with input_mode():
            paint()
            while True:
                size = terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                now = time.monotonic()
                if (
                    terminal_error is None
                    and scheduler.due(now=now)
                    and request(LifecycleTrigger.PERIODIC, now=now)
                ):
                    paint()

                completed = lifecycle.take_completed(lambda submission: submission.handle.done())
                if completed is not None:
                    operation, submission = completed
                    current_operation = lifecycle.accepts(
                        operation,
                        generation=submission.generation,
                    )
                    if not current_operation:
                        lifecycle.abandon(operation)
                    try:
                        outcome = submission.result()
                        if current_operation:
                            previous_options = current
                            accepted = component.accept(outcome)
                            if accepted:
                                lifecycle.complete(
                                    operation,
                                    generation=submission.generation,
                                )
                                current = component.candidate
                                last_snapshot = component.snapshot
                                if (
                                    isinstance(current.chart, RankingConfig)
                                    and last_snapshot is not None
                                ):
                                    if not isinstance(previous_options.chart, RankingConfig) or (
                                        previous_options.chart.by,
                                        previous_options.chart.top,
                                        previous_options.chart.other,
                                        previous_options.chart.filters.agents,
                                        previous_options.chart.filters.models,
                                        previous_options.chart.filters.projects,
                                        previous_options.chart.date_range,
                                    ) != (
                                        current.chart.by,
                                        current.chart.top,
                                        current.chart.other,
                                        current.chart.filters.agents,
                                        current.chart.filters.models,
                                        current.chart.filters.projects,
                                        current.chart.date_range,
                                    ):
                                        ranking_deltas.clear()
                                        ranking_ranks.clear()
                                    ranking_deltas.accept(component.ranking_values())
                                    ranking_ranks.accept(component.ranking_keys())
                                base_status = (
                                    translator.text("status.demo", size=current.host.demo_size)
                                    if current.host.demo_size
                                    else translator.text(
                                        "status.query_time",
                                        seconds=f"{outcome.snapshot.elapsed:.2f}",
                                    )
                                )
                                if (
                                    submission.purpose is HistoricalPurpose.PRIMARY
                                    and component.missing_comparison_coverage().intervals
                                ):
                                    request(
                                        LifecycleTrigger.CONFIGURATION,
                                        now=time.monotonic(),
                                        data_affecting=False,
                                    )
                            else:
                                lifecycle.abandon(operation)
                    except BaseException as exc:
                        lifecycle.abandon(operation)
                        if current_operation:
                            component.fail(
                                exc,
                                generation=submission.generation,
                                purpose=submission.purpose,
                            )
                            base_status = format_error(
                                exc,
                                translator,
                                color=style_enabled(),
                                color_scheme=current.chart.presentation.theme,
                            )
                            if isinstance(exc, UsageError):
                                terminal_error = exc
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
                    terminal = inspect_terminal(
                        current.chart.kind,
                        no_color=current.chart.presentation.theme == "no-color",
                        ascii=current.host.ascii,
                        size=terminal_size(),
                    )
                    copied = (
                        format_command(current)
                        if body_view == "command"
                        else format_full_command(current)
                        if body_view == "full-command"
                        else render_snapshot_data(
                            current,
                            last_snapshot,
                            translator,
                            terminal,
                            view=body_view,
                            complete=True,
                        )
                    )
                    copied_successfully = copy_command(copied)
                    base_status = translator.text(
                        "status.command_copied"
                        if copied_successfully and body_view in {"command", "full-command"}
                        else "status.data_copied"
                        if copied_successfully
                        else "status.command_copy_failed"
                    )
                    paint()
                elif key in {"f", "F"} and body_view == "chart" and last_snapshot is not None:
                    editor_size = terminal_size()

                    editor_width = editor_size.columns
                    editor_height = editor_size.lines

                    def paint_filter_editor(
                        body: str,
                        editor_controls: str,
                        *,
                        width: int = editor_width,
                        height: int = editor_height,
                    ) -> None:
                        active_screen.paint(
                            compose_frame(
                                body,
                                translator.text("status.tui_adjust_history"),
                                controls_line(
                                    editor_controls,
                                    width=width,
                                    color=style_enabled(),
                                ),
                                height=height,
                            )
                        )

                    decoder = InputDecoder()

                    def read_filter_key(
                        input_decoder: InputDecoder = decoder,
                    ) -> str | None:
                        event = read_event(input_decoder, 0.1)
                        return event.value if isinstance(event, KeyEvent) else None

                    edited = run_filter_editor(
                        historical_chart(current).filters,
                        discover_filter_choices(
                            last_snapshot.records,
                            historical_chart(current).filters,
                            include_projects=last_snapshot.includes_project_attribution,
                        ),
                        translator,
                        width=editor_size.columns,
                        paint=paint_filter_editor,
                        read_key=read_filter_key,
                    )
                    if edited is not None and edited != historical_chart(current).filters:
                        current = replace_chart_filters(current, edited)
                        component.configure(current, data_affecting=True)
                        request(
                            LifecycleTrigger.CONFIGURATION,
                            now=time.monotonic(),
                            data_affecting=False,
                        )
                    paint(force=True)
                elif key in {"m", "M"} and body_view == "chart" and last_snapshot is not None:
                    picked = run_runtime_adjustment(
                        current, translator, last_snapshot, active_screen
                    )
                    if picked is not None:
                        previous = component.candidate
                        current = picked.options
                        last_chart = picked.seed.chart
                        last_notices = picked.seed.notices
                        last_snapshot = picked.seed.snapshot
                        current_chart = historical_chart(current)
                        previous_chart = historical_chart(previous)
                        data_affecting = current_chart != previous_chart and (
                            current_chart.date_range != previous_chart.date_range
                            or current_chart.filters != previous_chart.filters
                            or getattr(current_chart, "by", None)
                            != getattr(previous_chart, "by", None)
                        )
                        component.configure(current, data_affecting=data_affecting)
                        if data_affecting:
                            request(LifecycleTrigger.CONFIGURATION, now=time.monotonic())
                        elif component.missing_comparison_coverage().intervals:
                            request(
                                LifecycleTrigger.CONFIGURATION,
                                now=time.monotonic(),
                                data_affecting=False,
                            )
                    paint()
                elif key == " ":
                    if not lifecycle.paused:
                        scheduler.pause()
                        lifecycle.pause()
                    else:
                        now = time.monotonic()
                        lifecycle.resume()
                        scheduler.resume(now=now)
                        request(LifecycleTrigger.RESUME, now=now)
                    paint()
                elif current.host.demo_size and key in {"s", "d", "l"}:
                    size = {"s": "small", "d": "medium", "l": "large"}[key]
                    current = replace(current, host=replace(current.host, demo_size=size))
                    component.configure(current, data_affecting=True)
                    request(LifecycleTrigger.CONFIGURATION, now=time.monotonic())
                    paint()
    except KeyboardInterrupt:
        return 0
    finally:
        scheduler.shutdown()
        lifecycle.shutdown()
        runtime.cancel()
        active_screen.finish()
