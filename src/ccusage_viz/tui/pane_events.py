from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import AdjustmentTimeout
from ccusage_viz.animate import (
    cycle_animation_style,
)
from ccusage_viz.animation import AnimationSessionState, cycle_monitor_attachment
from ccusage_viz.command_copy import copy_command
from ccusage_viz.custom_component import CustomHistoricalComponent, custom_date_summary_supported
from ccusage_viz.custom_filter_draft import run_custom_filter_editor
from ccusage_viz.custom_models import CustomChartCapability
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.data_view import body_view_copy_kind, cycle_body_view
from ccusage_viz.filter_draft import discover_filter_choices, run_filter_editor
from ccusage_viz.historical_component import (
    HistoricalChartComponent,
    historical_replacement_required,
)
from ccusage_viz.lifecycle import LifecycleTrigger
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import (
    CustomChartConfig,
    MonitorConfig,
    StandaloneLaunch,
    adjust_custom_chart,
    adjust_standalone,
    is_monitor_ranking_style,
    is_v2_custom_ranking,
    replace_chart_filters,
)
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import compose_frame
from ccusage_viz.text_viewport import next_text_offset
from ccusage_viz.tui.adjustments import (
    _adjustment_key_supported,
    _adjustment_target,
    _adjustment_target_page,
    _animation_adjustment_target_page,
)
from ccusage_viz.tui.controls import _cycle
from ccusage_viz.tui.custom_adjustments import (
    _adjust_custom_monitor_chart,
    _custom_capability,
    _custom_pane_adjustment_keys,
    _custom_period_adjustment_chart,
    _custom_period_adjustment_target,
    _custom_runtime_filters,
    _custom_top_refresh_required,
    _cycle_custom_grouping,
    _cycle_custom_monitor_window,
    _cycle_custom_partitioning,
)
from ccusage_viz.tui.custom_rendering import _pane_copy_payload
from ccusage_viz.tui.datasets.modal import (
    open_dataset_modal,
)
from ccusage_viz.tui.history import (
    record_mutation,
)
from ccusage_viz.tui.input import (
    end_adjustment,
    raise_if_interrupt,
    read_adjustment_event,
)
from ccusage_viz.tui.layout import _grid_for_pane_count
from ccusage_viz.tui.models import (
    OverlayEditorState,
    OverlayHistoryState,
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    _pane_display_options,
)
from ccusage_viz.tui.painting import adjust_pane_weight, paint, pane_terminal
from ccusage_viz.tui.pane_lifecycle import _clear_changes, _shutdown_pane
from ccusage_viz.tui.queries import (
    pane_includes_projects,
    pane_records,
    refresh,
)
from ccusage_viz.tui.session import TuiSession
from ccusage_viz.tui_input import (
    KeyEvent,
    MouseEvent,
    PasteEvent,
)


def handle_pane_adjustment(
    session: TuiSession, event: object, key: object, *, now: float
) -> None:
    if key is None:
        return
    if key in {'\r', '\n', '\x1b'}:
        end_adjustment(session)
        paint(session)
        return
    assert session.focused is not None
    pane = session.panes[session.focused]
    focused_index = session.focused
    if isinstance(pane, TuiAnimationPane):
        if key == 'a':
            session.adjustment_page = 'advanced' if session.adjustment_page == 'quick' else 'quick'
        else:
            target_page = _animation_adjustment_target_page(session.adjustment_page, key)
            if target_page is not None:
                session.adjustment_page = target_page
        if key == 'a':
            paint(session)
            return
        animation_pane = pane
        if session.adjustment_page == 'quick' and key in {'p', 'P'}:
            record_mutation(session, ('pane', session.focused, 'overlay-position'), lambda pane=animation_pane: pane.overlay.cycle_position(1 if key == 'p' else -1))
        elif session.adjustment_page == 'quick' and key in {'t', 'T'}:
            record_mutation(session, ('pane', session.focused, 'theme'), lambda pane=animation_pane, now=now: pane.session.set_theme(_cycle(COLOR_SCHEMES, pane.session.theme, 1 if key == 't' else -1), now))
        elif session.adjustment_page == 'quick' and key in {'s', 'S'}:
            record_mutation(session, ('pane', session.focused, 'style'), lambda pane=animation_pane, now=now: cycle_animation_style(pane.session, target='pane', step=1 if key == 's' else -1, now=now))
        elif session.adjustment_page == 'advanced' and key == '\x1b[A':
            record_mutation(session, ('pane', session.focused, 'overlay-offset'), lambda pane=animation_pane: pane.overlay.adjust_offset(dy=-1))
        elif session.adjustment_page == 'advanced' and key == '\x1b[B':
            record_mutation(session, ('pane', session.focused, 'overlay-offset'), lambda pane=animation_pane: pane.overlay.adjust_offset(dy=1))
        elif session.adjustment_page == 'advanced' and key == '\x1b[C':
            record_mutation(session, ('pane', session.focused, 'overlay-offset'), lambda pane=animation_pane: pane.overlay.adjust_offset(dx=1))
        elif session.adjustment_page == 'advanced' and key == '\x1b[D':
            record_mutation(session, ('pane', session.focused, 'overlay-offset'), lambda pane=animation_pane: pane.overlay.adjust_offset(dx=-1))
        elif session.adjustment_page == 'advanced' and key == '0':
            record_mutation(session, ('pane', session.focused, 'overlay-offset'), lambda pane=animation_pane: pane.overlay.reset_offset())
        elif session.adjustment_page == 'advanced' and key == 'i':
            record_mutation(session, ('pane', session.focused, 'overlay-interval'), lambda pane=animation_pane, now=now: pane.overlay.cycle_interval(now=now) and None)
        elif session.adjustment_page == 'advanced' and key == 'L':
            session.overlay_history = OverlayHistoryState(session.focused)
        elif session.adjustment_page == 'advanced' and key == 'e':
            session.overlay_editor = OverlayEditorState(session.focused, 'command' if animation_pane.overlay.config.command is not None else 'text', animation_pane.overlay.text_draft, animation_pane.overlay.command_draft)
        else:
            now = None
        if now is not None:
            paint(session)
            return
    if isinstance(pane, TuiCustomPane) and key in {'v', 'V'}:
        record_mutation(session, ('pane', focused_index, 'view'), lambda pane=pane: setattr(pane, 'body_view', cycle_body_view(pane.body_view, step=1 if key == 'v' else -1)))
        paint(session)
        return
    if isinstance(pane, TuiCustomPane) and (key in {'a', 'f'} or key in _custom_pane_adjustment_keys(pane, session.adjustment_page) or key in _custom_pane_adjustment_keys(pane, 'advanced' if session.adjustment_page == 'quick' else 'quick') or (key in {'g', 'G'} and pane.component.candidate.kind == 'ranking' and isinstance((capability := _custom_capability(pane)), CustomChartCapability) and (capability.partition_by is not None))):
        if key == 'a':
            session.adjustment_page = 'advanced' if session.adjustment_page == 'quick' else 'quick'
            paint(session)
            return
        current_page_keys = _custom_pane_adjustment_keys(pane, session.adjustment_page)
        other_page = 'advanced' if session.adjustment_page == 'quick' else 'quick'
        other_page_keys = _custom_pane_adjustment_keys(pane, other_page)
        if key not in current_page_keys and key in other_page_keys:
            session.adjustment_page = other_page
        component = pane.component
        base = component.candidate
        capability = _custom_capability(pane)
        if key in {'d', 'D'} and pane.ranking_search.query:
            pane.ranking_search.density_notice = session.translator.text('status.ranking_search_density_locked')
            paint(session)
            return

        def apply_custom_query(config: CustomChartConfig, *, mutation: str, pane: TuiCustomPane=pane, pane_index: int=focused_index) -> None:
            pane.component.configure(config, data_affecting=True)
            if pane.summary is not None and (not custom_date_summary_supported(config)):
                pane.summary.invalidate()
            refresh(session, pane_index, trigger=LifecycleTrigger.CONFIGURATION, data_affecting=False, summary_affecting=mutation in {'granularity', 'filters', 'source'})
        if key in {'m', 'M'} and isinstance(component, (CustomHistoricalComponent, CustomMonitorComponent)):
            descriptor = component.v2_descriptor
            metric_id = component.candidate.metric_id
            if descriptor is None or metric_id is None:
                session.copy_feedback.show(session.translator.text('status.custom_metric_no_alternative'))
                return
            from ccusage_viz.custom_metric_switching import cycle_switch_metric
            target = cycle_switch_metric(descriptor, current_metric_id=metric_id, kind=base.kind, step=1 if key == 'm' else -1)
            if target is None:
                session.copy_feedback.show(session.translator.text('status.custom_metric_no_alternative'))
                return
            component.begin_metric_switch(replace(base, metric_id=target.id), now=datetime.now().astimezone(), timezone=session.options.host.timezone or 'UTC')
            refresh(session, focused_index, trigger=LifecycleTrigger.CONFIGURATION, data_affecting=False, summary_affecting=True)
        elif key == 'L':
            session.custom_logs_pane = focused_index
        elif isinstance(component, CustomMonitorComponent) and session.adjustment_page == 'advanced' and (pane.attachment is not None) and is_monitor_ranking_style(base.presentation.style) and (key in {'s', 'S', 't', 'T'}):
            attachment = pane.attachment

            def adjust_custom_attachment(pane: TuiCustomPane=pane, attachment: AnimationSessionState=attachment) -> None:
                now = time.monotonic()
                if key in {'s', 'S'}:
                    pane.attachment_enabled = cycle_monitor_attachment(attachment, enabled=pane.attachment_enabled, step=1 if key == 's' else -1, now=now)
                else:
                    attachment.set_theme(_cycle(COLOR_SCHEMES, attachment.theme, 1 if key == 't' else -1), now)
            record_mutation(session, ('pane', focused_index, 'custom-monitor-animation'), adjust_custom_attachment)
        elif isinstance(component, CustomMonitorComponent) and key in {'d', 's', 'S', 't', 'T', 'l', '+', '=', '-', '_', 'o'}:
            updated = _adjust_custom_monitor_chart(base, key, aggregation=component.aggregation)
            if updated != base:
                record_mutation(session, ('pane', focused_index, 'custom-monitor-presentation'), lambda config=updated: component.configure(config, data_affecting=False))
        elif isinstance(component, CustomMonitorComponent) and key == 'w':
            if base.presentation.style == 'cumulative-bars':
                record_mutation(session, ('pane', focused_index, 'custom-monitor-distribution-day'), component.toggle_distribution_day_window)
            else:
                window = _cycle_custom_monitor_window(component.display_window_seconds)
                record_mutation(session, ('pane', focused_index, 'custom-monitor-window'), lambda window=window: component.configure_display_window(window))
        elif key in {'p', 'P'}:
            period_base = _custom_period_adjustment_target(component) if isinstance(component, CustomHistoricalComponent) else _custom_period_adjustment_chart(base, capability)
            switch_anchor = component.switch_anchor if isinstance(component, CustomHistoricalComponent) and component.switch_target_config is not None else None
            updated = adjust_custom_chart(period_base, key, now=switch_anchor or datetime.now().astimezone(), timezone=session.options.host.timezone or 'UTC')
            if updated != period_base:
                if isinstance(component, CustomHistoricalComponent) and component.switch_target_config is not None:

                    def update_pending_metric_period(config: CustomChartConfig=updated, component: CustomHistoricalComponent=component, pane_index: int=focused_index) -> None:
                        component.begin_metric_switch(config, now=component.switch_anchor, timezone=session.options.host.timezone or 'UTC')
                        refresh(session, pane_index, trigger=LifecycleTrigger.CONFIGURATION, data_affecting=False, summary_affecting=True)
                    record_mutation(session, ('pane', focused_index, 'custom-period'), update_pending_metric_period)
                else:
                    record_mutation(session, ('pane', focused_index, 'custom-period'), lambda config=updated: apply_custom_query(config, mutation='period'))
            elif period_base.metric_periods:
                session.copy_feedback.show(session.translator.text('status.custom_period_restricted'))
        elif key in {'s', 'S'} and base.kind == 'ranking' and (session.adjustment_page == 'advanced'):
            modes = ('compact', 'space', 'line', 'dashed')
            position = modes.index(pane.ranking_item_spacing)
            pane.ranking_item_spacing = modes[(position + (1 if key == 's' else -1)) % len(modes)]
        elif key in {'g', 'G'} and base.kind == 'ranking' and isinstance(capability, CustomChartCapability) and (capability.partition_by is not None):
            updated = _cycle_custom_partitioning(base, capability.partition_by, capability.group_by, step=1 if key == 'g' else -1)
            if updated != base:
                record_mutation(session, ('pane', focused_index, 'custom-partition'), lambda config=updated: apply_custom_query(config, mutation='partition'))
            else:
                session.copy_feedback.show(session.translator.text('status.custom_partition_restricted'))
        elif key in {'g', 'G'} and (not is_v2_custom_ranking(base)) and (capability is not None) and capability.granularities:
            values = capability.granularities
            current = base.granularity if base.granularity in values else values[0]
            direction = 1 if key == 'g' else -1
            updated = replace(base, granularity=_cycle(values, current, direction))
            if updated != base:
                record_mutation(session, ('pane', focused_index, 'custom-granularity'), lambda config=updated: apply_custom_query(config, mutation='granularity'))
        elif key in {'b', 'B'} and base.kind != 'calendar' and (capability is not None):
            updated = _cycle_custom_grouping(base, capability.group_by, step=1 if key == 'b' else -1)
            if updated != base:
                record_mutation(session, ('pane', focused_index, 'custom-group'), lambda config=updated: apply_custom_query(config, mutation='group'))
            else:
                session.copy_feedback.show(session.translator.text('status.custom_group_restricted'))
        elif key == 'f' and capability is not None and _custom_runtime_filters(component):
            filters = _custom_runtime_filters(component)
            size = get_terminal_size()
            first_filter_frame = True

            def paint_custom_filter_editor(body: str, editor_controls: str) -> None:
                nonlocal first_filter_frame
                session.screen.paint(compose_frame(body, session.translator.text('label.adjust_filters'), editor_controls, height=size.lines), force=first_filter_frame)
                first_filter_frame = False

            def read_custom_filter_key() -> KeyEvent | MouseEvent | PasteEvent | None:
                editor_event = raise_if_interrupt(session, read_adjustment_event(session, session.decoder))
                if isinstance(editor_event, MouseEvent):
                    return replace(editor_event, y=editor_event.y - 1)
                return editor_event if isinstance(editor_event, (KeyEvent, PasteEvent)) else None
            try:
                edited = run_custom_filter_editor(base.filters, filters, session.translator, width=size.columns, height=max(0, size.lines - 2), paint=paint_custom_filter_editor, read_key=read_custom_filter_key, color=session.dashboard_theme != 'no-color', color_scheme=session.dashboard_theme)
            except AdjustmentTimeout:
                end_adjustment(session)
                paint(session, force=True)
                return
            paint(session, force=True)
            if edited is not None and edited != base.filters:
                updated = replace(base, filters=edited)
                record_mutation(session, ('pane', focused_index, 'custom-filters'), lambda config=updated: apply_custom_query(config, mutation='filters'))
        elif key == 'f':
            session.copy_feedback.show(session.translator.text('status.custom_filter_unavailable'))
        elif key in {'d', 'D', 't', 'T', 's', 'S', 'k', 'l', 'o', '+', '=', '-', '_'}:
            updated = adjust_custom_chart(base, key)
            if updated != base:

                def apply_custom_presentation(pane: TuiCustomPane=pane, config: CustomChartConfig=updated) -> None:
                    if isinstance(pane.component, CustomHistoricalComponent) and _custom_top_refresh_required(pane.component, config):
                        apply_custom_query(config, mutation='top')
                    else:
                        pane.component.configure(config, data_affecting=False)
                record_mutation(session, ('pane', focused_index, 'custom-presentation'), apply_custom_presentation)
        paint(session)
        return
    error_body = isinstance(pane, TuiCustomPane) and pane.body_view == 'chart' and (pane.component.error is not None) and (isinstance(pane.component, CustomMonitorComponent) or pane.component.model is None)
    if isinstance(pane, (TuiChartPane, TuiCustomPane)) and (pane.body_view != 'chart' or error_body):
        handled_body_key = False
        if key in {'\x1b[A', '\x1b[B', '\x1b[H', 'e'}:
            offset = next_text_offset(key, offset=pane.error_offset if error_body else pane.text_offsets.get(pane.body_view, 0), line_count=pane.error_line_count if error_body else pane.text_line_counts.get(pane.body_view, 0), visible_rows=pane.error_visible_rows if error_body else pane.text_visible_rows.get(pane.body_view, 0))
            assert offset is not None
            if error_body:
                pane.error_offset = offset
            else:
                pane.text_offsets[pane.body_view] = offset
            handled_body_key = True
        elif key in {'v', 'V'}:
            text_pane = pane
            record_mutation(session, ('pane', session.focused, 'view'), lambda pane=text_pane: setattr(pane, 'body_view', cycle_body_view(pane.body_view, step=1 if key == 'v' else -1)))
            handled_body_key = True
        elif key in {'y', 'Y'} and body_view_copy_kind(pane.body_view) is not None:
            copy_kind = body_view_copy_kind(pane.body_view)
            assert copy_kind is not None
            copied = copy_command(_pane_copy_payload(pane, session.translator, pane_terminal(session, session.focused), dashboard=session.options))
            session.copy_feedback.show(session.translator.text('status.command_copied' if copied and copy_kind in {'command', 'full-command'} else 'status.data_copied' if copied else 'status.command_copy_failed'))
            handled_body_key = True
        if handled_body_key or not error_body:
            paint(session)
            return
    next_focused = _adjustment_target(session.focused, key, len(session.panes))
    if next_focused != session.focused:
        session.focused = next_focused
        paint(session)
        return
    if key == 'r':
        open_dataset_modal(session, 'replace', focused_index, initial=pane.component.candidate if isinstance(pane, TuiCustomPane) else None)
        paint(session)
        return
    if key in {'N', 'n'}:
        open_dataset_modal(session, 'insert_before' if key == 'N' else 'insert_after', focused_index)
        paint(session)
        return
    if key in {'{', '}', 'J', 'K'}:
        adjust_pane_weight(session, focused_index, axis='column' if key in {'{', '}'} else 'row', delta=1 if key in {'}', 'K'} else -1)
        paint(session)
        return
    if key == '[' and focused_index > 0:

        def move_previous(index: int=focused_index) -> None:
            session.panes[index - 1], session.panes[index] = (session.panes[index], session.panes[index - 1])
            session.focused = index - 1
        record_mutation(session, ('pane', focused_index, 'previous'), move_previous)
        paint(session)
        return
    if key == ']' and focused_index < len(session.panes) - 1:

        def move_next(index: int=focused_index) -> None:
            session.panes[index], session.panes[index + 1] = (session.panes[index + 1], session.panes[index])
            session.focused = index + 1
        record_mutation(session, ('pane', focused_index, 'next'), move_next)
        paint(session)
        return
    if key == 'x' and len(session.panes) > 1:

        def delete(index: int=focused_index) -> None:
            removed = session.panes.pop(index)
            _shutdown_pane(removed)
            session.active_grid = _grid_for_pane_count(session.active_grid, len(session.panes))
            session.focused = min(index, len(session.panes) - 1)
        record_mutation(session, ('pane', focused_index, 'delete'), delete)
        paint(session)
        return
    if not isinstance(pane, TuiChartPane):
        paint(session)
        return
    chart_pane = pane
    if key == 'a':
        session.adjustment_page = 'advanced' if session.adjustment_page == 'quick' else 'quick'
    else:
        chart = _pane_display_options(pane).chart
        target_page = _adjustment_target_page(chart.kind, session.adjustment_page, key, chart=chart, attachment_available=isinstance(chart, MonitorConfig) and is_monitor_ranking_style(chart.presentation.style) and (pane.attachment is not None))
        if target_page is not None:
            session.adjustment_page = target_page
    if session.adjustment_page == 'advanced' and key == 'f':
        component = pane.component
        base = component.candidate
        size = get_terminal_size()
        editor_width = size.columns
        editor_height = size.lines

        def paint_filter_editor(body: str, editor_controls: str, *, height: int=editor_height) -> None:
            session.screen.paint(compose_frame(body, session.translator.text('status.tui_adjust_history'), editor_controls, height=height))

        def read_filter_key() -> str | None:
            editor_event = raise_if_interrupt(session, read_adjustment_event(session, session.decoder))
            return editor_event.value if isinstance(editor_event, KeyEvent) else None
        try:
            edited = run_filter_editor(base.chart.filters, discover_filter_choices(pane_records(session, pane), base.chart.filters, include_projects=pane_includes_projects(session, pane)), session.translator, width=editor_width, paint=paint_filter_editor, read_key=read_filter_key)
        except AdjustmentTimeout:
            end_adjustment(session)
            paint(session)
            return
        if edited is not None and edited != base.chart.filters:

            def apply_filters(pane: TuiChartPane=pane, component: HistoricalChartComponent | MonitorComponent=component, base: StandaloneLaunch=base, edited=edited, pane_index: int=session.focused) -> None:
                _clear_changes(pane)
                component.configure(replace_chart_filters(base, edited), data_affecting=True)
                refresh(session, pane_index, trigger=LifecycleTrigger.CONFIGURATION, data_affecting=False)
            record_mutation(session, ('pane', session.focused, 'filters'), apply_filters)
    elif key in {'v', 'V'}:
        record_mutation(session, ('pane', session.focused, 'view'), lambda pane=chart_pane: setattr(pane, 'body_view', cycle_body_view(pane.body_view, step=1 if key == 'v' else -1)))
    elif session.adjustment_page == 'advanced' and chart_pane.attachment is not None and isinstance(_pane_display_options(chart_pane).chart, MonitorConfig) and is_monitor_ranking_style(_pane_display_options(chart_pane).chart.presentation.style) and (key in {'t', 'T', 's', 'S'}):
        attachment = chart_pane.attachment
        assert attachment is not None

        def adjust_attachment(pane: TuiChartPane=chart_pane, attachment: AnimationSessionState=attachment) -> None:
            now = time.monotonic()
            if key in {'s', 'S'}:
                pane.attachment_enabled = cycle_monitor_attachment(attachment, enabled=pane.attachment_enabled, step=1 if key == 's' else -1, now=now)
            else:
                attachment.set_theme(_cycle(COLOR_SCHEMES, attachment.theme, 1 if key == 't' else -1), now)
        record_mutation(session, ('pane', session.focused, 'attachment-style' if key in {'s', 'S'} else 'attachment-theme'), adjust_attachment)
    elif _adjustment_key_supported(_pane_display_options(pane).chart.kind, session.adjustment_page, key, chart=_pane_display_options(pane).chart):
        component = pane.component
        base = component.candidate
        if key in {'d', 'D'} and pane.ranking_search.query:
            pane.ranking_search.density_notice = session.translator.text('status.ranking_search_density_locked')
            paint(session)
            return
        updated = adjust_standalone(base, key)
        if updated != base:
            data_affecting = historical_replacement_required(base, updated) if isinstance(component, HistoricalChartComponent) else isinstance(base.chart, MonitorConfig) and isinstance(updated.chart, MonitorConfig) and (base.chart.by != updated.chart.by or base.chart.filters != updated.chart.filters)

            def apply_adjustment(pane: TuiChartPane=pane, component: HistoricalChartComponent | MonitorComponent=component, base: StandaloneLaunch=base, updated: StandaloneLaunch=updated, data_affecting: bool=data_affecting, pane_index: int=session.focused) -> None:
                _clear_changes(pane)
                component.configure(updated, data_affecting=data_affecting)
                if updated.host.interval != base.host.interval:
                    pane.scheduler.rebuild(updated.host.interval, now=time.monotonic())
                if data_affecting:
                    refresh(session, pane_index, trigger=LifecycleTrigger.CONFIGURATION)
                elif isinstance(component, HistoricalChartComponent) and component.missing_comparison_coverage().intervals:
                    refresh(session, pane_index, trigger=LifecycleTrigger.CONFIGURATION, data_affecting=False)
            record_mutation(session, ('pane', session.focused, 'configuration', key), apply_adjustment)
    paint(session)
    return
