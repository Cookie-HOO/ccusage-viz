from __future__ import annotations

# ruff: noqa: B023
import shlex
import sys
import time
import webbrowser
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from shutil import get_terminal_size
from threading import Event
from typing import cast

from ccusage_viz.acquisition import (
    builtin_summary_query_intent,
    builtin_summary_query_plan,
    custom_historical_query_intent,
    custom_probe_query_intent,
    custom_summary_query_intent,
    custom_v2_monitor_query_intent,
    custom_v2_probe_query_intent,
    custom_v2_summary_query_intent,
    historical_provider_id,
    historical_query_intent,
)
from ccusage_viz.adjustment_timeout import (
    HELP_IDLE_TIMEOUT_SECONDS,
    AdjustmentIdleTimer,
    AdjustmentTimeout,
)
from ccusage_viz.animate import (
    _editor_line_end,
    _editor_line_start,
    _editor_next_word,
    _editor_previous_word,
    _editor_viewport,
    _overlay_editor_controls,
    cycle_animation_style,
)
from ccusage_viz.animation import (
    AnimationSessionState,
    animation_spec,
    cycle_monitor_attachment,
    default_animation_spec,
)
from ccusage_viz.animation_overlay import (
    OverlayConfig,
    OverlayPlacement,
    format_execution_record,
    move_history_selection,
    render_history_table,
)
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.builtin_summary import build_builtin_pane_summary
from ccusage_viz.command_copy import (
    copy_command,
    format_full_command_display,
    format_full_dashboard_command,
)
from ccusage_viz.configuration import (
    apply_custom_probe_defaults,
    default_custom_pane,
    v2_metric_probe_descriptor,
)
from ccusage_viz.core.custom_ranking_time import refresh_custom_ranking_range
from ccusage_viz.core.time import DateRange, local_today, refresh_date_range
from ccusage_viz.custom_component import (
    CustomHistoricalComponent,
    custom_date_summary_supported,
    custom_replacement_required,
    custom_summary_replacement_required,
)
from ccusage_viz.custom_filter_draft import run_custom_filter_editor
from ccusage_viz.custom_models import (
    CustomChartCapability,
    CustomProtocolFailure,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor_component import (
    CustomMonitorCompletion,
    CustomMonitorComponent,
    resolve_metric,
)
from ccusage_viz.custom_protocol.requests import CustomSummaryRequest, V2SummaryRequest
from ccusage_viz.custom_protocol.responses import (
    CustomProbeResponse,
    CustomSummaryResponse,
    V2MonitorResponse,
    V2ProbeResponse,
    V2SummaryResponse,
)
from ccusage_viz.dashboard import DASHBOARD_PRESETS
from ccusage_viz.dashboard_history import DashboardHistory
from ccusage_viz.dashboard_layout import (
    MIN_PANE_HEIGHT,
    MIN_PANE_WIDTH,
    adjust_weight,
    layout_bands,
    reconcile_weights,
    resolve_pane_layout,
)
from ccusage_viz.dashboard_layout import PaneLayout as ResolvedPaneLayout
from ccusage_viz.dashboard_layout import pane_at as layout_pane_at
from ccusage_viz.dashboard_preset_store import DashboardPresetStore, DashboardPresetStoreError
from ccusage_viz.dashboard_state import DashboardPaneState, DashboardState
from ccusage_viz.data_view import (
    DashboardBodyView,
    body_view_copy_kind,
    cycle_body_view,
    cycle_dashboard_body_view,
)
from ccusage_viz.datasets.paths import dashboard_preset_state_root
from ccusage_viz.diagnostics import format_error
from ccusage_viz.domain import UsageRecord
from ccusage_viz.editor_help import editor_help_groups
from ccusage_viz.errors import QueryError, UsageError
from ccusage_viz.filter_draft import discover_filter_choices, run_filter_editor
from ccusage_viz.formatting import clip_width, display_width, pad_width, strip_ansi, wrap_width
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    HistoricalPurpose,
    UsageSnapshot,
    historical_replacement_required,
)
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import LifecycleTrigger, OperationToken, query_trigger
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import (
    DASHBOARD_STYLES,
    AnimationPaneConfig,
    ChartPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardLaunch,
    EmptyPaneConfig,
    MonitorConfig,
    PaneConfig,
    StandaloneLaunch,
    adjust_custom_chart,
    adjust_standalone,
    is_monitor_ranking_style,
    is_v2_custom_ranking,
    replace_chart_filters,
)
from ccusage_viz.presets.document import preset_from_launch
from ccusage_viz.presets.materialize import materialize_preset
from ccusage_viz.presets.values import DashboardPresetValidationError
from ccusage_viz.processing import required_summary_coverage
from ccusage_viz.processing.summaries import (
    SummaryQueryPlan,
    SummaryScope,
    range_summary_query_plan,
    summary_query_plan,
)
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.grouped_ranking_viewport import GroupedIdentity
from ccusage_viz.render.palette import COLOR_SCHEMES, get_color_scheme
from ccusage_viz.terminal import (
    Frame,
    FramePainter,
    Terminal,
    compose_frame,
    emphasize,
    set_cursor_visible,
)
from ccusage_viz.terminal_ui import TransientFeedback, controls_line, dimmed, feedback_lines
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.text_viewport import (
    next_text_offset,
    render_text_viewport,
    text_viewport_overflows,
)
from ccusage_viz.tui.adjustments import (
    _CUSTOM_PANE_KINDS,
    _LAYOUT_SHORTCUT_VALUES,
    _adjustment_footer,
    _adjustment_key_supported,
    _adjustment_target,
    _adjustment_target_page,
    _animation_adjustment_footer,
    _animation_adjustment_target_page,
    _choose_layout_shortcut,
    _empty_pane_adjustment_footer,
    _global_adjustment_footer,
    _pane_adjustment_state,
    _pane_help_action_text,
    _pane_help_settings_actions,
    _text_view_footer,
)
from ccusage_viz.tui.controls import _cycle
from ccusage_viz.tui.custom_adjustments import (
    _accepted_custom_metric_help_node,
    _adjust_custom_monitor_chart,
    _custom_adjustment_footer,
    _custom_capability,
    _custom_pane_adjustment_actions,
    _custom_pane_adjustment_keys,
    _custom_period_adjustment_chart,
    _custom_period_adjustment_target,
    _custom_runtime_filters,
    _custom_top_limit_notice,
    _custom_top_refresh_required,
    _cycle_custom_grouping,
    _cycle_custom_monitor_window,
    _cycle_custom_partitioning,
    _finish_ranking_search_editing,
    _ranking_search_eligible,
)
from ccusage_viz.tui.custom_rendering import (
    _custom_failure_log_detail,
    _custom_ranking_clipboard_all_text,
    _custom_ranking_clipboard_text,
    _custom_ranking_copyable_entries,
    _pane_copy_payload,
)
from ccusage_viz.tui.datasets.catalog import _official_catalog_viewport, _official_preview_rows
from ccusage_viz.tui.datasets.chooser import (
    _PANE_COMMANDS,
    _choose_dataset_pane_config,
    _choose_pane_type,
    _chooser_viewport,
    _dataset_metric_chooser_chrome,
    _dataset_metric_chooser_rows,
    _dataset_title,
    _metric_chooser_display_rows,
    _metric_chooser_previous_offset,
    _pane_chooser_rows,
)
from ccusage_viz.tui.header import (
    _custom_dashboard_sources,
    _custom_source_conflict,
    _custom_source_conflict_message,
    _cycle_header_summary,
    _dashboard_custom_source_conflict,
    _header_lines,
    _header_refresh_interval,
    _header_summary,
    _invalidate_custom_dashboard_summaries,
    _new_header,
    _reconcile_custom_dashboard_summaries,
    _replace_header_interval,
    _set_header_theme,
)
from ccusage_viz.tui.layout import (
    _compose_dashboard_overlays,
    _compose_resolved_panes,
    _dashboard_structure,
    _grid_for_pane_count,
    parse_grid,
)
from ccusage_viz.tui.models import (
    _DOUBLE_CLICK_SECONDS,
    BuiltinSummaryOutcome,
    CustomDashboardSummary,
    CustomLogRecord,
    CustomOutcome,
    CustomPaneDraft,
    DashboardDatasetModalState,
    DashboardOverlayPlacement,
    HelpOverlayState,
    HistoricalOutcome,
    MonitorOutcome,
    MonitorWarmupOutcome,
    OverlayEditorState,
    OverlayHistoryState,
    PaneFuture,
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    TuiEmptyPane,
    TuiPane,
    _chart_pane_config,
    _custom_metric_periods,
    _pane_display_options,
)
from ccusage_viz.tui.pane_lifecycle import (
    _await_builtin_summary_submission,
    _await_custom_submission,
    _await_historical,
    _await_historical_submission,
    _await_monitor_submission,
    _await_monitor_warmup,
    _clear_changes,
    _insert_pane,
    _new_pane,
    _new_pane_options,
    _refresh_deltas,
    _refresh_ranks,
    _replace_pane,
    _shutdown_pane,
)
from ccusage_viz.tui.rendering import (
    _append_monitor_attachment,
    _local_pane_content,
    _pane_animation_deadline,
    _pane_render,
    _update_custom_monitor_attachment_activity,
    _update_monitor_attachment_activity,
)
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    WheelEvent,
    read_event,
    tui_input_mode,
)
from ccusage_viz.tui_preset_manager import (
    ClosePresetManager,
    DeletePreset,
    LoadPreset,
    PresetCatalogEntry,
    PresetCatalogSnapshot,
    PresetManagerState,
    SavePreset,
    reconcile_preset_manager,
    reduce_preset_manager,
    render_preset_manager,
)


def run_tui(options: DashboardLaunch, translator: Translator) -> int:
    runtime = build_query_runtime()
    panes = [
        _new_pane(
            options,
            pane_config,
            f"dashboard:pane:{index}"
            if isinstance(pane_config, (ChartPaneConfig, CustomChartPaneConfig))
            else None,
            runtime,
        )
        for index, pane_config in enumerate(options.panes)
    ]
    for index, pane in enumerate(panes):
        pane.pane_id = index
    next_pane_id = len(panes)
    header = _new_header(options, runtime)
    _reconcile_custom_dashboard_summaries(
        header, _custom_dashboard_sources(panes), now=time.monotonic()
    )
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ccusage-viz-tui")
    focused: int | None = None
    active_grid = options.host.grid
    active_layout = options.host.layout
    column_weights = options.host.column_weights
    row_weights = options.host.row_weights
    header_style = options.host.header_style
    dashboard_style = options.host.style
    dashboard_theme = options.host.theme
    divider_style, frame_style = _dashboard_structure(dashboard_style)
    grid_draft: str | None = None
    grid_error: str | None = None
    adjustment_mode: str | None = None
    adjustment_page = "quick"
    adjustment_timer: AdjustmentIdleTimer | None = None
    controls_hidden = False
    body_view: DashboardBodyView = "chart"
    dashboard_text_offset = 0
    dashboard_text_line_count = 0
    dashboard_text_visible_rows = 0
    chooser_overlay: tuple[int, str] | None = None
    dataset_modal: DashboardDatasetModalState | None = None
    preset_manager: PresetManagerState | None = None
    current_preset_key: str | None = None
    overlay_editor: OverlayEditorState | None = None
    overlay_history: OverlayHistoryState | None = None
    custom_logs_pane: int | None = None
    help_overlay: HelpOverlayState | None = None
    help_was_active = False
    last_click: tuple[int, float] | None = None
    scrollbar_drag: tuple[int, int] | None = None
    scrollbar_hovered_pane: int | None = None
    copy_feedback = TransientFeedback()
    manual_refresh_operations: set[OperationToken] = set()
    displayed_custom_warnings: set[tuple[str, str]] = set()

    last_successful_update: datetime | None = None
    last_size: tuple[int, int] | None = None
    pane_render_cache: dict[
        int, tuple[tuple[object, ...], str, tuple[DashboardOverlayPlacement, ...]]
    ] = {}
    screen = FramePainter(sys.stdout)

    def set_screen_cursor_visible(visible: bool) -> None:
        stream = getattr(screen, "stream", None)
        if stream is not None:
            set_cursor_visible(stream, visible)

    def end_adjustment() -> None:
        nonlocal adjustment_mode, adjustment_timer, focused, grid_draft, grid_error, body_view
        adjustment_mode = None
        adjustment_timer = None
        focused = None
        grid_draft = None
        grid_error = None

    def active_dashboard_launch() -> DashboardLaunch:
        """Capture the displayed Dashboard without leaking live runtime state."""

        state = capture_dashboard_state()
        return DashboardLaunch(
            options.process,
            replace(
                options.host,
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

    def preset_catalog() -> PresetCatalogSnapshot:
        entries = [
            PresetCatalogEntry(f"builtin:{name}", name, "builtin") for name in DASHBOARD_PRESETS
        ]
        try:
            records = DashboardPresetStore(dashboard_preset_state_root()).list()
        except DashboardPresetStoreError:
            return PresetCatalogSnapshot(
                tuple(entries),
                current_source_key=current_preset_key,
                warning=translator.text("status.tui_preset_store_unavailable"),
            )
        entries.extend(
            PresetCatalogEntry(f"user:{record.name}", record.name, "user") for record in records
        )
        return PresetCatalogSnapshot(tuple(entries), current_source_key=current_preset_key)

    def preset_state_from_launch(launch: DashboardLaunch) -> DashboardState:
        return DashboardState(
            tuple(
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

    def builtin_preset_launch(name: str) -> DashboardLaunch:
        from ccusage_viz.command_parsing.panes import parse_pane_fragment

        preset = DASHBOARD_PRESETS[name]
        base = DashboardLaunch(
            options.process,
            replace(
                options.host,
                grid=preset.grid,
                layout=preset.layout,
                row_weights=preset.row_weights,
                refresh_interval=preset.refresh_interval,
                sampling_interval=preset.sampling_interval,
                style=preset.style,
            ),
            (),
            launcher=options.launcher,
        )
        panes = tuple(
            parse_pane_fragment(fragment, host=base, language=translator.language)
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
                        command=f"{options.launcher} text time-state --run", position="bottom-right"
                    ),
                ),
                *panes[1:],
            )
        return replace(base, panes=panes)

    def execute_preset_command(command: object) -> None:
        nonlocal options, preset_manager, current_preset_key
        if isinstance(command, ClosePresetManager):
            preset_manager = None
            return
        if isinstance(command, SavePreset):
            conflict = _dashboard_custom_source_conflict(panes)
            if conflict is not None:
                preset_manager = replace(
                    preset_manager,
                    notice=_custom_source_conflict_message(conflict, translator, preset=True),
                )
                return
            try:
                record = preset_from_launch(command.name, active_dashboard_launch())
                DashboardPresetStore(dashboard_preset_state_root()).save(record)
            except (DashboardPresetStoreError, DashboardPresetValidationError, ValueError):
                preset_manager = replace(preset_manager, notice="preset-save-failed")
            else:
                current_preset_key = f"user:{command.name}"
            return
        if isinstance(command, DeletePreset):
            try:
                DashboardPresetStore(dashboard_preset_state_root()).delete(
                    command.key.removeprefix("user:")
                )
            except DashboardPresetStoreError:
                preset_manager = replace(preset_manager, notice="preset-delete-failed")
            else:
                if current_preset_key == command.key:
                    current_preset_key = None
            return
        if isinstance(command, LoadPreset):
            try:
                if command.key.startswith("builtin:"):
                    launch = builtin_preset_launch(command.key.removeprefix("builtin:"))
                else:
                    from ccusage_viz.datasets.service import DatasetService

                    record = DashboardPresetStore(dashboard_preset_state_root()).get(
                        command.key.removeprefix("user:")
                    )
                    launch = materialize_preset(record, DatasetService().installed_command_source)
                loaded_options = replace(
                    launch, explicit=options.explicit, launcher=options.launcher
                )

                def apply_loaded_preset() -> None:
                    nonlocal options
                    options = loaded_options
                    apply_dashboard_state(preset_state_from_launch(loaded_options))

                record_mutation(("preset", "load", command.key), apply_loaded_preset)
            except (DashboardPresetStoreError, DashboardPresetValidationError, UsageError):
                preset_manager = replace(preset_manager, notice="preset-load-failed")
            else:
                current_preset_key = command.key
                preset_manager = None

    def open_preset_manager(*, save: bool = False) -> None:
        nonlocal preset_manager
        preset_manager = reconcile_preset_manager(
            PresetManagerState(mode="save" if save else "list"),
            preset_catalog(),
            visible_rows=max(1, get_terminal_size().lines - 4),
        )

    def open_help(
        *,
        context: str = "dashboard",
        action: str | None = None,
        selected: str | None = None,
        dataset_id: str | None = None,
        chart_kind: str | None = None,
    ) -> None:
        nonlocal help_overlay
        help_overlay = HelpOverlayState(
            AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS),
            adjustment_timer.remaining() if adjustment_timer is not None else None,
            context=context,
            action=action,
            selected=selected,
            dataset_id=dataset_id,
            chart_kind=chart_kind,
        )
        paint()

    def close_help() -> None:
        nonlocal adjustment_timer, help_overlay
        assert help_overlay is not None
        remaining = help_overlay.adjustment_remaining
        help_overlay = None
        if adjustment_mode is not None and remaining is not None:
            adjustment_timer = AdjustmentIdleTimer.from_remaining(remaining)

    def read_adjustment_event(decoder: InputDecoder) -> object:
        timeout = 0.1
        if help_overlay is not None:
            timeout = min(timeout, help_overlay.timer.remaining())
        deadline = animation_deadline()
        if deadline is not None:
            timeout = min(timeout, max(0.0, deadline - time.monotonic()))
        remaining = copy_feedback.remaining(now=time.monotonic())
        if remaining is not None:
            timeout = min(timeout, remaining)
        if help_overlay is not None:
            event = read_event(decoder, timeout)
            if isinstance(event, (KeyEvent, MouseEvent, PasteEvent, WheelEvent)) and not (
                isinstance(event, KeyEvent) and event.value == "\x03"
            ):
                help_overlay.timer.record_input()
            elif event is None:
                help_overlay.timer.check()
            return event
        if adjustment_timer is None:
            return read_event(decoder, timeout)
        event = read_event(decoder, min(timeout, adjustment_timer.remaining()))
        if isinstance(event, (KeyEvent, MouseEvent, PasteEvent, WheelEvent)):
            adjustment_timer.record_input()
        elif event is None:
            adjustment_timer.check()
        return event

    def raise_if_interrupt(event: object) -> object:
        """Route decoded Ctrl-C through the TUI's controlled cleanup path."""

        if isinstance(event, KeyEvent) and event.value == "\x03":
            raise KeyboardInterrupt
        return event

    def allocate_pane_id() -> int:
        nonlocal next_pane_id
        pane_id = next_pane_id
        next_pane_id += 1
        return pane_id

    def start_pane_submission(
        pane: TuiChartPane,
        operation: OperationToken,
    ) -> tuple[PaneFuture, Callable[[], None]]:
        component = pane.component
        if isinstance(component, MonitorComponent):
            if (
                component.candidate.host.demo_size
                and pane.demo_warmed_generation != component.generation
            ):
                chart = component.candidate.chart
                if not isinstance(chart, MonitorConfig):
                    raise TypeError("monitor pane component has historical configuration")
                cancelled = Event()
                steps = min(24, max(8, chart.window_seconds))
                warmup_future = executor.submit(
                    _await_monitor_warmup,
                    component,
                    generation=component.generation,
                    trigger=operation.trigger,
                    steps=steps,
                    cancelled=cancelled,
                )
                return warmup_future, cancelled.set
            try:
                submission = component.submit(
                    query_trigger(operation.trigger),
                    sample_ordinal=pane.demo_ordinal + 1,
                )
            except BaseException as exc:
                component.fail(exc, generation=component.generation)
                raise
            monitor_future = executor.submit(_await_monitor_submission, submission)
            return monitor_future, submission.cancel
        purpose = (
            HistoricalPurpose.SUPPLEMENTAL
            if operation.trigger is LifecycleTrigger.CONFIGURATION
            and component.snapshot is not None
            and component.accepted_generation == component.generation
            and component.missing_comparison_coverage().intervals
            else HistoricalPurpose.PRIMARY
        )
        try:
            submission = component.submit(
                query_trigger(operation.trigger),
                coverage=(
                    component.snapshot.coverage
                    if purpose is HistoricalPurpose.SUPPLEMENTAL and component.snapshot is not None
                    else None
                ),
                purpose=purpose,
            )
        except BaseException as exc:
            component.fail(
                exc,
                generation=component.generation,
                purpose=purpose,
            )
            raise
        historical_future = executor.submit(_await_historical_submission, submission)
        return historical_future, submission.cancel

    def record_custom_log(pane: TuiCustomPane, status: str, detail: str) -> None:
        pane.logs.append(CustomLogRecord(datetime.now().astimezone(), status, detail))
        pane.logs[:] = pane.logs[-20:]

    def record_custom_warnings(source: CustomCommandSource, response: object) -> None:
        for warning in getattr(response, "warnings", ()):
            identity = (source.dataset_id, warning.code)
            if identity in displayed_custom_warnings:
                continue
            displayed_custom_warnings.add(identity)
            message = warning.message.zh_cn if translator.language == "zh" else warning.message.en
            for pane in (item for item in panes if isinstance(item, TuiCustomPane)):
                if pane.component.candidate.source.dataset_id == source.dataset_id:
                    record_custom_log(pane, "warning", message)

    def start_custom_submission(
        pane: TuiCustomPane, operation: OperationToken
    ) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        custom_monitor = isinstance(pane.component, CustomMonitorComponent)
        if not pane.probe_complete:
            intent = (
                custom_v2_probe_query_intent
                if custom_monitor or pane.component.candidate.metric_id is not None
                else custom_probe_query_intent
            )(
                pane.component.candidate.source,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=pane.process,
            )
            handle = runtime.submit(intent)
            return (
                executor.submit(_await_custom_submission, handle, operation.generation, "probe"),
                handle.cancel,
            )
        if custom_monitor:
            if options.host.timezone is None:
                raise RuntimeError("custom Dataset requests require a timezone")
            intent = custom_v2_monitor_query_intent(
                pane.component.request_config,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                end_at=datetime.now().astimezone(),
                process=pane.process,
            )
            handle = runtime.submit(intent)
            return (
                executor.submit(_await_custom_submission, handle, operation.generation, "primary"),
                handle.cancel,
            )
        purpose = "comparison" if pane.component.comparison_is_pending else "primary"
        config = (
            pane.component.comparison_request_config()
            if purpose == "comparison"
            else pane.component.request_config
        )
        if config is None:
            raise RuntimeError("custom comparison request is no longer required")
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        intent = custom_historical_query_intent(
            config,
            timezone=options.host.timezone,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
            process=pane.process,
            request_id_suffix=":comparison" if purpose == "comparison" else "",
            partition_declared=pane.component.partition_declared_for_request,
        )
        handle = runtime.submit(intent)
        return (
            executor.submit(
                _await_custom_submission,
                handle,
                operation.generation,
                purpose,
                config if purpose == "comparison" else None,
            ),
            handle.cancel,
        )

    def start_builtin_pane_summary_submission(
        pane: TuiChartPane, operation: OperationToken
    ) -> tuple[Future[BuiltinSummaryOutcome], Callable[[], None]]:
        component = pane.component
        if not isinstance(component, HistoricalChartComponent):
            raise TypeError("monitor panes do not have built-in summary lifecycles")
        plan = builtin_summary_query_plan(
            component.candidate, today=local_today(timezone=options.host.timezone)
        )
        intent = builtin_summary_query_intent(
            component.candidate,
            runtime.definition(historical_provider_id(component.candidate)),
            plan,
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
        )
        handle = runtime.submit(intent)
        return (
            executor.submit(
                _await_builtin_summary_submission,
                handle,
                operation.generation,
                plan,
                component.candidate.chart,
            ),
            handle.cancel,
        )

    def refresh_builtin_pane_summary(
        pane: TuiChartPane,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
        invalidate: bool = False,
    ) -> bool:
        lifecycle = pane.summary_lifecycle
        if lifecycle is None or not isinstance(pane.component, HistoricalChartComponent):
            return False
        if invalidate:
            pane.summary_generation += 1
            lifecycle.detach_active()
        try:
            return lifecycle.request(
                trigger,
                generation=pane.summary_generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=lambda operation: start_builtin_pane_summary_submission(pane, operation),
            )
        except BaseException as exc:
            pane.summary_error = exc
            return False

    def start_builtin_pane_summary(pane: TuiChartPane, *, now: float) -> bool:
        lifecycle = pane.summary_lifecycle
        if lifecycle is None:
            return False
        try:
            return lifecycle.start_ready(
                now=now,
                start=lambda operation: start_builtin_pane_summary_submission(pane, operation),
            )
        except BaseException as exc:
            pane.summary_error = exc
            return False

    def start_custom_pane_summary_submission(
        pane: TuiCustomPane, operation: OperationToken
    ) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        summary = pane.summary
        if summary is None:
            raise RuntimeError("custom Pane has no summary lifecycle")
        config = pane.component.request_config
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        plan = (
            range_summary_query_plan(config.date_range)
            if config.date_range.fixed_bounds
            else summary_query_plan(
                local_today(timezone=options.host.timezone),
                cast(SummaryScope, config.granularity),
            )
        )
        summary.select(config.source, config.filters)
        intent = (
            custom_v2_summary_query_intent(
                config,
                plan,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=pane.process,
            )
            if config.metric_id is not None
            else custom_summary_query_intent(
                config.source,
                plan,
                filters=config.filters,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=pane.process,
            )
        )
        request = intent.payload
        if not isinstance(request, (CustomSummaryRequest, V2SummaryRequest)):
            raise TypeError("custom Pane summary intent has an unexpected payload")
        summary.requested_period = request.scope
        summary.requested_as_of_date = request.current.until
        handle = runtime.submit(intent)
        return (
            executor.submit(_await_custom_submission, handle, operation.generation),
            handle.cancel,
        )

    def refresh_custom_pane_summary(
        pane: TuiCustomPane,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
        summary_affecting: bool = False,
    ) -> bool:
        summary = pane.summary
        if summary is None:
            return False
        config = pane.component.request_config
        if not custom_date_summary_supported(config):
            if summary.response is not None or summary.lifecycle.active is not None:
                summary.invalidate()
            return False
        source_changed = summary.source != config.source or summary.filters != config.filters
        if source_changed:
            summary.invalidate()
        try:
            return summary.lifecycle.request(
                trigger,
                generation=summary.generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=lambda operation: start_custom_pane_summary_submission(pane, operation),
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def start_pane(index: int, *, now: float) -> bool:
        pane = panes[index]
        try:
            if isinstance(pane, TuiCustomPane):
                chart_started = pane.lifecycle.start_ready(
                    now=now,
                    start=lambda operation: start_custom_submission(pane, operation),
                )
                summary_started = (
                    refresh_custom_pane_summary(
                        pane, trigger=LifecycleTrigger.STARTUP, summary_affecting=True
                    )
                    if pane.probe_complete
                    else False
                )
                return chart_started or summary_started
            if isinstance(pane, TuiChartPane):
                chart_started = pane.lifecycle.start_ready(
                    now=now,
                    start=lambda operation: start_pane_submission(pane, operation),
                )
                return start_builtin_pane_summary(pane, now=now) or chart_started
        except BaseException as exc:
            if isinstance(pane, TuiCustomPane) and pane.component.fail(
                exc, generation=pane.component.generation
            ):
                record_custom_log(pane, "error", _custom_failure_log_detail(exc, translator))
            return False
        return False

    def pane_records(pane: TuiChartPane) -> tuple[UsageRecord, ...]:
        component = pane.component
        if isinstance(component, MonitorComponent):
            return component.accepted_records
        return component.snapshot.records if component.snapshot is not None else ()

    def start_new_pane(index: int) -> None:
        refresh(index, trigger=LifecycleTrigger.STARTUP)

    def pane_includes_projects(pane: TuiChartPane) -> bool:
        component = pane.component
        return (
            not isinstance(component, HistoricalChartComponent)
            or component.snapshot is None
            or component.snapshot.includes_project_attribution
        )

    def refresh(
        index: int,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
        data_affecting: bool = True,
        summary_affecting: bool = False,
    ) -> bool:
        pane = panes[index]
        if isinstance(pane, TuiCustomPane):
            if data_affecting:
                component = pane.component
                component.configure(
                    replace(
                        component.candidate,
                        date_range=refresh_custom_ranking_range(
                            component.candidate.date_range,
                            now=datetime.now().astimezone(),
                            timezone=options.host.timezone,
                        ),
                    ),
                    data_affecting=True,
                )
            now = time.monotonic()
            try:
                chart_requested = pane.lifecycle.request(
                    trigger,
                    generation=pane.component.generation,
                    now=now,
                    replace_active=replace_active,
                    start=lambda operation: start_custom_submission(pane, operation),
                )
                should_refresh_summary = summary_affecting or trigger in {
                    LifecycleTrigger.PERIODIC,
                    LifecycleTrigger.MANUAL,
                }
                summary_requested = (
                    refresh_custom_pane_summary(
                        pane,
                        trigger=trigger,
                        replace_active=replace_active,
                        summary_affecting=summary_affecting,
                    )
                    if should_refresh_summary and pane.probe_complete
                    else False
                )
                return chart_requested or summary_requested
            except BaseException as exc:
                if pane.component.fail(exc, generation=pane.component.generation):
                    record_custom_log(pane, "error", _custom_failure_log_detail(exc, translator))
                return False
        if not isinstance(pane, TuiChartPane):
            return False
        component = pane.component
        if not isinstance(component, MonitorComponent) and data_affecting:
            current = component.candidate
            if isinstance(current.chart, MonitorConfig):
                raise TypeError("historical pane component has monitor configuration")
            submitted = replace(
                current,
                chart=replace(
                    current.chart,
                    date_range=refresh_date_range(
                        current.chart.date_range, timezone=options.host.timezone
                    ),
                ),
            )
            component.configure(submitted, data_affecting=True)
        now = time.monotonic()
        try:
            chart_requested = pane.lifecycle.request(
                trigger,
                generation=component.generation,
                now=now,
                replace_active=replace_active,
                start=lambda operation: start_pane_submission(pane, operation),
            )
            summary_requested = refresh_builtin_pane_summary(
                pane,
                trigger=trigger,
                replace_active=replace_active,
                invalidate=data_affecting,
            )
            return chart_requested or summary_requested
        except BaseException:
            return False

    def start_custom_summary_submission(
        summary: CustomDashboardSummary, operation: OperationToken
    ) -> tuple[Future[CustomOutcome], Callable[[], None]]:
        selections = {item.source.dataset_id: item for item in _custom_dashboard_sources(panes)}
        selection = selections.get(summary.source.dataset_id)
        if selection is None:
            raise RuntimeError("custom Dashboard source is no longer visible")
        summary.select(selection.source, ())
        if options.host.timezone is None:
            raise RuntimeError("custom Dataset requests require a timezone")
        if selection.summary_mode == "none":
            raise RuntimeError("summary disabled for selected metric")
        plan = (
            range_summary_query_plan(selection.config.date_range)
            if selection.config is not None and selection.config.date_range.fixed_bounds
            else summary_query_plan(
                local_today(timezone=options.host.timezone),
                cast(SummaryScope, header.summary_period),
            )
        )
        if selection.summary_mode in {"total", "comparisons"} and selection.config is not None:
            if selection.summary_mode == "total":
                plan = SummaryQueryPlan("total", plan.current)
            intent = custom_v2_summary_query_intent(
                selection.config,
                plan,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=options.process,
            )
        else:
            intent = custom_summary_query_intent(
                summary.source,
                plan,
                filters=summary.filters,
                timezone=options.host.timezone,
                owner_id=operation.owner_id,
                generation=operation.generation,
                trigger=query_trigger(operation.trigger),
                process=options.process,
            )
        request = intent.payload
        if isinstance(request, V2SummaryRequest):
            summary.requested_period = request.scope
            summary.requested_as_of_date = request.current.until
        elif not isinstance(request, CustomSummaryRequest):
            raise TypeError("custom Dashboard summary intent has an unexpected payload")
        else:
            summary.requested_period = request.scope
            summary.requested_as_of_date = request.current.until
        handle = runtime.submit(intent)
        return (
            executor.submit(_await_custom_submission, handle, operation.generation),
            handle.cancel,
        )

    def start_custom_summary(summary: CustomDashboardSummary, *, now: float) -> bool:
        try:
            return summary.lifecycle.start_ready(
                now=now,
                start=lambda operation: start_custom_summary_submission(summary, operation),
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def refresh_custom_summary(
        summary: CustomDashboardSummary,
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
    ) -> bool:
        if header.summary_period == "none":
            return False
        try:
            return summary.lifecycle.request(
                trigger,
                generation=summary.generation,
                now=time.monotonic(),
                replace_active=replace_active,
                start=lambda operation: start_custom_summary_submission(summary, operation),
            )
        except BaseException as exc:
            summary.error = exc
            return False

    def refresh_custom_summaries(
        *, trigger: LifecycleTrigger, replace_active: bool = False
    ) -> tuple[OperationToken, ...]:
        return tuple(
            summary.lifecycle.active
            for summary in header.custom_summaries.values()
            if refresh_custom_summary(summary, trigger=trigger, replace_active=replace_active)
            and summary.lifecycle.active is not None
        )

    def start_header_submission(
        operation: OperationToken,
    ) -> tuple[Future[UsageSnapshot], Callable[[], None]]:
        requested = _header_refresh_interval(
            header,
            aggressive=operation.trigger is LifecycleTrigger.MANUAL,
        )
        if requested is None:
            raise AssertionError("admitted header refresh must require data")
        submitted = replace(
            header.options,
            chart=replace(
                header.options.chart,
                date_range=DateRange(requested.since, requested.until),
            ),
        )
        intent = historical_query_intent(
            submitted,
            header.runtime.definition(historical_provider_id(submitted)),
            owner_id=operation.owner_id,
            generation=operation.generation,
            trigger=query_trigger(operation.trigger),
        )
        started = time.monotonic()
        handle = header.runtime.submit(intent)
        header.options = submitted
        header.error = None
        return executor.submit(_await_historical, handle, started), handle.cancel

    def start_header(*, now: float) -> bool:
        if not header.token_enabled:
            return False
        try:
            return header.lifecycle.start_ready(now=now, start=start_header_submission)
        except BaseException as exc:
            header.error = str(exc)
            return False

    def refresh_header(
        *,
        trigger: LifecycleTrigger,
        replace_active: bool = False,
    ) -> bool:
        if not header.token_enabled:
            return False
        if (
            _header_refresh_interval(
                header,
                aggressive=trigger is LifecycleTrigger.MANUAL,
            )
            is None
        ):
            return False
        now = time.monotonic()
        try:
            return header.lifecycle.request(
                trigger,
                generation=header.generation,
                now=now,
                replace_active=replace_active,
                start=start_header_submission,
            )
        except BaseException as exc:
            header.error = str(exc)
            return False

    def collect() -> bool:
        nonlocal last_successful_update
        changed = False

        def retire_manual_refresh(operation: OperationToken) -> None:
            nonlocal changed
            if operation not in manual_refresh_operations:
                return
            manual_refresh_operations.remove(operation)
            if not manual_refresh_operations:
                changed = True

        active_operations = {
            lifecycle.active
            for lifecycle in (
                header.lifecycle,
                *(summary.lifecycle for summary in header.custom_summaries.values()),
                *(
                    lifecycle
                    for pane in panes
                    for lifecycle in (
                        (pane.lifecycle, pane.summary.lifecycle)
                        if isinstance(pane, TuiCustomPane) and pane.summary is not None
                        else (pane.lifecycle,)
                        if isinstance(pane, TuiChartPane) and pane.summary_lifecycle is not None
                        else (pane.lifecycle,)
                        if isinstance(pane, TuiChartPane)
                        else ()
                    )
                ),
            )
            if lifecycle.active is not None
        }
        if manual_refresh_operations - active_operations:
            manual_refresh_operations.intersection_update(active_operations)
            changed = True

        completed_header = header.lifecycle.take_completed(lambda future: future.done())
        if completed_header is not None:
            operation, future = completed_header
            observed_at = time.monotonic()
            try:
                result = future.result()
                if header.lifecycle.accepts(operation, generation=header.generation):
                    header.records = _replace_header_interval(header.records, result)
                    header.coverage = header.coverage.merge(result.coverage)
                    header.snapshot = result
                    header.accepted_at = datetime.now().astimezone()
                    last_successful_update = header.accepted_at
                    header.error = None
                    header.lifecycle.complete(operation, generation=header.generation)
                    changed = True
            except Exception as exc:
                if header.lifecycle.accepts(operation, generation=header.generation):
                    header.lifecycle.complete(operation, generation=header.generation)
                    header.error = str(exc)
                    changed = True
            retire_manual_refresh(operation)
            start_header(now=observed_at)
        for summary in header.custom_summaries.values():
            completed_custom_summary = summary.lifecycle.take_completed(
                lambda future: future.done()
            )
            if completed_custom_summary is None:
                continue
            operation, future = completed_custom_summary
            observed_at = time.monotonic()
            try:
                outcome = future.result()
                if not summary.lifecycle.accepts(operation, generation=outcome.generation):
                    summary.lifecycle.abandon(operation)
                elif outcome.error is not None:
                    summary.error = outcome.error
                    summary.lifecycle.complete(operation, generation=outcome.generation)
                    changed = True
                elif outcome.result is None:
                    summary.lifecycle.abandon(operation)
                else:
                    response = outcome.result.custom_response
                    if not isinstance(response, (CustomSummaryResponse, V2SummaryResponse)):
                        raise TypeError(
                            "custom provider result does not contain a summary response"
                        )
                    summary.response = response
                    record_custom_warnings(summary.source, response)
                    summary.error = None
                    summary.accepted_at = datetime.now().astimezone()
                    summary.accepted_period = summary.requested_period
                    summary.accepted_as_of_date = summary.requested_as_of_date
                    summary.lifecycle.complete(operation, generation=outcome.generation)
                    last_successful_update = summary.accepted_at
                    changed = True
            except Exception as exc:
                if summary.lifecycle.accepts(operation, generation=operation.generation):
                    summary.error = exc
                    summary.lifecycle.complete(operation, generation=operation.generation)
                    changed = True
            retire_manual_refresh(operation)
            start_custom_summary(summary, now=observed_at)
        for pane in (item for item in panes if isinstance(item, TuiCustomPane)):
            summary = pane.summary
            if summary is None:
                continue
            completed_pane_summary = summary.lifecycle.take_completed(lambda future: future.done())
            if completed_pane_summary is None:
                continue
            operation, future = completed_pane_summary
            observed_at = time.monotonic()
            try:
                outcome = future.result()
                if not summary.lifecycle.accepts(operation, generation=outcome.generation):
                    summary.lifecycle.abandon(operation)
                elif outcome.error is not None:
                    summary.error = outcome.error
                    summary.lifecycle.complete(operation, generation=outcome.generation)
                    changed = True
                elif outcome.result is None:
                    summary.lifecycle.abandon(operation)
                else:
                    response = outcome.result.custom_response
                    if not isinstance(response, (CustomSummaryResponse, V2SummaryResponse)):
                        raise TypeError("custom provider result does not contain a Pane summary")
                    summary.response = response
                    record_custom_warnings(summary.source, response)
                    summary.error = None
                    summary.accepted_at = datetime.now().astimezone()
                    summary.accepted_period = summary.requested_period
                    summary.accepted_as_of_date = summary.requested_as_of_date
                    summary.lifecycle.complete(operation, generation=outcome.generation)
                    last_successful_update = summary.accepted_at
                    changed = True
            except Exception as exc:
                if summary.lifecycle.accepts(operation, generation=operation.generation):
                    summary.error = exc
                    summary.lifecycle.complete(operation, generation=operation.generation)
                    changed = True
            retire_manual_refresh(operation)
            if summary.lifecycle.active is None:
                summary.lifecycle.start_ready(
                    now=observed_at,
                    start=lambda operation, pane=pane: start_custom_pane_summary_submission(
                        pane, operation
                    ),
                )
        for pane in (item for item in panes if isinstance(item, TuiChartPane)):
            lifecycle = pane.summary_lifecycle
            if lifecycle is None or not isinstance(pane.component, HistoricalChartComponent):
                continue
            completed_summary = lifecycle.take_completed(lambda future: future.done())
            if completed_summary is None:
                continue
            operation, future = completed_summary
            observed_at = time.monotonic()
            try:
                outcome = future.result()
                if not lifecycle.accepts(operation, generation=outcome.generation):
                    lifecycle.abandon(operation)
                elif outcome.error is not None:
                    pane.summary_error = outcome.error
                    lifecycle.complete(operation, generation=outcome.generation)
                    changed = True
                elif outcome.result is None:
                    lifecycle.abandon(operation)
                else:
                    pane.summary = build_builtin_pane_summary(
                        outcome.chart,
                        outcome.plan,
                        outcome.result.records,
                        outcome.result.coverage,
                        accepted_at=datetime.now().astimezone(),
                    )
                    pane.component.set_summary(pane.summary.summary)
                    pane.summary_error = None
                    lifecycle.complete(operation, generation=outcome.generation)
                    last_successful_update = pane.summary.accepted_at
                    changed = True
            except Exception as exc:
                if lifecycle.accepts(operation, generation=operation.generation):
                    pane.summary_error = exc
                    lifecycle.complete(operation, generation=operation.generation)
                    changed = True
            retire_manual_refresh(operation)
            start_builtin_pane_summary(pane, now=observed_at)
        for index, pane in enumerate(panes):
            if isinstance(pane, TuiCustomPane):
                completed_custom = pane.lifecycle.take_completed(lambda future: future.done())
                if completed_custom is None:
                    continue
                operation, future = completed_custom
                observed_at = time.monotonic()
                try:
                    outcome = future.result()
                    if not pane.lifecycle.accepts(operation, generation=outcome.generation):
                        pane.lifecycle.abandon(operation)
                    elif outcome.error is not None:
                        failure = (
                            outcome.error.values.get("custom_failure")
                            if isinstance(outcome.error, QueryError)
                            else None
                        )
                        retry = False
                        if (
                            isinstance(failure, CustomProtocolFailure)
                            and failure.code == "unsupported_query"
                            and failure.unsupported is not None
                            and isinstance(
                                pane.component, (CustomHistoricalComponent, CustomMonitorComponent)
                            )
                            and pane.component.switch_target_config is not None
                            and pane.component.v2_descriptor is not None
                        ):
                            target = next(
                                (
                                    metric
                                    for metric in pane.component.v2_descriptor.metrics
                                    if metric.id == pane.component.request_config.metric_id
                                ),
                                None,
                            )
                            field = failure.unsupported.get("field")
                            retry = (
                                target is not None
                                and field is not None
                                and pane.component.retry_metric_switch(field, target)
                            )
                        if retry:
                            pane.lifecycle.complete(operation, generation=outcome.generation)
                            refresh(
                                index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                            )
                            changed = True
                            continue
                        if (
                            isinstance(failure, CustomProtocolFailure)
                            and failure.code == "unsupported_query"
                            and failure.unsupported is not None
                            and isinstance(
                                pane.component, (CustomHistoricalComponent, CustomMonitorComponent)
                            )
                            and pane.component.switch_target_config is not None
                            and pane.component.v2_descriptor is not None
                        ):
                            target = next(
                                (
                                    metric
                                    for metric in pane.component.v2_descriptor.metrics
                                    if metric.id == pane.component.request_config.metric_id
                                ),
                                None,
                            )
                            field = failure.unsupported.get("field")
                            if target is not None and field is not None:
                                pane.component.cancel_metric_switch()
                                copy_feedback.show(
                                    translator.text(
                                        "status.custom_metric_switch_no_default",
                                        metric=_dataset_title(target.title, translator),
                                        field=field,
                                    )
                                )
                                pane.lifecycle.complete(operation, generation=outcome.generation)
                                changed = True
                                continue
                        failed = (
                            pane.component.fail(outcome.error, generation=outcome.generation)
                            if isinstance(pane.component, CustomMonitorComponent)
                            else pane.component.fail(
                                outcome.error,
                                generation=outcome.generation,
                                purpose="primary"
                                if outcome.purpose == "probe"
                                else outcome.purpose,
                            )
                        )
                        if failed:
                            record_custom_log(
                                pane, "error", _custom_failure_log_detail(outcome.error, translator)
                            )
                            pane.lifecycle.complete(operation, generation=outcome.generation)
                            changed = True
                        else:
                            pane.lifecycle.abandon(operation)
                    elif outcome.result is None:
                        pane.lifecycle.abandon(operation)
                    elif outcome.purpose == "probe":
                        response = outcome.result.custom_response
                        if isinstance(pane.component, CustomMonitorComponent):
                            if not isinstance(response, V2ProbeResponse):
                                raise TypeError("custom monitor probe did not return a V2 response")
                            resolved = resolve_metric(pane.component.candidate, response.descriptor)
                            metric = next(
                                (
                                    item
                                    for item in response.descriptor.metrics
                                    if item.id == resolved.metric_id
                                ),
                                None,
                            )
                            if metric is None or not isinstance(
                                metric.capabilities.charts.get("monitor"), V2MonitorCapability
                            ):
                                raise TypeError(
                                    "custom monitor metric is not supported by runtime probe"
                                )
                            from ccusage_viz.custom_monitor_component import (
                                apply_custom_monitor_defaults,
                            )

                            resolved, display_window = apply_custom_monitor_defaults(
                                resolved, metric
                            )
                            pane.component.configure(resolved, data_affecting=False)
                            pane.component.set_metric(metric)
                            if display_window is not None:
                                pane.component.configure_display_window(display_window)
                        elif isinstance(response, V2ProbeResponse):
                            resolved = resolve_metric(pane.component.candidate, response.descriptor)
                            descriptor = v2_metric_probe_descriptor(
                                response.descriptor, resolved.metric_id
                            )
                            pane.component.configure(
                                apply_custom_probe_defaults(
                                    resolved,
                                    descriptor,
                                    timezone=options.host.timezone or "UTC",
                                ),
                                data_affecting=False,
                            )
                            pane.component.set_capability(
                                descriptor.capabilities.charts[pane.component.candidate.kind]
                            )
                        elif not isinstance(response, CustomProbeResponse):
                            raise TypeError(
                                "custom provider result does not contain a probe response"
                            )
                        if options.host.timezone is None:
                            raise RuntimeError("custom Dataset requests require a timezone")
                        if isinstance(pane.component, CustomHistoricalComponent) and isinstance(
                            response, CustomProbeResponse
                        ):
                            pane.component.configure(
                                apply_custom_probe_defaults(
                                    pane.component.candidate,
                                    response.descriptor,
                                    timezone=options.host.timezone,
                                ),
                                data_affecting=False,
                            )
                            pane.component.set_capability(
                                response.descriptor.capabilities.charts[
                                    pane.component.candidate.kind
                                ]
                            )
                        if isinstance(pane.component, CustomHistoricalComponent):
                            capability = pane.component.capability
                            if (
                                capability is not None
                                and capability.refresh_interval_seconds is not None
                            ):
                                pane.scheduler.rebuild(
                                    capability.refresh_interval_seconds, now=observed_at
                                )
                        pane.probe_complete = True
                        try:
                            from ccusage_viz.datasets.service import DatasetService

                            DatasetService().update_runtime_probe(
                                pane.component.candidate.source, response
                            )
                        except OSError:
                            pass
                        record_custom_warnings(pane.component.candidate.source, response)
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        refresh(
                            index,
                            trigger=LifecycleTrigger.STARTUP,
                            data_affecting=False,
                        )
                        changed = True
                    elif isinstance(pane.component, CustomMonitorComponent):
                        response = outcome.result.custom_response
                        if not isinstance(response, V2MonitorResponse):
                            raise TypeError("custom monitor query did not return a V2 observation")
                        if pane.component.accept(
                            CustomMonitorCompletion(
                                outcome.generation, pane.component.request_config, response
                            ),
                            accepted_at=datetime.now().astimezone(),
                        ):
                            record_custom_warnings(pane.component.candidate.source, response)
                            record_custom_log(
                                pane, "ok", translator.text("status.custom_query_succeeded")
                            )
                            pane.lifecycle.complete(operation, generation=outcome.generation)
                            last_successful_update = pane.component.accepted_at
                            if pane.attachment is not None:
                                _update_custom_monitor_attachment_activity(
                                    pane.component,
                                    pane.attachment,
                                    now=time.monotonic(),
                                    wall=pane.component.accepted_at,
                                    translator=translator,
                                )
                            changed = True
                        else:
                            pane.lifecycle.abandon(operation)
                    elif pane.component.apply_provider_result(
                        outcome.result,
                        purpose=outcome.purpose,
                        comparison_request_config=outcome.comparison_request_config,
                    ):
                        record_custom_warnings(
                            pane.component.candidate.source, outcome.result.custom_response
                        )
                        record_custom_log(
                            pane,
                            "ok",
                            translator.text("status.custom_query_succeeded"),
                        )
                        pane.lifecycle.complete(operation, generation=outcome.generation)
                        last_successful_update = pane.component.accepted_at
                        changed = True
                        if (
                            outcome.purpose == "primary"
                            and pane.component.start_comparison() is not None
                        ):
                            refresh(
                                index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                            )
                    else:
                        pane.lifecycle.abandon(operation)
                except Exception as exc:
                    if pane.lifecycle.accepts(operation, generation=operation.generation):
                        pane.lifecycle.abandon(operation)
                        if pane.component.fail(
                            exc, generation=operation.generation, purpose="primary"
                        ):
                            record_custom_log(
                                pane, "error", _custom_failure_log_detail(exc, translator)
                            )
                            changed = True
                retire_manual_refresh(operation)
                start_pane(index, now=observed_at)
                continue
            if not isinstance(pane, TuiChartPane):
                continue
            completed_pane = pane.lifecycle.take_completed(lambda future: future.done())
            if completed_pane is None:
                continue
            operation, future = completed_pane
            component = pane.component
            observed_at = time.monotonic()
            purpose = HistoricalPurpose.PRIMARY
            try:
                loaded = future.result()
                if isinstance(loaded, HistoricalOutcome):
                    purpose = loaded.purpose
                active = pane.lifecycle.accepts(operation, generation=loaded.generation)
                if not active:
                    pane.lifecycle.abandon(operation)
                    retire_manual_refresh(operation)
                    continue
                if loaded.error is not None:
                    failed = (
                        component.fail(
                            loaded.error,
                            generation=loaded.generation,
                            purpose=loaded.purpose,
                        )
                        if isinstance(
                            component,
                            HistoricalChartComponent,
                        )
                        and isinstance(loaded, HistoricalOutcome)
                        else component.fail(
                            loaded.error,
                            generation=loaded.generation,
                        )
                    )
                    if failed:
                        pane.lifecycle.complete(operation, generation=loaded.generation)
                        changed = True
                    else:
                        pane.lifecycle.abandon(operation)
                else:
                    if isinstance(component, MonitorComponent):
                        if isinstance(loaded, MonitorWarmupOutcome):
                            if not loaded.completions:
                                pane.lifecycle.abandon(operation)
                                retire_manual_refresh(operation)
                                continue
                            chart = component.candidate.chart
                            if not isinstance(chart, MonitorConfig):
                                raise TypeError(
                                    "monitor pane component has historical configuration"
                                )
                            steps = len(loaded.completions)
                            demo_now = observed_at
                            demo_wall = datetime.now().astimezone()
                            demo_seconds = chart.window_seconds / max(1, steps - 1)
                            accepted = all(
                                component.accept(
                                    completion,
                                    now=demo_now - (steps - ordinal) * demo_seconds,
                                    wall=demo_wall
                                    - timedelta(seconds=(steps - ordinal) * demo_seconds),
                                    detect_gap=False,
                                )
                                for ordinal, completion in enumerate(loaded.completions, start=1)
                            )
                            if accepted:
                                pane.demo_ordinal = steps
                                pane.demo_warmed_generation = loaded.generation
                                pane.scheduler.rebuild(
                                    component.candidate.host.interval, now=observed_at
                                )
                        else:
                            assert isinstance(loaded, MonitorOutcome)
                            assert loaded.completion is not None
                            accepted = component.accept(
                                loaded.completion,
                                now=observed_at,
                                wall=datetime.now().astimezone(),
                            )
                            if accepted:
                                pane.demo_ordinal += 1
                    else:
                        assert isinstance(loaded, HistoricalOutcome)
                        assert loaded.completion is not None
                        accepted = component.accept(loaded.completion)
                        if accepted and component.candidate.chart.kind == "ranking":
                            _refresh_deltas(pane, component.ranking_values())
                            _refresh_ranks(pane, component.ranking_keys())
                    if accepted:
                        if pane.attachment is not None and isinstance(component, MonitorComponent):
                            _update_monitor_attachment_activity(
                                component,
                                pane.attachment,
                                now=observed_at,
                                wall=datetime.now().astimezone(),
                                translator=translator,
                            )
                        pane.lifecycle.complete(operation, generation=loaded.generation)
                        last_successful_update = component.accepted_at
                        changed = True
                        if (
                            isinstance(component, HistoricalChartComponent)
                            and isinstance(loaded, HistoricalOutcome)
                            and loaded.purpose is HistoricalPurpose.PRIMARY
                            and component.missing_comparison_coverage().intervals
                        ):
                            refresh(
                                index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                            )
                    else:
                        pane.lifecycle.abandon(operation)
            except Exception as exc:
                if pane.lifecycle.accepts(operation, generation=operation.generation):
                    pane.lifecycle.abandon(operation)
                    failed = (
                        component.fail(
                            exc,
                            generation=operation.generation,
                            purpose=purpose,
                        )
                        if isinstance(component, HistoricalChartComponent)
                        else component.fail(exc, generation=operation.generation)
                    )
                    if failed:
                        changed = True
            retire_manual_refresh(operation)
            start_pane(index, now=observed_at)
        return changed

    def animation_deadline() -> float | None:
        return min(
            (
                deadline
                for pane in panes
                if (deadline := _pane_animation_deadline(pane)) is not None
            ),
            default=None,
        )

    def capture_dashboard_state() -> DashboardState:
        pane_states: list[DashboardPaneState] = []
        for pane in panes:
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
            active_grid,
            active_layout,
            column_weights,
            row_weights,
            dashboard_theme,
            dashboard_style,
            header_style,
            header.summary_period,
            body_view,
        )

    history = DashboardHistory(capture_dashboard_state())

    def apply_dashboard_state(state: DashboardState) -> None:
        """Reconcile declarative history without discarding unaffected live Panes."""
        nonlocal panes, active_grid, active_layout, column_weights, row_weights
        nonlocal dashboard_theme, dashboard_style, divider_style, frame_style, header_style
        nonlocal body_view, focused, adjustment_mode, adjustment_page, adjustment_timer
        from ccusage_viz.configuration import standalone_from_chart_pane

        existing = {pane.pane_id: pane for pane in panes}
        reconciled: list[TuiPane] = []
        refresh_indexes: list[tuple[int, bool, bool]] = []
        now = time.monotonic()

        for pane_state in state.panes:
            pane = existing.pop(pane_state.pane_id, None)
            config = pane_state.config
            compatible = (
                (isinstance(config, EmptyPaneConfig) and isinstance(pane, TuiEmptyPane))
                or (isinstance(config, AnimationPaneConfig) and isinstance(pane, TuiAnimationPane))
                or (isinstance(config, CustomChartPaneConfig) and isinstance(pane, TuiCustomPane))
                or (
                    isinstance(config, ChartPaneConfig)
                    and isinstance(pane, TuiChartPane)
                    and type(_pane_display_options(pane).chart) is type(config.chart)
                )
            )
            if not compatible:
                if pane is not None:
                    _shutdown_pane(pane)
                pane = _new_pane(
                    options,
                    config,
                    f"dashboard:pane:{pane_state.pane_id}"
                    if isinstance(config, (ChartPaneConfig, CustomChartPaneConfig))
                    else None,
                    runtime,
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
                candidate = standalone_from_chart_pane(options, pane_state.config)
                current = component.candidate
                if candidate != current:
                    data_affecting = (
                        historical_replacement_required(current, candidate)
                        if isinstance(component, HistoricalChartComponent)
                        else (
                            isinstance(current.chart, MonitorConfig)
                            and isinstance(candidate.chart, MonitorConfig)
                            and (
                                current.chart.by != candidate.chart.by
                                or current.chart.filters != candidate.chart.filters
                            )
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
        panes = reconciled
        active_grid = state.grid
        active_layout = state.layout
        column_weights = state.column_weights
        row_weights = state.row_weights
        theme_changed = dashboard_theme != state.theme
        dashboard_theme = state.theme
        dashboard_style = state.style
        divider_style, frame_style = _dashboard_structure(dashboard_style)
        header_style = state.header_style
        header_refresh_required = (
            header.summary_period != state.header_summary
            and _header_summary(header, state.header_summary) is None
        )
        header.summary_period = state.header_summary
        if theme_changed:
            _set_header_theme(header, dashboard_theme)
        body_view = state.body_view
        if focused is not None and focused >= len(panes):
            end_adjustment()
        for index, data_affecting, summary_affecting in refresh_indexes:
            refresh(
                index,
                trigger=LifecycleTrigger.CONFIGURATION,
                data_affecting=data_affecting,
                summary_affecting=summary_affecting,
            )
        if header_style != "hidden" and header_refresh_required:
            refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
        sync_custom_dashboard_summaries()

    def sync_custom_dashboard_summaries() -> None:
        token_enabled = any(isinstance(pane, TuiChartPane) for pane in panes)
        if header.token_enabled and not token_enabled:
            header.generation += 1
            header.lifecycle.detach_active()
        header.token_enabled = token_enabled
        added = _reconcile_custom_dashboard_summaries(
            header, _custom_dashboard_sources(panes), now=time.monotonic()
        )
        if header_style != "hidden":
            if token_enabled:
                refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
            for summary in added:
                refresh_custom_summary(summary, trigger=LifecycleTrigger.CONFIGURATION)

    def record_mutation(family: object, mutate: Callable[[], None]) -> bool:
        nonlocal history
        before = capture_dashboard_state()
        mutate()
        after = capture_dashboard_state()
        if after == before:
            return False
        sync_custom_dashboard_summaries()
        history = history.record(after, family=family, target=family, timestamp=time.monotonic())
        return True

    def full_dashboard_command() -> str:
        return format_full_dashboard_command(
            replace(options, host=replace(options.host, theme=dashboard_theme)),
            tuple(
                EmptyPaneConfig()
                if isinstance(pane, TuiEmptyPane)
                else CustomChartPaneConfig(pane.component.candidate)
                if isinstance(pane, TuiCustomPane)
                else _chart_pane_config(pane)
                if isinstance(pane, TuiChartPane)
                else AnimationPaneConfig(pane.session.spec, pane.overlay.config)
                for pane in panes
            ),
            grid=active_grid,
            layout=active_layout,
            column_weights=column_weights,
            row_weights=row_weights,
            header_style=header_style,
            header_summary=header.summary_period,
            dashboard_style=dashboard_style,
        )

    def global_operations(width: int) -> str:
        return controls_line(
            translator.text("status.tui_global_operations"),
            width=width,
            color=dashboard_theme != "no-color",
        )

    def preset_operations(width: int) -> str:
        return clip_width(translator.text("status.tui_preset_operations"), width)

    def help_lines(width: int) -> tuple[str, ...]:
        mode = (
            "pane"
            if adjustment_mode == "pane"
            else "global"
            if adjustment_mode == "global"
            else "browse"
        )
        page = "quick" if adjustment_page == "quick" else "advanced"
        scheme = get_color_scheme(dashboard_theme)
        branch, last, pipe = ("|- ", "\\- ", "|  ") if options.host.ascii else ("├─ ", "└─ ", "│  ")
        active_icon = "* " if options.host.ascii else "● "
        selected_page_icon = "[x] " if options.host.ascii else "● "
        unselected_page_icon = "[ ] " if options.host.ascii else "○ "

        def tree_rows(prefix: str, continuation: str, value: str) -> tuple[str, ...]:
            available = max(1, width - display_width(prefix))
            wrapped = wrap_width(value, available)
            return tuple(
                f"{prefix if row_index == 0 else continuation}{row}"
                for row_index, row in enumerate(wrapped)
            )

        def tree_node(
            prefix: str,
            value: str,
            children: tuple[tuple[str, object], ...],
            *,
            is_last: bool,
        ) -> tuple[str, ...]:
            connector = last if is_last else branch
            child_prefix = prefix + ("   " if is_last else pipe)
            rows = list(tree_rows(prefix + connector, child_prefix + "   ", value))
            for index, (child_value, child_children) in enumerate(children):
                rows.extend(
                    tree_node(
                        child_prefix,
                        child_value,
                        cast(tuple[tuple[str, object], ...], child_children),
                        is_last=index == len(children) - 1,
                    )
                )
            return tuple(rows)

        def mode_node(
            name: str, *, active: bool, enter: str, exit: str
        ) -> tuple[str, tuple[object, ...]]:
            return (
                f"{active_icon if active else ''}{translator.text(name)}",
                ((enter, ()), (exit, ())),
            )

        def mode_pages() -> tuple[tuple[str, tuple[object, ...]], ...]:
            active_page = translator.text(f"status.tui_help_page_{page}")
            other_page = translator.text(
                f"status.tui_help_page_{'advanced' if page == 'quick' else 'quick'}"
            )
            return (
                (
                    translator.text(
                        "status.tui_help_mode_pages",
                        active=selected_page_icon.rstrip(),
                        page=active_page,
                        other=unselected_page_icon.rstrip(),
                        other_page=other_page,
                    ),
                    (),
                ),
                (translator.text("status.tui_help_mode_pages_detail"), ()),
            )

        def help_heading(value: str) -> str:
            return emphasize(
                value,
                color=scheme.highlight,
                enabled=dashboard_theme != "no-color",
            )

        if help_overlay is not None and help_overlay.context != "dashboard":
            if help_overlay.context == "chooser":
                assert help_overlay.action is not None
                assert help_overlay.selected is not None
                sections = (
                    (
                        "status.tui_help_section_selecting",
                        (
                            translator.text(f"status.tui_{help_overlay.action}_title"),
                            translator.text("status.tui_help_chooser_detail"),
                        ),
                    ),
                    (
                        "status.tui_help_section_options",
                        tuple(
                            translator.text(
                                "status.tui_help_labeled_option",
                                option=(
                                    f"{'*' if options.host.ascii else '●'} "
                                    f"{translator.text(f'label.pane_{item}')}"
                                    if item == help_overlay.selected
                                    else translator.text(f"label.pane_{item}")
                                ),
                                detail=translator.text(f"status.tui_help_chooser_option_{item}"),
                            )
                            for item in _PANE_COMMANDS
                        ),
                    ),
                )
                rows: list[str] = []
                for heading, values in sections:
                    if rows:
                        rows.append("")
                    rows.append(help_heading(translator.text(heading)))
                    for index, value in enumerate(values):
                        rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
                return tuple(clip_width(line, width) for line in rows)
            elif help_overlay.context == "dataset-chooser":
                assert dataset_modal is not None
                modal = dataset_modal
                if modal.stage == "source" and modal.statuses:
                    status = modal.statuses[modal.index]
                    descriptor = status.registration.probe.descriptor
                    sections = (
                        (
                            "status.tui_help_section_selecting",
                            (translator.text("status.tui_help_dataset_chooser"),),
                        ),
                        (
                            "status.tui_help_section_options",
                            (translator.text("status.tui_help_dataset_chooser_manage"),),
                        ),
                        (
                            "status.tui_help_section_selected",
                            (
                                translator.text(
                                    "status.tui_help_dataset_chooser_selected",
                                    name=_dataset_title(descriptor.dataset.title, translator),
                                    version=descriptor.version,
                                ),
                                (
                                    descriptor.dataset.description.zh_cn
                                    if translator.language == "zh"
                                    else descriptor.dataset.description.en
                                ),
                            ),
                        ),
                    )
                else:
                    assert modal.chart_kinds
                    chart_kind = modal.chart_kinds[modal.index]
                    sections = (
                        (
                            "status.tui_help_section_selecting",
                            (translator.text("status.tui_help_dataset_chart_chooser"),),
                        ),
                        (
                            "status.tui_help_section_options",
                            tuple(
                                translator.text(
                                    "status.tui_help_labeled_option",
                                    option=(
                                        f"{'*' if options.host.ascii else '●'} "
                                        f"{translator.text(f'label.pane_{item}')}"
                                        if item == chart_kind
                                        else translator.text(f"label.pane_{item}")
                                    ),
                                    detail=translator.text(
                                        f"status.tui_help_chooser_option_{item}"
                                    ),
                                )
                                for item in modal.chart_kinds
                            ),
                        ),
                    )
                rows = []
                for heading, values in sections:
                    if rows:
                        rows.append("")
                    rows.append(help_heading(translator.text(heading)))
                    for index, value in enumerate(values):
                        rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
                rows.append("")
                rows.append(help_heading(translator.text("status.tui_help_section_policy")))
                policy = (
                    translator.text("status.tui_help_dataset_policy"),
                    translator.text("status.tui_help_idle_close"),
                )
                for index, value in enumerate(policy):
                    rows.extend(tree_node("", value, (), is_last=index == len(policy) - 1))
                return tuple(clip_width(line, width) for line in rows)
            elif help_overlay.context == "catalog-browser":
                sections = (
                    (
                        "status.tui_help_section_selecting",
                        (translator.text("status.tui_help_catalog_browser"),),
                    ),
                    (
                        "status.tui_help_section_options",
                        (translator.text("status.tui_help_catalog_columns"),),
                    ),
                    (
                        "status.tui_help_section_selected",
                        (translator.text("status.tui_help_catalog_selected"),),
                    ),
                )
                rows = []
                for heading, values in sections:
                    if rows:
                        rows.append("")
                    rows.append(help_heading(translator.text(heading)))
                    for index, value in enumerate(values):
                        rows.extend(tree_node("", value, (), is_last=index == len(values) - 1))
                rows.append("")
                rows.append(help_heading(translator.text("status.tui_help_section_policy")))
                rows.extend(
                    tree_node("", translator.text("status.tui_help_idle_close"), (), is_last=True)
                )
                return tuple(clip_width(line, width) for line in rows)
            elif help_overlay.context == "editor":
                rows = [help_heading(translator.text("status.tui_help_section_controls"))]
                groups = editor_help_groups(dashboard=True)
                for index, group in enumerate(groups):
                    rows.extend(
                        tree_node(
                            "",
                            translator.text(group.heading_key),
                            tuple((translator.text(item_key), ()) for item_key in group.item_keys),
                            is_last=index == len(groups) - 1,
                        )
                    )
                return tuple(clip_width(line, width) for line in rows)
            else:
                context_nodes = (
                    (
                        translator.text("status.tui_help_history_overlay"),
                        ((translator.text("status.tui_help_history_overlay_detail"), ()),),
                    ),
                )
            rows = [help_heading(translator.text("status.tui_help_section_controls"))]
            for value, children in context_nodes:
                rows.extend(tree_node("", value, children, is_last=False))
            policy_children = [
                (
                    translator.text(
                        "status.tui_help_tip_ascii" if options.host.ascii else "status.tui_help_tip"
                    ),
                    (),
                )
            ]
            if help_overlay.context in {"editor", "history"}:
                policy_children.append((translator.text("status.tui_help_animation_hint"), ()))
            policy_children.append((translator.text("status.tui_help_idle_close"), ()))
            rows.append("")
            rows.append(help_heading(translator.text("status.tui_help_section_policy")))
            for index, (value, children) in enumerate(policy_children):
                rows.extend(
                    tree_node("", value, children, is_last=index == len(policy_children) - 1)
                )
            return tuple(clip_width(line, width) for line in rows)

        text_navigation: tuple[tuple[str, tuple[object, ...]], ...] = ()
        if mode == "browse" and body_view != "chart":
            text_children: list[tuple[str, tuple[object, ...]]] = []
            if text_viewport_overflows(
                line_count=dashboard_text_line_count,
                visible_rows=dashboard_text_visible_rows,
            ):
                text_children.append((translator.text("status.tui_help_text_scroll"), ()))
            text_children.append((translator.text("status.tui_help_text_copy"), ()))
            text_navigation = (
                (translator.text("status.tui_help_text_navigation"), tuple(text_children)),
            )
        elif mode == "pane" and focused is not None:
            focused_pane = panes[focused]
            if (
                isinstance(focused_pane, (TuiChartPane, TuiCustomPane))
                and focused_pane.body_view != "chart"
            ):
                text_children = [(translator.text("status.tui_help_content_view"), ())]
                if text_viewport_overflows(
                    line_count=focused_pane.text_line_counts.get(focused_pane.body_view, 0),
                    visible_rows=focused_pane.text_visible_rows.get(focused_pane.body_view, 0),
                ):
                    text_children.append((translator.text("status.tui_help_text_scroll"), ()))
                if body_view_copy_kind(focused_pane.body_view) is not None:
                    text_children.append((translator.text("status.tui_help_text_copy"), ()))
                text_navigation = (
                    (translator.text("status.tui_help_text_navigation"), tuple(text_children)),
                )

        current_metric_node = None
        common_children = [
            (translator.text("status.tui_help_history"), ()),
            (translator.text("status.tui_help_help"), ()),
        ]
        structure_children = [
            (translator.text("status.tui_help_content_view"), ()),
            (translator.text("status.tui_help_content_replace"), ()),
            (translator.text("status.tui_help_content_insert"), ()),
            (translator.text("status.tui_help_structure_move"), ()),
            (translator.text("status.tui_help_structure_select"), ()),
            (translator.text("status.tui_help_structure_width"), ()),
            (translator.text("status.tui_help_structure_height"), ()),
        ]
        if mode == "browse":
            browse_children = [
                (translator.text("status.tui_help_browse_view"), ()),
                (translator.text("status.tui_help_browse_pane"), ()),
                (translator.text("status.tui_help_browse_dashboard"), ()),
                (translator.text("status.tui_help_browse_presets"), ()),
            ]
            if body_view == "chart":
                browse_children[:0] = [
                    (translator.text("status.tui_help_browse_refresh"), ()),
                    (translator.text("status.tui_help_controls"), ()),
                    (
                        translator.text("status.tui_help_intervals_dashboard"),
                        (
                            (translator.text("status.tui_help_interval_historical"), ()),
                            (translator.text("status.tui_help_interval_monitor_dashboard"), ()),
                            (translator.text("status.tui_help_interval_header"), ()),
                        ),
                    ),
                ]
            control_nodes = (
                (translator.text("status.tui_help_browse"), tuple(browse_children)),
                (translator.text("status.tui_help_common"), tuple(common_children)),
                *text_navigation,
            )
        elif mode == "pane":
            assert focused is not None
            focused_pane = panes[focused]
            if len(panes) > 1:
                structure_children.insert(
                    3, (translator.text("status.tui_help_content_delete"), ())
                )
            parameter_children: list[tuple[str, tuple[object, ...]]] = []
            if isinstance(focused_pane, TuiChartPane) and focused_pane.body_view == "chart":
                chart = _pane_display_options(focused_pane).chart
                parameter_children.extend(
                    (_pane_help_action_text(page_name, action, translator), ())
                    for page_name, action in _pane_help_settings_actions(
                        chart.kind,
                        translator,
                        chart=chart,
                        attachment_available=(
                            isinstance(chart, MonitorConfig)
                            and is_monitor_ranking_style(chart.presentation.style)
                            and focused_pane.attachment is not None
                        ),
                    )
                )
                if isinstance(chart, MonitorConfig):
                    parameter_children.append(
                        (translator.text("status.tui_help_interval_monitor"), ())
                    )
            elif isinstance(focused_pane, TuiCustomPane) and focused_pane.body_view == "chart":
                parameter_children.extend(
                    (_pane_help_action_text(page_name, action, translator), ())
                    for page_name in ("quick", "advanced")
                    for action in _custom_pane_adjustment_actions(
                        focused_pane, page_name, translator
                    )
                )
            elif isinstance(focused_pane, TuiAnimationPane):
                parameter_children.extend(
                    (
                        (translator.text("status.tui_help_animation_position"), ()),
                        (translator.text("status.tui_help_animation_theme"), ()),
                        (translator.text("status.tui_help_animation_style"), ()),
                        (translator.text("status.tui_help_animation_move"), ()),
                        (translator.text("status.tui_help_animation_reset"), ()),
                        (translator.text("status.tui_help_animation_edit"), ()),
                        (translator.text("status.tui_help_animation_interval"), ()),
                        (
                            translator.text("status.tui_help_animation_history"),
                            ((translator.text("status.tui_help_history_overlay_detail"), ()),),
                        ),
                        (translator.text("status.tui_help_animation_schedule"), ()),
                    )
                )
                structure_children.pop(0)
            current_metric_node = (
                _accepted_custom_metric_help_node(focused_pane, translator)
                if isinstance(focused_pane, TuiCustomPane)
                else None
            )
            if not parameter_children:
                parameter_children.append(
                    (translator.text("status.tui_help_pane_settings_empty"), ())
                )
            control_nodes = (
                (translator.text("status.tui_help_mode"), mode_pages()),
                (translator.text("status.tui_help_pane_settings"), tuple(parameter_children)),
                (translator.text("status.tui_help_pane_structure"), tuple(structure_children)),
                (translator.text("status.tui_help_common"), tuple(common_children)),
                *text_navigation,
            )
        else:
            control_nodes = (
                (translator.text("status.tui_help_mode"), ()),
                (
                    translator.text("status.tui_help_dashboard_settings"),
                    (
                        (translator.text("status.tui_help_dashboard_theme"), ()),
                        (translator.text("status.tui_help_dashboard_style"), ()),
                        (translator.text("status.tui_help_dashboard_header"), ()),
                        (translator.text("status.tui_help_dashboard_summary"), ()),
                        (
                            translator.text("status.tui_help_dashboard_layout"),
                            ((translator.text("status.tui_help_layout_chooser"), ()),),
                        ),
                        (
                            translator.text("status.tui_help_dashboard_grid"),
                            ((translator.text("status.tui_help_grid_editor"), ()),),
                        ),
                    ),
                ),
                (translator.text("status.tui_help_common"), tuple(common_children)),
            )
        mode_nodes = (
            mode_node(
                "status.tui_help_browse_label",
                active=mode == "browse",
                enter=translator.text("status.tui_help_browse_enter"),
                exit=translator.text("status.tui_help_browse_exit"),
            ),
            mode_node(
                "status.tui_help_pane_label",
                active=mode == "pane",
                enter=translator.text("status.tui_help_pane_enter"),
                exit=translator.text("status.tui_help_pane_exit"),
            ),
            mode_node(
                "status.tui_help_global_label",
                active=mode == "global",
                enter=translator.text("status.tui_help_global_enter"),
                exit=translator.text("status.tui_help_global_exit"),
            ),
        )
        sections = (
            ("status.tui_help_section_modes", mode_nodes),
            *(
                (("status.tui_help_current_metric", current_metric_node[1]),)
                if current_metric_node is not None
                else ()
            ),
            ("status.tui_help_section_controls", control_nodes),
        )
        rows: list[str] = []
        for heading, nodes in sections:
            if rows:
                rows.append("")
            rows.append(help_heading(translator.text(heading)))
            for index, (value, children) in enumerate(nodes):
                rows.extend(
                    tree_node(
                        "",
                        value,
                        cast(tuple[tuple[str, object], ...], children),
                        is_last=index == len(nodes) - 1,
                    )
                )
        policy_children = [
            (
                translator.text(
                    "status.tui_help_tip_ascii" if options.host.ascii else "status.tui_help_tip"
                ),
                (),
            )
        ]
        if mode == "browse":
            policy_children.extend(
                (
                    (translator.text("status.tui_help_browse_hint"), ()),
                    (translator.text("status.tui_help_schedule_coalesce"), ()),
                )
            )
        elif (
            mode == "pane" and focused is not None and isinstance(panes[focused], TuiAnimationPane)
        ):
            policy_children.append((translator.text("status.tui_help_animation_hint"), ()))
        focused_pane = panes[focused] if focused is not None else None
        if (
            mode == "pane"
            and isinstance(focused_pane, TuiChartPane)
            and focused_pane.body_view == "chart"
            and not isinstance(_pane_display_options(focused_pane).chart, MonitorConfig)
        ):
            policy_children.extend(
                (
                    (
                        translator.text("status.tui_help_summary_scope"),
                        (
                            (translator.text("status.tui_help_summary_scope_fixed"), ()),
                            (translator.text("status.tui_help_summary_scope_filters"), ()),
                        ),
                    ),
                    (
                        translator.text("status.tui_help_summary_comparisons"),
                        (
                            (translator.text("status.tui_help_summary_comparisons_day"), ()),
                            (
                                translator.text(
                                    "status.tui_help_summary_comparisons_month_quarter"
                                ),
                                (),
                            ),
                            (translator.text("status.tui_help_summary_comparisons_year"), ()),
                        ),
                    ),
                )
            )
        policy_children.append((translator.text("status.tui_help_idle_close"), ()))
        rows.append("")
        rows.append(help_heading(translator.text("status.tui_help_section_policy")))
        for index, (value, children) in enumerate(policy_children):
            rows.extend(tree_node("", value, children, is_last=index == len(policy_children) - 1))
        return tuple(clip_width(line, width) for line in rows)

    def help_panel(size_columns: int, size_lines: int) -> tuple[str, ...]:
        content_width = max(1, min(size_columns - 4, 100))
        lines = help_lines(content_width)
        context = RenderContext(
            content_width,
            1,
            translator,
            color=dashboard_theme != "no-color",
            ascii=options.host.ascii,
            color_scheme=dashboard_theme,
        )
        scheme = get_color_scheme(dashboard_theme)
        editor_help = help_overlay is not None and help_overlay.context == "editor"
        title = clip_width(
            styled_text(
                translator.text(
                    "status.tui_help_editor_title" if editor_help else "status.tui_help_title"
                ),
                scheme.highlight,
                context,
                bold=True,
            ),
            content_width,
        )
        footer = clip_width(
            styled_text(
                translator.text(
                    "status.tui_help_editor_close" if editor_help else "status.tui_help_close"
                ),
                scheme.other,
                context,
                dim=True,
            ),
            content_width,
        )
        panel_width = max(
            1,
            min(
                size_columns, max(*(display_width(line) for line in (*lines, title, footer)), 1) + 4
            ),
        )
        body_rows = max(1, size_lines - 5)
        max_offset = max(0, len(lines) - body_rows)
        offset = min(help_overlay.scroll_offset if help_overlay is not None else 0, max_offset)
        visible = lines[offset : offset + body_rows]
        border = "-" * max(0, panel_width - 2)
        inner_width = max(0, panel_width - 4)
        rows = ["+" + border + "+", "| " + pad_width(title, inner_width) + " |"]
        rows.extend("| " + pad_width(line, inner_width) + " |" for line in visible)
        rows.append("|" + "-" * max(0, panel_width - 2) + "|")
        rows.append("| " + pad_width(footer, inner_width) + " |")
        rows.append("+" + border + "+")
        return tuple(rows)

    def help_panel_bounds(size_columns: int, size_lines: int) -> tuple[int, int, int, int]:
        panel = help_panel(size_columns, size_lines)
        width = max((display_width(line) for line in panel), default=1)
        height = len(panel)
        return (
            (size_columns - width) // 2 + 1,
            max(1, (size_lines - height) // 2 + 1),
            width,
            height,
        )

    def help_frame(size_columns: int, size_lines: int) -> Frame:
        panel = help_panel(size_columns, size_lines)
        x, y, panel_width, _ = help_panel_bounds(size_columns, size_lines)
        rows = ["" for _ in range(size_lines)]
        for offset, row in enumerate(panel):
            row_index = y - 1 + offset
            if 0 <= row_index < len(rows):
                rows[row_index] = " " * max(0, x - 1) + pad_width(row, panel_width)
        return Frame(tuple(rows))

    def process_help_event(event: object) -> None:
        assert help_overlay is not None
        if isinstance(event, KeyEvent) and event.value in {"h", "\x08", "\x1b", "\r", "\n"}:
            close_help()
        elif isinstance(event, KeyEvent) and event.value in {"\x1b[A", "\x1b[B"}:
            delta = -1 if event.value == "\x1b[A" else 1
            max_offset = max(
                0,
                len(help_lines(get_terminal_size().columns)) - get_terminal_size().lines + 5,
            )
            help_overlay.scroll_offset = min(max(0, help_overlay.scroll_offset + delta), max_offset)
        elif isinstance(event, MouseEvent) and event.pressed:
            size = get_terminal_size()
            x, y, width, height = help_panel_bounds(size.columns, size.lines)
            if not (x <= event.x < x + width and y <= event.y < y + height):
                close_help()
        paint()

    def _controls() -> tuple[str, ...]:
        width = get_terminal_size().columns
        if help_overlay is not None:
            return ()
        if grid_draft is not None:
            rows = [
                clip_width(translator.text("status.tui_layout_prompt", value=grid_draft), width)
            ]
            if grid_error is not None:
                rows.append(clip_width(grid_error, width))
            rows.append(clip_width(translator.text("status.tui_layout_controls"), width))
            return tuple(rows)
        if adjustment_mode == "pane" and focused is not None:
            pane = panes[focused]
            if isinstance(pane, TuiAnimationPane):
                return (
                    *_animation_adjustment_footer(
                        pane,
                        adjustment_page,
                        translator,
                        width,
                        color=dashboard_theme != "no-color",
                    ),
                    global_operations(width),
                )
            if isinstance(pane, TuiEmptyPane):
                return (
                    *_empty_pane_adjustment_footer(
                        translator,
                        width,
                        color=dashboard_theme != "no-color",
                    ),
                    global_operations(width),
                )
            if isinstance(pane, TuiCustomPane):
                if pane.body_view != "chart":
                    return (
                        *_text_view_footer(
                            pane.body_view,
                            translator,
                            width,
                            line_count=pane.text_line_counts.get(pane.body_view, 0),
                            visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                        ),
                        global_operations(width),
                    )
                return (
                    *_custom_adjustment_footer(
                        pane,
                        adjustment_page,
                        translator,
                        width,
                        color=dashboard_theme != "no-color",
                    ),
                    global_operations(width),
                )
            if pane.body_view != "chart":
                return (
                    *_text_view_footer(
                        pane.body_view,
                        translator,
                        width,
                        line_count=pane.text_line_counts.get(pane.body_view, 0),
                        visible_rows=pane.text_visible_rows.get(pane.body_view, 0),
                    ),
                    global_operations(width),
                )
            state = grid_error or _pane_adjustment_state(pane, adjustment_page, translator)
            return (
                *_adjustment_footer(
                    state,
                    _pane_display_options(pane).chart.kind,
                    adjustment_page,
                    pane.body_view,
                    translator,
                    width,
                    chart=_pane_display_options(pane).chart,
                    attachment_available=(
                        adjustment_page == "advanced"
                        and isinstance(_pane_display_options(pane).chart, MonitorConfig)
                        and is_monitor_ranking_style(
                            _pane_display_options(pane).chart.presentation.style
                        )
                        and pane.attachment is not None
                    ),
                    color=dashboard_theme != "no-color",
                ),
                global_operations(width),
            )
        if adjustment_mode == "global":
            state = translator.text(
                "status.tui_current_state",
                runtime=translator.text("status.tui_running"),
                settings=f"{active_layout or active_grid} · {dashboard_theme} · {dashboard_style} · "
                f"{header_style} · {header.summary_period}",
            )
            return (
                *_global_adjustment_footer(
                    state=grid_error or state,
                    translator=translator,
                    width=width,
                ),
                global_operations(width),
            )
        if body_view != "chart":
            return (
                *_text_view_footer(
                    body_view,
                    translator,
                    width,
                    line_count=dashboard_text_line_count,
                    visible_rows=dashboard_text_visible_rows,
                ),
                global_operations(width),
            )
        if controls_hidden:
            return ()
        context = grid_error or translator.text(
            f"status.tui_{body_view.replace('-', '_')}_controls"
        )
        return (clip_width(context, width), preset_operations(width), global_operations(width))

    def controls() -> tuple[str, ...]:
        return () if controls_hidden or get_terminal_size().lines < MIN_PANE_HEIGHT else _controls()

    def notices() -> tuple[str, ...]:
        feedback = feedback_lines(
            copy_feedback,
            width=get_terminal_size().columns,
            color=dashboard_theme != "no-color",
            now=time.monotonic(),
        )
        manual = (translator.text("status.tui_refreshing"),) if manual_refresh_operations else ()
        return (*manual, *feedback)

    def grid_geometry(
        size_columns: int,
        size_lines: int,
        header_rows: int,
        status_rows: int,
    ) -> ResolvedPaneLayout:
        grid_height = max(
            3, size_lines - len(controls()) - len(notices()) - header_rows - status_rows
        )
        bands = layout_bands(active_layout or active_grid, len(panes))
        resolved_column_weights = reconcile_weights(column_weights, bands.columns)
        resolved_row_weights = reconcile_weights(row_weights, bands.rows)
        return resolve_pane_layout(
            layout=active_layout or active_grid,
            pane_count=len(panes),
            width=size_columns,
            height=grid_height,
            divider_style=divider_style,
            column_weights=resolved_column_weights,
            row_weights=resolved_row_weights,
        )

    def adjust_pane_weight(pane_index: int, *, axis: str, delta: int) -> bool:
        """Adjust one Dashboard layout band and retain it in undo history."""

        nonlocal column_weights, row_weights
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        slot = layout.topology.slot(pane_index)

        def can_adjust_axis(
            *, axis: str, weights: tuple[int, ...], index: int
        ) -> tuple[bool, tuple[int, ...]]:
            candidate = adjust_weight(weights, index, delta)
            candidate_layout = resolve_pane_layout(
                layout=active_layout or active_grid,
                pane_count=len(panes),
                width=layout.width,
                height=layout.height,
                divider_style=divider_style,
                column_weights=(
                    candidate
                    if axis == "column"
                    else reconcile_weights(column_weights, layout.topology.columns)
                ),
                row_weights=(
                    candidate
                    if axis == "row"
                    else reconcile_weights(row_weights, layout.topology.rows)
                ),
            )
            before = layout.column_sizes if axis == "column" else layout.row_sizes
            after = (
                candidate_layout.column_sizes if axis == "column" else candidate_layout.row_sizes
            )
            return after != before, candidate

        if axis == "column":
            weights = reconcile_weights(column_weights, layout.topology.columns)
            can_adjust, candidate = can_adjust_axis(
                axis="column", weights=weights, index=slot.column
            )
            if not can_adjust:
                return False

            def adjust_column() -> None:
                nonlocal column_weights
                column_weights = candidate

            return record_mutation(("layout", "column-weight", slot.column), adjust_column)

        weights = reconcile_weights(row_weights, layout.topology.rows)
        can_adjust, candidate = can_adjust_axis(axis="row", weights=weights, index=slot.row)
        if not can_adjust:
            return False

        def adjust_row() -> None:
            nonlocal row_weights
            row_weights = candidate

        return record_mutation(("layout", "row-weight", slot.row), adjust_row)

    displayed_layout: ResolvedPaneLayout | None = None
    displayed_header_rows = 0

    def handle_ranking_wheel(event: WheelEvent) -> None:
        if (
            displayed_layout is None
            or body_view != "chart"
            or help_overlay is not None
            or preset_manager is not None
            or dataset_modal is not None
            or chooser_overlay is not None
            or overlay_editor is not None
            or overlay_history is not None
            or custom_logs_pane is not None
        ):
            return
        selected = layout_pane_at(
            displayed_layout, event.x - 1, event.y - displayed_header_rows - 1
        )
        if selected is None:
            return
        pane = panes[selected]
        if (
            isinstance(pane, TuiCustomPane)
            and isinstance(pane.component, CustomHistoricalComponent)
            and (pane.component.accepted_config or pane.component.candidate).kind == "ranking"
            and pane.body_view == "chart"
            and pane.active_ranking_viewport.active
        ):
            pane.active_ranking_viewport.scroll(event.delta)

    def handle_scrollbar_hover(event: MouseEvent) -> bool:
        """Track whether unpressed pointer motion is inside a Ranking scrollbar."""
        nonlocal scrollbar_hovered_pane
        blocked = (
            body_view != "chart"
            or displayed_layout is None
            or help_overlay is not None
            or preset_manager is not None
            or dataset_modal is not None
            or chooser_overlay is not None
            or overlay_editor is not None
            or overlay_history is not None
            or custom_logs_pane is not None
        )
        hovered: int | None = None
        if not blocked and not event.pressed:
            assert displayed_layout is not None
            grid_x = event.x - 1
            grid_y = event.y - displayed_header_rows - 1
            selected = layout_pane_at(displayed_layout, grid_x, grid_y)
            if selected is not None:
                pane = panes[selected]
                viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
                if viewport is not None and viewport.active and viewport.scrollbar is not None:
                    rect = displayed_layout.pane(selected)
                    framed = frame_style != "none" or selected == focused
                    interior_column = grid_x - rect.left - int(framed)
                    interior_row = grid_y - rect.top - int(framed)
                    if viewport.scrollbar.contains(interior_column, interior_row):
                        hovered = selected
        if scrollbar_hovered_pane == hovered:
            return False
        scrollbar_hovered_pane = hovered
        return True

    def handle_scrollbar_drag(event: MouseEvent) -> bool:
        """Let a press, drag, or track click on a Ranking scrollbar move its body."""
        nonlocal scrollbar_drag, scrollbar_hovered_pane
        blocked = (
            body_view != "chart"
            or displayed_layout is None
            or help_overlay is not None
            or preset_manager is not None
            or dataset_modal is not None
            or chooser_overlay is not None
            or overlay_editor is not None
            or overlay_history is not None
            or custom_logs_pane is not None
        )
        if blocked:
            scrollbar_drag = None
            scrollbar_hovered_pane = None
            return False
        # A release ends any capture without consuming other mouse handling.
        if not event.pressed:
            released = scrollbar_drag is not None
            scrollbar_drag = None
            return released
        assert displayed_layout is not None
        motion = bool(event.modifiers & 0b100000)
        grid_x = event.x - 1
        grid_y = event.y - displayed_header_rows - 1
        # While a drag is captured, follow the pointer's vertical position even
        # if the report arrives as held-button motion or a plain press.
        if scrollbar_drag is not None and (motion or event.button == 0):
            pane_index, grab = scrollbar_drag
            pane = panes[pane_index]
            viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
            bar = viewport.scrollbar if viewport is not None else None
            if bar is None or viewport is None:
                scrollbar_drag = None
                return False
            rect = displayed_layout.pane(pane_index)
            framed = frame_style != "none" or pane_index == focused
            interior_row = grid_y - rect.top - int(framed)
            viewport.offset = bar.offset_at(interior_row, grab)
            viewport.clamp()
            return True
        # A fresh capture only begins on a stationary primary-button press.
        if motion or event.button != 0:
            return False
        selected = layout_pane_at(displayed_layout, grid_x, grid_y)
        if selected is None:
            return False
        pane = panes[selected]
        viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
        bar = viewport.scrollbar if viewport is not None else None
        if bar is None or viewport is None or not viewport.active:
            return False
        rect = displayed_layout.pane(selected)
        framed = frame_style != "none" or selected == focused
        interior_row = grid_y - rect.top - int(framed)
        interior_column = grid_x - rect.left - int(framed)
        if not bar.contains(interior_column, interior_row):
            return False
        # Keep the expanded visual state throughout a scrollbar interaction,
        # including held-button motion reports that are not hover events.
        scrollbar_hovered_pane = selected
        if bar.on_thumb(interior_row):
            # Capture the thumb; a stationary press must not move the offset.
            scrollbar_drag = (selected, bar.grab_at(interior_row))
        else:
            # A track click moves one visible page and does not begin a drag.
            viewport.offset = bar.page_offset(interior_row)
            viewport.clamp()
        return True

    def handle_pane_mouse(event: MouseEvent) -> bool:
        """Handle pane focus clicks before pane-local modal input consumes them."""

        nonlocal adjustment_mode, adjustment_page, adjustment_timer, focused, last_click
        nonlocal overlay_editor, overlay_history, custom_logs_pane
        if (
            body_view != "chart"
            or not event.pressed
            or event.button != 0
            or event.modifiers & 0b1100000
        ):
            return False
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        grid_x = event.x - 1
        grid_y = event.y - header_rows - 1
        selected = layout_pane_at(layout, grid_x, grid_y)
        now = time.monotonic()
        double_click = (
            selected is not None
            and last_click is not None
            and last_click[0] == selected
            and now - last_click[1] <= _DOUBLE_CLICK_SECONDS
        )
        last_click = (selected, now) if selected is not None else None
        if selected is not None and isinstance(pane := panes[selected], TuiCustomPane):
            local_row = grid_y - layout.pane(selected).top
            local_column = grid_x - layout.pane(selected).left
            framed = frame_style != "none" or selected == focused
            if _copy_custom_ranking_all_at(
                pane, row=local_row, column=local_column, framed=framed, now=now
            ) or _copy_custom_ranking_entry_at(
                pane, row=local_row, column=local_column, framed=framed, now=now
            ):
                return True
        if adjustment_mode == "pane":
            if selected != focused and double_click and selected is not None:
                overlay_editor = None
                overlay_history = None
                custom_logs_pane = None
                focused = selected
                adjustment_page = "quick"
                adjustment_timer = AdjustmentIdleTimer()
            # Keep the first press inert: terminating adjustment here would
            # prevent a normal second press from completing the double-click.
            return True
        if adjustment_mode in {None, "global"} and double_click and selected is not None:
            focused = selected
            adjustment_mode = "pane"
            adjustment_page = "quick"
            adjustment_timer = AdjustmentIdleTimer()
        return True

    def _copy_custom_ranking_all_at(
        pane: TuiCustomPane,
        *,
        row: int,
        column: int,
        framed: bool,
        now: float,
    ) -> bool:
        """Copy all filtered Dataset Ranking entries from the fixed marker."""
        viewport = pane.active_ranking_viewport
        hit = viewport.copy_all_hit
        if hit is None:
            return False
        interior_row = row - int(framed)
        interior_column = column - int(framed)
        if interior_row != hit[0] or not hit[1] - 2 <= interior_column <= hit[1] + 2:
            return False
        if pane.grouped_ranking_viewport.active:
            payload = pane.grouped_ranking_viewport.clipboard_all_text()
            entries = ()
        elif pane.ranking_viewport.active:
            payload = pane.ranking_viewport.clipboard_all_text()
            entries = ()
        else:
            payload = ""
            entries = tuple(
                (label, description, link)
                for _, _, label, description, link in _custom_ranking_copyable_entries(
                    pane, translator
                )
            )
        if not payload and not entries:
            return False
        copied = copy_command(payload or _custom_ranking_clipboard_all_text(entries))
        if copied:
            pane.copied_ranking_all_until = now + 1.5
        copy_feedback.show(
            translator.text("status.data_copied" if copied else "status.command_copy_failed"),
            now=now,
        )
        return True

    def _copy_custom_ranking_entry_at(
        pane: TuiCustomPane,
        *,
        row: int,
        column: int,
        framed: bool,
        now: float,
    ) -> bool:
        """Copy one clicked Dataset Ranking entry only when its icon is hit."""
        interior_row = row - int(framed)
        interior_column = column - int(framed)
        target = pane.ranking_copy_rows.get(interior_row)
        if target is None:
            return False
        link_hit = target[2] is not None and target[2] - 1 <= interior_column <= target[2] + 1
        copy_hit = target[1] - 2 <= interior_column <= target[1] + 2
        if not copy_hit and not link_hit:
            return False
        if pane.grouped_ranking_viewport.active:
            identity = cast(GroupedIdentity, target[0])
            prepared_entry = pane.grouped_ranking_viewport.by_id.get(identity)
            if prepared_entry is None:
                return False
            payload = pane.grouped_ranking_viewport.clipboard_text(identity)
            entry_id = identity
            project_link = getattr(prepared_entry, "project_link", None) or getattr(
                prepared_entry, "link", None
            )
        elif pane.ranking_viewport.active:
            prepared_entry = pane.ranking_viewport.by_id.get(target[0])
            if prepared_entry is None:
                return False
            payload = pane.ranking_viewport.clipboard_text(str(prepared_entry.key))
            entry_id = str(prepared_entry.key)
            label, description, project_link = (
                prepared_entry.label,
                prepared_entry.description,
                prepared_entry.project_link,
            )
        else:
            entries = _custom_ranking_copyable_entries(pane, translator)
            entry = next((item for item in entries if item[1] == target[0]), None)
            if entry is None:
                return False
            payload = ""
            _, entry_id, label, description, project_link = entry
        if link_hit and project_link is not None:
            opened = webbrowser.open(project_link)
            copy_feedback.show(
                translator.text("status.data_copied" if opened else "status.command_copy_failed"),
                now=now,
            )
            return True
        copied = copy_command(
            payload or _custom_ranking_clipboard_text(label, description, project_link)
        )
        if copied:
            pane.copied_ranking_entry_id = entry_id
            pane.copied_ranking_until = now + 1.5
        copy_feedback.show(
            translator.text("status.data_copied" if copied else "status.command_copy_failed"),
            now=now,
        )
        return True

    def capture_custom_ranking_copy_rows(
        pane: TuiCustomPane,
        content: str,
        *,
        fixed_rows: int,
        framed: bool,
    ) -> None:
        """Map rendered copy markers to pane-local rows for the next mouse hit."""
        del fixed_rows, framed
        pane.ranking_copy_rows.clear()
        viewport = pane.active_ranking_viewport
        if viewport.active:
            pane.ranking_copy_rows.update(viewport.hits)
            return
        entries_by_rank = {
            rank: (entry_id, label, description, link)
            for rank, entry_id, label, description, link in _custom_ranking_copyable_entries(
                pane, translator
            )
        }
        for row, line in enumerate(content.splitlines()):
            visible = strip_ansi(line)
            marker_column = (
                display_width(visible.rsplit("⊞", 1)[0])
                if "⊞" in visible
                else (display_width(visible.rsplit("✓", 1)[0]) if "✓" in visible else None)
            )
            if marker_column is None:
                continue
            link_column = display_width(visible.rsplit("→", 1)[0]) if "→" in visible else None
            prefix, _, _ = visible.lstrip().partition(" ")
            if prefix.isdecimal() and (entry := entries_by_rank.get(int(prefix))) is not None:
                pane.ranking_copy_rows[row] = (entry[0], marker_column, link_column)

    def pane_terminal(index: int) -> Terminal:
        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        layout = grid_geometry(size.columns, size.lines, header_rows, 0)
        rect = layout.pane(index)
        framed = frame_style != "none" or index == focused
        pane = panes[index]
        if isinstance(pane, TuiAnimationPane):
            return Terminal(
                max(1, rect.width - 2 if framed else rect.width),
                max(1, rect.height - 2 if framed else rect.height),
                pane.session.theme != "no-color",
                options.host.ascii,
            )
        if isinstance(pane, TuiCustomPane):
            return Terminal(
                max(1, rect.width - 2 if framed else rect.width),
                max(1, rect.height - 2 if framed else rect.height),
                pane.component.candidate.presentation.theme != "no-color",
                options.host.ascii,
            )
        if isinstance(pane, TuiEmptyPane):
            return Terminal(
                max(1, rect.width - 2 if framed else rect.width),
                max(1, rect.height - 2 if framed else rect.height),
                dashboard_theme != "no-color",
                options.host.ascii,
            )
        pane_options = _pane_display_options(pane)
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            pane_options.chart.presentation.theme != "no-color",
            pane_options.host.ascii,
        )

    def paint(*, force: bool = False, animation_only: bool = False) -> None:
        nonlocal help_was_active, last_size, dashboard_text_offset, dashboard_text_line_count
        nonlocal dashboard_text_visible_rows, chooser_overlay
        nonlocal displayed_layout, displayed_header_rows
        displayed_layout = None
        if dataset_modal is None:
            chooser_overlay = None
        else:
            _paint_dataset_modal()
        size = get_terminal_size()
        if force or not animation_only or (size.columns, size.lines) != last_size:
            pane_render_cache.clear()
        paint_now = time.monotonic()
        if preset_manager is not None:
            frame = render_preset_manager(
                preset_manager,
                preset_catalog(),
                translator,
                Terminal(
                    size.columns, size.lines, dashboard_theme != "no-color", options.host.ascii
                ),
            )
            screen.paint(frame, force=force, atomic=True)
            help_was_active = False
            return
        atomic = (
            help_overlay is not None
            or help_was_active
            or any(isinstance(pane, TuiAnimationPane) for pane in panes)
        )
        if help_overlay is not None:
            last_size = (size.columns, size.lines)
            screen.paint(help_frame(size.columns, size.lines), force=force, atomic=atomic)
            help_was_active = True
            return
        last_size = (size.columns, size.lines)
        header_terminal = Terminal(
            size.columns, 4, dashboard_theme != "no-color", options.host.ascii
        )
        header_lines = _header_lines(
            header, header_style, translator, header_terminal, last_successful_update
        )
        status = None
        if body_view != "chart":
            control_rows = controls()
            notice_rows = notices()
            viewport = render_text_viewport(
                format_full_command_display(full_dashboard_command(), size.columns),
                offset=dashboard_text_offset,
                visible_rows=size.lines - len(control_rows) - len(notice_rows),
            )
            dashboard_text_offset = viewport.offset
            dashboard_text_line_count = viewport.line_count
            dashboard_text_visible_rows = viewport.visible_rows
            screen.paint(
                compose_frame(
                    viewport.body,
                    status,
                    control_rows,
                    notice_rows,
                    height=size.lines,
                ),
                force=force,
                atomic=atomic,
            )
            help_was_active = False
            return

        def render_panes(
            layout: ResolvedPaneLayout,
        ) -> tuple[list[str], tuple[DashboardOverlayPlacement, ...]]:
            rendered_panes: list[str] = []
            overlays: list[DashboardOverlayPlacement] = []
            for index, pane in enumerate(panes):
                rect = layout.pane(index)
                cell_width = rect.width
                cell_height = rect.height
                if cell_width < MIN_PANE_WIDTH or cell_height < MIN_PANE_HEIGHT:
                    rendered_panes.append(
                        clip_width(translator.text("status.tui_pane_too_small"), max(0, cell_width))
                        if cell_width > 0 and cell_height > 0
                        else ""
                    )
                    continue
                # The active frame-less pane gets a selection ring, so reserve its
                # interior too; its content is never overwritten by the indicator.
                framed = frame_style != "none" or index == focused
                interior_width = max(1, cell_width - 2 if framed else cell_width)
                interior_height = max(1, cell_height - 2 if framed else cell_height)
                if isinstance(pane, TuiAnimationPane):
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        pane.session.theme != "no-color",
                        options.host.ascii,
                    )
                    color_scheme = pane.session.theme
                elif isinstance(pane, TuiCustomPane):
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        pane.component.candidate.presentation.theme != "no-color",
                        options.host.ascii,
                    )
                    color_scheme = pane.component.candidate.presentation.theme
                elif isinstance(pane, TuiEmptyPane):
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        dashboard_theme != "no-color",
                        options.host.ascii,
                    )
                    color_scheme = dashboard_theme
                else:
                    pane_options = _pane_display_options(pane)
                    terminal = Terminal(
                        interior_width,
                        interior_height,
                        pane_options.chart.presentation.theme != "no-color",
                        pane_options.host.ascii,
                    )
                    color_scheme = pane_options.chart.presentation.theme
                if chooser_overlay is not None and chooser_overlay[0] == index:
                    rendered_panes.append(chooser_overlay[1])
                    continue
                if overlay_editor is not None and overlay_editor.pane_index == index:
                    editor_controls = _overlay_editor_controls(
                        translator, width=interior_width, color=terminal.color, dashboard=True
                    )
                    rendered_panes.append(
                        "\n".join(
                            compose_frame(
                                _editor_viewport(
                                    overlay_editor.draft,
                                    overlay_editor.cursor,
                                    interior_width,
                                    cursor_visible=int(time.monotonic() * 2) % 2 == 0,
                                )[0],
                                copy_feedback.message
                                or translator.text(
                                    "status.overlay_editor_mode_title",
                                    mode=translator.text(
                                        f"status.overlay_editor_mode_{overlay_editor.mode}"
                                    ),
                                ),
                                editor_controls,
                                height=interior_height,
                            ).rows
                        )
                    )
                    continue
                if custom_logs_pane == index:
                    assert isinstance(pane, TuiCustomPane)
                    rows = tuple(
                        f"{translator.text(f'status.custom_log_{record.status}')} "
                        f"{record.timestamp:%H:%M:%S}: {record.detail}"
                        for record in pane.logs
                    ) or (translator.text("status.custom_logs_empty"),)
                    rendered_panes.append(
                        "\n".join(
                            compose_frame(
                                "\n".join(rows),
                                translator.text("status.custom_logs_title"),
                                (translator.text("status.custom_logs_controls"),),
                                height=interior_height,
                            ).rows
                        )
                    )
                    continue
                if overlay_history is not None and overlay_history.pane_index == index:
                    assert isinstance(pane, TuiAnimationPane)
                    history_table = render_history_table(
                        tuple(pane.overlay.history),
                        overlay_history.table,
                        available_width=interior_width,
                        available_height=interior_height - 1,
                        empty=translator.text("status.overlay_history_empty"),
                    )
                    history_controls = controls_line(
                        translator.text("status.overlay_history_dashboard_controls"),
                        width=interior_width,
                        color=terminal.color,
                    )
                    rendered_panes.append(
                        "\n".join(
                            compose_frame(
                                history_table.body,
                                None,
                                (history_controls,),
                                height=interior_height,
                            ).rows
                        )
                    )
                    continue
                scrollbar_expanded = index == scrollbar_hovered_pane or (
                    scrollbar_drag is not None and index == scrollbar_drag[0]
                )
                cache_key = (id(pane), rect, terminal, framed, scrollbar_expanded)
                cached = pane_render_cache.get(index)
                deadline = _pane_animation_deadline(pane)
                if (
                    cached is not None
                    and cached[0] == cache_key
                    and (deadline is None or deadline > paint_now)
                ):
                    rendered_panes.append(cached[1])
                    overlays.extend(cached[2])
                    continue
                overlay_start = len(overlays)
                if isinstance(pane, TuiAnimationPane):
                    try:
                        rendered = _pane_render(
                            pane, translator, terminal, defer_animation_overlay=True
                        )
                    except TypeError as error:
                        if "defer_animation_overlay" not in str(error):
                            raise
                        rendered = _pane_render(pane, translator, terminal)
                elif isinstance(pane, TuiCustomPane):
                    rendered = _pane_render(
                        pane,
                        translator,
                        terminal,
                        dashboard=options,
                        scrollbar_hovered=scrollbar_expanded,
                    )
                else:
                    rendered = _pane_render(pane, translator, terminal)
                if isinstance(pane, TuiAnimationPane):
                    origin_x = rect.left + (1 if framed else 0)
                    origin_y = rect.top + (1 if framed else 0)
                    overlays.extend(
                        DashboardOverlayPlacement(
                            index,
                            OverlayPlacement(
                                origin_y + placement.row,
                                origin_x + placement.column,
                                placement.text,
                            ),
                        )
                        for placement in pane.overlay.unbounded_placements(
                            width=terminal.width, height=terminal.height
                        )
                    )
                search_notice = (
                    (pane.ranking_search.density_notice,)
                    if isinstance(pane, (TuiChartPane, TuiCustomPane))
                    and pane.ranking_search.density_notice is not None
                    else ()
                )
                local_notices = format_notice_lines(
                    (*rendered.notices, *_custom_top_limit_notice(pane, translator), *search_notice)
                    if isinstance(pane, TuiCustomPane)
                    else (*rendered.notices, *search_notice),
                    width=interior_width,
                    color=terminal.color,
                    ascii=terminal.ascii,
                    translator=translator,
                    color_scheme=color_scheme,
                )
                if isinstance(pane, TuiCustomPane) and pane.active_ranking_viewport.active:
                    viewport = pane.active_ranking_viewport
                    reserved = min(len(local_notices), max(0, interior_height - 3))
                    if reserved != viewport.reserved_rows:
                        viewport.reserved_rows = reserved
                        rendered = _pane_render(pane, translator, terminal, dashboard=options)
                chart = (
                    _append_monitor_attachment(
                        pane,
                        rendered.chart,
                        terminal=terminal,
                        reserved_rows=len(local_notices),
                        now=time.monotonic(),
                        translator=translator,
                    )
                    if isinstance(pane, TuiChartPane) and pane.body_view == "chart"
                    else rendered.chart
                )
                text_pane = (
                    pane
                    if isinstance(pane, (TuiChartPane, TuiAnimationPane, TuiCustomPane))
                    else None
                )
                error_body = isinstance(text_pane, TuiCustomPane) and rendered.error_body
                fixed_ranking_rows = 0
                scrollable = text_pane is not None and (
                    text_pane.body_view != "chart" or error_body
                )
                pane_content = _local_pane_content(
                    chart,
                    local_notices,
                    width=interior_width,
                    height=interior_height,
                    offset=(
                        text_pane.error_offset
                        if error_body
                        else text_pane.text_offsets.get(text_pane.body_view, 0)
                    )
                    if text_pane is not None
                    else 0,
                    scrollable=scrollable,
                    preserve_layout=False,
                    fixed_rows=0,
                    return_metadata=True,
                )
                assert isinstance(pane_content, tuple)
                content, offset, line_count, visible_rows = pane_content
                if text_pane is not None and scrollable:
                    if error_body:
                        text_pane.error_offset = offset
                        text_pane.error_line_count = line_count
                        text_pane.error_visible_rows = visible_rows
                    else:
                        text_pane.text_offsets[text_pane.body_view] = offset
                        text_pane.text_line_counts[text_pane.body_view] = line_count
                        text_pane.text_visible_rows[text_pane.body_view] = visible_rows
                if (
                    isinstance(text_pane, TuiCustomPane)
                    and isinstance(text_pane.component, CustomHistoricalComponent)
                    and (text_pane.component.accepted_config or text_pane.component.candidate).kind
                    == "ranking"
                ):
                    capture_custom_ranking_copy_rows(
                        text_pane,
                        content,
                        fixed_rows=fixed_ranking_rows,
                        framed=framed,
                    )
                rendered_panes.append(content)
                pane_render_cache[index] = (cache_key, content, tuple(overlays[overlay_start:]))
            return rendered_panes, tuple(overlays)

        layout = grid_geometry(size.columns, size.lines, len(header_lines), int(status is not None))
        pane_renders, dashboard_overlays = render_panes(layout)
        displayed_layout, displayed_header_rows = layout, len(header_lines)
        grid = _compose_resolved_panes(
            pane_renders,
            layout,
            focused=focused if focused is not None else -1,
            ascii=options.host.ascii,
            divider_style=divider_style,
            frame_style=frame_style,
            shell_context=RenderContext(
                size.columns,
                layout.height,
                translator,
                color=dashboard_theme != "no-color",
                ascii=options.host.ascii,
                color_scheme=dashboard_theme,
            ),
        )
        grid = _compose_dashboard_overlays(
            grid,
            layout,
            dashboard_overlays,
            focused=focused if focused is not None else -1,
        )
        body = "\n".join((*header_lines, grid))
        screen.paint(
            compose_frame(body, status, controls(), notices(), height=size.lines),
            force=force,
            atomic=atomic,
        )
        help_was_active = False

    def show_chooser_help(action: str, selected: str) -> None:
        open_help(context="chooser", action=action, selected=selected)
        while help_overlay is not None:
            try:
                event = raise_if_interrupt(read_adjustment_event(decoder))
            except AdjustmentTimeout:
                close_help()
                return
            process_help_event(event)

    def choose_pane_type_blocking(
        action: str, pane_index: int, *, initial: CustomChartConfig | None = None
    ) -> CustomChartPaneConfig | str | None:
        nonlocal chooser_overlay

        def chooser_height() -> int:
            size = get_terminal_size()
            header_rows = len(
                _header_lines(
                    header,
                    header_style,
                    translator,
                    Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                    last_successful_update,
                )
            )
            layout = grid_geometry(size.columns, size.lines, header_rows, 0)
            cell_height = layout.pane(pane_index).height
            framed = frame_style != "none" or pane_index == focused
            return max(1, cell_height - 2 if framed else cell_height)

        def paint_choices(
            choices: str,
            title: str,
            chooser_controls: str,
            chooser_notices: tuple[str, ...],
        ) -> None:
            nonlocal chooser_overlay
            size = get_terminal_size()
            header_rows = len(
                _header_lines(
                    header,
                    header_style,
                    translator,
                    Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                    last_successful_update,
                )
            )
            layout = grid_geometry(size.columns, size.lines, header_rows, 0)
            cell_height = layout.pane(pane_index).height
            framed = frame_style != "none" or pane_index == focused
            interior_height = max(1, cell_height - 2 if framed else cell_height)
            formatted_notices = format_notice_lines(
                chooser_notices,
                width=size.columns,
                color=dashboard_theme != "no-color",
                ascii=options.host.ascii,
                translator=translator,
                color_scheme=dashboard_theme,
            )
            chooser_frame = compose_frame(
                choices,
                title,
                chooser_controls,
                formatted_notices,
                height=interior_height,
            )
            chooser_overlay = (pane_index, "\n".join(chooser_frame.rows))
            paint()

        try:
            choice = _choose_pane_type(
                screen,
                translator,
                decoder,
                height=chooser_height(),
                action=action,
                paint_choices=paint_choices,
                read_input=lambda: raise_if_interrupt(read_adjustment_event(decoder)),
                on_help=lambda selected: show_chooser_help(action, selected),
            )
            if choice != "datasets":
                return choice
            return _choose_dataset_pane_config(
                screen,
                translator,
                decoder,
                height=chooser_height(),
                dashboard=options,
                initial=initial,
                paint_choices=paint_choices,
                read_input=lambda: raise_if_interrupt(read_adjustment_event(decoder)),
            )
        finally:
            chooser_overlay = None

    def open_dataset_modal(
        action: str, pane_index: int, *, initial: CustomChartConfig | None = None
    ) -> None:
        """Start a Dataset chooser without taking ownership of the event loop."""

        nonlocal dataset_modal
        from ccusage_viz.datasets.service import DatasetService

        service = DatasetService()
        try:
            statuses = tuple(service.ready_registered_sources())
            error = None
        except UsageError as exc:
            statuses = ()
            error = format_error(exc, translator)
        draft = CustomPaneDraft(
            kind=initial.kind if initial is not None else "timeline",
            dataset_id=initial.source.dataset_id if initial is not None else "",
            command=shlex.join(initial.source.command_argv) if initial is not None else "",
        )
        dataset_modal = DashboardDatasetModalState(
            action, pane_index, initial, statuses, service, draft=draft, error=error
        )

    def _dataset_modal_size(pane_index: int) -> tuple[int, int]:
        """Return the target pane's content dimensions for its Dataset modal."""

        size = get_terminal_size()
        header_rows = len(
            _header_lines(
                header,
                header_style,
                translator,
                Terminal(size.columns, 4, dashboard_theme != "no-color", options.host.ascii),
                last_successful_update,
            )
        )
        rect = grid_geometry(size.columns, size.lines, header_rows, 0).pane(pane_index)
        framed = frame_style != "none" or pane_index == focused
        return (
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
        )

    def _dataset_modal_height(pane_index: int) -> int:
        return _dataset_modal_size(pane_index)[1]

    def _paint_dataset_modal() -> None:
        """Render the active Dataset state in its target pane."""

        nonlocal chooser_overlay
        assert dataset_modal is not None
        modal = dataset_modal
        width, height = _dataset_modal_size(modal.pane_index)
        notices = () if modal.error is None else (modal.error,)
        if modal.stage == "pane":
            rows, positions = _pane_chooser_rows(translator, modal.index)
            body, modal.offset = _chooser_viewport(
                rows,
                index=positions[_PANE_COMMANDS[modal.index]],
                offset=modal.offset,
                height=height,
            )
            title = translator.text(f"status.tui_{modal.action}_title")
            controls = translator.text(f"status.tui_{modal.action}_controls")
        elif modal.stage == "source":
            entries = modal.statuses
            if not entries:
                body = translator.text("status.datasets_empty")
            else:
                modal.index %= len(entries)
                rows = []
                for item_index, status in enumerate(entries):
                    selected = "›" if item_index == modal.index else " "
                    descriptor = status.registration.probe.descriptor
                    rows.append(
                        f"{selected} {_dataset_title(descriptor.dataset.title, translator)} "
                        f"{descriptor.version} · {translator.text('status.dataset_ready')}"
                    )
                body, modal.offset = _chooser_viewport(
                    rows,
                    index=modal.index,
                    offset=modal.offset,
                    height=height,
                    reserved_rows=2 + len(notices),
                )
            title = translator.text("status.dataset_chooser_title")
            controls = translator.text("status.dataset_chooser_controls")
        elif modal.stage == "source_loading":
            body = ""
            title = translator.text("status.dataset_chooser_title")
            controls = translator.text("status.dataset_chooser_controls")
            notices = (translator.text("status.loading"),)
        elif modal.stage == "browse":
            if modal.future is not None:
                body = ""
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
                notices = (translator.text("status.dataset_catalog_loading"),)
            elif not modal.entries:
                body = ""
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
                notices = (translator.text("status.datasets_official_empty"),)
            else:
                body, modal.offset = _official_catalog_viewport(
                    modal.entries,
                    translator,
                    index=modal.index,
                    offset=modal.offset,
                    width=get_terminal_size().columns,
                    height=height,
                    color=dashboard_theme != "no-color",
                    color_scheme=dashboard_theme,
                )
                title = translator.text("status.dataset_browse_title")
                controls = translator.text("status.dataset_browse_controls")
        elif modal.stage == "browse_loading":
            body = ""
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_loading_controls")
            notices = (translator.text("status.dataset_browse_loading"),)
        elif modal.stage == "github":
            body = modal.draft.command or "—"
            title = translator.text("status.dataset_github_title")
            if modal.future is not None:
                controls = translator.text("status.dataset_github_loading_controls")
                notices = (translator.text("status.dataset_github_resolving"),)
            elif modal.artifact is not None:
                body = "\n".join(
                    (
                        modal.draft.command,
                        "",
                        f"{modal.artifact.release_tag} · {modal.artifact.asset_name}",
                        modal.artifact.sha256,
                        translator.text(
                            "status.dataset_github_confirm",
                            repository=modal.artifact.repository,
                        ),
                    )
                )
                controls = translator.text("status.dataset_github_confirm_controls")
            else:
                controls = translator.text("status.dataset_github_controls")
        elif modal.stage == "github_installing":
            body = modal.draft.command
            title = translator.text("status.dataset_github_title")
            controls = translator.text("status.dataset_github_loading_controls")
            notices = (translator.text("status.dataset_github_installing"),)
        elif modal.stage == "browse_confirm":
            assert modal.official_preview is not None
            body = "\n".join(_official_preview_rows(modal.official_preview, translator))
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_confirm_controls")
        elif modal.stage == "installing":
            body = modal.selected_dataset_id or ""
            title = translator.text("status.dataset_browse_title")
            controls = translator.text("status.dataset_browse_confirm_controls")
            notices = (
                translator.text(
                    "status.dataset_browse_installing", dataset_id=modal.selected_dataset_id
                ),
            )
        elif modal.stage == "installed":
            rows = [
                f"{'›' if item_index == modal.index else ' '} {translator.text(f'label.pane_{kind}')}"
                for item_index, kind in enumerate(modal.chart_kinds)
            ]
            body, modal.offset = _chooser_viewport(
                rows, index=modal.index, offset=modal.offset, height=height
            )
            title = translator.text("status.dataset_chooser_title")
            controls = translator.text("status.dataset_chooser_controls")
        elif modal.stage == "metric":
            selected = next(
                status.registration.probe.descriptor
                for status in modal.statuses
                if status.registration.dataset_id == modal.draft.dataset_id
            )
            assert isinstance(selected, V2ProbeDescriptor)
            metric_rows = _metric_chooser_display_rows(
                _dataset_metric_chooser_rows(selected, translator),
                width=width,
                ascii=options.host.ascii,
            )
            metric_row_index = next(
                index for index, row in enumerate(metric_rows) if row.metric_index == modal.index
            )
            scheme = get_color_scheme(dashboard_theme)
            rows = [
                f"{'›' if row.metric_index == modal.index else ' '} "
                + (
                    emphasize(
                        row.text,
                        color=scheme.highlight,
                        enabled=dashboard_theme != "no-color",
                    )
                    if row.kind == "group"
                    else dimmed(
                        row.text,
                        color=dashboard_theme != "no-color",
                    )
                    if row.kind == "description"
                    else row.text
                )
                for row in metric_rows
            ]
            metric_body, modal.offset = _chooser_viewport(
                rows, index=metric_row_index, offset=modal.offset, height=height, reserved_rows=4
            )
            title, prompt = _dataset_metric_chooser_chrome(selected, translator)
            body = "\n".join((prompt, metric_body))
            controls = translator.text("status.dataset_chooser_controls")
        else:
            fields = (
                translator.text("label.custom_kind"),
                translator.text("label.custom_dataset"),
                translator.text("label.custom_command"),
            )
            values = (modal.draft.kind, modal.draft.dataset_id, modal.draft.command)
            body = "\n".join(
                f"{'›' if index == modal.draft.field else ' '} {label}: {value or '—'}"
                for index, (label, value) in enumerate(zip(fields, values, strict=True))
            )
            title = translator.text("status.custom_pane_title")
            controls = translator.text("status.custom_pane_controls")
        formatted_notices = format_notice_lines(
            notices,
            width=width,
            color=dashboard_theme != "no-color",
            ascii=options.host.ascii,
            translator=translator,
            color_scheme=dashboard_theme,
        )
        chooser_overlay = (
            modal.pane_index,
            "\n".join(compose_frame(body, title, controls, formatted_notices, height=height).rows),
        )

    def finish_dataset_modal(choice: CustomChartPaneConfig | str | None) -> None:
        """Apply one completed modal choice through the normal history transaction."""

        nonlocal active_grid, focused, dataset_modal, chooser_overlay
        assert dataset_modal is not None
        modal = dataset_modal
        if isinstance(choice, CustomChartPaneConfig):
            source = choice.chart.source
            conflict = _custom_source_conflict(
                panes,
                source,
                replacing_index=modal.pane_index if modal.action == "replace" else None,
            )
            if conflict is not None:
                modal.error = _custom_source_conflict_message(conflict, translator)
                return
        dataset_modal = None
        chooser_overlay = None
        if choice is None:
            return
        if modal.action == "replace":
            record_mutation(
                ("pane", modal.pane_index, "replace"),
                lambda choice=choice, index=modal.pane_index: _replace_pane(
                    panes, index, create_pane(choice), start=start_new_pane
                ),
            )
            return
        insert_at = modal.pane_index if modal.action == "insert_before" else modal.pane_index + 1

        def insert(
            choice: CustomChartPaneConfig | str = choice, insert_at: int = insert_at
        ) -> None:
            nonlocal active_grid, focused
            active_grid = _grid_for_pane_count(active_grid, len(panes) + 1)
            _insert_pane(panes, insert_at, create_pane(choice), start=start_new_pane)
            focused = insert_at

        record_mutation(("pane", modal.pane_index, modal.action), insert)

    def advance_dataset_modal(status: object) -> bool:
        """Apply a refreshed source descriptor and report whether it advances the modal."""

        assert dataset_modal is not None
        modal = dataset_modal
        modal.draft.dataset_id = status.registration.dataset_id
        modal.metrics = ()
        modal.metric_id = None
        modal.metric_summary = "comparisons"
        modal.metric_periods = ()
        modal.metric_titles = None
        modal.chart_kinds = ()
        descriptor = status.registration.probe.descriptor
        if isinstance(descriptor, V2ProbeDescriptor):
            modal.metrics = descriptor.metrics
            selectable = tuple(
                row.metric_index
                for row in _dataset_metric_chooser_rows(descriptor, translator)
                if row.metric_index is not None
            )
            if not selectable:
                modal.stage, modal.offset = "source", 0
                modal.error = translator.text("status.dataset_unavailable")
                return False
            modal.index = next(
                (
                    position
                    for position in selectable
                    if descriptor.metrics[position].id == descriptor.default_metric_id
                ),
                selectable[0],
            )
            modal.offset = 0
            modal.stage = "metric"
            return True
        modal.chart_kinds = tuple(descriptor.capabilities.charts)
        if not modal.chart_kinds:
            modal.stage, modal.offset = "source", 0
            modal.error = translator.text("status.dataset_unavailable")
            return False
        modal.stage, modal.index, modal.offset = "installed", 0, 0
        return True

    def collect_dataset_modal() -> bool:
        """Consume a completed Dataset modal future without blocking the Dashboard."""

        assert dataset_modal is not None
        modal = dataset_modal
        if modal.future is None or not modal.future.done():
            return False
        if modal.stage == "source_loading":
            selected_index = modal.index
            selected_dataset_id = modal.pending_dataset_id
            try:
                refreshed = modal.future.result()
                refreshed_id = refreshed.registration.dataset_id
                if refreshed_id != selected_dataset_id:
                    raise UsageError("error.dataset_corrupt", dataset_id=selected_dataset_id)
                modal.statuses = tuple(
                    refreshed if item.registration.dataset_id == selected_dataset_id else item
                    for item in modal.statuses
                )
                advanced = advance_dataset_modal(refreshed)
                if advanced:
                    modal.error = None
            except (UsageError, QueryError) as exc:
                modal.stage, modal.index, modal.offset = "source", selected_index, 0
                modal.error = format_error(exc, translator)
            except Exception as exc:
                modal.stage, modal.index, modal.offset = "source", selected_index, 0
                modal.error = str(exc)
            modal.future = None
            modal.pending_dataset_id = None
            return True
        if modal.stage == "browse":
            try:
                modal.entries = tuple(modal.future.result())
                modal.error = None
            except UsageError as exc:
                modal.error = format_error(exc, translator)
            except Exception:
                modal.error = translator.text("status.dataset_catalog_unavailable")
            modal.future = None
            return True
        if modal.stage == "installing":
            try:
                modal.future.result()
                modal.statuses = tuple(modal.service.status())
                modal.draft.dataset_id = modal.selected_dataset_id or ""
                modal.stage, modal.index, modal.offset = "installed", 0, 0
                modal.error = None
            except UsageError as exc:
                modal.stage = "browse_confirm"
                modal.error = format_error(exc, translator)
            except Exception:
                modal.stage = "browse_confirm"
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        if modal.stage == "browse_loading":
            try:
                modal.official_preview = cast(tuple[object, bytes, object], modal.future.result())
                modal.stage = "browse_confirm"
                modal.error = None
            except UsageError as exc:
                modal.stage = "browse"
                modal.error = format_error(exc, translator)
            except Exception:
                modal.stage = "browse"
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        if modal.stage == "github":
            try:
                modal.artifact = modal.future.result()
                modal.error = None
            except UsageError as exc:
                modal.error = format_error(exc, translator)
            except Exception:
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        if modal.stage == "github_installing":
            try:
                status = modal.future.result()
                installed = status.installed
                if installed is None:
                    raise UsageError("error.dataset_corrupt")
                modal.draft.dataset_id = installed.dataset_id
                modal.statuses = tuple(modal.service.status())
                modal.stage, modal.index, modal.offset = "installed", 0, 0
                modal.error = None
            except UsageError as exc:
                modal.stage = "github"
                modal.error = format_error(exc, translator)
            except Exception:
                modal.stage = "github"
                modal.error = translator.text("error.dataset_download_failed")
            modal.future = None
            return True
        return False

    def handle_dataset_modal(event: object) -> None:
        """Apply one event to the active Dataset modal without blocking Dashboard work."""

        nonlocal dataset_modal
        assert dataset_modal is not None
        modal = dataset_modal
        if not isinstance(event, (KeyEvent, PasteEvent)):
            return
        if isinstance(event, PasteEvent):
            if modal.stage == "local" and modal.draft.field in {1, 2}:
                if modal.draft.field == 1:
                    modal.draft.dataset_id += event.value
                else:
                    modal.draft.command += event.value
            return
        key = event.value
        if key == "\x03":
            raise KeyboardInterrupt
        if modal.stage == "pane":
            if key == "h":
                open_help(
                    context="chooser",
                    action=modal.action,
                    selected=_PANE_COMMANDS[modal.index],
                )
                return
            if key == "\x1b":
                finish_dataset_modal(None)
            elif key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(_PANE_COMMANDS)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(_PANE_COMMANDS)
            elif key in {"\r", "\n"}:
                choice = _PANE_COMMANDS[modal.index]
                if choice == "datasets":
                    modal.stage, modal.index, modal.offset = "source", 0, 0
                else:
                    finish_dataset_modal(choice)
            return
        if modal.stage == "source_loading":
            if key == "\x1b":
                if modal.future is not None:
                    modal.future.cancel()
                modal.future = None
                modal.pending_dataset_id = None
                modal.stage, modal.offset = "source", 0
            return
        if modal.stage == "source":
            entries = modal.statuses
            if key == "h" and entries:
                open_help(
                    context="dataset-chooser",
                    dataset_id=entries[modal.index].registration.dataset_id,
                )
                return
            if key == "\x1b":
                modal.stage, modal.index, modal.offset = "pane", 0, 0
            elif key in {"j", "\x1b[B"} and entries:
                modal.index = (modal.index + 1) % len(entries)
            elif key in {"k", "\x1b[A"} and entries:
                modal.index = (modal.index - 1) % len(entries)
            elif key in {"\r", "\n"} and entries:
                status = entries[modal.index]
                modal.draft.dataset_id = status.registration.dataset_id
                modal.metrics = ()
                modal.metric_id = None
                modal.metric_summary = "comparisons"
                modal.metric_periods = ()
                modal.metric_titles = None
                modal.chart_kinds = ()
                modal.error = None
                # Registered Dataset services refresh the selected probe before
                # exposing its chart choices. Retain compatibility with simple
                # injected catalog services that only provide cached statuses.
                refresh = getattr(modal.service, "refresh", None)
                if refresh is None:
                    advance_dataset_modal(status)
                    return
                modal.pending_dataset_id = modal.draft.dataset_id
                modal.stage = "source_loading"
                modal.future = executor.submit(
                    cast(Callable[[str], object], refresh),
                    modal.pending_dataset_id,
                )
                # Test and embedded runtimes may complete a probe synchronously;
                # advance now so the following key targets the metric chooser.
                if modal.future.done():
                    collect_dataset_modal()
            return
        if modal.stage == "metric":
            selected = next(
                status.registration.probe.descriptor
                for status in modal.statuses
                if status.registration.dataset_id == modal.draft.dataset_id
            )
            assert isinstance(selected, V2ProbeDescriptor)
            selectable = tuple(
                row.metric_index
                for row in _dataset_metric_chooser_rows(selected, translator)
                if row.metric_index is not None
            )
            if key == "\x1b":
                modal.stage, modal.index, modal.offset = "source", 0, 0
            elif key in {"j", "\x1b[B"}:
                modal.index = selectable[(selectable.index(modal.index) + 1) % len(selectable)]
            elif key in {"k", "\x1b[A"}:
                width, _height = _dataset_modal_size(modal.pane_index)
                metric_display_rows = _metric_chooser_display_rows(
                    _dataset_metric_chooser_rows(selected, translator),
                    width=width,
                    ascii=options.host.ascii,
                )
                reveal_offset = _metric_chooser_previous_offset(
                    metric_display_rows,
                    selected_metric_index=modal.index,
                    offset=modal.offset,
                )
                if reveal_offset is not None:
                    modal.offset = reveal_offset
                else:
                    modal.index = selectable[(selectable.index(modal.index) - 1) % len(selectable)]
            elif key in {"\r", "\n"}:
                metric = modal.metrics[modal.index]
                modal.metric_id = metric.id
                modal.metric_summary = metric.summary
                modal.metric_titles = (metric.title.en, metric.title.zh_cn)
                modal.metric_periods = ()
                modal.chart_kinds = tuple(metric.capabilities.charts)
                if modal.chart_kinds:
                    modal.stage, modal.index, modal.offset = "installed", 0, 0
            return
        if modal.stage == "github":
            if key == "\x1b":
                if modal.future is not None:
                    return
                if modal.artifact is not None:
                    modal.artifact = None
                    modal.error = None
                else:
                    modal.stage, modal.index, modal.offset = "source", 0, 0
            elif modal.future is not None:
                return
            elif modal.artifact is not None:
                if key in {"\r", "\n"}:
                    modal.stage = "github_installing"
                    modal.future = executor.submit(
                        cast(
                            Callable[[object], object],
                            modal.service.install_resolved_github_artifact,
                        ),
                        modal.artifact,
                    )
            elif key in {"\r", "\n"}:
                if modal.draft.command.strip():
                    modal.future = executor.submit(
                        cast(Callable[[str], object], modal.service.resolve_github_repository),
                        modal.draft.command,
                    )
                    modal.error = None
            elif key in {"\x7f", "\b"}:
                modal.draft.command = modal.draft.command[:-1]
                modal.error = None
            elif len(key) == 1 and key.isprintable():
                modal.draft.command += key
                modal.error = None
            return
        if modal.stage == "github_installing":
            return
        if modal.stage == "browse":
            if key == "h" and modal.future is None and modal.entries:
                open_help(context="catalog-browser")
            elif key == "\x1b":
                if modal.future is not None:
                    modal.future.cancel()
                modal.future = None
                modal.stage, modal.index, modal.offset = "source", 0, 0
            elif modal.future is None and modal.entries:
                if key in {"j", "\x1b[B"}:
                    modal.index = (modal.index + 1) % len(modal.entries)
                elif key in {"k", "\x1b[A"}:
                    modal.index = (modal.index - 1) % len(modal.entries)
                elif key in {"\r", "\n"}:
                    selected = modal.entries[modal.index]
                    host_os, host_arch = cast(tuple[str, str], modal.service.platform)
                    if not any(
                        artifact.os == host_os and artifact.arch == host_arch
                        for artifact in selected.artifacts
                    ):
                        modal.error = translator.text(
                            "status.dataset_catalog_unavailable_platform",
                            platform=f"{host_os}/{host_arch}",
                        )
                    else:
                        modal.selected_dataset_id = selected.id
                        modal.stage = "browse_loading"
                        modal.future = executor.submit(
                            cast(Callable[[str], object], modal.service.prepare_official_install),
                            selected.id,
                        )
            return
        if modal.stage == "browse_loading":
            return
        if modal.stage == "browse_confirm":
            if key == "\x1b":
                modal.stage = "browse"
                modal.error = None
            elif key in {"\r", "\n"}:
                assert modal.selected_dataset_id is not None
                assert modal.official_preview is not None
                modal.stage = "installing"
                modal.future = executor.submit(
                    cast(Callable[[object, bytes], object], modal.service.install_artifact),
                    modal.official_preview[0],
                    modal.official_preview[1],
                )
            return
        if modal.stage == "installing":
            return
        if modal.stage == "installed":
            if key == "h":
                open_help(
                    context="dataset-chooser",
                    dataset_id=modal.draft.dataset_id,
                    chart_kind=modal.chart_kinds[modal.index],
                )
                return
            if key == "\x1b":
                if modal.metrics:
                    modal.index = next(
                        (
                            position
                            for position, metric in enumerate(modal.metrics)
                            if metric.id == modal.metric_id
                        ),
                        0,
                    )
                    modal.offset = 0
                    modal.stage = "metric"
                else:
                    modal.stage, modal.index, modal.offset = "source", 0, 0
            elif key in {"j", "\x1b[B"}:
                modal.index = (modal.index + 1) % len(modal.chart_kinds)
            elif key in {"k", "\x1b[A"}:
                modal.index = (modal.index - 1) % len(modal.chart_kinds)
            elif key in {"\r", "\n"}:
                try:
                    source = modal.service.registered_command_source(modal.draft.dataset_id)
                except UsageError as exc:
                    modal.error = format_error(exc, translator)
                else:
                    kind = modal.chart_kinds[modal.index]
                    metric_periods = modal.metric_periods
                    if modal.metric_id is not None:
                        metric = next(
                            item
                            for item in modal.metrics
                            if isinstance(item, V2MetricDescriptor) and item.id == modal.metric_id
                        )
                        metric_periods = _custom_metric_periods(metric, kind)
                    finish_dataset_modal(
                        default_custom_pane(
                            kind,
                            source=source,
                            dashboard=options,
                            metric_id=modal.metric_id,
                            metric_summary=modal.metric_summary,
                            metric_periods=metric_periods,
                            metric_titles=modal.metric_titles,
                        )
                    )
            return
        if key == "\x1b":
            modal.stage, modal.index, modal.offset = "source", 0, 0
        elif key in {"\t", "\x1b[B"}:
            modal.draft.field = (modal.draft.field + 1) % 3
        elif key == "\x1b[A":
            modal.draft.field = (modal.draft.field - 1) % 3
        elif modal.draft.field == 0 and key in {"j", "\x1b[C"}:
            kinds = _CUSTOM_PANE_KINDS
            modal.draft.kind = kinds[(kinds.index(modal.draft.kind) + 1) % len(kinds)]
        elif modal.draft.field == 0 and key in {"k", "\x1b[D"}:
            kinds = _CUSTOM_PANE_KINDS
            modal.draft.kind = kinds[(kinds.index(modal.draft.kind) - 1) % len(kinds)]
        elif key == "\x19":
            value = (modal.draft.kind, modal.draft.dataset_id, modal.draft.command)[
                modal.draft.field
            ]
            modal.error = translator.text(
                "status.command_copied" if copy_command(value) else "status.command_copy_failed"
            )
        elif key == "\x15":
            if modal.draft.field == 0:
                modal.error = translator.text("status.custom_pane_kind_required")
            elif modal.draft.field == 1:
                modal.draft.dataset_id = ""
                modal.error = translator.text("status.custom_pane_field_cleared")
            else:
                modal.draft.command = ""
                modal.error = translator.text("status.custom_pane_field_cleared")
        elif key in {"\r", "\n"}:
            try:
                source = CustomCommandSource(
                    modal.draft.dataset_id.strip(), tuple(shlex.split(modal.draft.command))
                )
                finish_dataset_modal(
                    default_custom_pane(modal.draft.kind, source=source, dashboard=options)
                )
            except ValueError as exc:
                modal.error = str(exc)
        elif modal.draft.field in {1, 2}:
            value = modal.draft.dataset_id if modal.draft.field == 1 else modal.draft.command
            if key in {"\x7f", "\b"}:
                value = value[:-1]
            elif len(key) == 1 and key.isprintable():
                value += key
            else:
                return
            if modal.draft.field == 1:
                modal.draft.dataset_id = value
            else:
                modal.draft.command = value

    def create_pane(command: PaneConfig | str, *, pane_id: int | None = None) -> TuiPane:
        pane_id = allocate_pane_id() if pane_id is None else pane_id
        if isinstance(command, CustomChartPaneConfig):
            pane = _new_pane(options, command, f"dashboard:pane:{pane_id}", runtime)
        elif command == "empty":
            pane = _new_pane(options, EmptyPaneConfig())
        elif command == "animate":
            pane = _new_pane(options, AnimationPaneConfig(default_animation_spec("pane")))
        else:
            assert isinstance(command, str)
            pane = _new_pane(
                _new_pane_options(command, options),
                f"dashboard:pane:{pane_id}",
                runtime,
            )
        pane.pane_id = pane_id
        return pane

    try:
        set_screen_cursor_visible(False)
        with tui_input_mode() as decoder:
            for index in range(len(panes)):
                refresh(index, trigger=LifecycleTrigger.STARTUP)
            if header_style != "hidden":
                refresh_header(trigger=LifecycleTrigger.STARTUP)
                refresh_custom_summaries(trigger=LifecycleTrigger.STARTUP)
            paint()
            while True:
                size = get_terminal_size()
                if (size.columns, size.lines) != last_size:
                    paint(force=True)
                changed = collect()
                if dataset_modal is not None:
                    changed = collect_dataset_modal() or changed
                now = time.monotonic()
                refresh_requested = False
                if header_style != "hidden" and header.scheduler.due(now=now):
                    refresh_requested = True
                    refresh_header(trigger=LifecycleTrigger.PERIODIC)
                    refresh_custom_summaries(trigger=LifecycleTrigger.PERIODIC)
                for index, pane in enumerate(panes):
                    if isinstance(pane, (TuiChartPane, TuiCustomPane)) and pane.scheduler.due(
                        now=now
                    ):
                        refresh_requested = True
                        refresh(index, trigger=LifecycleTrigger.PERIODIC)
                deadline = animation_deadline()
                feedback_expired = (
                    copy_feedback.message is not None and now >= copy_feedback.expires_at
                )
                copied_ranking_icon_expired = any(
                    isinstance(pane, TuiCustomPane)
                    and (
                        pane.copied_ranking_entry_id is not None
                        and now >= pane.copied_ranking_until
                        or pane.copied_ranking_all_until > 0
                        and now >= pane.copied_ranking_all_until
                    )
                    for pane in panes
                )
                if copied_ranking_icon_expired:
                    for pane in panes:
                        if not isinstance(pane, TuiCustomPane):
                            continue
                        if (
                            pane.copied_ranking_entry_id is not None
                            and now >= pane.copied_ranking_until
                        ):
                            pane.copied_ranking_entry_id = None
                        if (
                            pane.copied_ranking_all_until > 0
                            and now >= pane.copied_ranking_all_until
                        ):
                            pane.copied_ranking_all_until = 0.0
                cursor_tick = overlay_editor is not None and int(now * 2) != int((now - 0.1) * 2)
                if (
                    changed
                    or refresh_requested
                    or feedback_expired
                    or copied_ranking_icon_expired
                    or cursor_tick
                    or (deadline is not None and now >= deadline)
                ):
                    paint(
                        animation_only=not (
                            changed
                            or refresh_requested
                            or feedback_expired
                            or copied_ranking_icon_expired
                            or cursor_tick
                        )
                    )
                try:
                    event = raise_if_interrupt(read_adjustment_event(decoder))
                except AdjustmentTimeout:
                    if help_overlay is not None:
                        help_overlay = None
                    _finish_ranking_search_editing(panes[focused] if focused is not None else None)
                    end_adjustment()
                    paint()
                    continue
                if isinstance(event, WheelEvent):
                    scrolling = tuple(
                        pane.active_ranking_viewport
                        for pane in panes
                        if isinstance(pane, TuiCustomPane)
                    )
                    before = tuple(viewport.offset for viewport in scrolling)
                    handle_ranking_wheel(event)
                    if isinstance(decoder, InputDecoder):
                        for buffered in decoder.drain_wheel():
                            handle_ranking_wheel(buffered)
                    if before != tuple(viewport.offset for viewport in scrolling):
                        paint()
                    continue
                if help_overlay is not None:
                    process_help_event(event)
                    continue
                if preset_manager is not None:
                    if isinstance(event, (KeyEvent, PasteEvent)):
                        update = reduce_preset_manager(preset_manager, preset_catalog(), event)
                        preset_manager = update.state
                        if update.command is not None:
                            execute_preset_command(update.command)
                        if preset_manager is not None:
                            preset_manager = reconcile_preset_manager(
                                preset_manager,
                                preset_catalog(),
                                visible_rows=max(1, get_terminal_size().lines - 4),
                            )
                    paint()
                    continue
                if dataset_modal is not None:
                    handle_dataset_modal(event)
                    paint()
                    continue
                if isinstance(event, MouseEvent):
                    hover_changed = handle_scrollbar_hover(event)
                    if handle_scrollbar_drag(event):
                        paint()
                        continue
                    if handle_pane_mouse(event):
                        paint()
                        continue
                    if hover_changed:
                        paint()
                    continue
                # A text/command draft owns every printable key, including u/U/h.
                if overlay_editor is not None:
                    if not isinstance(event, (KeyEvent, PasteEvent)):
                        continue
                    pane = panes[overlay_editor.pane_index]
                    assert isinstance(pane, TuiAnimationPane)
                    animation_pane = pane
                    if isinstance(event, PasteEvent):
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[:cursor]
                            + event.value
                            + overlay_editor.draft[cursor:]
                        )
                        overlay_editor.cursor = cursor + len(event.value)
                        paint()
                        continue
                    key = event.value
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "\x1b":
                        overlay_editor = None
                    elif key == "\t":
                        overlay_editor.mode = "command" if overlay_editor.mode == "text" else "text"
                    elif key == "\r":
                        mode = overlay_editor.mode
                        draft = overlay_editor.draft
                        pane_index = overlay_editor.pane_index
                        record_mutation(
                            ("pane", pane_index, "overlay-source"),
                            lambda pane=animation_pane: pane.overlay.apply_draft(mode, draft),
                        )
                        overlay_editor = None
                    elif key in {"\n", "\x0b"}:
                        adjust_pane_weight(
                            overlay_editor.pane_index,
                            axis="row",
                            delta=1 if key == "\x0b" else -1,
                        )
                    elif key == "\x08":
                        open_help(context="editor")
                    elif key == "\x15":
                        overlay_editor.replace_draft("")
                        overlay_editor.cursor = 0
                        copy_feedback.show(translator.text("status.overlay_editor_cleared"))
                    elif key == "\x19":
                        copy_feedback.show(
                            translator.text(
                                "status.command_copied"
                                if copy_command(overlay_editor.draft)
                                else "status.command_copy_failed"
                            )
                        )
                    elif key == "\x12":
                        overlay_editor.replace_draft(
                            pane.overlay.config.text or ""
                            if overlay_editor.mode == "text"
                            else pane.overlay.config.command or ""
                        )
                        overlay_editor.cursor = len(overlay_editor.draft)
                    elif key == "\x7f" and overlay_editor.cursor:
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[: cursor - 1] + overlay_editor.draft[cursor:]
                        )
                        overlay_editor.cursor = cursor - 1
                    elif key in {"\x1b[3~", "\x04"}:
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[:cursor] + overlay_editor.draft[cursor + 1 :]
                        )
                    elif key == "\x1b[D":
                        overlay_editor.cursor = max(0, overlay_editor.cursor - 1)
                    elif key == "\x1b[C":
                        overlay_editor.cursor = min(
                            len(overlay_editor.draft), overlay_editor.cursor + 1
                        )
                    elif key in {"\x1b[H", "\x01"}:
                        overlay_editor.cursor = _editor_line_start(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif key == "\x02":
                        overlay_editor.cursor = _editor_previous_word(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif key == "\x17":
                        overlay_editor.cursor = _editor_next_word(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif key in {"\x1b[F", "\x05"}:
                        overlay_editor.cursor = _editor_line_end(
                            overlay_editor.draft, overlay_editor.cursor
                        )
                    elif len(key) == 1 and key.isprintable():
                        cursor = overlay_editor.cursor
                        overlay_editor.replace_draft(
                            overlay_editor.draft[:cursor] + key + overlay_editor.draft[cursor:]
                        )
                        overlay_editor.cursor = cursor + 1
                    paint()
                    continue
                if custom_logs_pane is not None:
                    if not isinstance(event, KeyEvent):
                        continue
                    key = event.value
                    pane = panes[custom_logs_pane]
                    assert isinstance(pane, TuiCustomPane)
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "\x1b":
                        custom_logs_pane = None
                    elif key in {"y", "Y"}:
                        copy_feedback.show(
                            translator.text(
                                "status.data_copied"
                                if copy_command(
                                    "\n".join(
                                        f"{record.timestamp.isoformat()} {record.status}: {record.detail}"
                                        for record in pane.logs
                                    )
                                )
                                else "status.command_copy_failed"
                            )
                        )
                    paint()
                    continue
                if overlay_history is not None:
                    if not isinstance(event, KeyEvent):
                        continue
                    key = event.value
                    pane = panes[overlay_history.pane_index]
                    assert isinstance(pane, TuiAnimationPane)
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "h":
                        open_help(context="history")
                        continue
                    if key == "\x1b":
                        overlay_history = None
                    else:
                        records = tuple(pane.overlay.history)
                        if key in {"y", "\r", "\n"} and overlay_history.table.selected is not None:
                            copy_feedback.show(
                                translator.text(
                                    "status.command_copied"
                                    if copy_command(
                                        format_execution_record(overlay_history.table.selected)
                                    )
                                    else "status.command_copy_failed"
                                )
                            )
                        elif key == "\x1b[A":
                            move_history_selection(overlay_history.table, records, -1)
                        elif key == "\x1b[B":
                            move_history_selection(overlay_history.table, records, 1)
                        elif key in {"{", "}", "J", "K"}:
                            adjust_pane_weight(
                                overlay_history.pane_index,
                                axis="column" if key in {"{", "}"} else "row",
                                delta=1 if key in {"}", "K"} else -1,
                            )
                    paint()
                    continue
                if isinstance(event, MouseEvent):
                    continue
                if focused is not None and _ranking_search_eligible(panes[focused]):
                    search = panes[focused].ranking_search
                    if search.editing:
                        if isinstance(event, PasteEvent):
                            search.query += event.value
                        elif isinstance(event, KeyEvent):
                            key = event.value
                            if key == "\x1b":
                                search.query = ""
                                search.editing = False
                                search.density_notice = None
                            elif key in {"\r", "\n"}:
                                search.editing = False
                            elif key in {"\x7f", "\b"}:
                                search.query = search.query[:-1]
                            elif len(key) == 1 and key.isprintable():
                                search.query += key
                        paint()
                        continue
                    if isinstance(event, KeyEvent) and event.value == "/":
                        search.editing = True
                        search.density_notice = None
                        paint()
                        continue
                key = event.value if isinstance(event, KeyEvent) else None
                if key == "\x03":
                    raise KeyboardInterrupt
                # A draft owns every ordinary key: root shortcuts must not leak in.
                if grid_draft is not None:
                    if key == "\x1b":
                        grid_draft = None
                        grid_error = None
                    elif key in {"\r", "\n"}:
                        parsed = parse_grid(grid_draft, len(panes))
                        if parsed is None:
                            grid_error = translator.text(
                                "error.tui_grid_runtime", value=grid_draft, count=len(panes)
                            )
                        else:
                            changed_grid = parsed != active_grid or active_layout is not None
                            if changed_grid:

                                def apply_grid() -> None:
                                    nonlocal active_grid, active_layout, column_weights, row_weights
                                    active_grid = parsed
                                    active_layout = None
                                    column_weights = None
                                    row_weights = None

                                record_mutation(("layout", "topology"), apply_grid)
                            grid_draft = None
                            grid_error = None
                    elif key in {"\x7f", "\b"}:
                        grid_draft = grid_draft[:-1]
                    elif key and (key.isalnum() or key in {"x", "X", "-"}):
                        grid_draft += key
                    paint()
                    continue
                if key in {"u", "U"}:
                    restored = history.undo() if key == "u" else history.redo()
                    if restored is history:
                        copy_feedback.show(
                            translator.text(
                                "status.tui_history_empty_undo"
                                if key == "u"
                                else "status.tui_history_empty_redo"
                            )
                        )
                    else:
                        history = restored
                        apply_dashboard_state(history.current)
                    paint()
                    continue
                if key == "h":
                    open_help()
                    continue
                if key == "c":
                    controls_hidden = not controls_hidden
                    paint(force=True)
                    continue
                if adjustment_mode == "pane":
                    if key is None:
                        continue
                    if key in {"\r", "\n", "\x1b"}:
                        end_adjustment()
                        paint()
                        continue
                    assert focused is not None
                    pane = panes[focused]
                    focused_index = focused
                    if isinstance(pane, TuiAnimationPane):
                        if key == "a":
                            adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                        else:
                            target_page = _animation_adjustment_target_page(adjustment_page, key)
                            if target_page is not None:
                                adjustment_page = target_page
                        if key == "a":
                            paint()
                            continue
                        animation_pane = pane
                        if adjustment_page == "quick" and key in {"p", "P"}:
                            record_mutation(
                                ("pane", focused, "overlay-position"),
                                lambda pane=animation_pane: pane.overlay.cycle_position(
                                    1 if key == "p" else -1
                                ),
                            )
                        elif adjustment_page == "quick" and key in {"t", "T"}:
                            record_mutation(
                                ("pane", focused, "theme"),
                                lambda pane=animation_pane, now=now: pane.session.set_theme(
                                    _cycle(
                                        COLOR_SCHEMES, pane.session.theme, 1 if key == "t" else -1
                                    ),
                                    now,
                                ),
                            )
                        elif adjustment_page == "quick" and key in {"s", "S"}:
                            record_mutation(
                                ("pane", focused, "style"),
                                lambda pane=animation_pane, now=now: cycle_animation_style(
                                    pane.session,
                                    target="pane",
                                    step=1 if key == "s" else -1,
                                    now=now,
                                ),
                            )
                        elif adjustment_page == "advanced" and key == "\x1b[A":
                            record_mutation(
                                ("pane", focused, "overlay-offset"),
                                lambda pane=animation_pane: pane.overlay.adjust_offset(dy=-1),
                            )
                        elif adjustment_page == "advanced" and key == "\x1b[B":
                            record_mutation(
                                ("pane", focused, "overlay-offset"),
                                lambda pane=animation_pane: pane.overlay.adjust_offset(dy=1),
                            )
                        elif adjustment_page == "advanced" and key == "\x1b[C":
                            record_mutation(
                                ("pane", focused, "overlay-offset"),
                                lambda pane=animation_pane: pane.overlay.adjust_offset(dx=1),
                            )
                        elif adjustment_page == "advanced" and key == "\x1b[D":
                            record_mutation(
                                ("pane", focused, "overlay-offset"),
                                lambda pane=animation_pane: pane.overlay.adjust_offset(dx=-1),
                            )
                        elif adjustment_page == "advanced" and key == "0":
                            record_mutation(
                                ("pane", focused, "overlay-offset"),
                                lambda pane=animation_pane: pane.overlay.reset_offset(),
                            )
                        elif adjustment_page == "advanced" and key == "i":
                            record_mutation(
                                ("pane", focused, "overlay-interval"),
                                lambda pane=animation_pane, now=now: pane.overlay.cycle_interval(
                                    now=now
                                )
                                and None,
                            )
                        elif adjustment_page == "advanced" and key == "L":
                            overlay_history = OverlayHistoryState(focused)
                        elif adjustment_page == "advanced" and key == "e":
                            overlay_editor = OverlayEditorState(
                                focused,
                                "command"
                                if animation_pane.overlay.config.command is not None
                                else "text",
                                animation_pane.overlay.text_draft,
                                animation_pane.overlay.command_draft,
                            )
                        else:
                            now = None
                        if now is not None:
                            paint()
                            continue
                    if isinstance(pane, TuiCustomPane) and key in {"v", "V"}:
                        record_mutation(
                            ("pane", focused_index, "view"),
                            lambda pane=pane: setattr(
                                pane,
                                "body_view",
                                cycle_body_view(pane.body_view, step=1 if key == "v" else -1),
                            ),
                        )
                        paint()
                        continue
                    if isinstance(pane, TuiCustomPane) and (
                        key in {"a", "f"}
                        or key in _custom_pane_adjustment_keys(pane, adjustment_page)
                        or key
                        in _custom_pane_adjustment_keys(
                            pane,
                            "advanced" if adjustment_page == "quick" else "quick",
                        )
                        or (
                            key in {"g", "G"}
                            and pane.component.candidate.kind == "ranking"
                            and isinstance(
                                capability := _custom_capability(pane), CustomChartCapability
                            )
                            and capability.partition_by is not None
                        )
                    ):
                        if key == "a":
                            adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                            paint()
                            continue
                        current_page_keys = _custom_pane_adjustment_keys(pane, adjustment_page)
                        other_page = "advanced" if adjustment_page == "quick" else "quick"
                        other_page_keys = _custom_pane_adjustment_keys(pane, other_page)
                        if key not in current_page_keys and key in other_page_keys:
                            adjustment_page = other_page
                        component = pane.component
                        base = component.candidate
                        capability = _custom_capability(pane)
                        if key in {"d", "D"} and pane.ranking_search.query:
                            pane.ranking_search.density_notice = translator.text(
                                "status.ranking_search_density_locked"
                            )
                            paint()
                            continue

                        def apply_custom_query(
                            config: CustomChartConfig,
                            *,
                            mutation: str,
                            pane: TuiCustomPane = pane,
                            pane_index: int = focused_index,
                        ) -> None:
                            pane.component.configure(config, data_affecting=True)
                            if pane.summary is not None and not custom_date_summary_supported(
                                config
                            ):
                                pane.summary.invalidate()
                            refresh(
                                pane_index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                                summary_affecting=mutation in {"granularity", "filters", "source"},
                            )

                        if key in {"m", "M"} and isinstance(
                            component, (CustomHistoricalComponent, CustomMonitorComponent)
                        ):
                            descriptor = component.v2_descriptor
                            metric_id = component.candidate.metric_id
                            if descriptor is None or metric_id is None:
                                copy_feedback.show(
                                    translator.text("status.custom_metric_no_alternative")
                                )
                                continue
                            from ccusage_viz.custom_metric_switching import cycle_switch_metric

                            target = cycle_switch_metric(
                                descriptor,
                                current_metric_id=metric_id,
                                kind=base.kind,
                                step=1 if key == "m" else -1,
                            )
                            if target is None:
                                copy_feedback.show(
                                    translator.text("status.custom_metric_no_alternative")
                                )
                                continue
                            component.begin_metric_switch(
                                replace(base, metric_id=target.id),
                                now=datetime.now().astimezone(),
                                timezone=options.host.timezone or "UTC",
                            )
                            refresh(
                                focused_index,
                                trigger=LifecycleTrigger.CONFIGURATION,
                                data_affecting=False,
                                summary_affecting=True,
                            )
                        elif key == "L":
                            custom_logs_pane = focused_index
                        elif (
                            isinstance(component, CustomMonitorComponent)
                            and adjustment_page == "advanced"
                            and pane.attachment is not None
                            and is_monitor_ranking_style(base.presentation.style)
                            and key in {"s", "S", "t", "T"}
                        ):
                            attachment = pane.attachment

                            def adjust_custom_attachment(
                                pane: TuiCustomPane = pane,
                                attachment: AnimationSessionState = attachment,
                            ) -> None:
                                now = time.monotonic()
                                if key in {"s", "S"}:
                                    pane.attachment_enabled = cycle_monitor_attachment(
                                        attachment,
                                        enabled=pane.attachment_enabled,
                                        step=1 if key == "s" else -1,
                                        now=now,
                                    )
                                else:
                                    attachment.set_theme(
                                        _cycle(
                                            COLOR_SCHEMES, attachment.theme, 1 if key == "t" else -1
                                        ),
                                        now,
                                    )

                            record_mutation(
                                ("pane", focused_index, "custom-monitor-animation"),
                                adjust_custom_attachment,
                            )
                        elif isinstance(component, CustomMonitorComponent) and key in {
                            "d",
                            "s",
                            "S",
                            "t",
                            "T",
                            "l",
                            "+",
                            "=",
                            "-",
                            "_",
                            "o",
                        }:
                            updated = _adjust_custom_monitor_chart(
                                base, key, aggregation=component.aggregation
                            )
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-monitor-presentation"),
                                    lambda config=updated: component.configure(
                                        config, data_affecting=False
                                    ),
                                )
                        elif isinstance(component, CustomMonitorComponent) and key == "w":
                            if base.presentation.style == "cumulative-bars":
                                record_mutation(
                                    ("pane", focused_index, "custom-monitor-distribution-day"),
                                    component.toggle_distribution_day_window,
                                )
                            else:
                                window = _cycle_custom_monitor_window(
                                    component.display_window_seconds
                                )
                                record_mutation(
                                    ("pane", focused_index, "custom-monitor-window"),
                                    lambda window=window: component.configure_display_window(
                                        window
                                    ),
                                )
                        elif key in {"p", "P"}:
                            period_base = (
                                _custom_period_adjustment_target(component)
                                if isinstance(component, CustomHistoricalComponent)
                                else _custom_period_adjustment_chart(base, capability)
                            )
                            switch_anchor = (
                                component.switch_anchor
                                if isinstance(component, CustomHistoricalComponent)
                                and component.switch_target_config is not None
                                else None
                            )
                            updated = adjust_custom_chart(
                                period_base,
                                key,
                                now=switch_anchor or datetime.now().astimezone(),
                                timezone=options.host.timezone or "UTC",
                            )
                            if updated != period_base:
                                if (
                                    isinstance(component, CustomHistoricalComponent)
                                    and component.switch_target_config is not None
                                ):

                                    def update_pending_metric_period(
                                        config: CustomChartConfig = updated,
                                        component: CustomHistoricalComponent = component,
                                        pane_index: int = focused_index,
                                    ) -> None:
                                        component.begin_metric_switch(
                                            config,
                                            now=component.switch_anchor,
                                            timezone=options.host.timezone or "UTC",
                                        )
                                        refresh(
                                            pane_index,
                                            trigger=LifecycleTrigger.CONFIGURATION,
                                            data_affecting=False,
                                            summary_affecting=True,
                                        )

                                    record_mutation(
                                        ("pane", focused_index, "custom-period"),
                                        update_pending_metric_period,
                                    )
                                else:
                                    record_mutation(
                                        ("pane", focused_index, "custom-period"),
                                        lambda config=updated: apply_custom_query(
                                            config, mutation="period"
                                        ),
                                    )
                            elif period_base.metric_periods:
                                copy_feedback.show(
                                    translator.text("status.custom_period_restricted")
                                )
                        elif (
                            key in {"s", "S"}
                            and base.kind == "ranking"
                            and adjustment_page == "advanced"
                        ):
                            modes = ("compact", "space", "line", "dashed")
                            position = modes.index(pane.ranking_item_spacing)
                            pane.ranking_item_spacing = modes[
                                (position + (1 if key == "s" else -1)) % len(modes)
                            ]
                        elif (
                            key in {"g", "G"}
                            and base.kind == "ranking"
                            and isinstance(capability, CustomChartCapability)
                            and capability.partition_by is not None
                        ):
                            updated = _cycle_custom_partitioning(
                                base,
                                capability.partition_by,
                                capability.group_by,
                                step=1 if key == "g" else -1,
                            )
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-partition"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="partition"
                                    ),
                                )
                            else:
                                copy_feedback.show(
                                    translator.text("status.custom_partition_restricted")
                                )
                        elif (
                            key in {"g", "G"}
                            and not is_v2_custom_ranking(base)
                            and capability is not None
                            and capability.granularities
                        ):
                            values = capability.granularities
                            current = base.granularity if base.granularity in values else values[0]
                            direction = 1 if key == "g" else -1
                            updated = replace(base, granularity=_cycle(values, current, direction))
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-granularity"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="granularity"
                                    ),
                                )
                        elif (
                            key in {"b", "B"} and base.kind != "calendar" and capability is not None
                        ):
                            updated = _cycle_custom_grouping(
                                base, capability.group_by, step=1 if key == "b" else -1
                            )
                            if updated != base:
                                record_mutation(
                                    ("pane", focused_index, "custom-group"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="group"
                                    ),
                                )
                            else:
                                copy_feedback.show(
                                    translator.text("status.custom_group_restricted")
                                )
                        elif (
                            key == "f"
                            and capability is not None
                            and _custom_runtime_filters(component)
                        ):
                            filters = _custom_runtime_filters(component)
                            size = get_terminal_size()
                            first_filter_frame = True

                            def paint_custom_filter_editor(body: str, editor_controls: str) -> None:
                                nonlocal first_filter_frame
                                screen.paint(
                                    compose_frame(
                                        body,
                                        translator.text("label.adjust_filters"),
                                        editor_controls,
                                        height=size.lines,
                                    ),
                                    force=first_filter_frame,
                                )
                                first_filter_frame = False

                            def read_custom_filter_key() -> (
                                KeyEvent | MouseEvent | PasteEvent | None
                            ):
                                editor_event = raise_if_interrupt(read_adjustment_event(decoder))
                                if isinstance(editor_event, MouseEvent):
                                    # The filter body begins below compose_frame's title row.
                                    return replace(editor_event, y=editor_event.y - 1)
                                return (
                                    editor_event
                                    if isinstance(editor_event, (KeyEvent, PasteEvent))
                                    else None
                                )

                            try:
                                edited = run_custom_filter_editor(
                                    base.filters,
                                    filters,
                                    translator,
                                    width=size.columns,
                                    height=max(0, size.lines - 2),
                                    paint=paint_custom_filter_editor,
                                    read_key=read_custom_filter_key,
                                    color=dashboard_theme != "no-color",
                                    color_scheme=dashboard_theme,
                                )
                            except AdjustmentTimeout:
                                end_adjustment()
                                paint(force=True)
                                continue
                            paint(force=True)
                            if edited is not None and edited != base.filters:
                                updated = replace(base, filters=edited)
                                record_mutation(
                                    ("pane", focused_index, "custom-filters"),
                                    lambda config=updated: apply_custom_query(
                                        config, mutation="filters"
                                    ),
                                )
                        elif key == "f":
                            copy_feedback.show(translator.text("status.custom_filter_unavailable"))
                        elif key in {
                            "d",
                            "D",
                            "t",
                            "T",
                            "s",
                            "S",
                            "k",
                            "l",
                            "o",
                            "+",
                            "=",
                            "-",
                            "_",
                        }:
                            updated = adjust_custom_chart(base, key)
                            if updated != base:

                                def apply_custom_presentation(
                                    pane: TuiCustomPane = pane,
                                    config: CustomChartConfig = updated,
                                ) -> None:
                                    if isinstance(
                                        pane.component, CustomHistoricalComponent
                                    ) and _custom_top_refresh_required(pane.component, config):
                                        apply_custom_query(config, mutation="top")
                                    else:
                                        pane.component.configure(config, data_affecting=False)

                                record_mutation(
                                    ("pane", focused_index, "custom-presentation"),
                                    apply_custom_presentation,
                                )
                        paint()
                        continue
                    error_body = (
                        isinstance(pane, TuiCustomPane)
                        and pane.body_view == "chart"
                        and pane.component.error is not None
                        and (
                            isinstance(pane.component, CustomMonitorComponent)
                            or pane.component.model is None
                        )
                    )
                    if isinstance(pane, (TuiChartPane, TuiCustomPane)) and (
                        pane.body_view != "chart" or error_body
                    ):
                        handled_body_key = False
                        if key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                            offset = next_text_offset(
                                key,
                                offset=(
                                    pane.error_offset
                                    if error_body
                                    else pane.text_offsets.get(pane.body_view, 0)
                                ),
                                line_count=(
                                    pane.error_line_count
                                    if error_body
                                    else pane.text_line_counts.get(pane.body_view, 0)
                                ),
                                visible_rows=(
                                    pane.error_visible_rows
                                    if error_body
                                    else pane.text_visible_rows.get(pane.body_view, 0)
                                ),
                            )
                            assert offset is not None
                            if error_body:
                                pane.error_offset = offset
                            else:
                                pane.text_offsets[pane.body_view] = offset
                            handled_body_key = True
                        elif key in {"v", "V"}:
                            text_pane = pane
                            record_mutation(
                                ("pane", focused, "view"),
                                lambda pane=text_pane: setattr(
                                    pane,
                                    "body_view",
                                    cycle_body_view(pane.body_view, step=1 if key == "v" else -1),
                                ),
                            )
                            handled_body_key = True
                        elif key in {"y", "Y"} and body_view_copy_kind(pane.body_view) is not None:
                            copy_kind = body_view_copy_kind(pane.body_view)
                            assert copy_kind is not None
                            copied = copy_command(
                                _pane_copy_payload(
                                    pane,
                                    translator,
                                    pane_terminal(focused),
                                    dashboard=options,
                                )
                            )
                            copy_feedback.show(
                                translator.text(
                                    "status.command_copied"
                                    if copied and copy_kind in {"command", "full-command"}
                                    else "status.data_copied"
                                    if copied
                                    else "status.command_copy_failed"
                                )
                            )
                            handled_body_key = True
                        if handled_body_key or not error_body:
                            paint()
                            continue
                        # An error-only custom pane remains a Dashboard pane: keys it
                        # does not own must reach the existing management routes below.
                    next_focused = _adjustment_target(focused, key, len(panes))
                    if next_focused != focused:
                        focused = next_focused
                        paint()
                        continue
                    if key == "r":
                        open_dataset_modal(
                            "replace",
                            focused_index,
                            initial=pane.component.candidate
                            if isinstance(pane, TuiCustomPane)
                            else None,
                        )
                        paint()
                        continue
                    if key in {"N", "n"}:
                        open_dataset_modal(
                            "insert_before" if key == "N" else "insert_after", focused_index
                        )
                        paint()
                        continue
                    if key in {"{", "}", "J", "K"}:
                        adjust_pane_weight(
                            focused_index,
                            axis="column" if key in {"{", "}"} else "row",
                            delta=1 if key in {"}", "K"} else -1,
                        )
                        paint()
                        continue
                    if key == "[" and focused_index > 0:

                        def move_previous(index: int = focused_index) -> None:
                            nonlocal focused
                            panes[index - 1], panes[index] = panes[index], panes[index - 1]
                            focused = index - 1

                        record_mutation(("pane", focused_index, "previous"), move_previous)
                        paint()
                        continue
                    if key == "]" and focused_index < len(panes) - 1:

                        def move_next(index: int = focused_index) -> None:
                            nonlocal focused
                            panes[index], panes[index + 1] = panes[index + 1], panes[index]
                            focused = index + 1

                        record_mutation(("pane", focused_index, "next"), move_next)
                        paint()
                        continue
                    if key == "x" and len(panes) > 1:

                        def delete(index: int = focused_index) -> None:
                            nonlocal active_grid, focused
                            removed = panes.pop(index)
                            _shutdown_pane(removed)
                            active_grid = _grid_for_pane_count(active_grid, len(panes))
                            focused = min(index, len(panes) - 1)

                        record_mutation(("pane", focused_index, "delete"), delete)
                        paint()
                        continue
                    if not isinstance(pane, TuiChartPane):
                        paint()
                        continue
                    chart_pane = pane
                    if key == "a":
                        adjustment_page = "advanced" if adjustment_page == "quick" else "quick"
                    else:
                        chart = _pane_display_options(pane).chart
                        target_page = _adjustment_target_page(
                            chart.kind,
                            adjustment_page,
                            key,
                            chart=chart,
                            attachment_available=(
                                isinstance(chart, MonitorConfig)
                                and is_monitor_ranking_style(chart.presentation.style)
                                and pane.attachment is not None
                            ),
                        )
                        if target_page is not None:
                            adjustment_page = target_page
                    if adjustment_page == "advanced" and key == "f":
                        component = pane.component
                        base = component.candidate
                        size = get_terminal_size()
                        editor_width = size.columns
                        editor_height = size.lines

                        def paint_filter_editor(
                            body: str,
                            editor_controls: str,
                            *,
                            height: int = editor_height,
                        ) -> None:
                            screen.paint(
                                compose_frame(
                                    body,
                                    translator.text("status.tui_adjust_history"),
                                    editor_controls,
                                    height=height,
                                )
                            )

                        def read_filter_key() -> str | None:
                            editor_event = raise_if_interrupt(read_adjustment_event(decoder))
                            return (
                                editor_event.value if isinstance(editor_event, KeyEvent) else None
                            )

                        try:
                            edited = run_filter_editor(
                                base.chart.filters,
                                discover_filter_choices(
                                    pane_records(pane),
                                    base.chart.filters,
                                    include_projects=pane_includes_projects(pane),
                                ),
                                translator,
                                width=editor_width,
                                paint=paint_filter_editor,
                                read_key=read_filter_key,
                            )
                        except AdjustmentTimeout:
                            end_adjustment()
                            paint()
                            continue
                        if edited is not None and edited != base.chart.filters:

                            def apply_filters(
                                pane: TuiChartPane = pane,
                                component: HistoricalChartComponent | MonitorComponent = component,
                                base: StandaloneLaunch = base,
                                edited=edited,
                                pane_index: int = focused,
                            ) -> None:
                                _clear_changes(pane)
                                component.configure(
                                    replace_chart_filters(base, edited),
                                    data_affecting=True,
                                )
                                refresh(
                                    pane_index,
                                    trigger=LifecycleTrigger.CONFIGURATION,
                                    data_affecting=False,
                                )

                            record_mutation(("pane", focused, "filters"), apply_filters)
                    elif key in {"v", "V"}:
                        record_mutation(
                            ("pane", focused, "view"),
                            lambda pane=chart_pane: setattr(
                                pane,
                                "body_view",
                                cycle_body_view(pane.body_view, step=1 if key == "v" else -1),
                            ),
                        )
                    elif (
                        adjustment_page == "advanced"
                        and chart_pane.attachment is not None
                        and isinstance(_pane_display_options(chart_pane).chart, MonitorConfig)
                        and is_monitor_ranking_style(
                            _pane_display_options(chart_pane).chart.presentation.style
                        )
                        and key in {"t", "T", "s", "S"}
                    ):
                        attachment = chart_pane.attachment
                        assert attachment is not None

                        def adjust_attachment(
                            pane: TuiChartPane = chart_pane,
                            attachment: AnimationSessionState = attachment,
                        ) -> None:
                            now = time.monotonic()
                            if key in {"s", "S"}:
                                pane.attachment_enabled = cycle_monitor_attachment(
                                    attachment,
                                    enabled=pane.attachment_enabled,
                                    step=1 if key == "s" else -1,
                                    now=now,
                                )
                            else:
                                attachment.set_theme(
                                    _cycle(
                                        COLOR_SCHEMES,
                                        attachment.theme,
                                        1 if key == "t" else -1,
                                    ),
                                    now,
                                )

                        record_mutation(
                            (
                                "pane",
                                focused,
                                "attachment-style" if key in {"s", "S"} else "attachment-theme",
                            ),
                            adjust_attachment,
                        )
                    elif _adjustment_key_supported(
                        _pane_display_options(pane).chart.kind,
                        adjustment_page,
                        key,
                        chart=_pane_display_options(pane).chart,
                    ):
                        component = pane.component
                        base = component.candidate
                        if key in {"d", "D"} and pane.ranking_search.query:
                            pane.ranking_search.density_notice = translator.text(
                                "status.ranking_search_density_locked"
                            )
                            paint()
                            continue
                        updated = adjust_standalone(base, key)
                        if updated != base:
                            data_affecting = (
                                historical_replacement_required(base, updated)
                                if isinstance(component, HistoricalChartComponent)
                                else (
                                    isinstance(base.chart, MonitorConfig)
                                    and isinstance(updated.chart, MonitorConfig)
                                    and (
                                        base.chart.by != updated.chart.by
                                        or base.chart.filters != updated.chart.filters
                                    )
                                )
                            )

                            def apply_adjustment(
                                pane: TuiChartPane = pane,
                                component: HistoricalChartComponent | MonitorComponent = component,
                                base: StandaloneLaunch = base,
                                updated: StandaloneLaunch = updated,
                                data_affecting: bool = data_affecting,
                                pane_index: int = focused,
                            ) -> None:
                                _clear_changes(pane)
                                component.configure(updated, data_affecting=data_affecting)
                                if updated.host.interval != base.host.interval:
                                    pane.scheduler.rebuild(
                                        updated.host.interval,
                                        now=time.monotonic(),
                                    )
                                if data_affecting:
                                    refresh(
                                        pane_index,
                                        trigger=LifecycleTrigger.CONFIGURATION,
                                    )
                                elif (
                                    isinstance(component, HistoricalChartComponent)
                                    and component.missing_comparison_coverage().intervals
                                ):
                                    refresh(
                                        pane_index,
                                        trigger=LifecycleTrigger.CONFIGURATION,
                                        data_affecting=False,
                                    )

                            record_mutation(
                                ("pane", focused, "configuration", key), apply_adjustment
                            )
                    paint()
                    continue
                if adjustment_mode == "global":
                    if key in {"\r", "\n", "\x1b"}:
                        end_adjustment()
                    elif key in {"t", "T"}:

                        def cycle_theme() -> None:
                            nonlocal dashboard_theme
                            dashboard_theme = _cycle(
                                COLOR_SCHEMES, dashboard_theme, 1 if key == "t" else -1
                            )
                            _set_header_theme(header, dashboard_theme)

                        record_mutation(("dashboard", "theme"), cycle_theme)
                    elif key in {"s", "S"}:

                        def cycle_style() -> None:
                            nonlocal dashboard_style, divider_style, frame_style
                            dashboard_style = _cycle(
                                DASHBOARD_STYLES, dashboard_style, 1 if key == "s" else -1
                            )
                            divider_style, frame_style = _dashboard_structure(dashboard_style)

                        record_mutation(("dashboard", "style"), cycle_style)
                    elif key == "H":

                        def cycle_header() -> None:
                            nonlocal header_style
                            header_style = _cycle(
                                ("hidden", "compact", "banner", "panel"), header_style, 1
                            )
                            if header_style != "hidden" and header.summary_period != "none":
                                required = required_summary_coverage(
                                    local_today(), header.summary_period
                                )
                                if header.token_enabled and any(
                                    not header.coverage.covers(item) for item in required.intervals
                                ):
                                    refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
                                refresh_custom_summaries(trigger=LifecycleTrigger.CONFIGURATION)

                        record_mutation(("header", "style"), cycle_header)
                    elif key in {"p", "P"}:

                        def cycle_summary() -> None:
                            next_summary = _cycle_header_summary(
                                header.summary_period, step=1 if key == "p" else -1
                            )
                            header.summary_period = next_summary
                            header.generation += 1
                            header.lifecycle.detach_active()
                            _invalidate_custom_dashboard_summaries(header)
                            if header_style != "hidden" and next_summary != "none":
                                required = required_summary_coverage(local_today(), next_summary)
                                if header.token_enabled and any(
                                    not header.coverage.covers(item) for item in required.intervals
                                ):
                                    refresh_header(trigger=LifecycleTrigger.CONFIGURATION)
                                refresh_custom_summaries(trigger=LifecycleTrigger.CONFIGURATION)

                        record_mutation(("header", "summary"), cycle_summary)
                    elif key == "z":
                        try:
                            shortcut = _choose_layout_shortcut(
                                screen,
                                translator,
                                decoder,
                                height=get_terminal_size().lines,
                                current=active_layout or active_grid,
                                pane_count=len(panes),
                                read_input=lambda: raise_if_interrupt(
                                    read_adjustment_event(decoder)
                                ),
                            )
                        except AdjustmentTimeout:
                            end_adjustment()
                            paint()
                            continue
                        if shortcut is not None:
                            resolved = _LAYOUT_SHORTCUT_VALUES[shortcut]

                            def choose_layout() -> None:
                                nonlocal \
                                    active_grid, \
                                    active_layout, \
                                    column_weights, \
                                    row_weights, \
                                    grid_error
                                if shortcut in {"wide", "narrow", "all"}:
                                    active_grid = resolved
                                    active_layout = None
                                else:
                                    active_layout = resolved
                                column_weights = None
                                row_weights = None
                                grid_error = None

                            record_mutation(("layout", "topology"), choose_layout)
                    elif key == "Z":
                        grid_draft = ""
                        grid_error = None
                    else:
                        continue
                    paint()
                    continue
                if body_view != "chart" and key in {"\x1b[A", "\x1b[B", "\x1b[H", "e"}:
                    offset = next_text_offset(
                        key,
                        offset=dashboard_text_offset,
                        line_count=dashboard_text_line_count,
                        visible_rows=dashboard_text_visible_rows,
                    )
                    assert offset is not None
                    dashboard_text_offset = offset
                    paint(force=True)
                    continue
                if body_view == "chart" and key == "r":
                    manual_refresh_operations.clear()
                    for index in range(len(panes)):
                        if refresh(
                            index,
                            trigger=LifecycleTrigger.MANUAL,
                            replace_active=True,
                        ):
                            pane = panes[index]
                            if (
                                isinstance(pane, (TuiChartPane, TuiCustomPane))
                                and pane.lifecycle.active is not None
                            ):
                                manual_refresh_operations.add(pane.lifecycle.active)
                    if refresh_header(
                        trigger=LifecycleTrigger.MANUAL,
                        replace_active=True,
                    ):
                        operation = header.lifecycle.active
                        if operation is not None:
                            manual_refresh_operations.add(operation)
                    manual_refresh_operations.update(
                        refresh_custom_summaries(
                            trigger=LifecycleTrigger.MANUAL,
                            replace_active=True,
                        )
                    )
                    paint(force=True)
                elif key == "\x10" and body_view == "chart":
                    open_preset_manager()
                    paint()
                    continue
                elif key == "\x13" and body_view == "chart":
                    open_preset_manager(save=True)
                    paint()
                    continue
                elif key in {"v", "V"}:

                    def cycle_dashboard_view() -> None:
                        nonlocal body_view
                        body_view = cycle_dashboard_body_view(
                            body_view, step=1 if key == "v" else -1
                        )

                    record_mutation(("dashboard", "view"), cycle_dashboard_view)
                elif key in {"y", "Y"} and body_view != "chart":
                    copy_feedback.show(
                        translator.text(
                            "status.command_copied"
                            if copy_command(full_dashboard_command())
                            else "status.command_copy_failed"
                        )
                    )
                elif key == "\t":
                    continue
                elif key == "d" and body_view == "chart":
                    focused = None
                    adjustment_mode = "global"
                    adjustment_page = "quick"
                    adjustment_timer = AdjustmentIdleTimer()
                elif key == "m" and body_view == "chart":
                    focused = _adjustment_target(focused, key, len(panes))
                    adjustment_mode = "pane" if focused is not None else None
                    adjustment_page = "quick"
                    adjustment_timer = AdjustmentIdleTimer() if focused is not None else None
                else:
                    continue
                paint()
    except KeyboardInterrupt:
        return 0
    finally:
        for pane in panes:
            _shutdown_pane(pane)
        for summary in tuple(header.custom_summaries.values()):
            summary.scheduler.shutdown()
            summary.lifecycle.shutdown()
        header.scheduler.shutdown()
        header.lifecycle.shutdown()
        runtime.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        screen.finish()
        set_screen_cursor_visible(True)
