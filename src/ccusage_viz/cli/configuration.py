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
from ccusage_viz.dashboard_layout import layout_bands, reconcile_weights
from ccusage_viz.dashboard_preset_store import (
    DashboardPresetStore,
    DashboardPresetStoreCorruptError,
    DashboardPresetStoreError,
    DashboardPresetStoreLegacyError,
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


def _validate_dashboard_topology(
    launch: DashboardLaunch, namespace: argparse.Namespace, explicit: frozenset[str]
) -> DashboardLaunch:
    try:
        bands = layout_bands(
            columns=launch.host.columns,
            spotlight=launch.host.spotlight,
            pane_count=len(launch.panes),
        )
    except ValueError as exc:
        raise UsageError("error.arguments", detail=str(exc)) from exc
    explicit_columns = tuple(namespace.column_weights) or None
    explicit_rows = tuple(namespace.row_weights) or None
    columns = explicit_columns or launch.host.column_weights
    rows = explicit_rows or launch.host.row_weights
    if columns is not None and len(columns) != bands.columns:
        if explicit_columns is not None:
            raise UsageError(
                "error.tui_layout_weight_count",
                axis="column",
                expected=bands.columns,
                actual=len(columns),
                layout=f"{launch.host.columns} columns / {launch.host.spotlight} spotlight",
            )
        columns = None
    if rows is not None and len(rows) != bands.rows:
        if explicit_rows is not None:
            raise UsageError(
                "error.tui_layout_weight_count",
                axis="row",
                expected=bands.rows,
                actual=len(rows),
                layout=f"{launch.host.columns} columns / {launch.host.spotlight} spotlight",
            )
        rows = None
    for axis, weights in (("column", columns), ("row", rows)):
        if weights is not None and any(weight < 1 for weight in weights):
            raise UsageError("error.tui_layout_weight_positive", axis=axis)
    return replace(
        launch,
        host=replace(
            launch.host,
            column_weights=(
                reconcile_weights(columns, bands.columns) if columns is not None else None
            ),
            row_weights=reconcile_weights(rows, bands.rows) if rows is not None else None,
        ),
        explicit=explicit,
    )


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
            disallowed = explicit - {
                "demo",
                "lang",
                "empty",
                "ccusage_bin",
                "timezone",
                "columns",
                "spotlight",
                "column_weights",
                "row_weights",
            }
            if disallowed:
                names = ", ".join(f"--{name.replace('_', '-')}" for name in sorted(disallowed))
                raise UsageError(
                    "error.arguments",
                    detail=(f"a named dashboard preset received unsupported overrides: {names}"),
                )
            try:
                user_records = DashboardPresetStore(dashboard_preset_state_root()).list()
            except (DashboardPresetStoreCorruptError, DashboardPresetStoreLegacyError):
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
                if "timezone" in explicit:
                    named_launch = replace(
                        named_launch,
                        host=replace(named_launch.host, timezone=timezone),
                    )
                if "columns" in explicit or "spotlight" in explicit:
                    named_launch = replace(
                        named_launch,
                        host=replace(
                            named_launch.host,
                            columns=(
                                namespace.columns
                                if "columns" in explicit
                                else named_launch.host.columns
                            ),
                            spotlight=(
                                namespace.spotlight
                                if "spotlight" in explicit
                                else named_launch.host.spotlight
                            ),
                        ),
                    )
                named_launch = replace(
                    named_launch,
                    explicit=explicit,
                    launcher=launcher,
                    language=namespace.lang if "lang" in explicit else named_launch.language,
                )
                if namespace.empty:
                    named_launch = empty_preset_launch(named_launch)
                return _validate_dashboard_topology(named_launch, namespace, explicit)
        if preset_name is None and not namespace.panes and not namespace.empty:
            structural_options = {"columns", "spotlight", "column_weights", "row_weights"}
            if explicit & structural_options:
                raise UsageError(
                    "error.arguments",
                    detail="dashboard layout options require a preset, --pane, or --empty",
                )
            preset_name = "wide-clock"
        preset = DASHBOARD_PRESETS.get(preset_name)
        if preset_name is not None and preset is None:
            raise _invalid_choice_error(
                f"unknown dashboard preset: {preset_name}",
                preset_name,
                _dashboard_preset_choices(tuple(record.name for record in user_records)),
                kind="preset",
            )
        if namespace.empty and preset_name is None:
            fragments = [
                *namespace.panes,
                *("empty" for _ in range(max(0, 4 - len(namespace.panes)))),
            ]
        else:
            fragments = [*(preset.panels if preset is not None else ()), *namespace.panes]
        columns = (
            namespace.columns
            if namespace.columns is not None
            else preset.columns
            if preset is not None
            else 2
        )
        spotlight = (
            namespace.spotlight
            if namespace.spotlight is not None
            else preset.spotlight
            if preset is not None
            else 0
        )
        try:
            bands = layout_bands(columns=columns, spotlight=spotlight, pane_count=len(fragments))
        except ValueError as exc:
            raise UsageError("error.arguments", detail=str(exc)) from exc
        explicit_column_weights = tuple(namespace.column_weights) or None
        explicit_row_weights = tuple(namespace.row_weights) or None
        inherited_row_weights = preset.row_weights if preset is not None else None
        column_weights = explicit_column_weights
        row_weights = explicit_row_weights or (
            inherited_row_weights
            if inherited_row_weights is not None and len(inherited_row_weights) == bands.rows
            else None
        )
        for axis, weights, expected, supplied in (
            ("column", column_weights, bands.columns, explicit_column_weights is not None),
            ("row", row_weights, bands.rows, explicit_row_weights is not None),
        ):
            if weights is not None and any(weight < 1 for weight in weights):
                raise UsageError("error.tui_layout_weight_positive", axis=axis)
            if supplied and weights is not None and len(weights) != expected:
                raise UsageError(
                    "error.tui_layout_weight_count",
                    axis=axis,
                    expected=expected,
                    actual=len(weights),
                    layout=f"{columns} columns / {spotlight} spotlight",
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
            columns=columns,
            spotlight=spotlight,
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
        launch = DashboardLaunch(process, host, (), explicit, launcher, language=namespace.lang)
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
