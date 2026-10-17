from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time
from collections.abc import Callable
from dataclasses import replace
from shutil import get_terminal_size

from ccusage_viz.animation import animation_spec
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.command_copy import format_full_dashboard_command
from ccusage_viz.custom_component import (
    custom_replacement_required,
    custom_summary_replacement_required,
)
from ccusage_viz.dashboard import DASHBOARD_PRESETS
from ccusage_viz.dashboard_preset_store import DashboardPresetStore, DashboardPresetStoreError
from ccusage_viz.dashboard_state import DashboardPaneState, DashboardState
from ccusage_viz.datasets.paths import dashboard_preset_state_root
from ccusage_viz.errors import UsageError
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    historical_replacement_required,
)
from ccusage_viz.lifecycle import LifecycleTrigger
from ccusage_viz.options import (
    AnimationPaneConfig,
    ChartPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    MonitorConfig,
)
from ccusage_viz.presets.document import preset_from_launch
from ccusage_viz.presets.materialize import materialize_preset
from ccusage_viz.presets.values import DashboardPresetValidationError
from ccusage_viz.tui.header import (
    _custom_source_conflict_message,
    _dashboard_custom_source_conflict,
    _header_summary,
    _set_header_theme,
)
from ccusage_viz.tui.layout import _dashboard_structure
from ccusage_viz.tui.models import (
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    TuiEmptyPane,
    TuiPane,
    _chart_pane_config,
    _pane_display_options,
)
from ccusage_viz.tui.pane_lifecycle import _clear_changes, _new_pane, _shutdown_pane
from ccusage_viz.tui_preset_manager import (
    ClosePresetManager,
    DeletePreset,
    LoadPreset,
    PresetCatalogEntry,
    PresetCatalogSnapshot,
    PresetManagerState,
    SavePreset,
    reconcile_preset_manager,
)


def active_dashboard_launch(session: TuiSession) -> DashboardLaunch:
    """Capture the displayed Dashboard without leaking live runtime state."""
    state = capture_dashboard_state(session)
    return DashboardLaunch(
        session.options.process,
        replace(
            session.options.host,
            grid=state.grid,
            layout=state.layout,
            column_weights=state.column_weights,
            row_weights=state.row_weights,
            theme=state.theme,
            style=state.style,
            header_style=state.header_style,
            header_summary=state.header_summary,
        ),
        tuple(pane.config for pane in state.panes),
    )


def preset_catalog(session: TuiSession) -> PresetCatalogSnapshot:
    entries = [PresetCatalogEntry(f"builtin:{name}", name, "builtin") for name in DASHBOARD_PRESETS]
    try:
        records = DashboardPresetStore(dashboard_preset_state_root()).list()
    except DashboardPresetStoreError:
        return PresetCatalogSnapshot(
            tuple(entries),
            current_source_key=session.current_preset_key,
            warning=session.translator.text("status.tui_preset_store_unavailable"),
        )
    entries.extend(
        PresetCatalogEntry(f"user:{record.name}", record.name, "user") for record in records
    )
    return PresetCatalogSnapshot(tuple(entries), current_source_key=session.current_preset_key)


def preset_state_from_launch(session: TuiSession, launch: DashboardLaunch) -> DashboardState:
    return DashboardState(
        tuple(
            (
                DashboardPaneState(
                    index,
                    pane,
                    "chart",
                    pane.attachment_style
                    if isinstance(pane, (ChartPaneConfig, CustomChartPaneConfig))
                    else None,
                    pane.attachment_theme
                    if isinstance(pane, (ChartPaneConfig, CustomChartPaneConfig))
                    else None,
                    isinstance(pane, (ChartPaneConfig, CustomChartPaneConfig))
                    and pane.attachment_style is not None,
                )
                for index, pane in enumerate(launch.panes)
            )
        ),
        launch.host.grid,
        launch.host.layout,
        launch.host.column_weights,
        launch.host.row_weights,
        launch.host.theme,
        launch.host.style,
        launch.host.header_style,
        launch.host.header_summary,
        "chart",
    )


def builtin_preset_launch(session: TuiSession, name: str) -> DashboardLaunch:
    from ccusage_viz.command_parsing.panes import parse_pane_fragment

    preset = DASHBOARD_PRESETS[name]
    base = DashboardLaunch(
        session.options.process,
        replace(
            session.options.host,
            grid=preset.grid,
            layout=preset.layout,
            row_weights=preset.row_weights,
            refresh_interval=preset.refresh_interval,
            sampling_interval=preset.sampling_interval,
            style=preset.style,
        ),
        (),
        launcher=session.options.launcher,
    )
    panes = tuple(
        parse_pane_fragment(fragment, host=base, language=session.translator.language)
        for fragment in preset.panels
    )
    if (
        name in {"wide-clock", "narrow-clock"}
        and panes
        and isinstance(panes[0], AnimationPaneConfig)
    ):
        panes = (
            replace(
                panes[0],
                overlay=OverlayConfig(
                    command=f"{session.options.launcher} text time-state --run",
                    position="bottom-right",
                ),
            ),
            *panes[1:],
        )
    return replace(base, panes=panes)


def execute_preset_command(session: TuiSession, command: object) -> None:
    if isinstance(command, ClosePresetManager):
        session.preset_manager = None
        return
    if isinstance(command, SavePreset):
        conflict = _dashboard_custom_source_conflict(session.panes)
        if conflict is not None:
            session.preset_manager = replace(
                session.preset_manager,
                notice=_custom_source_conflict_message(conflict, session.translator, preset=True),
            )
            return
        try:
            record = preset_from_launch(command.name, active_dashboard_launch(session))
            DashboardPresetStore(dashboard_preset_state_root()).save(record)
        except (DashboardPresetStoreError, DashboardPresetValidationError, ValueError):
            session.preset_manager = replace(session.preset_manager, notice="preset-save-failed")
        else:
            session.current_preset_key = f"user:{command.name}"
        return
    if isinstance(command, DeletePreset):
        try:
            DashboardPresetStore(dashboard_preset_state_root()).delete(
                command.key.removeprefix("user:")
            )
        except DashboardPresetStoreError:
            session.preset_manager = replace(session.preset_manager, notice="preset-delete-failed")
        else:
            if session.current_preset_key == command.key:
                session.current_preset_key = None
        return
    if isinstance(command, LoadPreset):
        try:
            if command.key.startswith("builtin:"):
                launch = builtin_preset_launch(session, command.key.removeprefix("builtin:"))
            else:
                from ccusage_viz.datasets.service import DatasetService

                record = DashboardPresetStore(dashboard_preset_state_root()).get(
                    command.key.removeprefix("user:")
                )
                launch = materialize_preset(record, DatasetService().installed_command_source)
            loaded_options = replace(
                launch, explicit=session.options.explicit, launcher=session.options.launcher
            )

            def apply_loaded_preset() -> None:
                session.options = loaded_options
                apply_dashboard_state(session, preset_state_from_launch(session, loaded_options))

            record_mutation(session, ("preset", "load", command.key), apply_loaded_preset)
        except (DashboardPresetStoreError, DashboardPresetValidationError, UsageError):
            session.preset_manager = replace(session.preset_manager, notice="preset-load-failed")
        else:
            session.current_preset_key = command.key
            session.preset_manager = None


def open_preset_manager(session: TuiSession, *, save: bool = False) -> None:
    session.preset_manager = reconcile_preset_manager(
        PresetManagerState(mode="save" if save else "list"),
        preset_catalog(session),
        visible_rows=max(1, get_terminal_size().lines - 4),
    )


def capture_dashboard_state(session: TuiSession) -> DashboardState:
    pane_states: list[DashboardPaneState] = []
    for pane in session.panes:
        if isinstance(pane, TuiEmptyPane):
            pane_states.append(DashboardPaneState(pane.pane_id, EmptyPaneConfig(), "chart"))
        elif isinstance(pane, TuiCustomPane):
            attachment = pane.attachment
            pane_states.append(
                DashboardPaneState(
                    pane.pane_id,
                    CustomChartPaneConfig(
                        pane.component.candidate,
                        attachment.spec.style
                        if attachment is not None and pane.attachment_enabled
                        else None,
                        attachment.theme if attachment is not None else None,
                        pane.ranking_item_spacing,
                    ),
                    pane.body_view,
                    attachment.spec.style if attachment is not None else None,
                    attachment.theme if attachment is not None else None,
                    pane.attachment_enabled,
                )
            )
        elif isinstance(pane, TuiAnimationPane):
            pane_states.append(
                DashboardPaneState(
                    pane.pane_id,
                    AnimationPaneConfig(pane.session.spec, pane.overlay.config),
                    pane.body_view,
                    animation_theme=pane.session.theme,
                )
            )
        else:
            assert isinstance(pane, TuiChartPane)
            attachment = pane.attachment
            chart = _pane_display_options(pane).chart
            assert not isinstance(chart, CustomChartConfig)
            pane_states.append(
                DashboardPaneState(
                    pane.pane_id,
                    ChartPaneConfig(
                        chart,
                        attachment.spec.style
                        if attachment is not None and pane.attachment_enabled
                        else None,
                        attachment.theme if attachment is not None else None,
                    ),
                    pane.body_view,
                    attachment.spec.style if attachment is not None else None,
                    attachment.theme if attachment is not None else None,
                    pane.attachment_enabled,
                )
            )
    return DashboardState(
        tuple(pane_states),
        session.active_grid,
        session.active_layout,
        session.column_weights,
        session.row_weights,
        session.dashboard_theme,
        session.dashboard_style,
        session.header_style,
        session.header.summary_period,
        session.body_view,
    )


def apply_dashboard_state(session: TuiSession, state: DashboardState) -> None:
    from ccusage_viz.tui.input import end_adjustment
    from ccusage_viz.tui.queries import refresh, refresh_header, sync_custom_dashboard_summaries

    """Reconcile declarative history without discarding unaffected live Panes."""
    from ccusage_viz.configuration import standalone_from_chart_pane

    existing = {pane.pane_id: pane for pane in session.panes}
    reconciled: list[TuiPane] = []
    refresh_indexes: list[tuple[int, bool, bool]] = []
    now = time.monotonic()
    for pane_state in state.panes:
        pane = existing.pop(pane_state.pane_id, None)
        config = pane_state.config
        compatible = (
            isinstance(config, EmptyPaneConfig)
            and isinstance(pane, TuiEmptyPane)
            or (isinstance(config, AnimationPaneConfig) and isinstance(pane, TuiAnimationPane))
            or (isinstance(config, CustomChartPaneConfig) and isinstance(pane, TuiCustomPane))
            or (
                isinstance(config, ChartPaneConfig)
                and isinstance(pane, TuiChartPane)
                and (type(_pane_display_options(pane).chart) is type(config.chart))
            )
        )
        if not compatible:
            if pane is not None:
                _shutdown_pane(pane)
            pane = _new_pane(
                session.options,
                config,
                f"dashboard:pane:{pane_state.pane_id}"
                if isinstance(config, (ChartPaneConfig, CustomChartPaneConfig))
                else None,
                session.runtime,
            )
            pane.pane_id = pane_state.pane_id
            if isinstance(pane, TuiCustomPane):
                refresh_indexes.append((len(reconciled), True, True))
            elif isinstance(pane, TuiChartPane):
                refresh_indexes.append((len(reconciled), True, False))
        if isinstance(pane, (TuiChartPane, TuiAnimationPane, TuiCustomPane)):
            pane.body_view = pane_state.body_view
        if isinstance(pane, TuiAnimationPane):
            assert isinstance(pane_state.config, AnimationPaneConfig)
            if pane.session.spec != pane_state.config.animation:
                pane.session.set_style(pane_state.config.animation, now)
            if pane.overlay.config != pane_state.config.overlay:
                pane.overlay.apply(pane_state.config.overlay, now=now)
            if pane_state.animation_theme is not None:
                pane.session.set_theme(pane_state.animation_theme, now)
        elif isinstance(pane, TuiCustomPane):
            assert isinstance(pane_state.config, CustomChartPaneConfig)
            pane.ranking_item_spacing = pane_state.config.ranking_item_spacing
            if pane.component.candidate != pane_state.config.chart:
                current = pane.component.candidate
                data_affecting = custom_replacement_required(current, pane_state.config.chart)
                summary_affecting = custom_summary_replacement_required(
                    current, pane_state.config.chart
                )
                pane.component.configure(pane_state.config.chart, data_affecting=data_affecting)
                if current.source != pane_state.config.chart.source:
                    pane.probe_complete = False
                if data_affecting or summary_affecting:
                    refresh_indexes.append((len(reconciled), data_affecting, summary_affecting))
            if pane.attachment is not None:
                if pane_state.attachment_style is not None:
                    pane.attachment.set_style(
                        animation_spec(pane_state.attachment_style, target="monitor"), now
                    )
                if pane_state.attachment_theme is not None:
                    pane.attachment.set_theme(pane_state.attachment_theme, now)
                pane.attachment_enabled = pane_state.attachment_enabled
        elif isinstance(pane, TuiChartPane):
            assert isinstance(pane_state.config, ChartPaneConfig)
            component = pane.component
            candidate = standalone_from_chart_pane(session.options, pane_state.config)
            current = component.candidate
            if candidate != current:
                data_affecting = (
                    historical_replacement_required(current, candidate)
                    if isinstance(component, HistoricalChartComponent)
                    else isinstance(current.chart, MonitorConfig)
                    and isinstance(candidate.chart, MonitorConfig)
                    and (
                        current.chart.by != candidate.chart.by
                        or current.chart.filters != candidate.chart.filters
                    )
                )
                _clear_changes(pane)
                component.configure(candidate, data_affecting=data_affecting)
                if candidate.host.interval != current.host.interval:
                    pane.scheduler.rebuild(candidate.host.interval, now=now)
                if data_affecting:
                    refresh_indexes.append((len(reconciled), True, False))
                elif (
                    isinstance(component, HistoricalChartComponent)
                    and component.missing_comparison_coverage().intervals
                ):
                    refresh_indexes.append((len(reconciled), False, False))
            if pane.attachment is not None:
                if pane_state.attachment_style is not None:
                    pane.attachment.set_style(
                        animation_spec(pane_state.attachment_style, target="monitor"), now
                    )
                if pane_state.attachment_theme is not None:
                    pane.attachment.set_theme(pane_state.attachment_theme, now)
                pane.attachment_enabled = pane_state.attachment_enabled
        reconciled.append(pane)
    for pane in existing.values():
        _shutdown_pane(pane)
    session.panes = reconciled
    session.active_grid = state.grid
    session.active_layout = state.layout
    session.column_weights = state.column_weights
    session.row_weights = state.row_weights
    theme_changed = session.dashboard_theme != state.theme
    session.dashboard_theme = state.theme
    session.dashboard_style = state.style
    session.divider_style, session.frame_style = _dashboard_structure(session.dashboard_style)
    session.header_style = state.header_style
    header_refresh_required = (
        session.header.summary_period != state.header_summary
        and _header_summary(session.header, state.header_summary) is None
    )
    session.header.summary_period = state.header_summary
    if theme_changed:
        _set_header_theme(session.header, session.dashboard_theme)
    session.body_view = state.body_view
    if session.focused is not None and session.focused >= len(session.panes):
        end_adjustment(session)
    for index, data_affecting, summary_affecting in refresh_indexes:
        refresh(
            session,
            index,
            trigger=LifecycleTrigger.CONFIGURATION,
            data_affecting=data_affecting,
            summary_affecting=summary_affecting,
        )
    if session.header_style != "hidden" and header_refresh_required:
        refresh_header(session, trigger=LifecycleTrigger.CONFIGURATION)
    sync_custom_dashboard_summaries(session)


def record_mutation(session: TuiSession, family: object, mutate: Callable[[], None]) -> bool:
    from ccusage_viz.tui.queries import sync_custom_dashboard_summaries

    before = capture_dashboard_state(session)
    mutate()
    after = capture_dashboard_state(session)
    if after == before:
        return False
    sync_custom_dashboard_summaries(session)
    session.history = session.history.record(
        after, family=family, target=family, timestamp=time.monotonic()
    )
    return True


def full_dashboard_command(session: TuiSession) -> str:
    return format_full_dashboard_command(
        replace(session.options, host=replace(session.options.host, theme=session.dashboard_theme)),
        tuple(
            EmptyPaneConfig()
            if isinstance(pane, TuiEmptyPane)
            else CustomChartPaneConfig(pane.component.candidate)
            if isinstance(pane, TuiCustomPane)
            else _chart_pane_config(pane)
            if isinstance(pane, TuiChartPane)
            else AnimationPaneConfig(pane.session.spec, pane.overlay.config)
            for pane in session.panes
        ),
        grid=session.active_grid,
        layout=session.active_layout,
        column_weights=session.column_weights,
        row_weights=session.row_weights,
        header_style=session.header_style,
        header_summary=session.header.summary_period,
        dashboard_style=session.dashboard_style,
    )
