from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import PurePath
from shutil import which

from ccusage_viz.options import DEFAULT_STYLES, CommandOptions

_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _is_private_path(value: str) -> bool:
    return (
        value.startswith(("/", "~"))
        or bool(_WINDOWS_PATH.match(value))
        or PurePath(value).is_absolute()
    )


def format_command(options: CommandOptions) -> str:
    """Return a safe, reproducible public command for the active view."""
    args = ["ccusage-viz", options.command]
    if options.command == "monitor":
        if options.window_seconds is not None:
            unit = "h" if options.window_seconds % 3600 == 0 else "m"
            value = options.window_seconds // (3600 if unit == "h" else 60)
            args.extend(("--window", f"{value}{unit}"))
        if options.interval is not None:
            args.extend(("--interval", f"{options.interval:g}"))
    else:
        args.extend(
            (
                "--since",
                options.date_range.since.isoformat(),
                "--until",
                options.date_range.until.isoformat(),
            )
        )
        if options.date_range.timezone:
            args.extend(("--timezone", options.date_range.timezone))
    if options.by is not None:
        args.extend(("--by", options.by))
    if options.top is not None:
        args.extend(("--top", str(options.top)))
    if options.show_other:
        args.append("--show-other")
    if options.split_cache:
        args.append("--split-cache")
    if options.no_summary:
        args.append("--no-summary")
    for agent in options.agents:
        args.extend(("--agent", agent))
    for model in options.models:
        args.extend(("--model", model))
    for project in options.projects:
        if not _is_private_path(project):
            args.extend(("--project", project))
    if options.watch is not None:
        args.extend(("--watch", f"{options.watch:g}"))
    if options.demo is not None:
        args.extend(("--demo", options.demo))
    if options.color_scheme != "classic":
        args.extend(("--theme", options.color_scheme))
    if options.style != DEFAULT_STYLES[options.command]:
        args.extend(("--style", options.style))
    if options.legend_position != "below-title":
        args.extend(("--legend-position", options.legend_position))
    if options.ascii:
        args.append("--ascii")
    if options.no_color:
        args.append("--no-color")
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
