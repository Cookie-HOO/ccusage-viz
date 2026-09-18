from __future__ import annotations

import os
import queue
import sys
import threading
import time
from collections.abc import Hashable, Mapping
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
from ccusage_viz.errors import UsageError
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalCompletion,
    UsageSnapshot,
)
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    HistoricalChartConfig,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    StandaloneLaunch,
    TimelineConfig,
    adjust_standalone,
    compatible_styles,
)
from ccusage_viz.query.coordinator import QueryHandle
from ccusage_viz.query.models import ProviderResult, QueryTrigger
from ccusage_viz.render import RenderContext
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import InteractiveScreen, Terminal, inspect_terminal
from ccusage_viz.terminal_ui import controls_line, dimmed, input_mode, notice_lines, read_key


@dataclass(frozen=True, slots=True)
class RenderedChart:
    chart: str
    notices: tuple[str, ...]


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
    "timeline": frozenset("pPgbB+-=tTsS"),
    "calendar": frozenset("pPtTsS"),
    "stack": frozenset("pPgtTsS"),
    "ranking": frozenset("pPbB+-=tTsS"),
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


def historical_chart_config(options: StandaloneLaunch) -> HistoricalChartConfig:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical rendering does not support monitor configurations")
    return options.chart


def _render_component(
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
) -> RenderedChart:
    options = component.accepted_options
    model = component.model
    if options is None or model is None:
        raise RuntimeError("historical component has no accepted model")
    chart = historical_chart_config(options)
    title_content = (
        translator.text(f"label.{options.chart.by or 'total'}")
        if normalize_titles and options.chart.kind == "timeline"
        else translator.text(f"label.{options.chart.by or 'project'}")
        if normalize_titles and options.chart.kind == "ranking"
        else None
    )
    context = RenderContext(
        terminal.width,
        max(1, terminal.height - 1 - len(model.notices) - int(reserve_prompt) - control_rows),
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=options.chart.presentation.theme,
        style=options.chart.presentation.style,
        legend_position=options.chart.presentation.legend,
        hide_upper_right_axes=hide_upper_right_axes,
        deltas=ranking_deltas,
        rank_deltas=ranking_rank_deltas,
        weekday_mode=getattr(options.chart, "weekdays", "show"),
        period=chart.date_range.period if chart.date_range.relative_until else None,
        title_content=title_content,
    )
    chart = component.render(context)
    messages = tuple(translator.text(notice.key, **notice.values) for notice in model.notices)
    return RenderedChart(chart, messages)


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
    rendered = _render_component(
        component,
        translator,
        terminal,
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
        hide_upper_right_axes=hide_upper_right_axes,
        ranking_deltas=ranking_deltas,
        ranking_rank_deltas=ranking_rank_deltas,
        normalize_titles=normalize_titles,
    )
    return RefreshResult(
        rendered.chart,
        rendered.notices,
        snapshot.elapsed,
        snapshot,
        options,
    )


def run_once(options: StandaloneLaunch, translator: Translator) -> int:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("one-shot historical rendering does not support monitor configurations")
    current = replace(
        options,
        chart=replace(options.chart, date_range=refresh_date_range(options.chart.date_range)),
    )
    terminal = inspect_terminal(
        current.chart.kind,
        no_color=current.chart.presentation.theme == "no-color",
        ascii=current.host.ascii,
    )
    runtime = build_query_runtime()
    component = HistoricalChartComponent(
        current,
        owner_id="standalone",
        runtime=runtime,
        registry=build_chart_registry(),
    )
    try:
        completion = component.submit(QueryTrigger.STARTUP).result()
        if not component.accept(completion):
            raise RuntimeError("startup historical result was rejected")
        result = render_component(
            component,
            translator,
            terminal,
            reserve_prompt=True,
            normalize_titles=True,
        )
        status = (
            translator.text("status.demo", size=current.host.demo_size)
            if current.host.demo_size
            else translator.text("status.query_time", seconds=f"{result.elapsed:.2f}")
        )
        screen = InteractiveScreen(sys.stdout)
        screen.paint(
            result.chart,
            status,
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
        screen.finish()
        return 0
    finally:
        runtime.cancel()


def _paint(
    body: str,
    status: str,
    controls: str | tuple[str, ...],
    notices: tuple[str, ...] = (),
    *,
    height: int | None = None,
) -> None:
    InteractiveScreen(sys.stdout).paint(body, status, controls, notices, height=height)


def _paint_status(status: str) -> None:
    InteractiveScreen(sys.stdout).paint_status(status)


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
    screen: InteractiveScreen,
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


def run_watch(
    options: StandaloneLaunch,
    translator: Translator,
    *,
    seed: RefreshResult | None = None,
    screen: InteractiveScreen | None = None,
) -> int:
    if isinstance(options.chart, MonitorConfig):
        raise TypeError("historical watch mode does not support monitor configurations")
    active_screen = screen or InteractiveScreen(sys.stdout)
    interval = options.host.interval or 10.0
    runtime = build_query_runtime()
    current = seed.options if seed and seed.options is not None else options
    component = HistoricalChartComponent(
        current,
        owner_id="standalone",
        runtime=runtime,
        registry=build_chart_registry(),
    )
    results: queue.Queue[tuple[int, HistoricalCompletion | BaseException]] = queue.Queue()
    running = False
    pending_trigger: QueryTrigger | None = None
    active_handle: QueryHandle[ProviderResult] | None = None
    paused = False
    controls_hidden = False
    body_view: BodyView = "chart"
    last_chart = seed.chart if seed else ""
    last_notices: tuple[str, ...] = seed.notices if seed else ()
    last_snapshot = seed.snapshot if seed else None
    terminal_error: UsageError | None = None
    render_warning: str | None = None
    last_size: tuple[int, int] | None = None
    base_status = (
        translator.text("status.demo", size=options.host.demo_size)
        if seed and options.host.demo_size
        else translator.text("status.query_time", seconds=f"{seed.elapsed:.2f}")
        if seed
        else translator.text("status.loading")
    )
    if seed is not None and seed.snapshot is not None:
        component.seed(current, seed.snapshot)

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
    next_refresh = time.monotonic() + interval if seed else time.monotonic()

    def style_enabled() -> bool:
        return color_enabled(sys.stdout, no_color=current.chart.presentation.theme == "no-color")

    def terminal_size() -> os.terminal_size:
        return get_terminal_size()

    def status() -> str:
        return _watch_status(
            base_status,
            translator,
            interval=interval,
            paused=paused,
            running=running,
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
            force=force,
        )

    def start_refresh(trigger: QueryTrigger) -> None:
        nonlocal active_handle, running
        chart = historical_chart(current)
        submitted = replace(
            current,
            chart=replace(chart, date_range=refresh_date_range(chart.date_range)),
        )
        component.configure(submitted, data_affecting=True)
        generation = component.generation
        try:
            submission = component.submit(trigger)
        except BaseException as exc:
            results.put((generation, exc))
            running = True
            return
        active_handle = submission.handle

        def work() -> None:
            try:
                results.put((generation, submission.result()))
            except BaseException as exc:
                results.put((generation, exc))

        running = True
        threading.Thread(target=work, name="ccusage-viz-refresh", daemon=True).start()

    try:
        with input_mode():
            paint()
            while True:
                size = terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                now = time.monotonic()
                if terminal_error is None and not running:
                    trigger = pending_trigger
                    if trigger is None and not paused and now >= next_refresh:
                        trigger = QueryTrigger.STARTUP if last_snapshot is None else QueryTrigger.TICK
                    if trigger is not None:
                        pending_trigger = None
                        start_refresh(trigger)
                        active_screen.paint_status(status())

                try:
                    outcome = results.get_nowait()
                except queue.Empty:
                    outcome = None
                if outcome is not None:
                    outcome_generation, outcome = outcome
                    running = False
                    active_handle = None
                    next_refresh = time.monotonic() + interval
                    if outcome_generation != component.generation:
                        next_refresh = time.monotonic()
                        continue
                    if isinstance(outcome, HistoricalCompletion):
                        previous_options = current
                        try:
                            accepted = component.accept(outcome)
                        except BaseException as exc:
                            component.fail(exc, generation=outcome_generation)
                            base_status = format_error(
                                exc,
                                translator,
                                color=style_enabled(),
                                color_scheme=current.chart.presentation.theme,
                            )
                            if isinstance(exc, UsageError):
                                terminal_error = exc
                            paint()
                            continue
                        if not accepted:
                            next_refresh = time.monotonic()
                            continue
                        current = component.candidate
                        last_snapshot = component.snapshot
                        if isinstance(current.chart, RankingConfig) and last_snapshot is not None:
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
                                "status.query_time", seconds=f"{outcome.snapshot.elapsed:.2f}"
                            )
                        )
                    else:
                        component.fail(outcome, generation=outcome_generation)
                        base_status = format_error(
                            outcome,
                            translator,
                            color=style_enabled(),
                            color_scheme=current.chart.presentation.theme,
                        )
                        if isinstance(outcome, UsageError):
                            terminal_error = outcome
                    paint()
                    if pending_trigger is not None:
                        next_refresh = time.monotonic()

                key = read_key(0.05)
                if key == "\x03":
                    raise KeyboardInterrupt
                if key == "r":
                    pending_trigger = QueryTrigger.REFRESH
                    if running and active_handle is not None:
                        active_handle.cancel()
                    else:
                        next_refresh = time.monotonic()
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
                elif key in {"m", "M"} and body_view == "chart" and last_snapshot is not None:
                    picked = run_runtime_adjustment(
                        current, translator, last_snapshot, active_screen
                    )
                    if picked is not None:
                        current = picked.options
                        last_chart = picked.seed.chart
                        last_notices = picked.seed.notices
                        last_snapshot = picked.seed.snapshot
                        component.configure(current, data_affecting=True)
                        if last_snapshot is not None:
                            component.seed(current, last_snapshot)
                        pending_trigger = QueryTrigger.REFRESH
                        if running and active_handle is not None:
                            active_handle.cancel()
                        else:
                            next_refresh = time.monotonic()
                    paint()
                elif key == " ":
                    paused = not paused
                    if not paused:
                        next_refresh = time.monotonic() + interval
                    active_screen.paint_status(status())
                elif current.host.demo_size and key in {"s", "d", "l"}:
                    size = {"s": "small", "d": "medium", "l": "large"}[key]
                    current = replace(current, host=replace(current.host, demo_size=size))
                    component.configure(current, data_affecting=True)
                    pending_trigger = QueryTrigger.REFRESH
                    if running and active_handle is not None:
                        active_handle.cancel()
                    else:
                        next_refresh = time.monotonic()
    except KeyboardInterrupt:
        return 0
    finally:
        if active_handle is not None:
            active_handle.cancel()
        runtime.cancel()
        if screen is None:
            active_screen.finish()
