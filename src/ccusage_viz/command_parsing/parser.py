from __future__ import annotations

import argparse

from ccusage_viz import __version__
from ccusage_viz.animation_overlay import OVERLAY_COLORS, OVERLAY_POSITIONS
from ccusage_viz.command_parsing.common import _DATASET_COMMANDS, _TEXT_PRESETS, _TUI_COMMANDS
from ccusage_viz.command_parsing.errors import LocalizedParser
from ccusage_viz.dashboard_layout import NAMED_LAYOUTS
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    CACHE_MODES,
    COMMAND_STYLES,
    DASHBOARD_STYLES,
    DEFAULT_STYLES,
    DENSITIES,
    GRANULARITIES,
    HEADER_SUMMARIES,
    OTHER_MODES,
    WEEKDAY_MODES,
)
from ccusage_viz.render.palette import COLOR_SCHEMES


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
        default="full" if command == "ranking" else "detailed",
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

    chart = subparsers.add_parser(
        "chart", help=tr.text("help.chart"), description=tr.text("help.chart")
    )
    chart_subparsers = chart.add_subparsers(dest="chart_kind", required=True, metavar="KIND")
    chart.set_subcommand_choices(_TUI_COMMANDS)

    def add_custom_source_arguments(chart_parser: argparse.ArgumentParser, command: str) -> None:
        chart_parser.add_argument("--dataset", metavar="ID")
        chart_parser.add_argument("--metric", metavar="ID")
        chart_parser.add_argument("--command", dest="command_text", metavar="TEXT")
        chart_parser.add_argument(
            "--filter", dest="custom_filters", action="append", default=[], metavar="ID=OPTION"
        )
        chart_parser.add_argument("--group-by")
        chart_parser.add_argument("--partition-by")
        if command == "monitor":
            chart_parser.add_argument(
                "--other", choices=OTHER_MODES, default="show", help=tr.text("help.other")
            )

    for command in _TUI_COMMANDS:
        chart_parser = chart_subparsers.add_parser(
            command, help=tr.text(f"help.{command}"), description=tr.text(f"help.{command}")
        )
        if command == "monitor":
            _add_monitor(chart_parser, tr)
        else:
            _add_history_shared(chart_parser, tr, command)
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
        add_custom_source_arguments(chart_parser, command)

    tui = subparsers.add_parser(
        "dashboard", help=tr.text("help.dashboard"), description=tr.text("help.dashboard")
    )
    tui.add_argument(
        "preset",
        nargs="?",
        metavar="PRESET",
        help=tr.text("help.dashboard_preset"),
    )
    tui.add_argument("--empty", action="store_true", help=argparse.SUPPRESS)
    _add_tui(tui, tr)

    dataset = subparsers.add_parser(
        "dataset", help=tr.text("help.dataset"), description=tr.text("help.dataset")
    )
    dataset.add_argument("--lang", choices=("en", "zh"), help=tr.text("help.lang"))
    dataset_subparsers = dataset.add_subparsers(dest="dataset_command", metavar="COMMAND")
    dataset.set_subcommand_choices(_DATASET_COMMANDS)
    dataset_subparsers.add_parser(_DATASET_COMMANDS[0], help=tr.text("help.dataset_list"))
    dataset_local = dataset_subparsers.add_parser(
        _DATASET_COMMANDS[1], help="Register a local Dataset command"
    )
    dataset_local.add_argument("command_argv", nargs=argparse.REMAINDER, metavar="COMMAND")

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
    animate.add_argument(
        "--overlay-offset-x", type=int, default=0, help=tr.text("help.overlay_offset_x")
    )
    animate.add_argument(
        "--overlay-offset-y", type=int, default=0, help=tr.text("help.overlay_offset_y")
    )
    animate.add_argument("--ascii", action="store_true", help=tr.text("help.ascii"))

    text = subparsers.add_parser(
        "text", help=tr.text("help.text"), description=tr.text("help.text")
    )
    text.add_argument("preset", choices=_TEXT_PRESETS, help=tr.text("help.text_preset"))
    text.set_choice_metadata(_TEXT_PRESETS, metavar="preset", kind="preset")
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
