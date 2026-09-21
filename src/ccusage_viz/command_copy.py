from __future__ import annotations

import shlex
import subprocess
from dataclasses import replace
from shutil import which

from ccusage_viz.formatting import char_width, display_width
from ccusage_viz.options import (
    COMMAND_DEFAULT_PERIODS,
    DashboardLaunch,
    MonitorConfig,
    PaneConfig,
    RankingConfig,
    StackConfig,
    StandaloneLaunch,
    TimelineConfig,
    compatible_styles,
)


def _window_duration(seconds: int) -> str:
    unit = "h" if seconds % 3600 == 0 else "m"
    return f"{seconds // (3600 if unit == 'h' else 60)}{unit}"


def _default_interval(config: StandaloneLaunch) -> float:
    if isinstance(config.chart, MonitorConfig):
        return 1.0 if config.host.demo_size is not None else 15.0
    return 10.0


def _is_default_top(chart: object, by: str | None, top: int | None) -> bool:
    if isinstance(chart, RankingConfig):
        return top == 10
    return by is not None and top == 3


def _chart_args(config: StandaloneLaunch, *, full: bool, pane: bool = False) -> list[str]:
    chart = config.chart
    args = [chart.kind]
    if isinstance(chart, MonitorConfig):
        if full or chart.window_seconds != 3600:
            args.extend(("--window", _window_duration(chart.window_seconds)))
        if not pane and (full or config.host.interval != _default_interval(config)):
            args.extend(("--interval", f"{config.host.interval:g}"))
    else:
        date_range = chart.date_range
        if date_range.relative_until and date_range.period is not None:
            if full or date_range.period != COMMAND_DEFAULT_PERIODS[chart.kind]:
                args.extend(("--period", date_range.period))
        else:
            args.extend(("--since", date_range.since.isoformat()))
            if not date_range.implicit_until:
                args.extend(("--until", date_range.until.isoformat()))
        if not pane and config.host.timezone:
            args.extend(("--timezone", config.host.timezone))
        if isinstance(chart, (TimelineConfig, StackConfig)):
            if full or chart.granularity != "day":
                args.extend(("--granularity", chart.granularity))
            if full or chart.weekdays != "show":
                args.extend(("--weekdays", chart.weekdays))
    by, top = getattr(chart, "by", None), getattr(chart, "top", None)
    if by is not None and (full or not isinstance(chart, RankingConfig) or by != "project"):
        args.extend(("--by", by))
    if top is not None and (full or not _is_default_top(chart, by, top)):
        args.extend(("--top", str(top)))
    if isinstance(chart, (TimelineConfig, RankingConfig)) and (
        full or chart.project_aggregation != "name"
    ):
        args.extend(("--project-aggregation", chart.project_aggregation))
    if isinstance(chart, (TimelineConfig, RankingConfig)) and (full or chart.other != "show"):
        args.extend(("--other", chart.other))
    if isinstance(chart, StackConfig) and (full or chart.cache != "combined"):
        args.extend(("--cache", chart.cache))
    for value in chart.filters.agents:
        args.extend(("--agent", value))
    for value in chart.filters.models:
        args.extend(("--model", value))
    for value in chart.filters.projects:
        args.extend(("--project", value))
    if not pane and not isinstance(chart, MonitorConfig):
        if not config.host.watch:
            args.append("--no-watch")
        elif full or config.host.interval != _default_interval(config):
            args.extend(("--interval", f"{config.host.interval:g}"))
    if not pane and config.host.demo_size is not None:
        args.extend(("--demo", config.host.demo_size))
    if full and not pane:
        args.extend(
            (
                "--ccusage-bin",
                config.process.ccusage_bin,
                "--query-timeout",
                f"{config.process.query_timeout:g}",
            )
        )
    theme = chart.presentation.theme
    if not config.host.ascii and (full or theme != "classic"):
        args.extend(("--theme", theme))
    default_style = compatible_styles(chart.kind, by)[0]
    if full or chart.presentation.style != default_style:
        args.extend(("--style", chart.presentation.style))
    if full or chart.presentation.density != "full":
        args.extend(("--density", chart.presentation.density))
    if chart.kind in {"timeline", "stack", "monitor"} and (
        full or chart.presentation.legend != "below-title"
    ):
        args.extend(("--legend", chart.presentation.legend))
    if not pane and config.host.ascii:
        args.append("--ascii")
    return args


def format_command(options: StandaloneLaunch) -> str:
    return shlex.join(["ccuv", *_chart_args(options, full=False)])


def format_full_command(options: StandaloneLaunch) -> str:
    return shlex.join(["ccuv", *_chart_args(options, full=True)])


def format_dashboard_pane_command(
    options: StandaloneLaunch, *, refresh_interval: float, sampling_interval: float | None = None
) -> str:
    interval = (
        sampling_interval
        if isinstance(options.chart, MonitorConfig) and sampling_interval is not None
        else refresh_interval
    )
    return format_command(
        replace(options, host=replace(options.host, interval=interval, watch=True))
    )


def format_full_dashboard_command(
    options: DashboardLaunch,
    panes: tuple[PaneConfig, ...] | None = None,
    *,
    grid: str | None = None,
    layout: str | None = None,
    column_weights: tuple[int, ...] | None = None,
    row_weights: tuple[int, ...] | None = None,
    header_style: str | None = None,
    dashboard_style: str | None = None,
    header_summary: str | None = None,
) -> str:
    host = options.host
    args = ["ccuv", "dashboard"]
    from ccusage_viz.configuration import standalone_from_pane

    for pane_config in panes or options.panes:
        args.extend(
            (
                "--pane",
                shlex.join(
                    _chart_args(standalone_from_pane(options, pane_config), full=True, pane=True)
                ),
            )
        )
    if layout is not None:
        args.extend(("--layout", layout))
    elif grid is not None:
        args.extend(("--grid", grid))
    elif host.layout is not None:
        args.extend(("--layout", host.layout))
    else:
        args.extend(("--grid", host.grid))
    args.extend(
        (
            "--refresh-interval",
            f"{host.refresh_interval:g}",
            "--sampling-interval",
            f"{host.sampling_interval:g}",
            "--header-style",
            header_style or host.header_style,
            "--header-summary",
            header_summary or host.header_summary,
            "--header-interval",
            f"{host.header_interval:g}",
            "--style",
            dashboard_style or host.style,
        )
    )
    for weight in column_weights if column_weights is not None else host.column_weights or ():
        args.extend(("--column-weight", str(weight)))
    for weight in row_weights if row_weights is not None else host.row_weights or ():
        args.extend(("--row-weight", str(weight)))
    if host.timezone is not None:
        args.extend(("--timezone", host.timezone))
    if host.demo_size is not None:
        args.extend(("--demo", host.demo_size))
    args.extend(
        (
            "--ccusage-bin",
            options.process.ccusage_bin,
            "--query-timeout",
            f"{options.process.query_timeout:g}",
        )
    )
    if host.ascii:
        args.append("--ascii")
    else:
        args.extend(("--theme", host.theme))
    return shlex.join(args)


def format_full_command_display(command: str, width: int) -> str:
    if width <= 0:
        return ""
    tokens = shlex.split(command)
    if len(tokens) <= 2:
        return command
    lines = [shlex.join(tokens[:2])]
    for start in range(2, len(tokens), 6):
        lines.append(shlex.join(tokens[start : start + 6]))
    return "\n".join(wrap_command(line, width) for line in lines)


def wrap_command(command: str, width: int) -> str:
    if width <= 0:
        return ""
    lines, line = [], ""
    for token in command.split(" "):
        candidate = token if not line else f"{line} {token}"
        if line and display_width(candidate) > width:
            lines.append(line)
            line = token
        else:
            line = candidate
        while display_width(line) > width:
            split_at = used = 0
            for index, char in enumerate(line):
                size = char_width(char)
                if used + size > width:
                    break
                used += size
                split_at = index + 1
            lines.append(line[:split_at])
            line = line[split_at:]
    if line:
        lines.append(line)
    return "\n".join(lines)


def copy_command(command: str) -> bool:
    executable = which("pbcopy")
    if executable is None:
        return False
    try:
        subprocess.run(
            [executable],
            input=command,
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True
