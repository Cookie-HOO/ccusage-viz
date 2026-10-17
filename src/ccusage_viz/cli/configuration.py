from __future__ import annotations

import argparse
import math
import secrets
from dataclasses import replace

from ccusage_viz.animation import animation_spec, default_animation_spec
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.command_parsing.charts import (
    _chart_from_namespace,
    _custom_chart_from_namespace,
    _request_timezone,
    _validate_chart,
)
from ccusage_viz.command_parsing.errors import _invalid_choice_error
from ccusage_viz.command_parsing.panes import _time_state_command, parse_pane_fragment
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
from ccusage_viz.dashboard_preset_store import (
    DashboardPresetStore,
    DashboardPresetStoreCorruptError,
    DashboardPresetStoreError,
)
from ccusage_viz.datasets.paths import dashboard_preset_state_root
from ccusage_viz.errors import UsageError
from ccusage_viz.options import (
    AnimationLaunch,
    AnimationPaneConfig,
    AnimationRoute,
    DashboardHostConfig,
    DashboardLaunch,
    DashboardRoute,
    LaunchConfig,
    LaunchRoute,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    StandaloneRoute,
)
from ccusage_viz.presets.materialize import empty_preset_launch, materialize_preset
from ccusage_viz.presets.values import DashboardPresetValidationError


def _dashboard_preset_choices(user_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*DASHBOARD_PRESETS, *user_names)))

def _demo_seed(namespace: argparse.Namespace) -> int | None:
    if namespace.demo is None:
        return None
    seed = getattr(namespace, "demo_seed", None)
    return seed if seed is not None else secrets.randbits(63)

def _to_options(
    namespace: argparse.Namespace,
    *,
    explicit: frozenset[str] = frozenset(),
    launcher: str = "ccuv",
) -> LaunchConfig:
    command = namespace.command or "chart"
    if (
        getattr(namespace, "command_text", None) is not None
        and getattr(namespace, "dataset", None) is None
    ):
        raise UsageError("error.arguments", detail="--command requires --dataset")
    if getattr(namespace, "dataset", None) is not None:
        timezone = _request_timezone(namespace)
        chart = _custom_chart_from_namespace(namespace, timezone=timezone, explicit=explicit)
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
            "overlay_offset_x",
            "overlay_offset_y",
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
                offset_x=namespace.overlay_offset_x,
                offset_y=namespace.overlay_offset_y,
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
        user_records = ()
        if preset_name is not None:
            disallowed = explicit - {"demo", "lang", "empty", "ccusage_bin"}
            if disallowed:
                names = ", ".join(f"--{name.replace('_', '-')}" for name in sorted(disallowed))
                raise UsageError(
                    "error.arguments",
                    detail=(
                        "a named dashboard preset only permits --demo, --lang, --empty, "
                        f"and --ccusage-bin; received {names}"
                    ),
                )
            try:
                user_records = DashboardPresetStore(dashboard_preset_state_root()).list()
            except DashboardPresetStoreCorruptError:
                # A damaged user collection must never make a valid built-in unavailable.
                if preset_name not in DASHBOARD_PRESETS:
                    raise UsageError(
                        "error.arguments", detail="user dashboard preset storage is unavailable"
                    ) from None
            except DashboardPresetStoreError as exc:
                raise UsageError(
                    "error.arguments", detail="user dashboard preset storage is unavailable"
                ) from exc
            record = next(
                (item for item in user_records if item.name == preset_name),
                None,
            )
            if record is not None:
                from ccusage_viz.datasets.service import DatasetService

                try:
                    named_launch = materialize_preset(
                        record, DatasetService().installed_command_source
                    )
                except (DashboardPresetValidationError, UsageError) as exc:
                    raise UsageError(
                        "error.arguments", detail=f"dashboard preset {preset_name!r} is unavailable"
                    ) from exc
                if "ccusage_bin" in explicit:
                    named_launch = replace(
                        named_launch,
                        process=replace(named_launch.process, ccusage_bin=namespace.ccusage_bin),
                    )
                if "demo" in explicit:
                    named_launch = replace(
                        named_launch,
                        host=replace(
                            named_launch.host,
                            demo_size=namespace.demo,
                            demo_seed=_demo_seed(namespace),
                        ),
                    )
                named_launch = replace(named_launch, explicit=explicit, launcher=launcher)
                return empty_preset_launch(named_launch) if namespace.empty else named_launch
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
        if preset_name is not None and preset is None:
            raise _invalid_choice_error(
                f"unknown dashboard preset: {preset_name}",
                preset_name,
                _dashboard_preset_choices(tuple(record.name for record in user_records)),
                kind="preset",
            )
        layout = namespace.layout or (preset.layout if preset is not None else None)
        if namespace.empty and preset_name is None:
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
            header_summary=(
                preset.header_summary
                if preset is not None and "header_summary" not in explicit
                else namespace.header_summary
            ),
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
        resolved_launch = replace(launch, panes=panes)
        return (
            empty_preset_launch(resolved_launch)
            if namespace.empty and preset_name is not None
            else resolved_launch
        )
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

def _route(options: LaunchConfig) -> LaunchRoute:
    if isinstance(options, DashboardLaunch):
        return DashboardRoute(options)
    if isinstance(options, AnimationLaunch):
        return AnimationRoute(options)
    return StandaloneRoute(options)

def _validate_configuration(options: LaunchConfig) -> None:
    if options.host.ascii and options.was_explicit("color_scheme"):
        raise UsageError(
            "error.arguments", detail="--ascii cannot be combined with an explicit --theme"
        )
