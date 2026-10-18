from __future__ import annotations

import shlex
from dataclasses import replace

from ccusage_viz.animation import animation_spec
from ccusage_viz.animation_overlay import OVERLAY_COLORS, OVERLAY_POSITIONS, OverlayConfig
from ccusage_viz.command_parsing.charts import (
    _chart_from_namespace,
    _custom_chart_from_namespace,
    _validate_chart,
)
from ccusage_viz.command_parsing.common import (
    _PANE_FORBIDDEN_OPTIONS,
    _TUI_COMMANDS,
    _explicit_fields,
)
from ccusage_viz.command_parsing.errors import LocalizedParser
from ccusage_viz.command_parsing.parser import build_parser
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import Translator
from ccusage_viz.locales import CATALOGS
from ccusage_viz.options import (
    AnimationPaneConfig,
    ChartPaneConfig,
    CustomChartPaneConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    PaneConfig,
    default_monitor_attachment_style,
)


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
    is_custom_pane = tokens[0] == "custom" or (
        tokens[0] == "chart"
        and any(token == "--dataset" or token.startswith("--dataset=") for token in tokens[1:])
    )
    if is_custom_pane:
        if any(
            token.split("=", 1)[0] in _PANE_FORBIDDEN_OPTIONS
            or token.split("=", 1)[0].startswith("--header-")
            for token in tokens[1:]
        ):
            raise UsageError("error.tui_panel", value=fragment)
        try:
            namespace = build_parser(Translator("en", dict(CATALOGS["en"]))).parse_args(
                ["chart", *tokens[1:]]
            )
            explicit = _explicit_fields(tokens)
            chart = _custom_chart_from_namespace(
                namespace,
                timezone=host.host.timezone if host is not None else None,
                explicit=explicit,
            )
            if "density" not in explicit:
                chart = replace(
                    chart,
                    presentation=replace(
                        chart.presentation,
                        density="full" if chart.kind == "ranking" else "compact",
                    ),
                )
            if host is not None and host.host.ascii and "color_scheme" in explicit:
                raise UsageError(
                    "error.arguments",
                    detail="Dashboard --ascii conflicts with an explicit Pane --theme",
                )
            return CustomChartPaneConfig(
                chart, attachment_style=default_monitor_attachment_style(chart)
            )
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
            parser.add_argument("--overlay-offset-x", type=int, default=0)
            parser.add_argument("--overlay-offset-y", type=int, default=0)
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
                offset_x=overlay_args.overlay_offset_x,
                offset_y=overlay_args.overlay_offset_y,
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
        namespace = build_parser(Translator("en", dict(CATALOGS["en"]))).parse_args(
            ["chart", *tokens]
        )
        chart = _chart_from_namespace(
            namespace, timezone=host.host.timezone if host is not None else None
        )
        if "density" not in explicit:
            chart = replace(
                chart,
                presentation=replace(
                    chart.presentation,
                    density="full" if chart.kind == "ranking" else "compact",
                ),
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
    return ChartPaneConfig(chart, attachment_style=default_monitor_attachment_style(chart))
