from __future__ import annotations

import argparse
import math
import re
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from typing import Never

from ccusage_viz import __version__
from ccusage_viz.application import run
from ccusage_viz.dashboard import DEFAULT_DASHBOARD_PANELS
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.errors import UsageError, VizError
from ccusage_viz.i18n import Translator, detect_language, load_translator
from ccusage_viz.locales import CATALOGS
from ccusage_viz.options import (
    COMMAND_STYLES,
    DASHBOARD_STYLES,
    DEFAULT_STYLES,
    HEADER_SUMMARIES,
    CommandOptions,
    compatible_styles,
    resolve_date_range,
)
from ccusage_viz.render.palette import COLOR_SCHEMES

_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor", "dashboard")
_TUI_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor")
_DURATION_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>[mh])$")


class LocalizedParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise UsageError("error.arguments", detail=message)


def _preparse_language(argv: list[str]) -> tuple[str, str | None]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--lang", choices=("en", "zh"))
    parser.add_argument("--lang-file")
    namespace, _ = parser.parse_known_args(argv)
    return namespace.lang or detect_language(), namespace.lang_file


def _add_presentation(
    parser: argparse.ArgumentParser, tr: Translator, command: str, *, include_pick: bool = True
) -> None:
    parser.add_argument(
        "--demo",
        nargs="?",
        choices=("small", "medium", "large"),
        const="medium",
        help=tr.text("help.demo"),
    )
    if include_pick:
        parser.add_argument("--pick", action="store_true", help=tr.text("help.pick"))
    parser.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))
    parser.add_argument("--lang-file", type=Path, help=tr.text("help.lang_file"))
    parser.add_argument("--ccusage-bin", default="ccusage", help=tr.text("help.ccusage_bin"))
    parser.add_argument("--timeout", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--ascii", action="store_true", help=tr.text("help.ascii"))
    parser.add_argument(
        "--theme",
        dest="color_scheme",
        choices=COLOR_SCHEMES,
        default="classic",
        help=tr.text("help.theme"),
    )
    parser.add_argument(
        "--style",
        choices=COMMAND_STYLES[command],
        default=DEFAULT_STYLES[command],
        help=tr.text("help.style"),
    )
    if command in {"timeline", "monitor", "stack"}:
        parser.add_argument(
            "--legend-position",
            choices=("below-title", "hidden")
            if command == "stack"
            else ("below-title", "inside", "hidden", "values")
            if command == "monitor"
            else ("below-title", "inside", "hidden"),
            default="below-title",
            help=tr.text("help.legend_position"),
        )


def _add_history_shared(
    parser: argparse.ArgumentParser,
    tr: Translator,
    command: str,
    *,
    include_summary: bool = False,
) -> None:
    parser.add_argument("--period", help=tr.text("help.period"))
    parser.add_argument("--since", help=tr.text("help.since"))
    parser.add_argument("--until", help=tr.text("help.until"))
    parser.add_argument("--timezone", help=tr.text("help.timezone"))
    if command in {"timeline", "stack"}:
        parser.add_argument(
            "--aggregate",
            choices=("day", "month", "quarter", "year"),
            default="day",
            help=tr.text("help.aggregate"),
        )
        parser.add_argument(
            "--weekdays",
            choices=("auto", "show", "hidden"),
            default="auto",
            help=tr.text("help.weekdays"),
        )
    parser.add_argument("--agent", action="append", default=[], help=tr.text("help.agent"))
    parser.add_argument("--model", action="append", default=[], help=tr.text("help.model"))
    parser.add_argument("--project", action="append", default=[], help=tr.text("help.project"))
    if include_summary:
        parser.add_argument("--no-summary", action="store_true", help=tr.text("help.no_summary"))
    parser.add_argument(
        "--watch",
        nargs="?",
        type=float,
        const=5.0,
        metavar="SECONDS",
        help=tr.text("help.watch"),
    )
    _add_presentation(parser, tr, command)


def _add_tui(parser: argparse.ArgumentParser, tr: Translator) -> None:
    parser.add_argument(
        "--panel", dest="panels", action="append", default=[], help=tr.text("help.panel")
    )
    parser.add_argument("--grid", default="2x2", help=tr.text("help.grid"))
    parser.add_argument("--interval", type=float, default=15.0, help=tr.text("help.interval"))
    parser.add_argument(
        "--header-style",
        choices=("hidden", "compact", "banner", "panel"),
        default="panel",
        help=tr.text("help.header_style"),
    )
    parser.add_argument(
        "--header-summary",
        choices=HEADER_SUMMARIES,
        default="day",
        help=tr.text("help.header_summary"),
    )
    parser.add_argument(
        "--header-interval", type=float, default=60.0, help=tr.text("help.header_interval")
    )
    parser.add_argument(
        "--style",
        dest="dashboard_style",
        choices=DASHBOARD_STYLES,
        default="split",
        help=tr.text("help.style"),
    )
    parser.add_argument(
        "--demo",
        nargs="?",
        choices=("small", "medium", "large"),
        const="medium",
        help=tr.text("help.demo"),
    )
    parser.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))
    parser.add_argument("--lang-file", type=Path, help=tr.text("help.lang_file"))
    parser.add_argument("--ccusage-bin", default="ccusage", help=tr.text("help.ccusage_bin"))
    parser.add_argument("--timeout", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--ascii", action="store_true", help=tr.text("help.ascii"))
    parser.add_argument(
        "--theme",
        dest="color_scheme",
        choices=COLOR_SCHEMES,
        default="classic",
        help=tr.text("help.theme"),
    )


def _add_monitor(parser: argparse.ArgumentParser, tr: Translator) -> None:
    parser.add_argument("--window", default="1h", metavar="DURATION", help=tr.text("help.window"))
    parser.add_argument(
        "--interval", type=float, default=None, metavar="SECONDS", help=tr.text("help.interval")
    )
    parser.add_argument(
        "--by", choices=("agent", "model", "project"), help=tr.text("help.monitor_by")
    )
    parser.add_argument("--top", type=int, help=tr.text("help.monitor_top"))
    parser.add_argument("--agent", action="append", default=[], help=tr.text("help.agent"))
    parser.add_argument("--model", action="append", default=[], help=tr.text("help.model"))
    parser.add_argument("--project", action="append", default=[], help=tr.text("help.project"))
    _add_presentation(parser, tr, "monitor", include_pick=False)
    # Grouped monitor views need a line-compatible default rather than the
    # ungrouped Total mode's bar default.
    parser.set_defaults(style=None)
    parser.add_argument("--pick", action="store_true", help=argparse.SUPPRESS)


def build_parser(tr: Translator) -> argparse.ArgumentParser:
    parser = LocalizedParser(description=tr.text("app.description"))
    parser.add_argument("--version", action="version", version=f"ccusage-viz {__version__}")
    subparsers = parser.add_subparsers(
        dest="command", metavar="COMMAND", help=tr.text("help.command")
    )

    timeline = subparsers.add_parser(
        "timeline", help=tr.text("help.timeline"), description=tr.text("help.timeline")
    )
    _add_history_shared(timeline, tr, "timeline", include_summary=True)
    timeline.add_argument(
        "--by",
        choices=("total", "agent", "model", "project"),
        default="total",
        help=tr.text("help.by"),
    )
    timeline.add_argument("--top", type=int, default=None, help=tr.text("help.top"))
    timeline.add_argument("--show-other", action="store_true", help=tr.text("help.show_other"))

    calendar = subparsers.add_parser(
        "calendar", help=tr.text("help.calendar"), description=tr.text("help.calendar")
    )
    _add_history_shared(calendar, tr, "calendar", include_summary=True)

    stack = subparsers.add_parser(
        "stack", help=tr.text("help.stack"), description=tr.text("help.stack")
    )
    _add_history_shared(stack, tr, "stack", include_summary=True)
    stack.add_argument("--split-cache", action="store_true", help=tr.text("help.split_cache"))

    ranking = subparsers.add_parser(
        "ranking", help=tr.text("help.ranking"), description=tr.text("help.ranking")
    )
    _add_history_shared(ranking, tr, "ranking", include_summary=True)
    ranking.add_argument(
        "--by", choices=("agent", "model", "project"), default="project", help=tr.text("help.by")
    )
    ranking.add_argument("--top", type=int, default=10, help=tr.text("help.top"))
    ranking.add_argument("--show-other", action="store_true", help=tr.text("help.show_other"))

    monitor = subparsers.add_parser(
        "monitor", help=tr.text("help.monitor"), description=tr.text("help.monitor")
    )
    _add_monitor(monitor, tr)

    tui = subparsers.add_parser(
        "dashboard", help=tr.text("help.dashboard"), description=tr.text("help.dashboard")
    )
    _add_tui(tui, tr)

    return parser


def _parse_window(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise UsageError("error.window_invalid", value=value)
    seconds = int(match["value"]) * (60 if match["unit"] == "m" else 3600)
    if not 5 * 60 <= seconds <= 24 * 3600:
        raise UsageError("error.window_range")
    return seconds


def _inject_default_command(argv: list[str]) -> list[str]:
    if not argv:
        return ["timeline"]
    if argv[0] in _COMMANDS or argv[0] in {"-h", "--help", "--version"}:
        return argv
    leading: list[str] = []
    remaining = list(argv)
    while remaining and remaining[0] in {"--lang", "--lang-file"}:
        if len(remaining) < 2:
            return ["timeline", *argv]
        leading.extend(remaining[:2])
        remaining = remaining[2:]
    if remaining and remaining[0] in _COMMANDS:
        return [remaining[0], *leading, *remaining[1:]]
    return ["timeline", *argv]


def _to_options(namespace: argparse.Namespace) -> CommandOptions:
    command = namespace.command or "timeline"
    if command == "dashboard":
        if not namespace.panels:
            namespace.panels = list(DEFAULT_DASHBOARD_PANELS)
        parsed_panels = []
        for fragment in namespace.panels:
            try:
                tokens = shlex.split(fragment)
            except ValueError as exc:
                raise UsageError("error.tui_panel", value=fragment) from exc
            if not tokens or tokens[0] not in _TUI_COMMANDS:
                raise UsageError("error.tui_panel", value=fragment)
            parsed_panels.append(fragment)
        namespace.panels = parsed_panels
        if namespace.grid != "auto":
            try:
                rows, columns = (int(item) for item in namespace.grid.lower().split("x", 1))
            except (ValueError, AttributeError):
                raise UsageError("error.tui_grid", value=namespace.grid) from None
            if rows < 1 or columns < 1 or rows * columns < len(namespace.panels):
                raise UsageError("error.tui_grid", value=namespace.grid)
        if not math.isfinite(namespace.interval) or namespace.interval < 1:
            raise UsageError("error.interval_min", minimum=1)
        if not math.isfinite(namespace.header_interval) or namespace.header_interval < 1:
            raise UsageError("error.interval_min", minimum=1)
        if not math.isfinite(namespace.timeout) or namespace.timeout <= 0:
            raise UsageError("error.arguments", detail="--timeout must be positive and finite")
        return CommandOptions(
            command="dashboard",
            date_range=resolve_date_range(
                "timeline", period="14d", since=None, until=None, timezone=None
            ),
            by=None,
            top=None,
            show_other=False,
            split_cache=False,
            agents=(),
            models=(),
            projects=(),
            watch=None,
            demo=namespace.demo,
            ccusage_bin=namespace.ccusage_bin,
            timeout=namespace.timeout,
            no_color=namespace.color_scheme == "no-color",
            ascii=namespace.ascii,
            color_scheme=namespace.color_scheme,
            panels=tuple(namespace.panels),
            grid=namespace.grid,
            interval=namespace.interval,
            header_style=namespace.header_style,
            header_summary=namespace.header_summary,
            header_interval=namespace.header_interval,
            dashboard_style=namespace.dashboard_style,
        )
    if command == "monitor" and getattr(namespace, "pick", False):
        raise UsageError(
            "error.monitor_demo_pick" if namespace.demo is not None else "error.monitor_pick"
        )
    top = getattr(namespace, "top", None)
    if command == "timeline" and namespace.by != "total" and top is None:
        top = 3
        namespace.show_other = True
    if command == "monitor" and namespace.by in {"agent", "model", "project"} and top is None:
        top = 3
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    if command == "timeline" and top is not None and namespace.by == "total":
        raise UsageError("error.top_requires_by")
    if (
        command == "monitor"
        and top is not None
        and namespace.by not in {"agent", "model", "project"}
    ):
        raise UsageError("error.top_requires_by")
    if getattr(namespace, "show_other", False) and (
        top is None or (command == "timeline" and namespace.by == "total")
    ):
        raise UsageError("error.show_other_requires_top")
    requested_style = getattr(namespace, "style", None)
    style = requested_style or compatible_styles(command, getattr(namespace, "by", None))[0]
    if style not in compatible_styles(command, getattr(namespace, "by", None)):
        raise UsageError("error.style_incompatible", style=style, mode=namespace.by or "total")
    watch = getattr(namespace, "watch", None)
    if watch is not None and (not math.isfinite(watch) or watch < 2):
        raise UsageError("error.watch_min", minimum=2)
    requested_interval = getattr(namespace, "interval", None)
    interval = requested_interval
    if command == "monitor" and interval is None:
        interval = 1.0 if namespace.demo is not None else 15.0
    interval_minimum = 1 if command == "monitor" and namespace.demo is not None else 5
    if interval is not None and (not math.isfinite(interval) or interval < interval_minimum):
        raise UsageError("error.interval_min", minimum=interval_minimum)
    if not math.isfinite(namespace.timeout) or namespace.timeout <= 0:
        raise UsageError("error.arguments", detail="--timeout must be positive and finite")
    if command == "monitor":
        window_seconds = _parse_window(namespace.window)
        date_range = resolve_date_range(
            "timeline", period="1d", since=None, until=None, timezone=None
        )
    else:
        window_seconds = None
        aggregation = getattr(namespace, "aggregate", "day")
        date_range = resolve_date_range(
            command,
            period=namespace.period,
            since=namespace.since,
            until=namespace.until,
            timezone=namespace.timezone,
            aggregation=aggregation,
        )
    return CommandOptions(
        command=command,
        date_range=date_range,
        by=getattr(namespace, "by", None),
        top=top,
        show_other=getattr(namespace, "show_other", False),
        split_cache=getattr(namespace, "split_cache", False),
        agents=tuple(namespace.agent),
        models=tuple(namespace.model),
        projects=tuple(getattr(namespace, "project", ())),
        watch=watch,
        demo=namespace.demo,
        ccusage_bin=namespace.ccusage_bin,
        timeout=namespace.timeout,
        no_color=namespace.color_scheme == "no-color",
        ascii=namespace.ascii,
        color_scheme=namespace.color_scheme,
        style=style,
        pick=getattr(namespace, "pick", False),
        window_seconds=window_seconds,
        interval=interval,
        no_summary=getattr(namespace, "no_summary", False),
        legend_position=getattr(namespace, "legend_position", "below-title"),
        aggregation=getattr(namespace, "aggregate", "day"),
        weekday_mode=getattr(namespace, "weekdays", "auto"),
    )


def main(argv: list[str] | None = None) -> int:
    args = _inject_default_command(list(sys.argv[1:] if argv is None else argv))
    ccusage_bin_explicit = any(
        argument == "--ccusage-bin" or argument.startswith("--ccusage-bin=") for argument in args
    )
    language, lang_file = _preparse_language(args)
    builtin = Translator(language, dict(CATALOGS[language]))
    tr = builtin
    try:
        tr = load_translator(language, lang_file)
        parser = build_parser(tr)
        namespace = parser.parse_args(args)
        options = replace(_to_options(namespace), ccusage_bin_explicit=ccusage_bin_explicit)
        return run(options, tr)
    except VizError as exc:
        error_translator = builtin if exc.key.startswith("error.lang_file_") else tr
        text = format_error(
            exc,
            error_translator,
            color=color_enabled(
                sys.stderr,
                no_color=getattr(locals().get("namespace"), "color_scheme", "classic")
                == "no-color",
            ),
            color_scheme=getattr(locals().get("namespace"), "color_scheme", "classic"),
        )
        print(text, file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
