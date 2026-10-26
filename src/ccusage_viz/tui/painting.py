from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.tui.session import TuiSession

import time
from shutil import get_terminal_size

from ccusage_viz.animation_host.overlay_editor import _editor_viewport, _overlay_editor_controls
from ccusage_viz.animation_overlay import OverlayPlacement, render_history_table
from ccusage_viz.command_copy import format_full_command_display
from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.dashboard_layout import (
    MIN_PANE_HEIGHT,
    MIN_PANE_WIDTH,
    adjust_weight,
    layout_bands,
    reconcile_weights,
    resolve_pane_layout,
)
from ccusage_viz.dashboard_layout import PaneLayout as ResolvedPaneLayout
from ccusage_viz.formatting import clip_width
from ccusage_viz.history_selection import reconcile_history_selection
from ccusage_viz.render.base import RenderContext
from ccusage_viz.terminal import Terminal, compose_frame
from ccusage_viz.terminal_ui import controls_line
from ccusage_viz.terminal_ui import notice_lines as format_notice_lines
from ccusage_viz.text_viewport import render_text_viewport
from ccusage_viz.tui.custom_adjustments import _custom_top_limit_notice
from ccusage_viz.tui.header import _header_lines
from ccusage_viz.tui.layout import _compose_dashboard_overlays, _compose_resolved_panes
from ccusage_viz.tui.models import (
    DashboardOverlayPlacement,
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    TuiEmptyPane,
    _pane_display_options,
)
from ccusage_viz.tui.rendering import (
    _append_monitor_attachment,
    _local_pane_content,
    _pane_animation_deadline,
    _pane_render,
)
from ccusage_viz.tui_preset_manager import render_preset_manager


def effective_topology(session: TuiSession) -> tuple[int, int]:
    draft = getattr(session, "layout_draft", None)
    if draft is not None:
        return draft.columns, draft.spotlight
    return session.columns, session.spotlight


def grid_geometry(
    session: TuiSession, size_columns: int, size_lines: int, header_rows: int, status_rows: int
) -> ResolvedPaneLayout:
    from ccusage_viz.tui.help import controls, notices

    grid_height = max(
        3, size_lines - len(controls(session)) - len(notices(session)) - header_rows - status_rows
    )
    columns, spotlight = effective_topology(session)
    bands = layout_bands(columns=columns, spotlight=spotlight, pane_count=len(session.panes))
    accepted_bands = layout_bands(
        columns=session.columns, spotlight=session.spotlight, pane_count=len(session.panes)
    )
    resolved_column_weights = reconcile_weights(
        session.column_weights if bands.columns == accepted_bands.columns else None,
        bands.columns,
    )
    resolved_row_weights = reconcile_weights(
        session.row_weights if bands.rows == accepted_bands.rows else None,
        bands.rows,
    )
    return resolve_pane_layout(
        columns=columns,
        spotlight=spotlight,
        pane_count=len(session.panes),
        width=size_columns,
        height=grid_height,
        divider_style=session.divider_style,
        column_weights=resolved_column_weights,
        row_weights=resolved_row_weights,
    )


def adjust_pane_weight(session: TuiSession, pane_index: int, *, axis: str, delta: int) -> bool:
    from ccusage_viz.tui.history import record_mutation

    """Adjust one Dashboard layout band and retain it in undo history."""
    size = get_terminal_size()
    header_rows = len(
        _header_lines(
            session.header,
            session.header_style,
            session.translator,
            Terminal(
                size.columns, 4, session.dashboard_theme != "no-color", session.options.host.ascii
            ),
            session.last_successful_update,
        )
    )
    layout = grid_geometry(session, size.columns, size.lines, header_rows, 0)
    slot = layout.topology.slot(pane_index)

    def can_adjust_axis(
        *, axis: str, weights: tuple[int, ...], index: int
    ) -> tuple[bool, tuple[int, ...]]:
        candidate = adjust_weight(weights, index, delta)
        candidate_layout = resolve_pane_layout(
            columns=session.columns,
            spotlight=session.spotlight,
            pane_count=len(session.panes),
            width=layout.width,
            height=layout.height,
            divider_style=session.divider_style,
            column_weights=candidate
            if axis == "column"
            else reconcile_weights(session.column_weights, layout.topology.columns),
            row_weights=candidate
            if axis == "row"
            else reconcile_weights(session.row_weights, layout.topology.rows),
        )
        before = layout.column_sizes if axis == "column" else layout.row_sizes
        after = candidate_layout.column_sizes if axis == "column" else candidate_layout.row_sizes
        return (after != before, candidate)

    if axis == "column":
        weights = reconcile_weights(session.column_weights, layout.topology.columns)
        can_adjust, candidate = can_adjust_axis(axis="column", weights=weights, index=slot.column)
        if not can_adjust:
            return False

        def adjust_column() -> None:
            session.column_weights = candidate

        return record_mutation(session, ("layout", "column-weight", slot.column), adjust_column)
    weights = reconcile_weights(session.row_weights, layout.topology.rows)
    can_adjust, candidate = can_adjust_axis(axis="row", weights=weights, index=slot.row)
    if not can_adjust:
        return False

    def adjust_row() -> None:
        session.row_weights = candidate

    return record_mutation(session, ("layout", "row-weight", slot.row), adjust_row)


def pane_terminal(session: TuiSession, index: int) -> Terminal:
    size = get_terminal_size()
    header_rows = len(
        _header_lines(
            session.header,
            session.header_style,
            session.translator,
            Terminal(
                size.columns, 4, session.dashboard_theme != "no-color", session.options.host.ascii
            ),
            session.last_successful_update,
        )
    )
    layout = grid_geometry(session, size.columns, size.lines, header_rows, 0)
    rect = layout.pane(index)
    framed = session.frame_style != "none" or index == session.focused
    pane = session.panes[index]
    if isinstance(pane, TuiAnimationPane):
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            pane.session.theme != "no-color",
            session.options.host.ascii,
        )
    if isinstance(pane, TuiCustomPane):
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            pane.component.candidate.presentation.theme != "no-color",
            session.options.host.ascii,
        )
    if isinstance(pane, TuiEmptyPane):
        return Terminal(
            max(1, rect.width - 2 if framed else rect.width),
            max(1, rect.height - 2 if framed else rect.height),
            session.dashboard_theme != "no-color",
            session.options.host.ascii,
        )
    pane_options = _pane_display_options(pane)
    return Terminal(
        max(1, rect.width - 2 if framed else rect.width),
        max(1, rect.height - 2 if framed else rect.height),
        pane_options.chart.presentation.theme != "no-color",
        pane_options.host.ascii,
    )


def paint(session: TuiSession, *, force: bool = False, animation_only: bool = False) -> None:
    from ccusage_viz.tui.datasets.modal import _paint_dataset_modal
    from ccusage_viz.tui.help import controls, help_frame, notices
    from ccusage_viz.tui.history import full_dashboard_command, preset_catalog
    from ccusage_viz.tui.pointer import capture_custom_ranking_copy_rows

    session.displayed_layout = None
    if session.dataset_modal is None:
        session.chooser_overlay = None
    else:
        _paint_dataset_modal(session)
    size = get_terminal_size()
    if force or not animation_only or (size.columns, size.lines) != session.last_size:
        session.pane_render_cache.clear()
    paint_now = time.monotonic()
    if session.preset_manager is not None:
        frame = render_preset_manager(
            session.preset_manager,
            preset_catalog(session),
            session.translator,
            Terminal(
                size.columns,
                size.lines,
                session.dashboard_theme != "no-color",
                session.options.host.ascii,
            ),
        )
        session.screen.paint(frame, force=force, atomic=True)
        session.help_was_active = False
        return
    atomic = (
        session.help_overlay is not None
        or session.help_was_active
        or any(isinstance(pane, TuiAnimationPane) for pane in session.panes)
    )
    if session.help_overlay is not None:
        session.last_size = (size.columns, size.lines)
        session.screen.paint(
            help_frame(session, size.columns, size.lines), force=force, atomic=atomic
        )
        session.help_was_active = True
        return
    session.last_size = (size.columns, size.lines)
    header_terminal = Terminal(
        size.columns, 4, session.dashboard_theme != "no-color", session.options.host.ascii
    )
    header_lines = _header_lines(
        session.header,
        session.header_style,
        session.translator,
        header_terminal,
        session.last_successful_update,
    )
    status = None
    if session.body_view != "chart":
        control_rows = controls(session)
        notice_rows = notices(session)
        viewport = render_text_viewport(
            format_full_command_display(full_dashboard_command(session), size.columns),
            offset=session.dashboard_text_offset,
            visible_rows=size.lines - len(control_rows) - len(notice_rows),
        )
        session.dashboard_text_offset = viewport.offset
        session.dashboard_text_line_count = viewport.line_count
        session.dashboard_text_visible_rows = viewport.visible_rows
        session.screen.paint(
            compose_frame(viewport.body, status, control_rows, notice_rows, height=size.lines),
            force=force,
            atomic=atomic,
        )
        session.help_was_active = False
        return

    def render_panes(
        layout: ResolvedPaneLayout,
    ) -> tuple[list[str], tuple[DashboardOverlayPlacement, ...]]:
        rendered_panes: list[str] = []
        overlays: list[DashboardOverlayPlacement] = []
        for index, pane in enumerate(session.panes):
            rect = layout.pane(index)
            cell_width = rect.width
            cell_height = rect.height
            if cell_width < MIN_PANE_WIDTH or cell_height < MIN_PANE_HEIGHT:
                rendered_panes.append(
                    clip_width(
                        session.translator.text("status.tui_pane_too_small"), max(0, cell_width)
                    )
                    if cell_width > 0 and cell_height > 0
                    else ""
                )
                continue
            framed = session.frame_style != "none" or index == session.focused
            interior_width = max(1, cell_width - 2 if framed else cell_width)
            interior_height = max(1, cell_height - 2 if framed else cell_height)
            if isinstance(pane, TuiAnimationPane):
                terminal = Terminal(
                    interior_width,
                    interior_height,
                    pane.session.theme != "no-color",
                    session.options.host.ascii,
                )
                color_scheme = pane.session.theme
            elif isinstance(pane, TuiCustomPane):
                terminal = Terminal(
                    interior_width,
                    interior_height,
                    pane.component.candidate.presentation.theme != "no-color",
                    session.options.host.ascii,
                )
                color_scheme = pane.component.candidate.presentation.theme
            elif isinstance(pane, TuiEmptyPane):
                terminal = Terminal(
                    interior_width,
                    interior_height,
                    session.dashboard_theme != "no-color",
                    session.options.host.ascii,
                )
                color_scheme = session.dashboard_theme
            else:
                pane_options = _pane_display_options(pane)
                terminal = Terminal(
                    interior_width,
                    interior_height,
                    pane_options.chart.presentation.theme != "no-color",
                    pane_options.host.ascii,
                )
                color_scheme = pane_options.chart.presentation.theme
            if session.chooser_overlay is not None and session.chooser_overlay[0] == index:
                rendered_panes.append(session.chooser_overlay[1])
                continue
            if session.overlay_editor is not None and session.overlay_editor.pane_index == index:
                editor_controls = _overlay_editor_controls(
                    session.translator, width=interior_width, color=terminal.color, dashboard=True
                )
                rendered_panes.append(
                    "\n".join(
                        compose_frame(
                            _editor_viewport(
                                session.overlay_editor.draft,
                                session.overlay_editor.cursor,
                                interior_width,
                                cursor_visible=int(time.monotonic() * 2) % 2 == 0,
                            )[0],
                            session.copy_feedback.message
                            or session.translator.text(
                                "status.overlay_editor_mode_title",
                                mode=session.translator.text(
                                    f"status.overlay_editor_mode_{session.overlay_editor.mode}"
                                ),
                            ),
                            editor_controls,
                            height=interior_height,
                        ).rows
                    )
                )
                continue
            if session.custom_logs is not None and session.custom_logs.pane_index == index:
                assert isinstance(pane, TuiCustomPane)
                records = tuple(reversed(pane.logs))
                state = session.custom_logs.table
                visible = max(1, interior_height - 2)
                selected_index = reconcile_history_selection(state, records, visible)
                if selected_index is not None:
                    rows = tuple(
                        f"{'›' if position == selected_index else ' '} "
                        f"{session.translator.text(f'status.custom_log_{record.status}')} "
                        f"{record.timestamp:%H:%M:%S}: {record.detail}"
                        for position, record in enumerate(
                            records[state.offset : state.offset + visible], start=state.offset
                        )
                    )
                else:
                    rows = (session.translator.text("status.custom_logs_empty"),)
                rendered_panes.append(
                    "\n".join(
                        compose_frame(
                            "\n".join(rows),
                            session.translator.text("status.custom_logs_title"),
                            (session.translator.text("status.custom_logs_controls"),),
                            height=interior_height,
                        ).rows
                    )
                )
                continue
            if session.overlay_history is not None and session.overlay_history.pane_index == index:
                assert isinstance(pane, TuiAnimationPane)
                history_table = render_history_table(
                    tuple(pane.overlay.history),
                    session.overlay_history.table,
                    available_width=interior_width,
                    available_height=interior_height - 1,
                    empty=session.translator.text("status.overlay_history_empty"),
                )
                history_controls = controls_line(
                    session.translator.text("status.overlay_history_dashboard_controls"),
                    width=interior_width,
                    color=terminal.color,
                )
                rendered_panes.append(
                    "\n".join(
                        compose_frame(
                            history_table.body, None, (history_controls,), height=interior_height
                        ).rows
                    )
                )
                continue
            scrollbar_expanded = index == session.scrollbar_hovered_pane or (
                session.scrollbar_drag is not None and index == session.scrollbar_drag[0]
            )
            cache_key = (id(pane), rect, terminal, framed, scrollbar_expanded)
            cached = session.pane_render_cache.get(index)
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
                        pane, session.translator, terminal, defer_animation_overlay=True
                    )
                except TypeError as error:
                    if "defer_animation_overlay" not in str(error):
                        raise
                    rendered = _pane_render(pane, session.translator, terminal)
            elif isinstance(pane, TuiCustomPane):
                rendered = _pane_render(
                    pane,
                    session.translator,
                    terminal,
                    dashboard=session.options,
                    scrollbar_hovered=scrollbar_expanded,
                )
            else:
                rendered = _pane_render(pane, session.translator, terminal)
            if isinstance(pane, TuiAnimationPane):
                origin_x = rect.left + (1 if framed else 0)
                origin_y = rect.top + (1 if framed else 0)
                overlays.extend(
                    DashboardOverlayPlacement(
                        index,
                        OverlayPlacement(
                            origin_y + placement.row, origin_x + placement.column, placement.text
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
                (
                    *rendered.notices,
                    *_custom_top_limit_notice(pane, session.translator),
                    *search_notice,
                )
                if isinstance(pane, TuiCustomPane)
                else (*rendered.notices, *search_notice),
                width=interior_width,
                color=terminal.color,
                ascii=terminal.ascii,
                translator=session.translator,
                color_scheme=color_scheme,
            )
            if isinstance(pane, TuiCustomPane) and pane.active_ranking_viewport.active:
                viewport = pane.active_ranking_viewport
                reserved = min(len(local_notices), max(0, interior_height - 3))
                if reserved != viewport.reserved_rows:
                    viewport.reserved_rows = reserved
                    rendered = _pane_render(
                        pane, session.translator, terminal, dashboard=session.options
                    )
            chart = (
                _append_monitor_attachment(
                    pane,
                    rendered.chart,
                    terminal=terminal,
                    reserved_rows=len(local_notices),
                    now=time.monotonic(),
                    translator=session.translator,
                )
                if isinstance(pane, TuiChartPane) and pane.body_view == "chart"
                else rendered.chart
            )
            text_pane = (
                pane if isinstance(pane, (TuiChartPane, TuiAnimationPane, TuiCustomPane)) else None
            )
            error_body = isinstance(text_pane, TuiCustomPane) and rendered.error_body
            fixed_ranking_rows = 0
            scrollable = text_pane is not None and (text_pane.body_view != "chart" or error_body)
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
                and (
                    (text_pane.component.accepted_config or text_pane.component.candidate).kind
                    == "ranking"
                )
            ):
                capture_custom_ranking_copy_rows(
                    session, text_pane, content, fixed_rows=fixed_ranking_rows, framed=framed
                )
            rendered_panes.append(content)
            session.pane_render_cache[index] = (cache_key, content, tuple(overlays[overlay_start:]))
        return (rendered_panes, tuple(overlays))

    layout = grid_geometry(
        session, size.columns, size.lines, len(header_lines), int(status is not None)
    )
    pane_renders, dashboard_overlays = render_panes(layout)
    session.displayed_layout, session.displayed_header_rows = (layout, len(header_lines))
    grid = _compose_resolved_panes(
        pane_renders,
        layout,
        focused=session.focused if session.focused is not None else -1,
        ascii=session.options.host.ascii,
        divider_style=session.divider_style,
        frame_style=session.frame_style,
        shell_context=RenderContext(
            size.columns,
            layout.height,
            session.translator,
            color=session.dashboard_theme != "no-color",
            ascii=session.options.host.ascii,
            color_scheme=session.dashboard_theme,
        ),
    )
    grid = _compose_dashboard_overlays(
        grid,
        layout,
        dashboard_overlays,
        focused=session.focused if session.focused is not None else -1,
    )
    body = "\n".join((*header_lines, grid))
    session.screen.paint(
        compose_frame(body, status, controls(session), notices(session), height=size.lines),
        force=force,
        atomic=atomic,
    )
    session.help_was_active = False
