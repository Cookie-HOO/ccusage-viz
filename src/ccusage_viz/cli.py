from __future__ import annotations

import argparse
import math
import os
import re
import secrets
import shlex
import sys
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Never, cast

from ccusage_viz import __version__
from ccusage_viz.animation import animation_spec, default_animation_spec
from ccusage_viz.animation_overlay import OVERLAY_COLORS, OVERLAY_POSITIONS, OverlayConfig
from ccusage_viz.application import run
from ccusage_viz.core.time import system_timezone, validate_timezone
from ccusage_viz.dashboard import DASHBOARD_PRESETS
from ccusage_viz.dashboard_layout import (
    NAMED_LAYOUTS,
    fixed_shape,
    layout_bands,
    layout_for_pane_count,
    parse_grid,
    parse_layout,
    reconcile_weights,
)
from ccusage_viz.diagnostics import color_enabled, format_error
from ccusage_viz.errors import UsageError, VizError
from ccusage_viz.i18n import Translator, detect_language, load_translator
from ccusage_viz.locales import CATALOGS
from ccusage_viz.options import (
    CACHE_MODES,
    COMMAND_STYLES,
    DASHBOARD_STYLES,
    DEFAULT_STYLES,
    DENSITIES,
    GRANULARITIES,
    HEADER_SUMMARIES,
    OTHER_MODES,
    PROJECT_AGGREGATIONS,
    WEEKDAY_MODES,
    AnimationLaunch,
    AnimationPaneConfig,
    AnimationRoute,
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardHostConfig,
    DashboardLaunch,
    DashboardRoute,
    Density,
    EmptyPaneConfig,
    Filters,
    LaunchConfig,
    LaunchRoute,
    MonitorConfig,
    PaneConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    StandaloneRoute,
    TimelineConfig,
    compatible_styles,
    resolve_date_range,
)
from ccusage_viz.render.palette import COLOR_SCHEMES

_COMMANDS = (
    "timeline",
    "calendar",
    "stack",
    "ranking",
    "monitor",
    "dashboard",
    "animate",
    "custom",
    "datasets",
    "text",
)
_TUI_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor")
_CUSTOM_COMMANDS = ("timeline", "calendar", "stack", "ranking")
_DURATION_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>[mh])$")
_PANE_FORBIDDEN_OPTIONS = frozenset(
    {
        "--interval",
        "--no-watch",
        "--watch",
        "--ascii",
        "--demo",
        "--lang",
        "--ccusage-bin",
        "--query-timeout",
        "--timezone",
        "--pane",
        "--grid",
        "--refresh-interval",
        "--sampling-interval",
        "--header-style",
        "--header-summary",
        "--header-interval",
        "--help",
        "--version",
        "-h",
    }
)


class LocalizedParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

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
    parser.add_argument("--demo-seed", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))
    parser.add_argument("--ccusage-bin", default="ccusage", help=tr.text("help.ccusage_bin"))
    parser.add_argument("--query-timeout", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--timezone", metavar="AREA/LOCATION", help=tr.text("help.timezone"))
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
    parser.add_argument(
        "--density",
        choices=DENSITIES,
        default="detailed",
        help=tr.text("help.density"),
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
        "--pane", dest="panes", action="append", default=[], help=tr.text("help.pane")
    )
    parser.add_argument("--grid", help=tr.text("help.grid"))
    parser.add_argument(
        "--layout", choices=tuple(sorted(NAMED_LAYOUTS)), help=tr.text("help.layout")
    )
    parser.add_argument(
        "--column-weight",
        dest="column_weights",
        action="append",
        type=int,
        default=[],
        metavar="WEIGHT",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--row-weight",
        dest="row_weights",
        action="append",
        type=int,
        default=[],
        metavar="WEIGHT",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=15.0,
        help=tr.text("help.refresh_interval"),
    )
    parser.add_argument(
        "--sampling-interval",
        type=float,
        default=15.0,
        help=tr.text("help.sampling_interval"),
    )
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
    parser.add_argument("--demo-seed", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))
    parser.add_argument("--ccusage-bin", default="ccusage", help=tr.text("help.ccusage_bin"))
    parser.add_argument("--query-timeout", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--timezone", metavar="AREA/LOCATION", help=tr.text("help.timezone"))
    parser.add_argument("--ascii", action="store_true", help=tr.text("help.ascii"))
    parser.add_argument(
        "--theme",
        dest="color_scheme",
        choices=COLOR_SCHEMES,
        default="classic",
        help=tr.text("help.theme"),
    )


def _add_custom_history(parser: argparse.ArgumentParser, tr: Translator, command: str) -> None:
    parser.add_argument("--dataset", required=True, metavar="ID")
    parser.add_argument("--command", dest="command_text", metavar="TEXT")
    parser.add_argument("--period", help=tr.text("help.period"))
    parser.add_argument("--since", help=tr.text("help.since"))
    parser.add_argument("--until", help=tr.text("help.until"))
    parser.add_argument(
        "--filter", dest="custom_filters", action="append", default=[], metavar="ID=OPTION"
    )
    parser.add_argument("--group-by")
    if command in {"timeline", "stack"}:
        parser.add_argument("--granularity", choices=GRANULARITIES, default="day")
        parser.add_argument("--weekdays", choices=WEEKDAY_MODES, default="show")
    if command in {"timeline", "ranking"}:
        parser.add_argument("--top", type=int, default=None, help=tr.text("help.top"))
        parser.add_argument(
            "--other", choices=OTHER_MODES, default="show", help=tr.text("help.other")
        )
    _add_presentation(parser, tr, command)


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
    parser.add_argument(
        "--project-aggregation",
        choices=PROJECT_AGGREGATIONS,
        default="name",
        help=tr.text("help.project_aggregation"),
    )
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
        "--project-aggregation",
        choices=PROJECT_AGGREGATIONS,
        default="name",
        help=tr.text("help.project_aggregation"),
    )
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
    ranking.add_argument(
        "--project-aggregation",
        choices=PROJECT_AGGREGATIONS,
        default="name",
        help=tr.text("help.project_aggregation"),
    )
    ranking.add_argument("--other", choices=OTHER_MODES, default="show", help=tr.text("help.other"))

    monitor = subparsers.add_parser(
        "monitor", help=tr.text("help.monitor"), description=tr.text("help.monitor")
    )
    _add_monitor(monitor, tr)

    tui = subparsers.add_parser(
        "dashboard", help=tr.text("help.dashboard"), description=tr.text("help.dashboard")
    )
    tui.add_argument(
        "preset",
        nargs="?",
        choices=tuple(DASHBOARD_PRESETS),
        help=tr.text("help.dashboard_preset"),
    )
    tui.add_argument("--empty", action="store_true", help=argparse.SUPPRESS)
    _add_tui(tui, tr)

    custom = subparsers.add_parser("custom", help="Render a custom command-backed chart")
    custom_subparsers = custom.add_subparsers(dest="custom_kind", required=True, metavar="COMMAND")
    for command in _CUSTOM_COMMANDS:
        custom_parser = custom_subparsers.add_parser(command)
        _add_custom_history(custom_parser, tr, command)

    datasets = subparsers.add_parser(
        "datasets", help=tr.text("help.datasets"), description=tr.text("help.datasets")
    )
    dataset_subparsers = datasets.add_subparsers(
        dest="datasets_command", required=True, metavar="COMMAND"
    )
    dataset_subparsers.add_parser("list", help=tr.text("help.datasets_list"))
    show = dataset_subparsers.add_parser("show", help=tr.text("help.datasets_show"))
    show.add_argument("dataset_id", metavar="ID")
    status = dataset_subparsers.add_parser("status", help=tr.text("help.datasets_status"))
    status.add_argument("dataset_id", nargs="?", metavar="ID")
    remove = dataset_subparsers.add_parser("remove", help=tr.text("help.datasets_remove"))
    remove.add_argument("dataset_id", metavar="ID")
    install = dataset_subparsers.add_parser("install", help=tr.text("help.datasets_install"))
    install_subparsers = install.add_subparsers(
        dest="dataset_source", required=True, metavar="SOURCE"
    )
    github = install_subparsers.add_parser("github")
    github.add_argument("repository", metavar="OWNER/REPOSITORY")
    github.add_argument("--release", required=True, metavar="TAG")
    github.add_argument("--asset", required=True, metavar="NAME")
    github.add_argument("--sha256", required=True, metavar="HEX")
    github.add_argument("--replace", action="store_true")
    official = install_subparsers.add_parser("official")
    official.add_argument("dataset_id", metavar="ID")
    official.add_argument("--replace", action="store_true")
    update = dataset_subparsers.add_parser("update", help=tr.text("help.datasets_update"))
    update.add_argument("dataset_id", nargs="?", metavar="ID")
    update.add_argument("--replace", action="store_true")

    animate = subparsers.add_parser(
        "animate", help=tr.text("help.animate"), description=tr.text("help.animate")
    )
    animate.add_argument("style", nargs="?", metavar="STYLE", help=tr.text("help.animate_style"))
    animate.add_argument("--gallery", action="store_true", help=tr.text("help.animate_gallery"))
    source = animate.add_mutually_exclusive_group()
    source.add_argument("--overlay-text", metavar="TEXT", help=tr.text("help.overlay_text"))
    source.add_argument(
        "--overlay-command", metavar="COMMAND", help=tr.text("help.overlay_command")
    )
    source.add_argument("--overlay-time-band", action="store_true", help=argparse.SUPPRESS)
    animate.add_argument(
        "--overlay-position",
        choices=OVERLAY_POSITIONS,
        default="bottom-center",
        help=tr.text("help.overlay_position"),
    )
    animate.add_argument(
        "--overlay-color",
        choices=OVERLAY_COLORS,
        default="auto",
        help=tr.text("help.overlay_color"),
    )
    animate.add_argument("--overlay-interval", type=float, help=tr.text("help.overlay_interval"))
    animate.add_argument(
        "--overlay-max-width", type=int, default=40, help=tr.text("help.overlay_max_width")
    )
    animate.add_argument("--ascii", action="store_true", help=tr.text("help.ascii"))

    text = subparsers.add_parser(
        "text", help=tr.text("help.text"), description=tr.text("help.text")
    )
    text.add_argument("preset", choices=("time-state",), help=tr.text("help.text_preset"))
    text_mode = text.add_mutually_exclusive_group()
    text_mode.add_argument(
        "--run", action="store_const", const="run", dest="text_mode", help=tr.text("help.text_run")
    )
    text_mode.add_argument(
        "--describe",
        action="store_const",
        const="describe",
        dest="text_mode",
        help=tr.text("help.text_describe"),
    )
    text.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))

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


def _chart_from_namespace(namespace: argparse.Namespace, *, timezone: str | None = None):
    command = namespace.command or "timeline"
    filters = Filters(
        tuple(namespace.agent), tuple(namespace.model), tuple(getattr(namespace, "project", ()))
    )
    style = (
        getattr(namespace, "style", None)
        or compatible_styles(command, getattr(namespace, "by", None))[0]
    )
    presentation = ChartPresentation(
        theme=namespace.color_scheme,
        style=style,
        legend=getattr(namespace, "legend", "below-title"),
        density=cast(Density, getattr(namespace, "density", "detailed")),
    )
    top = getattr(namespace, "top", None)
    if command in {"timeline", "monitor"} and namespace.by is not None and top is None:
        top = 3
    if command == "monitor":
        if style != "cumulative-bars" and presentation.legend == "values":
            presentation = replace(presentation, legend="below-title")
        return MonitorConfig(
            kind="monitor",
            window_seconds=_parse_window(namespace.window),
            filters=filters,
            presentation=presentation,
            by=namespace.by,
            top=top,
            project_aggregation=getattr(namespace, "project_aggregation", "name"),
        )
    date_range = resolve_date_range(
        command,
        period=namespace.period,
        since=namespace.since,
        until=namespace.until,
        timezone=timezone,
    )
    if command == "timeline":
        return TimelineConfig(
            "timeline",
            date_range,
            filters,
            presentation,
            namespace.by,
            top,
            namespace.other,
            namespace.granularity,
            namespace.weekdays,
            getattr(namespace, "project_aggregation", "name"),
        )
    if command == "calendar":
        return CalendarConfig("calendar", date_range, filters, presentation)
    if command == "stack":
        return StackConfig(
            "stack",
            date_range,
            filters,
            presentation,
            namespace.cache,
            namespace.granularity,
            namespace.weekdays,
        )
    return RankingConfig(
        "ranking",
        date_range,
        filters,
        presentation,
        namespace.by,
        top if top is not None else 10,
        namespace.other,
        getattr(namespace, "project_aggregation", "name"),
    )


def _request_timezone(namespace: argparse.Namespace) -> str:
    try:
        timezone = getattr(namespace, "timezone", None)
        return validate_timezone(timezone) if timezone else system_timezone()
    except ValueError as exc:
        raise UsageError("error.arguments", detail=str(exc)) from exc


def _custom_chart_from_namespace(
    namespace: argparse.Namespace, *, timezone: str | None = None
) -> CustomChartConfig:
    filters: dict[str, set[str]] = {}
    for value in namespace.custom_filters:
        filter_id, separator, option_id = value.partition("=")
        if not separator or not filter_id or not option_id:
            raise UsageError("error.arguments", detail="--filter must use ID=OPTION")
        filters.setdefault(filter_id, set()).add(option_id)
    if namespace.command_text is None:
        from ccusage_viz.datasets.service import DatasetService

        source = DatasetService().installed_command_source(namespace.dataset)
    else:
        try:
            command_argv = tuple(shlex.split(namespace.command_text))
        except ValueError as exc:
            raise UsageError(
                "error.arguments", detail="--command contains invalid shell quoting"
            ) from exc
        if not command_argv:
            raise UsageError("error.arguments", detail="--command must not be empty")
        source = CustomCommandSource(namespace.dataset, command_argv)
    kind = namespace.custom_kind
    group_by = namespace.group_by
    top = getattr(namespace, "top", None)
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    if top is not None and group_by is None:
        raise UsageError("error.top_requires_by")
    style = namespace.style or compatible_styles(kind, group_by)[0]
    if style not in compatible_styles(kind, group_by):
        raise UsageError("error.style_incompatible", style=style, mode=group_by or "total")
    date_range = resolve_date_range(
        kind,
        period=namespace.period,
        since=namespace.since,
        until=namespace.until,
        timezone=timezone,
    )
    return CustomChartConfig(
        kind=kind,
        source=source,
        date_range=date_range,
        filters=tuple(
            (filter_id, tuple(sorted(option_ids)))
            for filter_id, option_ids in sorted(filters.items())
        ),
        presentation=ChartPresentation(
            theme=namespace.color_scheme,
            style=style,
            legend=getattr(namespace, "legend", "below-title"),
            density=cast(Density, namespace.density),
        ),
        group_by=group_by,
        top=top,
        other=getattr(namespace, "other", "show"),
        granularity=getattr(namespace, "granularity", "day"),
        weekdays=getattr(namespace, "weekdays", "show"),
    )


def _validate_chart(
    namespace: argparse.Namespace, chart, *, explicit: frozenset[str], demo: str | None
) -> float:
    top = getattr(chart, "top", None)
    by = getattr(chart, "by", None)
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    if namespace.command in {"timeline", "monitor"} and top is not None and by is None:
        raise UsageError("error.top_requires_by")
    if chart.presentation.style not in compatible_styles(namespace.command, by):
        raise UsageError(
            "error.style_incompatible", style=chart.presentation.style, mode=by or "total"
        )
    no_watch = getattr(namespace, "no_watch", False)
    requested = getattr(namespace, "interval", None)
    if no_watch and "interval" in explicit:
        raise UsageError("error.arguments", detail="--interval cannot be combined with --no-watch")
    if namespace.command == "monitor" and no_watch:
        raise UsageError("error.arguments", detail="monitor does not support --no-watch")
    interval = requested
    if namespace.command == "monitor" and interval is None:
        interval = 1.0 if demo is not None else 15.0
    minimum = (
        1
        if namespace.command == "monitor" and demo is not None
        else 5
        if namespace.command == "monitor"
        else 2
    )
    if interval is not None and (not math.isfinite(interval) or interval < minimum):
        raise UsageError("error.interval_min", minimum=minimum)
    return interval if interval is not None else 10.0


def _demo_seed(namespace: argparse.Namespace) -> int | None:
    if namespace.demo is None:
        return None
    seed = getattr(namespace, "demo_seed", None)
    return seed if seed is not None else secrets.randbits(63)


def _time_state_command(launcher: str = "ccuv") -> str:
    """Return the inspectable command source used by built-in clock overlays."""

    from ccusage_viz.clock_overlay import time_state_overlay_command

    return time_state_overlay_command(launcher)


def parse_pane_fragment(
    fragment: str, *, host: DashboardLaunch | None = None, language: str = "en"
) -> PaneConfig:
    try:
        tokens = shlex.split(fragment)
    except ValueError as exc:
        raise UsageError("error.tui_panel", value=fragment) from exc
    if tokens == ["empty"]:
        return EmptyPaneConfig()
    if not tokens:
        raise UsageError("error.tui_panel", value=fragment)
    if tokens[0] == "custom":
        if any(
            token.split("=", 1)[0] in _PANE_FORBIDDEN_OPTIONS
            or token.split("=", 1)[0].startswith("--header-")
            for token in tokens[1:]
        ):
            raise UsageError("error.tui_panel", value=fragment)
        try:
            namespace = build_parser(Translator("en", dict(CATALOGS["en"]))).parse_args(tokens)
            chart = _custom_chart_from_namespace(
                namespace, timezone=host.host.timezone if host is not None else None
            )
            explicit = _explicit_fields(tokens)
            if "density" not in explicit:
                chart = replace(chart, presentation=replace(chart.presentation, density="compact"))
            if host is not None and host.host.ascii and "color_scheme" in explicit:
                raise UsageError(
                    "error.arguments",
                    detail="Dashboard --ascii conflicts with an explicit Pane --theme",
                )
            return CustomChartPaneConfig(chart)
        except UsageError as exc:
            raise UsageError("error.tui_panel", value=fragment) from exc
    if tokens[0] == "animate":
        if len(tokens) < 2:
            raise UsageError("error.tui_panel", value=fragment)
        try:
            animation = animation_spec(tokens[1], target="pane")
            parser = LocalizedParser(add_help=False)
            source = parser.add_mutually_exclusive_group()
            source.add_argument("--overlay-text")
            source.add_argument("--overlay-command")
            source.add_argument("--overlay-time-band", action="store_true")
            parser.add_argument(
                "--overlay-position", choices=OVERLAY_POSITIONS, default="bottom-center"
            )
            parser.add_argument("--overlay-color", choices=OVERLAY_COLORS, default="auto")
            parser.add_argument("--overlay-interval", type=float)
            parser.add_argument("--overlay-max-width", type=int, default=40)
            overlay_args = parser.parse_args(tokens[2:])
            has_source = (
                overlay_args.overlay_text is not None
                or overlay_args.overlay_command is not None
                or overlay_args.overlay_time_band
            )
            if not has_source and tokens[2:]:
                raise ValueError("overlay options require a source")
            if (
                overlay_args.overlay_interval is not None
                and overlay_args.overlay_command is None
                and not overlay_args.overlay_time_band
            ):
                raise ValueError("overlay interval requires a command source")
            overlay = OverlayConfig(
                text=overlay_args.overlay_text,
                command=(
                    _time_state_command(host.launcher if host is not None else "ccuv")
                    if overlay_args.overlay_time_band
                    else overlay_args.overlay_command
                ),
                position=overlay_args.overlay_position,
                color=overlay_args.overlay_color,
                interval=60.0
                if overlay_args.overlay_interval is None
                else overlay_args.overlay_interval,
                max_width=overlay_args.overlay_max_width,
            )
            return AnimationPaneConfig(animation, overlay)
        except (UsageError, ValueError) as exc:
            raise UsageError("error.tui_panel", value=fragment) from exc
    if tokens[0] not in _TUI_COMMANDS:
        raise UsageError("error.tui_panel", value=fragment)
    if any(
        token.split("=", 1)[0] in _PANE_FORBIDDEN_OPTIONS
        or token.split("=", 1)[0].startswith("--header-")
        for token in tokens[1:]
    ):
        raise UsageError("error.tui_panel", value=fragment)
    explicit = _explicit_fields(tokens)
    try:
        namespace = build_parser(Translator("en", dict(CATALOGS["en"]))).parse_args(tokens)
        chart = _chart_from_namespace(
            namespace, timezone=host.host.timezone if host is not None else None
        )
        if "density" not in explicit:
            chart = replace(
                chart,
                presentation=replace(chart.presentation, density="compact"),
            )
        if host is not None and host.host.ascii and "color_scheme" in explicit:
            raise UsageError(
                "error.arguments",
                detail="Dashboard --ascii conflicts with an explicit Pane --theme",
            )
        _validate_chart(
            namespace, chart, explicit=explicit, demo=host.host.demo_size if host else None
        )
    except UsageError as exc:
        raise UsageError("error.tui_panel", value=fragment) from exc
    return ChartPaneConfig(chart)


def _to_options(
    namespace: argparse.Namespace,
    *,
    explicit: frozenset[str] = frozenset(),
    launcher: str = "ccuv",
) -> LaunchConfig:
    command = namespace.command or "timeline"
    if command == "custom":
        timezone = _request_timezone(namespace)
        chart = _custom_chart_from_namespace(namespace, timezone=timezone)
        process = ProcessConfig(
            ccusage_bin=namespace.ccusage_bin,
            query_timeout=namespace.query_timeout,
        )
        if not math.isfinite(process.query_timeout) or process.query_timeout <= 0:
            raise UsageError(
                "error.arguments", detail="--query-timeout must be positive and finite"
            )
        return StandaloneLaunch(
            process, StandaloneHostConfig(ascii=namespace.ascii, timezone=timezone), chart, explicit
        )
    if command == "animate":
        has_source = (
            namespace.overlay_text is not None
            or namespace.overlay_command is not None
            or namespace.overlay_time_band
        )
        overlay_fields = {
            "overlay_position",
            "overlay_color",
            "overlay_interval",
            "overlay_max_width",
        }
        if namespace.gallery and (has_source or explicit & overlay_fields):
            raise UsageError("error.arguments", detail="--gallery does not support overlay options")
        if not has_source and explicit & overlay_fields:
            raise UsageError(
                "error.arguments", detail="overlay display options require an overlay source"
            )
        if (
            namespace.overlay_interval is not None
            and namespace.overlay_command is None
            and not namespace.overlay_time_band
        ):
            raise UsageError(
                "error.arguments", detail="--overlay-interval requires --overlay-command"
            )
        try:
            overlay = OverlayConfig(
                text=namespace.overlay_text,
                command=(
                    _time_state_command()
                    if namespace.overlay_time_band
                    else namespace.overlay_command
                ),
                position=namespace.overlay_position,
                color=namespace.overlay_color,
                interval=60.0 if namespace.overlay_interval is None else namespace.overlay_interval,
                max_width=namespace.overlay_max_width,
            )
        except ValueError as exc:
            raise UsageError("error.arguments", detail=str(exc)) from exc
        return AnimationLaunch(
            ProcessConfig(),
            StandaloneHostConfig(ascii=namespace.ascii),
            default_animation_spec("standalone")
            if namespace.style is None
            else animation_spec(namespace.style, target="standalone"),
            explicit,
            gallery=namespace.gallery,
            overlay=overlay,
        )
    process = ProcessConfig(
        ccusage_bin=namespace.ccusage_bin,
        query_timeout=namespace.query_timeout,
    )
    if not math.isfinite(process.query_timeout) or process.query_timeout <= 0:
        raise UsageError("error.arguments", detail="--query-timeout must be positive and finite")
    demo_seed = _demo_seed(namespace)
    if command == "dashboard":
        timezone = _request_timezone(namespace)
        preset_name = namespace.preset
        if namespace.empty and preset_name is not None:
            raise UsageError(
                "error.arguments", detail="--empty cannot be combined with a dashboard preset"
            )
        if preset_name is None and not namespace.panes and not namespace.empty:
            structural_options = {"grid", "layout", "column_weights", "row_weights"}
            if explicit & structural_options:
                raise UsageError(
                    "error.arguments",
                    detail="dashboard layout options require a preset, --pane, or --empty",
                )
            preset_name = "wide-clock"
        if preset_name is not None and namespace.grid is not None:
            raise UsageError(
                "error.arguments",
                detail="a dashboard preset cannot be combined with --grid",
            )
        if namespace.layout is not None and (preset_name is not None or namespace.grid is not None):
            raise UsageError(
                "error.arguments",
                detail="--layout cannot be combined with a dashboard preset or --grid",
            )
        preset = DASHBOARD_PRESETS.get(preset_name)
        layout = namespace.layout or (preset.layout if preset is not None else None)
        if namespace.empty:
            grid_text = layout or namespace.grid or "2x2"
            if grid_text in NAMED_LAYOUTS:
                empty_count = 1 if grid_text == "auto" else 2
            else:
                try:
                    rows, columns = fixed_shape(grid_text)
                except ValueError as exc:
                    raise UsageError("error.tui_grid", value=grid_text) from exc
                empty_count = rows * columns
            fragments = [
                *namespace.panes,
                *("empty" for _ in range(max(0, empty_count - len(namespace.panes)))),
            ]
        else:
            fragments = [*(preset.panels if preset is not None else ()), *namespace.panes]
        configured_layout = layout or (
            preset.grid if preset is not None else namespace.grid or "2x2"
        )
        if (preset is not None and namespace.panes) or (namespace.empty and layout is None):
            configured_layout = layout_for_pane_count(configured_layout, len(fragments))
        if layout is not None:
            layout = parse_layout(configured_layout, len(fragments))
            if layout is None:
                raise UsageError("error.tui_grid", value=configured_layout)
            grid = preset.grid if preset is not None else "2x2"
        else:
            grid = parse_grid(configured_layout, len(fragments))
            if grid is None:
                raise UsageError("error.tui_grid", value=configured_layout)
        bands = layout_bands(layout or grid, len(fragments))
        column_weights = tuple(namespace.column_weights) or None
        preset_row_weights = (
            preset.row_weights
            if preset is not None
            and "row_weights" not in explicit
            and preset.row_weights is not None
            and len(preset.row_weights) == bands.rows
            else None
        )
        row_weights = tuple(namespace.row_weights) or preset_row_weights
        for axis, weights, expected in (
            ("column", column_weights, bands.columns),
            ("row", row_weights, bands.rows),
        ):
            if weights is not None and any(weight < 1 for weight in weights):
                raise UsageError("error.tui_layout_weight_positive", axis=axis)
            if weights is not None and len(weights) != expected:
                raise UsageError(
                    "error.tui_layout_weight_count",
                    axis=axis,
                    expected=expected,
                    actual=len(weights),
                    layout=grid,
                )
        if column_weights is not None:
            column_weights = reconcile_weights(column_weights, bands.columns)
        if row_weights is not None:
            row_weights = reconcile_weights(row_weights, bands.rows)
        for cadence in (
            namespace.refresh_interval,
            namespace.sampling_interval,
            namespace.header_interval,
        ):
            if not math.isfinite(cadence) or cadence < 1:
                raise UsageError("error.interval_min", minimum=1)
        host = DashboardHostConfig(
            ascii=namespace.ascii,
            demo_size=namespace.demo,
            demo_seed=demo_seed,
            timezone=timezone,
            grid=grid,
            layout=layout,
            column_weights=column_weights,
            row_weights=row_weights,
            refresh_interval=(
                preset.refresh_interval
                if preset is not None and "refresh_interval" not in explicit
                else namespace.refresh_interval
            ),
            sampling_interval=(
                preset.sampling_interval
                if preset is not None and "sampling_interval" not in explicit
                else namespace.sampling_interval
            ),
            header_style=namespace.header_style,
            header_summary=namespace.header_summary,
            header_interval=namespace.header_interval,
            theme=namespace.color_scheme,
            style=(
                preset.style
                if preset is not None and "style" not in explicit
                else namespace.dashboard_style
            ),
        )
        launch = DashboardLaunch(process, host, (), explicit, launcher)
        panes = tuple(
            parse_pane_fragment(fragment, host=launch, language=namespace.lang or "en")
            for fragment in fragments
        )
        if preset_name in {"wide-clock", "narrow-clock"} and panes:
            first = panes[0]
            if isinstance(first, AnimationPaneConfig):
                panes = (
                    replace(
                        first,
                        overlay=OverlayConfig(
                            command=_time_state_command(launcher), position="bottom-right"
                        ),
                    ),
                    *panes[1:],
                )
        return replace(launch, panes=panes)
    timezone = _request_timezone(namespace)
    chart = _chart_from_namespace(namespace, timezone=timezone)
    interval = _validate_chart(namespace, chart, explicit=explicit, demo=namespace.demo)
    host = StandaloneHostConfig(
        ascii=namespace.ascii,
        timezone=timezone,
        demo_size=namespace.demo,
        demo_seed=demo_seed,
        watch=not getattr(namespace, "no_watch", False),
        interval=interval,
    )
    return StandaloneLaunch(process, host, chart, explicit)


def _explicit_fields(argv: list[str]) -> frozenset[str]:
    fields = set()
    for argument in argv:
        if not argument.startswith("--"):
            continue
        name = argument[2:].split("=", 1)[0].replace("-", "_")
        aliases = {
            "theme": "color_scheme",
            "column_weight": "column_weights",
            "row_weight": "row_weights",
        }
        fields.add(aliases.get(name, name))
    return frozenset(fields)


def _route(options: LaunchConfig) -> LaunchRoute:
    if isinstance(options, DashboardLaunch):
        return DashboardRoute(options)
    if isinstance(options, AnimationLaunch):
        return AnimationRoute(options)
    return StandaloneRoute(options)


def _run_datasets(namespace: argparse.Namespace, translator: Translator) -> int:
    from ccusage_viz.datasets.service import DatasetService

    service = DatasetService()
    command = namespace.datasets_command
    if command == "status":
        statuses = service.status(getattr(namespace, "dataset_id", None))
        if not statuses:
            print(translator.text("status.datasets_empty"))
            return 0
        for status in statuses:
            if status.installed is None:
                if status.corrupt:
                    print(
                        translator.text(
                            "error.dataset_corrupt",
                            dataset_id=status.dataset_id or namespace.dataset_id,
                        )
                    )
                elif getattr(namespace, "dataset_id", None) is not None:
                    print(
                        translator.text(
                            "status.dataset_not_installed", dataset_id=namespace.dataset_id
                        )
                    )
                continue
            state = (
                translator.text("status.dataset_ready")
                if status.ready
                else translator.text("status.dataset_setup_required")
            )
            print(f"{status.installed.dataset_id} {status.installed.version} · {state}")
            for missing in status.missing_required:
                print(f"  {missing.requirement.name}: {missing.requirement.how_to_get.en}")
        return 0
    if command == "show":
        status = service.status(namespace.dataset_id)[0]
        if status.corrupt:
            raise UsageError("error.dataset_corrupt", dataset_id=namespace.dataset_id)
        if status.installed is None or status.manifest is None:
            raise UsageError("error.dataset_not_installed", dataset_id=namespace.dataset_id)
        print(f"{status.installed.dataset_id} {status.installed.version}")
        print(status.manifest.metric.title.en)
        return 0
    if command == "list":
        catalog = service.official_catalog()
        if not catalog.entries:
            print(translator.text("status.datasets_official_empty"))
            return 0
        host_os, host_arch = service.platform
        platform_name = f"{host_os}/{host_arch}"
        for entry in catalog.entries:
            available = any(
                artifact.os == host_os and artifact.arch == host_arch
                for artifact in entry.artifacts
            )
            state = (
                translator.text("status.dataset_catalog_available")
                if available
                else translator.text(
                    "status.dataset_catalog_unavailable_platform", platform=platform_name
                )
            )
            print(f"{entry.id} · {entry.title.en} · {state}")
            print(f"  {entry.description.en}")
        return 0
    if command == "remove":
        service.remove(namespace.dataset_id)
        print(translator.text("status.dataset_removed", dataset_id=namespace.dataset_id))
        return 0
    if command == "install":
        if namespace.dataset_source == "official":
            status = service.install_official(namespace.dataset_id, replace=namespace.replace)
            assert status.installed is not None
            print(
                translator.text(
                    "status.dataset_installed_official", dataset_id=status.installed.dataset_id
                )
            )
            return 0
        status = service.install_github(
            repository=namespace.repository,
            release_tag=namespace.release,
            asset_name=namespace.asset,
            sha256=namespace.sha256,
            replace=namespace.replace,
        )
        assert status.installed is not None
        print(translator.text("status.dataset_installed", dataset_id=status.installed.dataset_id))
        return 0
    if command == "update":
        statuses = service.update_official(namespace.dataset_id, replace=namespace.replace)
        for status in statuses:
            assert status.installed is not None
            print(
                translator.text(
                    "status.dataset_installed_official", dataset_id=status.installed.dataset_id
                )
            )
        return 0
    raise AssertionError("unsupported datasets command")


def _validate_configuration(options: LaunchConfig) -> None:
    if options.host.ascii and options.was_explicit("color_scheme"):
        raise UsageError(
            "error.arguments", detail="--ascii cannot be combined with an explicit --theme"
        )


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    launcher = os.environ.get("CCUV_LAUNCHER") or "ccuv"
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
        if hasattr(namespace, "lang") and namespace.lang is None:
            namespace.lang = language
        if namespace.command == "datasets":
            return _run_datasets(namespace, tr)
        if namespace.command == "text":
            from ccusage_viz.clock_overlay import describe_time_state, render_time_state

            if namespace.preset == "time-state":
                if namespace.text_mode == "describe":
                    print(describe_time_state(namespace.lang or language))
                else:
                    print(render_time_state(namespace.lang or language))
                return 0
            raise AssertionError("unsupported text preset")
        options = _to_options(namespace, explicit=explicit, launcher=launcher)
        _validate_configuration(options)
        route = _route(options)
        return run(route.launch, tr)
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
