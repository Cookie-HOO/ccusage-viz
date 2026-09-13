from __future__ import annotations

import os
import queue
import select
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from shutil import get_terminal_size

from ccusage_viz.command_copy import copy_command, format_command
from ccusage_viz.demo import generate_demo
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions, compatible_styles, refresh_date_range
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.query.models import QueryKind
from ccusage_viz.query.planner import plan_queries
from ccusage_viz.render import (
    RenderContext,
    render_calendar,
    render_ranking,
    render_stack,
    render_timeline,
)
from ccusage_viz.render.base import styled_text
from ccusage_viz.render.palette import COLOR_SCHEMES, WARNING_COLOR
from ccusage_viz.schema import parse_usage_records
from ccusage_viz.terminal import InteractiveScreen, Terminal, inspect_terminal
from ccusage_viz.transform import (
    build_calendar,
    build_ranking,
    build_stack,
    build_timeline,
    filter_records,
)


@dataclass(frozen=True, slots=True)
class RenderedChart:
    chart: str
    notices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    records: tuple[UsageRecord, ...]
    notices: tuple[Notice, ...]
    elapsed: float
    includes_project_attribution: bool = False


@dataclass(frozen=True, slots=True)
class RefreshResult:
    chart: str
    notices: tuple[str, ...]
    elapsed: float
    snapshot: UsageSnapshot | None = None


@dataclass(frozen=True, slots=True)
class AppearancePickerResult:
    options: CommandOptions
    seed: RefreshResult


def _render(
    options: CommandOptions,
    translator: Translator,
    terminal: Terminal,
    records: tuple[UsageRecord, ...],
    notices: tuple[Notice, ...],
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
) -> RenderedChart:
    filtered, filter_notices = filter_records(
        records,
        options.date_range,
        agents=options.agents,
        models=options.models,
        projects=options.projects,
    )
    all_notices = (*notices, *filter_notices)

    def context_for(notice_count: int) -> RenderContext:
        return RenderContext(
            terminal.width,
            max(
                1,
                terminal.height - 1 - notice_count - int(reserve_prompt) - control_rows,
            ),
            translator,
            color=terminal.color,
            ascii=terminal.ascii,
            color_scheme=options.color_scheme,
            style=options.style,
            legend_position=options.legend_position,
        )

    if options.command == "timeline":
        model = build_timeline(
            filtered,
            options.date_range,
            by=None if options.by == "total" else options.by,
            top=options.top,
            show_other=options.show_other,
            include_summary=not options.no_summary,
            notices=all_notices,
        )
        chart = render_timeline(model, context_for(len(model.notices)))
    elif options.command == "calendar":
        model = build_calendar(
            filtered,
            options.date_range,
            include_summary=not options.no_summary,
            notices=all_notices,
        )
        chart = render_calendar(model, context_for(len(model.notices)))
    elif options.command == "stack":
        model = build_stack(
            filtered,
            options.date_range,
            split_cache=options.split_cache,
            include_summary=not options.no_summary,
            notices=all_notices,
        )
        chart = render_stack(model, context_for(len(model.notices)))
    else:
        model = build_ranking(
            filtered,
            options.date_range,
            by=options.by or "project",
            top=options.top,
            show_other=options.show_other,
            include_summary=not options.no_summary,
            notices=all_notices,
        )
        chart = render_ranking(model, context_for(len(model.notices)))
    messages = tuple(translator.text(notice.key, **notice.values) for notice in model.notices)
    return RenderedChart(chart, messages)


def load_snapshot(options: CommandOptions, runner: QueryRunner) -> UsageSnapshot:
    started = time.monotonic()
    if options.demo:
        records = generate_demo(options.demo, options.date_range)
        notices: tuple[Notice, ...] = ()
        includes_project_attribution = True
    else:
        plan = plan_queries(options)
        results = runner.run(plan)
        records = tuple(
            record for result in results for record in parse_usage_records(result.kind, result.data)
        )
        notices = plan.notices
        includes_project_attribution = any(
            query.kind in {QueryKind.CLAUDE_DAILY_PROJECTS, QueryKind.CODEX_SESSIONS}
            for query in plan.queries
        )
    return UsageSnapshot(
        records,
        notices,
        time.monotonic() - started,
        includes_project_attribution,
    )


def render_snapshot(
    options: CommandOptions,
    translator: Translator,
    terminal: Terminal,
    snapshot: UsageSnapshot,
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
) -> RefreshResult:
    rendered = _render(
        options,
        translator,
        terminal,
        snapshot.records,
        snapshot.notices,
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
    )
    return RefreshResult(rendered.chart, rendered.notices, snapshot.elapsed, snapshot)


def _refresh(
    options: CommandOptions,
    translator: Translator,
    terminal: Terminal,
    runner: QueryRunner,
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
) -> RefreshResult:
    return render_snapshot(
        options,
        translator,
        terminal,
        load_snapshot(options, runner),
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
    )


def run_once(options: CommandOptions, translator: Translator) -> str:
    terminal = inspect_terminal(
        options.command,
        no_color=options.no_color,
        ascii=options.ascii,
    )
    runner = QueryRunner(options.ccusage_bin, timeout=options.timeout)
    result = _refresh(options, translator, terminal, runner, reserve_prompt=True)
    status = (
        translator.text("status.demo", size=options.demo)
        if options.demo
        else translator.text("status.query_time", seconds=f"{result.elapsed:.2f}")
    )
    body = "\n".join((*result.notices, result.chart)) if result.notices else result.chart
    return f"{status}\n{body}"


@contextmanager
def _input_mode() -> Iterator[None]:
    if os.name != "posix":
        yield
        return
    import termios
    import tty

    if not sys.stdin.isatty():
        raise UsageError("error.tty")
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def _read_key(timeout: float) -> str | None:
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                return msvcrt.getwch()
            time.sleep(min(0.05, timeout))
        return None
    readable, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if readable else None


def _dimmed(text: str, *, color: bool) -> str:
    return f"\x1b[2m{text}\x1b[0m" if color else text


def _notice_lines(
    notices: tuple[str, ...],
    *,
    width: int,
    color: bool,
    ascii: bool,
    translator: Translator,
    color_scheme: str = "classic",
) -> tuple[str, ...]:
    context = RenderContext(
        width,
        1,
        translator,
        color=color,
        ascii=ascii,
        color_scheme=color_scheme,
    )
    glyph = "!" if ascii else "⚠"
    notice_color = 255 if color_scheme == "mono" else WARNING_COLOR
    return tuple(
        clip_width(styled_text(f"{glyph} {notice}", notice_color, context, bold=True), width)
        for notice in notices
    )


def _controls_line(controls: str, *, width: int, color: bool) -> str:
    return clip_width(_dimmed(controls, color=color), width)


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
    refreshing = _dimmed(translator.text("status.refreshing"), color=color)
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
        parts.append(_dimmed(translator.text("status.refreshing"), color=color))
    return " · ".join(parts)


def run_appearance_picker(
    options: CommandOptions,
    translator: Translator,
    snapshot: UsageSnapshot,
    screen: InteractiveScreen,
    *,
    adjust_display: bool = False,
) -> AppearancePickerResult | None:
    theme_index = COLOR_SCHEMES.index(options.color_scheme)
    last_size: os.terminal_size | None = None
    current = options
    rendered: RefreshResult | None = None
    copied_status: str | None = None

    def grouping_choices() -> tuple[str, ...]:
        if current.command == "timeline":
            return ("total", "agent", "model", "project")
        if current.command == "ranking":
            return ("agent", "model", "project")
        return ()

    def paint() -> None:
        nonlocal current, last_size, rendered
        theme = COLOR_SCHEMES[theme_index]
        styles = compatible_styles(current.command, current.by)
        style = current.style if current.style in styles else styles[0]
        current = replace(current, color_scheme=theme, style=style)
        last_size = get_terminal_size()
        terminal = inspect_terminal(
            current.command,
            no_color=current.no_color,
            ascii=current.ascii,
            size=last_size,
        )
        rendered = render_snapshot(
            current,
            translator,
            terminal,
            snapshot,
            control_rows=2 if adjust_display else 1,
        )
        source_status = (
            translator.text("status.demo", size=current.demo)
            if current.demo
            else translator.text("status.query_time", seconds=f"{snapshot.elapsed:.2f}")
        )
        common = {
            "theme_index": theme_index + 1,
            "theme_count": len(COLOR_SCHEMES),
            "theme": theme,
            "style_index": styles.index(style) + 1,
            "style_count": len(styles),
            "style": style,
            "summary": translator.text("label.off" if current.no_summary else "label.on"),
        }
        if adjust_display:
            status_key = f"status.appearance_picker_adjust_{current.command}"
            key_key = f"status.appearance_picker_keys_{current.command}"
            state_values = dict(common)
            if current.command in {"timeline", "ranking"}:
                state_values.update(
                    grouping=current.by or translator.text("label.all"),
                    top=current.top if current.top is not None else translator.text("label.all"),
                    other=translator.text("label.on" if current.show_other else "label.off"),
                )
            if current.command == "timeline":
                state_values["legend_position"] = translator.text(
                    f"label.legend_{current.legend_position.replace('-', '_')}"
                )
            if current.command == "stack":
                state_values["cache"] = translator.text(
                    "label.on" if current.split_cache else "label.off"
                )
                state_values["legend_position"] = translator.text(
                    f"label.legend_{current.legend_position.replace('-', '_')}"
                )
            state = translator.text(status_key, **state_values)
            project_preview_missing = (
                current.command in {"timeline", "ranking"}
                and current.by == "project"
                and not snapshot.includes_project_attribution
            )
            preview_notice = (
                translator.text("status.project_preview_missing")
                if project_preview_missing
                else None
            )
            controls: str | tuple[str, ...] = (
                _controls_line(
                    " · ".join(part for part in (state, copied_status) if part is not None),
                    width=terminal.width,
                    color=terminal.color,
                ),
                _controls_line(
                    translator.text(key_key), width=terminal.width, color=terminal.color
                ),
            )
            status = " · ".join(part for part in (source_status, preview_notice) if part)
        else:
            status = " · ".join(
                part
                for part in (
                    translator.text("status.appearance_picker", **common),
                    source_status,
                    copied_status,
                )
                if part is not None
            )
            controls = _controls_line(
                translator.text("status.appearance_picker_style_keys"),
                width=terminal.width,
                color=terminal.color,
            )
        screen.paint(
            rendered.chart,
            status,
            controls,
            _notice_lines(
                rendered.notices,
                width=terminal.width,
                color=terminal.color,
                ascii=terminal.ascii,
                translator=translator,
                color_scheme=theme,
            ),
            height=terminal.height,
        )

    try:
        with _input_mode():
            paint()
            while True:
                key = _read_key(0.1)
                if get_terminal_size() != last_size:
                    paint()
                if key in {"q", "Q"}:
                    return None
                if key in {"\r", "\n"}:
                    assert rendered is not None
                    return AppearancePickerResult(current, rendered)
                if key in {"y", "Y"}:
                    copied_status = (
                        translator.text("status.command_copied")
                        if copy_command(format_command(current))
                        else translator.text("status.command_copy_failed")
                    )
                    paint()
                elif key in {"n", "N"}:
                    theme_index = (theme_index + 1) % len(COLOR_SCHEMES)
                    paint()
                elif key in {"p", "P"}:
                    theme_index = (theme_index - 1) % len(COLOR_SCHEMES)
                    paint()
                elif key == "j":
                    styles = compatible_styles(current.command, current.by)
                    current = replace(
                        current, style=styles[(styles.index(current.style) + 1) % len(styles)]
                    )
                    paint()
                elif key == "k":
                    styles = compatible_styles(current.command, current.by)
                    current = replace(
                        current, style=styles[(styles.index(current.style) - 1) % len(styles)]
                    )
                    paint()
                elif (
                    adjust_display
                    and key in {"l", "L"}
                    and current.command
                    in {
                        "timeline",
                        "stack",
                    }
                ):
                    positions = (
                        ("below-title", "inside", "hidden")
                        if current.command == "timeline"
                        else ("below-title", "hidden")
                    )
                    current = replace(
                        current,
                        legend_position=positions[
                            (positions.index(current.legend_position) + 1) % len(positions)
                        ],
                    )
                    paint()
                elif adjust_display and key in {"b", "B"} and (choices := grouping_choices()):
                    next_by = choices[(choices.index(current.by) + 1) % len(choices)]
                    next_styles = compatible_styles(current.command, next_by)
                    current = replace(
                        current,
                        by=next_by,
                        style=current.style if current.style in next_styles else next_styles[0],
                    )
                    paint()
                elif (
                    adjust_display
                    and key in {"+", "="}
                    and current.command in {"timeline", "ranking"}
                ):
                    current = replace(current, top=(current.top or 0) % 10 + 1)
                    paint()
                elif adjust_display and key == "-" and current.command in {"timeline", "ranking"}:
                    current = replace(
                        current, top=10 if current.top in {None, 1} else current.top - 1
                    )
                    paint()
                elif (
                    adjust_display
                    and key in {"o", "O"}
                    and current.command in {"timeline", "ranking"}
                ):
                    current = replace(current, show_other=not current.show_other)
                    paint()
                elif adjust_display and key in {"c", "C"} and current.command == "stack":
                    current = replace(current, split_cache=not current.split_cache)
                    paint()
                elif (
                    adjust_display
                    and key in {"u", "U"}
                    and current.command in {"timeline", "calendar", "stack", "ranking"}
                ):
                    current = replace(current, no_summary=not current.no_summary)
                    paint()
    except KeyboardInterrupt:
        return None


def run_watch(
    options: CommandOptions,
    translator: Translator,
    *,
    seed: RefreshResult | None = None,
    screen: InteractiveScreen | None = None,
) -> int:
    active_screen = screen or InteractiveScreen(sys.stdout)
    interval = options.watch or 5.0
    runner = QueryRunner(options.ccusage_bin, timeout=options.timeout)
    results: queue.Queue[RefreshResult | BaseException] = queue.Queue()
    running = False
    queued = False
    paused = False
    last_chart = seed.chart if seed else ""
    last_notices: tuple[str, ...] = seed.notices if seed else ()
    last_snapshot = seed.snapshot if seed else None
    terminal_error: UsageError | None = None
    last_size: tuple[int, int] | None = None
    base_status = (
        translator.text("status.demo", size=options.demo)
        if seed and options.demo
        else translator.text("status.query_time", seconds=f"{seed.elapsed:.2f}")
        if seed
        else translator.text("status.loading")
    )
    current = options
    next_refresh = time.monotonic() + interval if seed else time.monotonic()

    def style_enabled() -> bool:
        return color_enabled(sys.stdout, no_color=current.no_color)

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
        keys = translator.text("status.keys")
        if current.demo:
            keys = f"{keys} · {translator.text('status.demo_keys')}"
        return keys

    def paint() -> None:
        nonlocal last_chart, last_notices, last_snapshot, terminal_error, last_size
        size = terminal_size()
        last_size = (size.columns, size.lines)
        color = style_enabled()
        try:
            terminal = inspect_terminal(
                current.command, no_color=current.no_color, ascii=current.ascii, size=size
            )
        except UsageError as exc:
            terminal_error = exc
            active_screen.paint(
                format_error(exc, translator, color=False, color_scheme=current.color_scheme),
                status(),
                _controls_line(controls(), width=size.columns, color=False),
                height=size.lines,
            )
            return
        terminal_error = None
        if last_snapshot is not None:
            rendered = render_snapshot(current, translator, terminal, last_snapshot, control_rows=1)
            last_chart = rendered.chart
            last_notices = rendered.notices
        active_screen.paint(
            last_chart,
            status(),
            _controls_line(controls(), width=size.columns, color=color),
            _notice_lines(
                last_notices,
                width=size.columns,
                color=color,
                ascii=current.ascii,
                translator=translator,
                color_scheme=current.color_scheme,
            ),
            height=size.lines,
        )

    def start_refresh() -> None:
        nonlocal running
        try:
            terminal = inspect_terminal(
                current.command,
                no_color=current.no_color,
                ascii=current.ascii,
            )
        except BaseException as exc:
            results.put(exc)
            running = True
            return

        snapshot = replace(current, date_range=refresh_date_range(current.date_range))

        def work(snapshot: CommandOptions = snapshot, size: Terminal = terminal) -> None:
            try:
                results.put(_refresh(snapshot, translator, size, runner, control_rows=1))
            except BaseException as exc:
                results.put(exc)

        running = True
        threading.Thread(target=work, name="ccusage-viz-refresh", daemon=True).start()

    try:
        with _input_mode():
            paint()
            while True:
                size = terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint()
                now = time.monotonic()
                if (
                    terminal_error is None
                    and not running
                    and (queued or (not paused and now >= next_refresh))
                ):
                    queued = False
                    start_refresh()
                    active_screen.paint_status(status())

                try:
                    outcome = results.get_nowait()
                except queue.Empty:
                    outcome = None
                if outcome is not None:
                    running = False
                    next_refresh = time.monotonic() + interval
                    if isinstance(outcome, RefreshResult):
                        last_chart = outcome.chart
                        last_notices = outcome.notices
                        last_snapshot = outcome.snapshot
                        base_status = (
                            translator.text("status.demo", size=current.demo)
                            if current.demo
                            else translator.text(
                                "status.query_time", seconds=f"{outcome.elapsed:.2f}"
                            )
                        )
                    else:
                        base_status = format_error(
                            outcome,
                            translator,
                            color=style_enabled(),
                            color_scheme=current.color_scheme,
                        )
                        if isinstance(outcome, UsageError):
                            terminal_error = outcome
                    paint()
                    if queued:
                        next_refresh = time.monotonic()

                key = _read_key(0.05)
                if key in {"q", "Q"}:
                    runner.cancel()
                    return 0
                if key in {"r", "R"}:
                    if running:
                        queued = True
                    else:
                        next_refresh = time.monotonic()
                elif key in {"m", "M"} and last_snapshot is not None:
                    picked = run_appearance_picker(
                        current, translator, last_snapshot, active_screen, adjust_display=True
                    )
                    if picked is not None:
                        current = picked.options
                        last_chart = picked.seed.chart
                        last_notices = picked.seed.notices
                    paint()
                elif key == " ":
                    paused = not paused
                    if not paused:
                        next_refresh = time.monotonic() + interval
                    active_screen.paint_status(status())
                elif current.demo and key in {"s", "d", "l"}:
                    size = {"s": "small", "d": "medium", "l": "large"}[key]
                    current = replace(current, demo=size)
                    if running:
                        queued = True
                    else:
                        next_refresh = time.monotonic()
    except KeyboardInterrupt:
        runner.cancel()
        return 0
    finally:
        if screen is None:
            active_screen.finish()
