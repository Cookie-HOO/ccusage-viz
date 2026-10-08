"""Parser-neutral chart configuration helpers shared by CLI and Dashboard panes."""

from __future__ import annotations

import argparse
import math
import re
import shlex
from dataclasses import replace
from typing import Any, Never, cast

from ccusage_viz.core.time import resolve_date_range, system_timezone, validate_timezone
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    CACHE_MODES,
    COMMAND_STYLES,
    DENSITIES,
    GRANULARITIES,
    OTHER_MODES,
    WEEKDAY_MODES,
    CalendarConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    Density,
    Filters,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    TimelineConfig,
    compatible_styles,
)
from ccusage_viz.render.palette import COLOR_SCHEMES

_TUI_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor")
_DURATION_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>[mh])$")


class LocalizedParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> Never:
        raise UsageError("error.arguments", detail=message)


def add_presentation(parser: argparse.ArgumentParser, tr: Translator, command: str) -> None:
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
        default=COMMAND_STYLES[command][0],
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


def add_history_shared(parser: argparse.ArgumentParser, tr: Translator, command: str) -> None:
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
    add_presentation(parser, tr, command)


def add_monitor(parser: argparse.ArgumentParser, tr: Translator) -> None:
    parser.add_argument("--window", default="1h", metavar="DURATION", help=tr.text("help.window"))
    parser.add_argument(
        "--interval", type=float, default=None, metavar="SECONDS", help=tr.text("help.interval")
    )
    parser.add_argument("--no-watch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--by", choices=("agent", "model", "project"), help=tr.text("help.monitor_by"))
    parser.add_argument("--top", type=int, help=tr.text("help.monitor_top"))
    parser.add_argument("--agent", action="append", default=[], help=tr.text("help.agent"))
    parser.add_argument("--model", action="append", default=[], help=tr.text("help.model"))
    parser.add_argument("--project", action="append", default=[], help=tr.text("help.project"))
    add_presentation(parser, tr, "monitor")
    parser.set_defaults(style=None)


def add_chart_subcommands(
    chart_subparsers: argparse._SubParsersAction[argparse.ArgumentParser], tr: Translator
) -> None:
    def add_custom_source_arguments(chart_parser: argparse.ArgumentParser) -> None:
        chart_parser.add_argument("--dataset", metavar="ID")
        chart_parser.add_argument("--metric", metavar="ID")
        chart_parser.add_argument("--command", dest="command_text", metavar="TEXT")
        chart_parser.add_argument(
            "--filter", dest="custom_filters", action="append", default=[], metavar="ID=OPTION"
        )
        chart_parser.add_argument("--group-by")

    for command in _TUI_COMMANDS:
        chart_parser = chart_subparsers.add_parser(
            command, help=tr.text(f"help.{command}"), description=tr.text(f"help.{command}")
        )
        if command == "monitor":
            add_monitor(chart_parser, tr)
        else:
            add_history_shared(chart_parser, tr, command)
            if command in {"timeline", "stack"}:
                chart_parser.add_argument(
                    "--by",
                    choices=("composition", "agent", "model", "project"),
                    default=None if command == "timeline" else "composition",
                    help=tr.text("help.by"),
                )
                chart_parser.add_argument("--top", type=int, default=None, help=tr.text("help.top"))
                chart_parser.add_argument(
                    "--other", choices=OTHER_MODES, default="show", help=tr.text("help.other")
                )
            if command == "stack":
                chart_parser.add_argument(
                    "--cache", choices=CACHE_MODES, default="combined", help=tr.text("help.cache")
                )
            elif command == "ranking":
                chart_parser.add_argument(
                    "--by",
                    choices=("composition", "agent", "model", "project"),
                    default="project",
                    help=tr.text("help.by"),
                )
                chart_parser.add_argument("--top", type=int, default=10, help=tr.text("help.top"))
                chart_parser.add_argument(
                    "--other", choices=OTHER_MODES, default="show", help=tr.text("help.other")
                )
        add_custom_source_arguments(chart_parser)


def build_chart_fragment_parser(tr: Translator) -> argparse.ArgumentParser:
    """Build the chart-only grammar used by declarative Dashboard pane fragments."""

    parser = LocalizedParser(add_help=False)
    subparsers = parser.add_subparsers(dest="chart_kind", required=True)
    add_chart_subcommands(subparsers, tr)
    return parser


def parse_window(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise UsageError("error.window_invalid", value=value)
    seconds = int(match["value"]) * (60 if match["unit"] == "m" else 3600)
    if not 5 * 60 <= seconds <= 24 * 3600:
        raise UsageError("error.window_range")
    return seconds


def chart_kind(namespace: argparse.Namespace) -> str:
    return getattr(namespace, "chart_kind", None) or namespace.command or "timeline"


def chart_from_namespace(namespace: argparse.Namespace, *, timezone: str | None = None):
    command = chart_kind(namespace)
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
            window_seconds=parse_window(namespace.window),
            filters=filters,
            presentation=presentation,
            by=namespace.by,
            top=top,
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
            namespace.by,
            top if top is not None else 10,
            namespace.other,
        )
    return RankingConfig(
        "ranking",
        date_range,
        filters,
        presentation,
        namespace.by,
        top if top is not None else 10,
        namespace.other,
    )


def request_timezone(namespace: argparse.Namespace) -> str:
    try:
        timezone = getattr(namespace, "timezone", None)
        return validate_timezone(timezone) if timezone else system_timezone()
    except ValueError as exc:
        raise UsageError("error.arguments", detail=str(exc)) from exc


def custom_chart_from_namespace(
    namespace: argparse.Namespace,
    *,
    timezone: str | None = None,
    explicit: frozenset[str] = frozenset(),
) -> CustomChartConfig:
    unsupported = explicit & {"agent", "model", "project", "by", "cache"}
    if unsupported:
        names = ", ".join(f"--{name.replace('_', '-')}" for name in sorted(unsupported))
        raise UsageError(
            "error.arguments",
            detail=f"{names} cannot be combined with --dataset; use --filter or --group-by",
        )
    filters: dict[str, set[str]] = {}
    for value in namespace.custom_filters:
        filter_id, separator, option_id = value.partition("=")
        if not separator or not filter_id or not option_id:
            raise UsageError("error.arguments", detail="--filter must use ID=OPTION")
        filters.setdefault(filter_id, set()).add(option_id)
    if namespace.command_text is None:
        if namespace.dataset is None:
            raise UsageError("error.arguments", detail="--dataset or --command is required")
        from ccusage_viz.datasets.service import DatasetService

        source = DatasetService().command_source(namespace.dataset)
    else:
        try:
            command_argv = tuple(shlex.split(namespace.command_text))
        except ValueError as exc:
            raise UsageError("error.arguments", detail="--command contains invalid shell quoting") from exc
        if not command_argv:
            raise UsageError("error.arguments", detail="--command must not be empty")
        if namespace.dataset is None:
            raise UsageError("error.arguments", detail="--command requires --dataset")
        source = CustomCommandSource(namespace.dataset, command_argv)
    kind = chart_kind(namespace)
    group_by = namespace.group_by
    top = getattr(namespace, "top", None)
    if kind == "ranking" and group_by is None and top == 10 and "top" not in explicit:
        top = None
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    if top is not None and group_by is None:
        raise UsageError("error.top_requires_by")
    style = namespace.style or (
        "points" if kind == "monitor" else compatible_styles(kind, group_by)[0]
    )
    if style not in compatible_styles(kind, group_by):
        raise UsageError("error.style_incompatible", style=style, mode=group_by or "total")
    date_range = resolve_date_range(
        "timeline" if kind == "monitor" else kind,
        period=getattr(namespace, "period", None),
        since=getattr(namespace, "since", None),
        until=getattr(namespace, "until", None),
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
        initial_explicit=explicit
        & {"period", "since", "until", "group_by", "top", "filter", "granularity", "other", "style", "color_scheme", "window"},
        metric_id=namespace.metric,
    )


def validate_chart(
    namespace: argparse.Namespace, chart: object, *, explicit: frozenset[str], demo: str | None
) -> float:
    top = getattr(chart, "top", None)
    by = getattr(chart, "by", None)
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    command = chart_kind(namespace)
    if command in {"timeline", "monitor"} and top is not None and by is None:
        raise UsageError("error.top_requires_by")
    if chart.presentation.style not in compatible_styles(command, by):
        raise UsageError(
            "error.style_incompatible", style=chart.presentation.style, mode=by or "total"
        )
    no_watch = getattr(namespace, "no_watch", False)
    requested = getattr(namespace, "interval", None)
    if no_watch and "interval" in explicit:
        raise UsageError("error.arguments", detail="--interval cannot be combined with --no-watch")
    if command == "monitor" and no_watch:
        raise UsageError("error.arguments", detail="monitor does not support --no-watch")
    interval = requested
    if command == "monitor" and interval is None:
        interval = 1.0 if demo is not None else 15.0
    minimum = 1 if command == "monitor" and demo is not None else 5 if command == "monitor" else 2
    if interval is not None and (not math.isfinite(interval) or interval < minimum):
        raise UsageError("error.interval_min", minimum=minimum)
    return interval if interval is not None else 10.0


def explicit_fields(argv: list[str]) -> frozenset[str]:
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
