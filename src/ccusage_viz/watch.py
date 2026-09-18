from __future__ import annotations

import os
import queue
import select
import sys
import threading
import time
from collections.abc import Hashable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from shutil import get_terminal_size

from ccusage_viz.command_copy import (
    copy_command,
    format_command,
    format_full_command,
    format_full_command_display,
    wrap_command,
)
from ccusage_viz.core.time import refresh_date_range
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.data_view import BodyView, next_body_view, render_snapshot_data
from ccusage_viz.deltas import RefreshDeltas, RefreshRanks
from ccusage_viz.demo import generate_demo
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions, adjust_option, compatible_styles
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


_EMPTY_COVERAGE = DateCoverage()


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    records: tuple[UsageRecord, ...]
    notices: tuple[Notice, ...]
    elapsed: float
    includes_project_attribution: bool = False
    coverage: DateCoverage = _EMPTY_COVERAGE
    summary_notices: tuple[Notice, ...] = ()


@dataclass(frozen=True, slots=True)
class RefreshResult:
    chart: str
    notices: tuple[str, ...]
    elapsed: float
    snapshot: UsageSnapshot | None = None
    options: CommandOptions | None = None


@dataclass(frozen=True, slots=True)
class RuntimeAdjustmentResult:
    options: CommandOptions
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


def _without_summary_control(text: str) -> str:
    """Drop the retired summary runtime control from localized adjustment text."""
    return " · ".join(part for part in text.split(" · ") if "{summary}" not in part and not part.startswith("u "))


def _render(
    options: CommandOptions,
    translator: Translator,
    terminal: Terminal,
    records: tuple[UsageRecord, ...],
    notices: tuple[Notice, ...],
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
    hide_upper_right_axes: bool = False,
    ranking_deltas: Mapping[Hashable, float] | None = None,
    ranking_rank_deltas: Mapping[Hashable, int] | None = None,
    coverage: DateCoverage = _EMPTY_COVERAGE,
    summary_notices: tuple[Notice, ...] = (),
    normalize_titles: bool = False,
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
        title_content = (
            translator.text(f"label.{options.by or 'total'}")
            if normalize_titles and options.command == "timeline"
            else translator.text(f"label.{options.by or 'project'}")
            if normalize_titles and options.command == "ranking"
            else None
        )
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
            legend_position=options.legend,
            hide_upper_right_axes=hide_upper_right_axes,
            deltas=ranking_deltas,
            rank_deltas=ranking_rank_deltas,
            weekday_mode=options.weekdays,
            period=options.date_range.period if options.date_range.relative_until else None,
            title_content=title_content,
        )

    if options.command == "timeline":
        model = build_timeline(
            filtered,
            options.date_range,
            by=None if options.by == "total" else options.by,
            top=options.top,
            show_other=options.other == "show",
            include_summary=True,
            notices=all_notices,
            aggregation=options.granularity,
            coverage=coverage,
        )
        chart = render_timeline(model, context_for(len(model.notices)))
    elif options.command == "calendar":
        model = build_calendar(
            filtered,
            options.date_range,
            include_summary=True,
            notices=all_notices,
            coverage=coverage,
        )
        chart = render_calendar(model, context_for(len(model.notices)))
    elif options.command == "stack":
        model = build_stack(
            filtered,
            options.date_range,
            split_cache=options.cache == "split",
            include_summary=True,
            notices=all_notices,
            aggregation=options.granularity,
            coverage=coverage,
        )
        chart = render_stack(model, context_for(len(model.notices)))
    else:
        model = build_ranking(
            filtered,
            options.date_range,
            by=options.by or "project",
            top=options.top,
            show_other=options.other == "show",
            include_summary=True,
            notices=all_notices,
            summary_notices=summary_notices,
            coverage=coverage,
        )
        chart = render_ranking(model, context_for(len(model.notices)))
    messages = tuple(translator.text(notice.key, **notice.values) for notice in model.notices)
    return RenderedChart(chart, messages)


def ranking_entries(
    options: CommandOptions, snapshot: UsageSnapshot
) -> tuple[tuple[Hashable, float, bool], ...]:
    filtered, _ = filter_records(
        snapshot.records,
        options.date_range,
        agents=options.agents,
        models=options.models,
        projects=options.projects,
    )
    model = build_ranking(
        filtered,
        options.date_range,
        by=options.by or "project",
        top=options.top,
        show_other=options.other == "show",
        include_summary=False,
        notices=snapshot.notices,
    )
    return tuple((entry.key, float(entry.usage.total), entry.is_other) for entry in model.entries)


def ranking_values(options: CommandOptions, snapshot: UsageSnapshot) -> dict[Hashable, float]:
    return {key: value for key, value, _ in ranking_entries(options, snapshot)}


def ranking_keys(options: CommandOptions, snapshot: UsageSnapshot) -> tuple[Hashable, ...]:
    return tuple(key for key, _, is_other in ranking_entries(options, snapshot) if not is_other)


def load_snapshot(options: CommandOptions, runner: QueryRunner) -> UsageSnapshot:
    started = time.monotonic()
    if options.demo:
        records = generate_demo(options.demo, options.date_range)
        notices: tuple[Notice, ...] = ()
        includes_project_attribution = True
        coverage = DateCoverage.from_interval(options.date_range.since, options.date_range.until)
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
        daily_intervals = tuple(
            query.daily_coverage for query in plan.queries if query.daily_coverage is not None
        )
        coverage = DateCoverage(daily_intervals)
    return UsageSnapshot(
        records,
        notices,
        time.monotonic() - started,
        includes_project_attribution,
        coverage,
        () if options.demo else plan.summary_notices,
    )


def render_snapshot(
    options: CommandOptions,
    translator: Translator,
    terminal: Terminal,
    snapshot: UsageSnapshot,
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
    hide_upper_right_axes: bool = False,
    ranking_deltas: Mapping[Hashable, float] | None = None,
    ranking_rank_deltas: Mapping[Hashable, int] | None = None,
    normalize_titles: bool = False,
) -> RefreshResult:
    rendered = _render(
        options,
        translator,
        terminal,
        snapshot.records,
        snapshot.notices,
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
        hide_upper_right_axes=hide_upper_right_axes,
        ranking_deltas=ranking_deltas,
        ranking_rank_deltas=ranking_rank_deltas,
        coverage=snapshot.coverage,
        summary_notices=snapshot.summary_notices,
        normalize_titles=normalize_titles,
    )
    return RefreshResult(rendered.chart, rendered.notices, snapshot.elapsed, snapshot, options)


def _refresh(
    options: CommandOptions,
    translator: Translator,
    terminal: Terminal,
    runner: QueryRunner,
    *,
    reserve_prompt: bool = False,
    control_rows: int = 0,
    normalize_titles: bool = False,
) -> RefreshResult:
    return render_snapshot(
        options,
        translator,
        terminal,
        load_snapshot(options, runner),
        reserve_prompt=reserve_prompt,
        control_rows=control_rows,
        normalize_titles=normalize_titles,
    )


def run_once(options: CommandOptions, translator: Translator) -> str:
    current = replace(options, date_range=refresh_date_range(options.date_range))
    terminal = inspect_terminal(
        current.command,
        no_color=current.no_color,
        ascii=current.ascii,
    )
    runner = QueryRunner(current.ccusage_bin, timeout=current.query_timeout)
    result = _refresh(
        current, translator, terminal, runner, reserve_prompt=True, normalize_titles=True
    )
    status = (
        translator.text("status.demo", size=current.demo)
        if current.demo
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
        attributes = termios.tcgetattr(descriptor)
        attributes[3] &= ~termios.ISIG
        termios.tcsetattr(descriptor, termios.TCSADRAIN, attributes)
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


def run_runtime_adjustment(
    options: CommandOptions,
    translator: Translator,
    snapshot: UsageSnapshot,
    screen: InteractiveScreen,
) -> RuntimeAdjustmentResult | None:
    theme_index = COLOR_SCHEMES.index(options.color_scheme)
    last_size: os.terminal_size | None = None
    current = options
    rendered: RefreshResult | None = None
    rendered_options: CommandOptions | None = None
    render_warning: str | None = None
    copied_status: str | None = None
    adjustment_page = "quick"

    def grouping_choices() -> tuple[str, ...]:
        if current.command == "timeline":
            return ("total", "agent", "model", "project")
        if current.command == "ranking":
            return ("agent", "model", "project")
        return ()

    def paint() -> None:
        nonlocal current, last_size, rendered, rendered_options, render_warning
        theme = COLOR_SCHEMES[theme_index]
        styles = compatible_styles(current.command, current.by)
        style = current.style if current.style in styles else styles[0]
        current = replace(current, color_scheme=theme, style=style)
        last_size = get_terminal_size()
        terminal = Terminal(last_size.columns, last_size.lines, not current.no_color, current.ascii)
        try:
            terminal = inspect_terminal(
                current.command,
                no_color=current.no_color,
                ascii=current.ascii,
                size=last_size,
            )
            candidate = render_snapshot(
                current,
                translator,
                terminal,
                snapshot,
                control_rows=2,
            )
        except UsageError as exc:
            render_warning = format_error(
                exc, translator, color=terminal.color, color_scheme=current.color_scheme
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
        status_key = f"status.runtime_adjustment_{current.command}_{adjustment_page}"
        key_key = f"status.tui_adjust_{current.command}_{adjustment_page}_controls"
        state_values = dict(common)
        if current.command in {"timeline", "ranking"}:
            state_values.update(
                grouping=current.by or translator.text("label.all"),
                top=current.top if current.top is not None else translator.text("label.all"),
                other=translator.text("label.on" if current.other == "show" else "label.off"),
            )
        if current.command in {"timeline", "stack"}:
            state_values["weekday"] = translator.text(f"label.weekday_{current.weekdays}")
            state_values["legend_position"] = translator.text(
                f"label.legend_{current.legend.replace('-', '_')}"
            )
        if current.command == "stack":
            state_values["cache"] = translator.text(
                "label.on" if current.cache == "split" else "label.off"
            )
        state = _without_summary_control(translator.messages[status_key]).format(**state_values)
        project_preview_missing = (
            current.command in {"timeline", "ranking"}
            and current.by == "project"
            and not snapshot.includes_project_attribution
        )
        preview_notice = (
            translator.text("status.project_preview_missing") if project_preview_missing else None
        )
        controls: str | tuple[str, ...] = (
            _controls_line(
                " · ".join(part for part in (state, copied_status) if part is not None),
                width=terminal.width,
                color=terminal.color,
            ),
            _controls_line(
                f"{translator.text(f'status.tui_adjust_{adjustment_page}')} · "
                f"{_without_summary_control(translator.messages[key_key])}",
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
            _notice_lines(
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
        with _input_mode():
            paint()
            while True:
                key = _read_key(0.1)
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
                    current.command, adjustment_page, key
                ):
                    updated = adjust_option(current, key)
                    if updated != current:
                        current = updated
                        theme_index = COLOR_SCHEMES.index(current.color_scheme)
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
    runner = QueryRunner(options.ccusage_bin, timeout=options.query_timeout)
    results: queue.Queue[tuple[int, RefreshResult | BaseException]] = queue.Queue()
    running = False
    queued = False
    refresh_generation = 0
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
        translator.text("status.demo", size=options.demo)
        if seed and options.demo
        else translator.text("status.query_time", seconds=f"{seed.elapsed:.2f}")
        if seed
        else translator.text("status.loading")
    )
    current = seed.options if seed and seed.options is not None else options
    ranking_deltas = RefreshDeltas()
    ranking_ranks = RefreshRanks()
    if current.command == "ranking" and last_snapshot is not None:
        ranking_deltas.accept(ranking_values(current, last_snapshot))
        ranking_ranks.accept(ranking_keys(current, last_snapshot))
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
        if current.demo:
            keys = f"{keys} · {translator.text('status.demo_keys')}"
        return keys

    def paint(*, force: bool = False) -> None:
        nonlocal last_chart, last_notices, last_snapshot, terminal_error, render_warning, last_size
        size = terminal_size()
        last_size = (size.columns, size.lines)
        color = style_enabled()
        try:
            terminal = inspect_terminal(
                current.command, no_color=current.no_color, ascii=current.ascii, size=size
            )
        except UsageError as exc:
            terminal_error = exc
            warning = format_error(exc, translator, color=False, color_scheme=current.color_scheme)
            active_screen.paint(
                last_chart or warning,
                status(),
                ()
                if controls_hidden
                else _controls_line(controls(), width=size.columns, color=False),
                _notice_lines(
                    (*last_notices, warning) if last_chart else (),
                    width=size.columns,
                    color=False,
                    ascii=current.ascii,
                    translator=translator,
                    color_scheme=current.color_scheme,
                ),
                height=size.lines,
                force=force,
            )
            return
        terminal_error = None
        if last_snapshot is not None:
            try:
                rendered = render_snapshot(
                    current,
                    translator,
                    terminal,
                    last_snapshot,
                    control_rows=0 if controls_hidden else 1,
                    ranking_deltas=ranking_deltas.current if current.command == "ranking" else None,
                    ranking_rank_deltas=(
                        ranking_ranks.current if current.command == "ranking" else None
                    ),
                    normalize_titles=True,
                )
            except UsageError as exc:
                render_warning = format_error(
                    exc, translator, color=color, color_scheme=current.color_scheme
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
            () if not footer else _controls_line(footer, width=size.columns, color=color),
            _notice_lines(
                (*last_notices, render_warning) if render_warning is not None else last_notices,
                width=size.columns,
                color=color,
                ascii=current.ascii,
                translator=translator,
                color_scheme=current.color_scheme,
            ),
            height=size.lines,
            force=force,
        )

    def start_refresh() -> None:
        nonlocal running
        generation = refresh_generation
        try:
            terminal = inspect_terminal(
                current.command,
                no_color=current.no_color,
                ascii=current.ascii,
            )
        except BaseException as exc:
            results.put((generation, exc))
            running = True
            return

        snapshot = replace(current, date_range=refresh_date_range(current.date_range))

        def work(
            generation: int = generation,
            snapshot: CommandOptions = snapshot,
            size: Terminal = terminal,
        ) -> None:
            try:
                results.put(
                    (
                        generation,
                        _refresh(
                            snapshot,
                            translator,
                            size,
                            runner,
                            control_rows=1,
                            normalize_titles=True,
                        ),
                    )
                )
            except BaseException as exc:
                results.put((generation, exc))

        running = True
        threading.Thread(target=work, name="ccusage-viz-refresh", daemon=True).start()

    try:
        with _input_mode():
            paint()
            while True:
                size = terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
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
                    outcome_generation, outcome = outcome
                    running = False
                    next_refresh = time.monotonic() + interval
                    if outcome_generation != refresh_generation:
                        next_refresh = time.monotonic()
                        continue
                    if isinstance(outcome, RefreshResult):
                        previous_options = current
                        if outcome.options is not None:
                            current = outcome.options
                        last_chart = outcome.chart
                        last_notices = outcome.notices
                        last_snapshot = outcome.snapshot
                        if current.command == "ranking" and last_snapshot is not None:
                            if (
                                previous_options.by,
                                previous_options.top,
                                previous_options.other,
                                previous_options.agents,
                                previous_options.models,
                                previous_options.projects,
                                previous_options.date_range,
                            ) != (
                                current.by,
                                current.top,
                                current.other,
                                current.agents,
                                current.models,
                                current.projects,
                                current.date_range,
                            ):
                                ranking_deltas.clear()
                                ranking_ranks.clear()
                            ranking_deltas.accept(ranking_values(current, last_snapshot))
                            ranking_ranks.accept(ranking_keys(current, last_snapshot))
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
                if key == "\x03":
                    raise KeyboardInterrupt
                if key == "r":
                    if running:
                        queued = True
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
                        current.command,
                        no_color=current.no_color,
                        ascii=current.ascii,
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
                        refresh_generation += 1
                        next_refresh = time.monotonic()
                    paint()
                elif key == " ":
                    paused = not paused
                    if not paused:
                        next_refresh = time.monotonic() + interval
                    active_screen.paint_status(status())
                elif current.demo and key in {"s", "d", "l"}:
                    size = {"s": "small", "d": "medium", "l": "large"}[key]
                    current = replace(current, demo=size)
                    refresh_generation += 1
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
