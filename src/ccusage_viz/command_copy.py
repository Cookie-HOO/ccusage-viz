from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import replace
from pathlib import PurePath
from shutil import which

from ccusage_viz.formatting import char_width, display_width
from ccusage_viz.options import DEFAULT_STYLES, CommandOptions

_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _is_private_path(value: str) -> bool:
    return (
        value.startswith(("/", "~"))
        or bool(_WINDOWS_PATH.match(value))
        or PurePath(value).is_absolute()
    )


def _window_duration(seconds: int | None) -> str:
    value = seconds or 3600
    unit = "h" if value % 3600 == 0 else "m"
    return f"{value // (3600 if unit == 'h' else 60)}{unit}"


def _format_args(args: list[str]) -> str:
    return shlex.join(args)


def format_command(options: CommandOptions) -> str:
    """Return a safe, reproducible public command for the active view."""
    args = ["ccuv", options.command]
    if options.command == "monitor":
        if options.window_seconds is not None:
            args.extend(("--window", _window_duration(options.window_seconds)))
        if options.interval is not None:
            args.extend(("--interval", f"{options.interval:g}"))
    else:
        if options.date_range.relative_until and options.date_range.period is not None:
            args.extend(("--period", options.date_range.period))
        else:
            args.extend(("--since", options.date_range.since.isoformat()))
            if not options.date_range.implicit_until:
                args.extend(("--until", options.date_range.until.isoformat()))
        if options.date_range.timezone:
            args.extend(("--timezone", options.date_range.timezone))
        if options.command in {"timeline", "stack"}:
            if options.granularity != "day":
                args.extend(("--granularity", options.granularity))
            if options.weekdays != "show":
                args.extend(("--weekdays", options.weekdays))
    if options.by is not None:
        args.extend(("--by", options.by))
    if options.top is not None:
        args.extend(("--top", str(options.top)))
    if options.command in {"timeline", "ranking"} and options.other != "show":
        args.extend(("--other", options.other))
    if options.command == "stack" and options.cache != "combined":
        args.extend(("--cache", options.cache))
    for agent in options.agents:
        args.extend(("--agent", agent))
    for model in options.models:
        args.extend(("--model", model))
    for project in options.projects:
        if not _is_private_path(project):
            args.extend(("--project", project))
    if options.command != "monitor":
        if options.no_watch:
            args.append("--no-watch")
        elif options.interval is not None and options.interval != 10.0:
            args.extend(("--interval", f"{options.interval:g}"))
    if options.demo is not None:
        args.extend(("--demo", options.demo))
    if options.color_scheme != "classic" and not options.ascii:
        args.extend(("--theme", options.color_scheme))
    if options.style != DEFAULT_STYLES[options.command]:
        args.extend(("--style", options.style))
    if options.legend != "below-title":
        args.extend(("--legend", options.legend))
    if options.ascii:
        args.append("--ascii")
    return _format_args(args)


def format_full_command(options: CommandOptions) -> str:
    """Return an executable command with every effective setting made explicit.

    Unlike :func:`format_command`, this deliberate audit view includes local
    project paths, the configured executable, and the query timeout.
    """
    args = ["ccuv", options.command]
    if options.command == "monitor":
        args.extend(("--window", _window_duration(options.window_seconds)))
        args.extend(("--interval", f"{(options.interval or 15.0):g}"))
    else:
        if options.date_range.relative_until and options.date_range.period is not None:
            args.extend(("--period", options.date_range.period))
        else:
            args.extend(("--since", options.date_range.since.isoformat()))
            args.extend(("--until", options.date_range.until.isoformat()))
        if options.date_range.timezone:
            args.extend(("--timezone", options.date_range.timezone))
        if options.command in {"timeline", "stack"}:
            args.extend(("--granularity", options.granularity))
            args.extend(("--weekdays", options.weekdays))
    if options.by is not None:
        args.extend(("--by", options.by))
    if options.top is not None:
        args.extend(("--top", str(options.top)))
    if options.command in {"timeline", "ranking"} and options.other != "show":
        args.extend(("--other", options.other))
    if options.command == "stack" and options.cache != "combined":
        args.extend(("--cache", options.cache))
    for agent in options.agents:
        args.extend(("--agent", agent))
    for model in options.models:
        args.extend(("--model", model))
    for project in options.projects:
        args.extend(("--project", project))
    if options.command != "monitor":
        if options.no_watch:
            args.append("--no-watch")
        elif options.interval is not None and options.interval != 10.0:
            args.extend(("--interval", f"{options.interval:g}"))
    if options.demo is not None:
        args.extend(("--demo", options.demo))
    args.extend(("--ccusage-bin", options.ccusage_bin))
    args.extend(("--query-timeout", f"{options.query_timeout:g}"))
    if not options.ascii:
        args.extend(("--theme", options.color_scheme))
    args.extend(("--style", options.style))
    if options.command in {"timeline", "stack", "monitor"}:
        args.extend(("--legend", options.legend))
    if options.ascii:
        args.append("--ascii")
    return _format_args(args)


def format_full_command_display(command: str, width: int) -> str:
    """Lay out a full command in short semantic lines without changing it."""
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
    """Wrap a normalized command at token boundaries for terminal display."""
    if width <= 0:
        return ""
    lines: list[str] = []
    line = ""
    for token in command.split(" "):
        candidate = token if not line else f"{line} {token}"
        if line and display_width(candidate) > width:
            lines.append(line)
            line = token
        else:
            line = candidate
        while display_width(line) > width:
            split_at = 0
            used = 0
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


def format_dashboard_pane_command(
    options: CommandOptions, *, refresh_interval: float | None
) -> str:
    """Serialize a Dashboard pane as its equivalent standalone live command."""
    if options.command == "monitor":
        return format_command(options)
    return format_command(replace(options, interval=refresh_interval or 15.0, no_watch=False))


def format_full_dashboard_command(
    options: CommandOptions,
    panels: tuple[CommandOptions, ...],
    *,
    grid: str,
    header_style: str,
    dashboard_style: str,
    header_summary: str = "day",
) -> str:
    """Serialize the complete Dashboard state, including local configuration."""
    args = ["ccuv", "dashboard"]
    for panel in panels:
        panel_args = shlex.split(format_full_command(panel))
        args.extend(("--panel", shlex.join(panel_args[1:])))
    args.extend(("--grid", grid))
    args.extend(("--header-style", header_style))
    args.extend(("--header-summary", header_summary))
    args.extend(("--header-interval", f"{options.header_interval:g}"))
    args.extend(("--style", dashboard_style))
    if options.demo is not None:
        args.extend(("--demo", options.demo))
    args.extend(("--ccusage-bin", options.ccusage_bin))
    args.extend(("--query-timeout", f"{options.query_timeout:g}"))
    if not options.ascii:
        args.extend(("--theme", options.color_scheme))
    if options.ascii:
        args.append("--ascii")
    return shlex.join(args)


def copy_command(command: str) -> bool:
    """Copy through a local clipboard program without invoking a shell."""
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
