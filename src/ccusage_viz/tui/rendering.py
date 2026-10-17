from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import cast

from ccusage_viz.animation import AnimationSessionState, last_activity_label
from ccusage_viz.animation_overlay import compose_overlay_row
from ccusage_viz.command_copy import (
    format_command,
    format_full_command,
    format_full_command_display,
    wrap_command,
)
from ccusage_viz.custom_component import CustomHistoricalComponent, custom_date_summary_supported
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.data_view import (
    render_current_monitor_data,
    render_custom_data,
    render_snapshot_data,
)
from ccusage_viz.diagnostics import format_error, transient_query_recovery_lines
from ccusage_viz.errors import UsageError, VizError
from ccusage_viz.historical_component import HistoricalChartComponent
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import Translator
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import (
    DashboardLaunch,
    Filters,
    HistoricalChartConfig,
    MonitorConfig,
    is_monitor_ranking_style,
)
from ccusage_viz.render.base import RenderAudit, RenderContext, audit_row_visible, render_audit
from ccusage_viz.render.custom import render_custom_pending
from ccusage_viz.render.filters import active_filter_summary
from ccusage_viz.render.surfaces import SurfaceControls, dashboard_pane_surface
from ccusage_viz.terminal import Terminal
from ccusage_viz.text_viewport import render_text_viewport, wrap_text_rows
from ccusage_viz.tui.custom_rendering import (
    _append_custom_monitor_attachment,
    _apply_custom_ranking_spacing,
    _custom_render_context,
    _custom_response_warning_notices,
    _render_custom_failure,
    _render_custom_monitor,
    _render_custom_projection,
    _retain_custom_facts_while_pending,
)
from ccusage_viz.tui.models import (
    PaneRender,
    TuiAnimationPane,
    TuiChartPane,
    TuiCustomPane,
    TuiEmptyPane,
    TuiPane,
    _custom_pane_options,
    _pane_display_options,
    _pane_options,
)


def _pane_animation_deadline(pane: TuiPane) -> float | None:
    if isinstance(pane, TuiAnimationPane) and pane.body_view == "chart":
        deadlines = (pane.session.next_deadline, pane.overlay.next_due)
    elif (
        isinstance(pane, (TuiChartPane, TuiCustomPane))
        and pane.body_view == "chart"
        and pane.attachment is not None
    ):
        deadlines = (pane.attachment.next_deadline,)
    else:
        deadlines = ()
    return min((deadline for deadline in deadlines if deadline is not None), default=None)

def _pane_render(
    pane: TuiPane,
    translator: Translator,
    terminal: Terminal,
    *,
    dashboard: DashboardLaunch | None = None,
    defer_animation_overlay: bool = False,
    ranking_entry_offset: int = 0,
    ranking_entry_limit: int | None = None,
    scrollbar_hovered: bool = False,
) -> PaneRender:
    if isinstance(pane, TuiEmptyPane):
        return PaneRender(
            "\n".join(
                (
                    translator.text("status.empty_pane"),
                    translator.text("status.empty_pane_hint"),
                )
            )
        )
    if isinstance(pane, TuiCustomPane):
        component = pane.component
        display_config = (
            component.accepted_config or component.candidate
            if isinstance(component, CustomHistoricalComponent)
            else None
        )
        pane.ranking_viewport.active = False
        pane.grouped_ranking_viewport.active = False
        for viewport in (pane.ranking_viewport, pane.grouped_ranking_viewport):
            viewport.scrollbar = None
            viewport.copy_all_hit = None
            viewport.hits.clear()
        pane.ranking_copy_rows.clear()
        if display_config is None or display_config.kind != "ranking":
            pane.ranking_viewport.clear()
            pane.grouped_ranking_viewport.clear()
        if (
            pane.body_view in {"command", "full-command", "data-table", "data-json"}
            and dashboard is None
        ):
            raise ValueError("custom pane text views require dashboard options")
        options = _custom_pane_options(dashboard, pane) if dashboard is not None else None
        if isinstance(component, CustomMonitorComponent):
            if pane.body_view == "command":
                assert options is not None
                return PaneRender(wrap_command(format_command(options), terminal.width))
            if pane.body_view == "full-command":
                assert options is not None
                return PaneRender(
                    format_full_command_display(format_full_command(options), terminal.width)
                )
            rendered = _render_custom_monitor(
                component,
                translator,
                terminal,
                interval=pane.interval,
                refreshing=_retain_custom_facts_while_pending(
                    pane.lifecycle, generation=component.generation
                ),
            )
            return PaneRender(
                _append_custom_monitor_attachment(
                    pane,
                    rendered.chart,
                    terminal=terminal,
                    now=time.monotonic(),
                    translator=translator,
                ),
                rendered.notices,
                rendered.overlay_placements,
                error_body=rendered.error_body,
            )
        if component.error is not None and component.model is None:
            return _render_custom_failure(
                component,
                translator,
                terminal,
                accepted_at=component.accepted_at,
                interval=pane.interval,
                surface=dashboard_pane_surface(component.candidate.kind),
            )
        if pane.body_view == "command":
            assert options is not None
            return PaneRender(wrap_command(format_command(options), terminal.width))
        if pane.body_view == "full-command":
            assert options is not None
            return PaneRender(
                format_full_command_display(format_full_command(options), terminal.width)
            )
        if pane.body_view in {"data-table", "data-json"}:
            if component.model is None:
                return PaneRender(translator.text("status.loading"))
            return PaneRender(
                render_custom_data(
                    component.model,
                    language=translator.language,
                    translator=translator,
                    view=pane.body_view,
                )
            )
        if component.is_pending and (
            component.model is None
            or not _retain_custom_facts_while_pending(
                pane.lifecycle, generation=component.generation
            )
        ):
            active_config = component.request_config
            context = _custom_render_context(
                active_config,
                translator,
                terminal,
                accepted_at=component.accepted_at,
                interval=pane.interval,
                pending=True,
                surface=dashboard_pane_surface(active_config.kind),
            )
            rendered = render_custom_pending(active_config, context, component.presentation)
            audit = render_audit(context)
            return PaneRender("\n".join(line for line in (rendered, audit) if line))
        if component.model is None:
            return PaneRender(translator.text("status.loading"))
        assert display_config is not None
        retain_accepted = _retain_custom_facts_while_pending(
            pane.lifecycle, generation=component.generation
        )
        data_pending = component.is_pending and not retain_accepted
        rendered = _render_custom_projection(
            component.model,
            display_config,
            translator,
            terminal,
            accepted_at=component.accepted_at,
            interval=pane.interval,
            pending=data_pending,
            refreshing=component.is_pending or pane.lifecycle.submission is not None,
            surface=dashboard_pane_surface(display_config.kind),
            # Keep accepted ranking facts visible while a sub-day request is
            # pending, but do not pair them with a stale date-only summary.
            summary=(
                pane.summary
                if custom_date_summary_supported(component.candidate)
                and custom_date_summary_supported(component.request_config)
                and (
                    display_config.metric_id is None
                    or pane.summary is not None
                    and pane.summary.metric_id == display_config.metric_id
                )
                else None
            ),
            search_query=(
                pane.ranking_search.query
                if display_config.kind == "ranking" and pane.body_view == "chart"
                else ""
            ),
            search_editing=(
                pane.ranking_search.editing
                if display_config.kind == "ranking" and pane.body_view == "chart"
                else False
            ),
            copied_entry_id=(
                pane.copied_ranking_entry_id
                if pane.copied_ranking_until > time.monotonic()
                else None
            ),
            copied_all=pane.copied_ranking_all_until > time.monotonic(),
            item_spacing=pane.ranking_item_spacing,
            entry_offset=ranking_entry_offset,
            entry_limit=ranking_entry_limit,
            ranking_viewport=(
                pane.ranking_viewport
                if dashboard is not None and display_config.kind == "ranking"
                else None
            ),
            grouped_ranking_viewport=(
                pane.grouped_ranking_viewport
                if dashboard is not None and display_config.kind == "ranking"
                else None
            ),
            scrollbar_hovered=scrollbar_hovered,
        )
        if (
            display_config.kind == "ranking"
            and pane.body_view == "chart"
            and pane.ranking_item_spacing != "compact"
            and not pane.active_ranking_viewport.active
        ):
            rendered = PaneRender(
                _apply_custom_ranking_spacing(
                    rendered.chart,
                    mode=pane.ranking_item_spacing,
                    width=terminal.width,
                    ascii=terminal.ascii,
                ),
                rendered.notices,
                rendered.error_body,
            )
        warning_notices = _custom_response_warning_notices(component, translator)
        if component.error is not None:
            return PaneRender(
                rendered.chart,
                (
                    *rendered.notices,
                    *warning_notices,
                    format_error(component.error, translator, color=False),
                ),
            )
        return PaneRender(rendered.chart, (*rendered.notices, *warning_notices))
    if isinstance(pane, TuiAnimationPane):
        if pane.body_view != "chart":
            return PaneRender("")
        now = time.monotonic()
        pane.overlay.poll(now=now, translator=translator)
        result = pane.renderer.render(
            pane.session,
            width=terminal.width,
            height=terminal.height,
            color=terminal.color,
            ascii=terminal.ascii,
            now=now,
            translator=translator,
        )
        rows = list(result.rows)
        if defer_animation_overlay:
            return PaneRender(
                "\n".join(rows),
                overlay_placements=pane.overlay.unbounded_placements(
                    width=terminal.width, height=len(rows)
                ),
            )
        for placement in pane.overlay.placements(width=terminal.width, height=len(rows)):
            if 0 <= placement.row < len(rows):
                rows[placement.row] = compose_overlay_row(
                    rows[placement.row], placement, width=terminal.width
                )
        return PaneRender("\n".join(rows))
    active = _pane_display_options(pane)
    component = pane.component
    if pane.body_view == "command":
        return PaneRender(wrap_command(format_command(active), terminal.width))
    if pane.body_view == "full-command":
        return PaneRender(format_full_command_display(format_full_command(active), terminal.width))
    if pane.body_view in {"data-table", "data-json"}:
        accepted = _pane_options(pane)
        if isinstance(component, MonitorComponent):
            if not isinstance(accepted.chart, MonitorConfig):
                raise TypeError("monitor pane component has historical configuration")
            return PaneRender(
                render_current_monitor_data(
                    component,
                    accepted.chart,
                    translator=translator,
                    terminal=terminal,
                    now=time.monotonic(),
                    wall=datetime.now().astimezone(),
                    view=pane.body_view,
                )
            )
        return PaneRender(
            render_snapshot_data(
                accepted,
                component.snapshot,
                translator,
                terminal,
                view=pane.body_view,
            )
        )
    error = component.error
    if error is not None:
        message = (
            format_error(
                error,
                translator,
                color=terminal.color,
                color_scheme=active.chart.presentation.theme,
            )
            if isinstance(error, VizError)
            else str(error)
        )
        recovery = transient_query_recovery_lines(
            error, translator, initial=component.accepted_options is None
        )
        if (
            recovery is not None
            and isinstance(component, HistoricalChartComponent)
            and component.snapshot is not None
        ):
            rendered = render_historical_component(
                component,
                translator,
                terminal,
                controls=SurfaceControls(),
                surface=dashboard_pane_surface(cast("HistoricalChartConfig", active.chart).kind),
                ranking_deltas=pane.deltas if active.chart.kind == "ranking" else None,
                ranking_rank_deltas=pane.rank_deltas if active.chart.kind == "ranking" else None,
                normalize_titles=True,
                interval=pane.scheduler.interval,
                refreshing=pane.lifecycle.submission is not None,
                ranking_search_query=(
                    pane.ranking_search.query if active.chart.kind == "ranking" else ""
                ),
                ranking_search_editing=(
                    pane.ranking_search.editing if active.chart.kind == "ranking" else False
                ),
                ranking_show_visible_count=active.chart.kind == "ranking",
            )
            pane.last_render = PaneRender(rendered.chart, (*rendered.notices, *recovery))
            return pane.last_render
        if recovery is not None and isinstance(component, HistoricalChartComponent):
            return PaneRender("\n".join(recovery))
        if recovery is not None and pane.last_render is not None:
            return PaneRender(pane.last_render.chart, (*pane.last_render.notices, *recovery))
        return PaneRender(message, recovery or ())
    try:
        if isinstance(component, MonitorComponent):
            if component.accepted_options is None and pane.lifecycle.submission is not None:
                return PaneRender(translator.text("status.loading"))
            display = component.display() if hasattr(component, "display") else component
            display_query_pending = getattr(display, "display_query_pending", False)
            title_chart = (
                active.chart
                if not display_query_pending or component.accepted_options is None
                else component.accepted_options.chart
            )
            if not isinstance(title_chart, MonitorConfig):
                raise TypeError("monitor pane component has historical configuration")
            audit = RenderAudit(
                component.accepted_at,
                component.last_elapsed,
                pane.scheduler.interval,
                "sample",
                refreshing=pane.lifecycle.submission is not None,
                querying=display_query_pending,
            )
            context = RenderContext(
                terminal.width,
                max(
                    1,
                    terminal.height
                    - int(audit_row_visible(active.chart.presentation.density, audit)),
                ),
                translator,
                color=terminal.color,
                ascii=terminal.ascii,
                color_scheme=active.chart.presentation.theme,
                style=active.chart.presentation.style,
                legend_position=active.chart.presentation.legend,
                title_content=translator.text(f"label.{title_chart.by or 'total'}"),
                hide_upper_right_axes=True,
                deltas=component.deltas,
                rank_deltas=component.rank_deltas,
                filter_summary=active_filter_summary(
                    active.chart.filters
                    if isinstance(active.chart.filters, Filters)
                    else Filters(),
                    translator,
                    width=terminal.width,
                ),
                density=active.chart.presentation.density,
                pending=display_query_pending,
                audit=audit,
            )
            candidate = PaneRender(
                display.render(
                    context,
                    now=time.monotonic(),
                    count=max(8, min(32, terminal.width // 4)),
                    wall=datetime.now().astimezone(),
                )
            )
        elif component.snapshot is None:
            label = translator.text(f"label.{active.chart.kind}")
            candidate = PaneRender(f"{label} · {translator.text('status.loading')}")
        else:
            rendered = render_historical_component(
                component,
                translator,
                terminal,
                controls=SurfaceControls(),
                surface=dashboard_pane_surface(cast("HistoricalChartConfig", active.chart).kind),
                ranking_deltas=pane.deltas if active.chart.kind == "ranking" else None,
                ranking_rank_deltas=pane.rank_deltas if active.chart.kind == "ranking" else None,
                normalize_titles=True,
                interval=pane.scheduler.interval,
                refreshing=pane.lifecycle.submission is not None,
                ranking_search_query=(
                    pane.ranking_search.query if active.chart.kind == "ranking" else ""
                ),
                ranking_search_editing=(
                    pane.ranking_search.editing if active.chart.kind == "ranking" else False
                ),
                ranking_show_visible_count=active.chart.kind == "ranking",
            )
            candidate = PaneRender(rendered.chart, rendered.notices)
    except UsageError as exc:
        pane.render_warning = exc
        warning = format_error(
            exc, translator, color=terminal.color, color_scheme=active.chart.presentation.theme
        )
        if pane.last_render is None:
            return PaneRender(warning)
        return PaneRender(pane.last_render.chart, (*pane.last_render.notices, warning))
    pane.last_render = candidate
    pane.render_warning = None
    return candidate

def _update_monitor_attachment_activity(
    component: MonitorComponent,
    attachment: AnimationSessionState,
    *,
    now: float,
    wall: datetime,
    translator: Translator,
) -> None:
    """Apply an accepted monitor interval and retain its last active wall time."""

    delta = component.accepted_total_token_delta
    active = (delta or 0) > 0
    attachment.set_playback_requested(active, now)
    if active:
        attachment.activity_label = last_activity_label(translator, wall)

def _append_monitor_attachment(
    pane: TuiChartPane,
    body: str,
    *,
    terminal: Terminal,
    reserved_rows: int,
    now: float,
    translator: Translator,
) -> str:
    """Append a pane-local rain attachment below viable ranking/list monitors."""
    if not isinstance(pane.component, MonitorComponent):
        return body
    attachment = pane.attachment
    renderer = pane.attachment_renderer
    config = _pane_display_options(pane)
    if (
        not pane.attachment_enabled
        or attachment is None
        or renderer is None
        or not isinstance(config.chart, MonitorConfig)
        or not is_monitor_ranking_style(config.chart.presentation.style)
        or (
            getattr(pane.component, "accepted_total_token_delta", None) is None
            and attachment.activity_label is None
        )
    ):
        if attachment is not None:
            attachment.set_visible(False, now)
        return body
    residual_height = terminal.height - len(body.rstrip("\r\n").splitlines()) - reserved_rows
    if residual_height < 1:
        attachment.set_visible(False, now)
        return body
    attachment.set_visible(True, now)
    result = renderer.render(
        attachment,
        width=terminal.width,
        height=residual_height,
        color=terminal.color,
        ascii=terminal.ascii,
        now=now,
        translator=translator,
    )
    if not result.viable:
        attachment.set_visible(False, now)
        return body
    return "\n".join((*((body,) if body else ()), *result.rows))

def _update_custom_monitor_attachment_activity(
    component: CustomMonitorComponent,
    attachment: AnimationSessionState,
    *,
    now: float,
    wall: datetime,
    translator: Translator,
) -> None:
    """Apply the latest source-owned Monitor total to a Dashboard attachment."""

    total = component.accepted_activity_total
    active = (total or Decimal()) > 0
    attachment.set_playback_requested(active, now)
    if active:
        attachment.activity_label = last_activity_label(translator, wall)

def _local_pane_content(
    chart: str,
    notices: tuple[str, ...],
    *,
    height: int,
    width: int = 80,
    offset: int = 0,
    scrollable: bool = False,
    preserve_layout: bool = False,
    fixed_rows: int = 0,
    return_metadata: bool = False,
) -> str | tuple[str, int, int, int]:
    """Keep notices fixed below an optionally scrollable pane body."""
    notice_rows = min(len(notices), max(0, height - 3))
    chart_height = max(0, height - notice_rows)
    # Chart renderers already fit and wrap their own rows. Re-wrapping a
    # Ranking as prose collapses intentional padding and destroys its columns.
    rows = (
        tuple(chart.splitlines())
        if scrollable and preserve_layout
        else (wrap_text_rows(chart, width=width) if scrollable else chart)
    )
    fixed_rows = min(max(0, fixed_rows), len(rows), chart_height)
    fixed = rows[:fixed_rows]
    viewport = render_text_viewport(
        rows[fixed_rows:], offset=offset, visible_rows=max(0, chart_height - fixed_rows)
    )
    chart_lines = [
        *fixed,
        *((viewport.body if scrollable else chart).splitlines()[: chart_height - fixed_rows]),
    ]
    chart_lines.extend("" for _ in range(chart_height - len(chart_lines)))
    content = "\n".join((*chart_lines, *notices[:notice_rows]))
    if not return_metadata:
        return content
    return (
        content,
        viewport.offset if scrollable else 0,
        viewport.line_count,
        viewport.visible_rows,
    )
