from __future__ import annotations

import argparse
import math
import re
import shlex
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Never

from ccusage_viz import __version__
from ccusage_viz.application import run
from ccusage_viz.dashboard import DEFAULT_DASHBOARD_PANELS
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.errors import UsageError, VizError
from ccusage_viz.i18n import Translator, detect_language, load_translator
from ccusage_viz.options import (
    CACHE_MODES,
    COMMAND_STYLES,
    DASHBOARD_STYLES,
    DEFAULT_STYLES,
    GRANULARITIES,
    HEADER_SUMMARIES,
    OTHER_MODES,
    WEEKDAY_MODES,
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


class ShortCircuitKind(StrEnum):
    HELP = "help"
    VERSION = "version"


@dataclass(frozen=True, slots=True)
class ShortCircuitRoute:
    kind: ShortCircuitKind
    command: str | None = None
    language: str | None = None


def probe_short_circuit(argv: list[str]) -> ShortCircuitRoute | None:
    """Identify side-effect-free routes before configuration or runtime setup."""
    if argv == ["--version"]:
        return ShortCircuitRoute(ShortCircuitKind.VERSION)
    help_flags = {"-h", "--help"}
    if not any(argument in help_flags for argument in argv):
        return None
    command = next((argument for argument in argv if argument in _COMMANDS), None)
    language = None
    for index, argument in enumerate(argv[:-1]):
        if argument == "--lang" and argv[index + 1] in {"en", "zh"}:
            language = argv[index + 1]
            break
    return ShortCircuitRoute(ShortCircuitKind.HELP, command, language)


def _render_short_circuit(route: ShortCircuitRoute) -> int:
    if route.kind is ShortCircuitKind.VERSION:
        print(f"ccusage-viz {__version__}")
        return 0
    tr = load_translator(route.language or detect_language())
    parser = build_parser(tr)
    parser.parse_args([route.command, "--help"] if route.command else ["--help"])
    raise AssertionError("argparse help did not exit")


def _preparse_language(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--lang", choices=("en", "zh"))
    namespace, _ = parser.parse_known_args(argv)
    return namespace.lang or detect_language()


def _add_presentation(parser: argparse.ArgumentParser, tr: Translator, command: str) -> None:
    parser.add_argument(
        "--demo",
        nargs="?",
        choices=("small", "medium", "large"),
        const="medium",
        help=tr.text("help.demo"),
    )
    parser.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))
    parser.add_argument("--ccusage-bin", default="ccusage", help=tr.text("help.ccusage_bin"))
    parser.add_argument("--query-timeout", type=float, default=30.0, help=argparse.SUPPRESS)
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
            "--legend",
            choices=("below-title", "hidden")
            if command == "stack"
            else ("below-title", "inside", "hidden", "values")
            if command == "monitor"
            else ("below-title", "inside", "hidden"),
            default="below-title",
            help=tr.text("help.legend"),
        )


def _add_history_shared(
    parser: argparse.ArgumentParser,
    tr: Translator,
    command: str,
) -> None:
    parser.add_argument("--period", help=tr.text("help.period"))
    parser.add_argument("--since", help=tr.text("help.since"))
    parser.add_argument("--until", help=tr.text("help.until"))
    parser.add_argument("--timezone", help=tr.text("help.timezone"))
    if command in {"timeline", "stack"}:
        parser.add_argument(
            "--granularity",
            choices=GRANULARITIES,
            default="day",
            help=tr.text("help.granularity"),
        )
        parser.add_argument(
            "--weekdays",
            choices=WEEKDAY_MODES,
            default="show",
            help=tr.text("help.weekdays"),
        )
    parser.add_argument("--agent", action="append", default=[], help=tr.text("help.agent"))
    parser.add_argument("--model", action="append", default=[], help=tr.text("help.model"))
    parser.add_argument("--project", action="append", default=[], help=tr.text("help.project"))
    parser.add_argument(
        "--interval", type=float, default=10.0, metavar="SECONDS", help=tr.text("help.interval")
    )
    parser.add_argument("--no-watch", action="store_true", help=tr.text("help.no_watch"))
    _add_presentation(parser, tr, command)


def _add_tui(parser: argparse.ArgumentParser, tr: Translator) -> None:
    parser.add_argument(
        "--panel", dest="panels", action="append", default=[], help=tr.text("help.panel")
    )
    parser.add_argument("--grid", default="2x2", help=tr.text("help.grid"))
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
    parser.add_argument("--ccusage-bin", default="ccusage", help=tr.text("help.ccusage_bin"))
    parser.add_argument("--query-timeout", type=float, default=30.0, help=argparse.SUPPRESS)
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
    parser.add_argument("--no-watch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--by", choices=("agent", "model", "project"), help=tr.text("help.monitor_by")
    )
    parser.add_argument("--top", type=int, help=tr.text("help.monitor_top"))
    parser.add_argument("--agent", action="append", default=[], help=tr.text("help.agent"))
    parser.add_argument("--model", action="append", default=[], help=tr.text("help.model"))
    parser.add_argument("--project", action="append", default=[], help=tr.text("help.project"))
    _add_presentation(parser, tr, "monitor")
    # Grouped monitor views need a line-compatible default rather than the
    # ungrouped Total mode's bar default.
    parser.set_defaults(style=None)


def build_parser(tr: Translator) -> argparse.ArgumentParser:
    parser = LocalizedParser(description=tr.text("app.description"))
    parser.add_argument("--version", action="version", version=f"ccusage-viz {__version__}")
    subparsers = parser.add_subparsers(
        dest="command", metavar="COMMAND", help=tr.text("help.command")
    )

    timeline = subparsers.add_parser(
        "timeline", help=tr.text("help.timeline"), description=tr.text("help.timeline")
    )
    _add_history_shared(timeline, tr, "timeline")
    timeline.add_argument(
        "--by",
        choices=("agent", "model", "project"),
        default=None,
        help=tr.text("help.by"),
    )
    timeline.add_argument("--top", type=int, default=None, help=tr.text("help.top"))
    timeline.add_argument(
        "--other", choices=OTHER_MODES, default="show", help=tr.text("help.other")
    )

    calendar = subparsers.add_parser(
        "calendar", help=tr.text("help.calendar"), description=tr.text("help.calendar")
    )
    _add_history_shared(calendar, tr, "calendar")

    stack = subparsers.add_parser(
        "stack", help=tr.text("help.stack"), description=tr.text("help.stack")
    )
    _add_history_shared(stack, tr, "stack")
    stack.add_argument(
        "--cache", choices=CACHE_MODES, default="combined", help=tr.text("help.cache")
    )

    ranking = subparsers.add_parser(
        "ranking", help=tr.text("help.ranking"), description=tr.text("help.ranking")
    )
    _add_history_shared(ranking, tr, "ranking")
    ranking.add_argument(
        "--by", choices=("agent", "model", "project"), default="project", help=tr.text("help.by")
    )
    ranking.add_argument("--top", type=int, default=10, help=tr.text("help.top"))
    ranking.add_argument("--other", choices=OTHER_MODES, default="show", help=tr.text("help.other"))

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
    while remaining and remaining[0] == "--lang":
        if len(remaining) < 2:
            return ["timeline", *argv]
        leading.extend(remaining[:2])
        remaining = remaining[2:]
    if remaining and remaining[0] in _COMMANDS:
        return [remaining[0], *leading, *remaining[1:]]
    return ["timeline", *argv]


def _to_options(
    namespace: argparse.Namespace, *, explicit: frozenset[str] = frozenset()
) -> CommandOptions:
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
        if not math.isfinite(namespace.header_interval) or namespace.header_interval < 1:
            raise UsageError("error.interval_min", minimum=1)
        if not math.isfinite(namespace.query_timeout) or namespace.query_timeout <= 0:
            raise UsageError(
                "error.arguments", detail="--query-timeout must be positive and finite"
            )
        return CommandOptions(
            command="dashboard",
            date_range=resolve_date_range(
                "timeline", period="14d", since=None, until=None, timezone=None
            ),
            by=None,
            top=None,
            other="show",
            cache="combined",
            agents=(),
            models=(),
            projects=(),
            demo=namespace.demo,
            ccusage_bin=namespace.ccusage_bin,
            query_timeout=namespace.query_timeout,
            no_color=namespace.color_scheme == "no-color",
            ascii=namespace.ascii,
            color_scheme=namespace.color_scheme,
            panes=tuple(namespace.panels),
            grid=namespace.grid,
            interval=15.0,
            header_style=namespace.header_style,
            header_summary=namespace.header_summary,
            header_interval=namespace.header_interval,
            dashboard_style=namespace.dashboard_style,
            explicit=explicit,
        )
    top = getattr(namespace, "top", None)
    if command == "timeline" and namespace.by is not None and top is None:
        top = 3
    if command == "monitor" and namespace.by in {"agent", "model", "project"} and top is None:
        top = 3
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    if command == "timeline" and top is not None and namespace.by is None:
        raise UsageError("error.top_requires_by")
    if (
        command == "monitor"
        and top is not None
        and namespace.by not in {"agent", "model", "project"}
    ):
        raise UsageError("error.top_requires_by")
    requested_style = getattr(namespace, "style", None)
    style = requested_style or compatible_styles(command, getattr(namespace, "by", None))[0]
    if style not in compatible_styles(command, getattr(namespace, "by", None)):
        raise UsageError("error.style_incompatible", style=style, mode=namespace.by or "total")
    no_watch = getattr(namespace, "no_watch", False)
    requested_interval = getattr(namespace, "interval", None)
    if no_watch and "interval" in explicit:
        raise UsageError("error.arguments", detail="--interval cannot be combined with --no-watch")
    if command == "monitor" and no_watch:
        raise UsageError("error.arguments", detail="monitor does not support --no-watch")
    interval = requested_interval
    if command == "monitor" and interval is None:
        interval = 1.0 if namespace.demo is not None else 15.0
    interval_minimum = (
        1
        if command == "monitor" and namespace.demo is not None
        else 5
        if command == "monitor"
        else 2
    )
    if interval is not None and (not math.isfinite(interval) or interval < interval_minimum):
        raise UsageError("error.interval_min", minimum=interval_minimum)
    if not math.isfinite(namespace.query_timeout) or namespace.query_timeout <= 0:
        raise UsageError("error.arguments", detail="--query-timeout must be positive and finite")
    if command == "monitor":
        window_seconds = _parse_window(namespace.window)
        date_range = resolve_date_range(
            "timeline", period="1d", since=None, until=None, timezone=None
        )
    else:
        window_seconds = None
        date_range = resolve_date_range(
            command,
            period=namespace.period,
            since=namespace.since,
            until=namespace.until,
            timezone=namespace.timezone,
        )
    return CommandOptions(
        command=command,
        date_range=date_range,
        by=getattr(namespace, "by", None),
        top=top,
        other=getattr(namespace, "other", "show"),
        cache=getattr(namespace, "cache", "combined"),
        agents=tuple(namespace.agent),
        models=tuple(namespace.model),
        projects=tuple(getattr(namespace, "project", ())),
        demo=namespace.demo,
        ccusage_bin=namespace.ccusage_bin,
        query_timeout=namespace.query_timeout,
        no_color=namespace.color_scheme == "no-color",
        ascii=namespace.ascii,
        color_scheme=namespace.color_scheme,
        style=style,
        window_seconds=window_seconds,
        interval=interval,
        legend=getattr(namespace, "legend", "below-title"),
        granularity=getattr(namespace, "granularity", "day"),
        weekdays=getattr(namespace, "weekdays", "show"),
        no_watch=no_watch,
        explicit=explicit,
    )


def _explicit_fields(argv: list[str]) -> frozenset[str]:
    fields = set()
    for argument in argv:
        if not argument.startswith("--"):
            continue
        name = argument[2:].split("=", 1)[0].replace("-", "_")
        fields.add("color_scheme" if name == "theme" else name)
    return frozenset(fields)


def _validate_configuration(options: CommandOptions) -> None:
    if options.ascii and options.was_explicit("color_scheme"):
        raise UsageError(
            "error.arguments", detail="--ascii cannot be combined with an explicit --theme"
        )


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    short_circuit = probe_short_circuit(raw_args)
    if short_circuit is not None:
        return _render_short_circuit(short_circuit)
    args = _inject_default_command(raw_args)
    explicit = _explicit_fields(args)
    language = _preparse_language(args)
    tr = load_translator(language)
    try:
        parser = build_parser(tr)
        namespace = parser.parse_args(args)
        options = _to_options(namespace, explicit=explicit)
        _validate_configuration(options)
        return run(options, tr)
    except VizError as exc:
        text = format_error(
            exc,
            tr,
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
