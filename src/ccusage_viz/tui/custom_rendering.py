from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from ccusage_viz.command_copy import format_command, format_full_command
from ccusage_viz.custom_component import CustomHistoricalComponent, custom_date_summary_supported
from ccusage_viz.custom_models import CustomProtocolFailure, V2MonitorCapability
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.data_view import (
    body_view_copy_kind,
    render_current_monitor_data,
    render_custom_data,
    render_snapshot_data,
)
from ccusage_viz.diagnostics import format_error
from ccusage_viz.errors import QueryError
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import LifecycleOperation, LifecycleTrigger
from ccusage_viz.monitor_component import MonitorComponent
from ccusage_viz.options import (
    CustomChartConfig,
    DashboardLaunch,
    MonitorConfig,
    is_monitor_ranking_style,
    is_v2_custom_ranking,
)
from ccusage_viz.processing.custom_historical import CustomChartProjection
from ccusage_viz.render.base import RenderContext, render_audit
from ccusage_viz.render.custom import (
    custom_heading,
    render_custom_failure,
    render_custom_pending,
    render_custom_projection,
)
from ccusage_viz.render.custom_monitor import render_custom_monitor, render_custom_monitor_heading
from ccusage_viz.render.custom_ranking_viewport import render_custom_ranking_viewport
from ccusage_viz.render.grouped_ranking_viewport import (
    GroupedRankingViewport,
    render_grouped_custom_ranking_viewport,
)
from ccusage_viz.render.ranking_description import copyable_description_text
from ccusage_viz.render.ranking_viewport import RankingViewport
from ccusage_viz.render.summary import render_custom_metrics
from ccusage_viz.render.surfaces import (
    EMPTY_SURFACE_CONTROLS,
    HistoricalPresentationSurface,
    SurfaceControls,
    SurfacePresentation,
    dashboard_pane_surface,
    standalone_surface,
)
from ccusage_viz.terminal import Terminal
from ccusage_viz.terminal_ui import AdjustmentAction
from ccusage_viz.tui.controls import _localized_actions
from ccusage_viz.tui.custom_adjustments import _custom_capability_for_component
from ccusage_viz.tui.models import (
    CustomDashboardSummary,
    PaneRender,
    TuiChartPane,
    TuiCustomPane,
    _custom_pane_options,
    _pane_options,
)


def _pane_copy_payload(
    pane: TuiChartPane | TuiCustomPane,
    translator: Translator,
    terminal: Terminal,
    *,
    dashboard: DashboardLaunch | None = None,
) -> str:
    """Return the focused non-chart pane view's complete clipboard payload."""
    if isinstance(pane, TuiCustomPane):
        if dashboard is None:
            raise ValueError("custom pane copy requires dashboard options")
        active = _custom_pane_options(dashboard, pane)
        view = body_view_copy_kind(pane.body_view)
        if view is None:
            raise ValueError("chart panes do not have a copy payload")
        if view == "command":
            return format_command(active)
        if view == "full-command":
            return format_full_command(active)
        if pane.component.model is None:
            return translator.text("status.loading")
        return render_custom_data(
            pane.component.model,
            language=translator.language,
            translator=translator,
            view=view,
        )
    active = _pane_options(pane)
    view = body_view_copy_kind(pane.body_view)
    if view is None:
        raise ValueError("chart panes do not have a copy payload")
    if view == "command":
        return format_command(active)
    if view == "full-command":
        return format_full_command(active)
    component = pane.component
    if isinstance(component, MonitorComponent):
        if not isinstance(active.chart, MonitorConfig):
            raise TypeError("monitor pane component has historical configuration")
        return render_current_monitor_data(
            component,
            active.chart,
            translator=translator,
            terminal=terminal,
            now=time.monotonic(),
            wall=datetime.now().astimezone(),
            view=view,
        )
    return render_snapshot_data(
        active,
        component.snapshot,
        translator,
        terminal,
        view=view,
    )


def _custom_render_context(
    config: CustomChartConfig,
    translator: Translator,
    terminal: Terminal,
    *,
    accepted_at: datetime | None,
    interval: float | None,
    pending: bool,
    surface: HistoricalPresentationSurface,
    refreshing: bool | None = None,
    controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
    reserved_summary_rows: int = 0,
) -> RenderContext:
    """Adapt Custom semantics to the selected kind-specific product surface."""
    is_ungrouped_timeline = config.kind == "timeline" and config.group_by is None
    presentation = SurfacePresentation(
        config.kind,
        config.presentation.theme,
        config.presentation.style,
        config.presentation.legend,
        config.presentation.density,
        config.weekdays,
        config.date_range.period if config.date_range.relative_until else None,
        translator.text("label.total") if is_ungrouped_timeline else None,
        None,
        accepted_at,
        None,
        interval,
        refreshing=pending if refreshing is None else refreshing,
        querying=pending,
        pending=pending,
    )
    return surface.context(
        terminal,
        translator,
        presentation,
        controls=controls,
        reserved_summary_rows=reserved_summary_rows,
    )


def _custom_failure_log_detail(error: BaseException, translator: Translator) -> str:
    if isinstance(error, QueryError):
        failure = error.values.get("custom_failure")
        if isinstance(failure, CustomProtocolFailure):
            message = failure.message.zh_cn if translator.language == "zh" else failure.message.en
            detail = f"{failure.code}: {message}"
            if failure.unsupported is not None:
                field = failure.unsupported.get("field")
                value = failure.unsupported.get("value")
                if isinstance(field, str) and isinstance(value, str):
                    detail = f"{detail} ({field}={value})"
            return detail
    return translator.text("status.custom_log_error")


def _render_custom_failure(
    component: CustomHistoricalComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    accepted_at: datetime | None,
    interval: float | None,
    surface: HistoricalPresentationSurface,
) -> PaneRender:
    context = _custom_render_context(
        component.candidate,
        translator,
        terminal,
        accepted_at=accepted_at,
        interval=interval,
        pending=False,
        surface=surface,
    )
    return PaneRender(
        "\n\n".join(
            (
                render_custom_failure(component.candidate, context, component.presentation),
                format_error(component.error, translator, color=False),
            )
        ),
        error_body=True,
    )


def _retain_custom_facts_while_pending(
    lifecycle: LifecycleOperation[object] | None = None,
    *,
    generation: int | None = None,
    trigger: LifecycleTrigger | None = None,
) -> bool:
    """Whether the newest same-generation Custom request may retain accepted facts.

    A periodic refresh can be queued while an older configuration request is
    still active. The queued intent is then the user's visible next state, so
    it must win over the active operation when choosing the pending display.
    """

    if lifecycle is not None:
        pending = lifecycle.coordinator.pending
        if pending is not None and pending.generation == generation:
            trigger = pending.trigger
        else:
            operation = lifecycle.operation
            if operation is not None and operation.generation == generation:
                trigger = operation.trigger
    return trigger in {LifecycleTrigger.PERIODIC, LifecycleTrigger.MANUAL}


def _render_custom_monitor(
    component: CustomMonitorComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    interval: float,
    refreshing: bool = False,
) -> PaneRender:
    config = component.accepted_config or component.candidate
    transient = component.accepted_response is None or (component.pending and not refreshing)
    context = dashboard_pane_surface("timeline").context(
        terminal,
        translator,
        SurfacePresentation(
            "timeline",
            config.presentation.theme,
            config.presentation.style,
            config.presentation.legend,
            config.presentation.density,
            config.weekdays,
            None,
            None,
            None,
            None,
            None,
            None,
            querying=(transient or refreshing) and component.error is None,
            pending=transient or refreshing,
        ),
    )
    if transient:
        body = (
            format_error(component.error, translator, color=False)
            if component.error
            else translator.text("status.loading")
        )
        capability = component.monitor_capability
        if capability is None and component.capability is not None:
            capability = component.capability.charts.get("monitor")
        if not isinstance(capability, V2MonitorCapability):
            return PaneRender(body, error_body=component.error is not None)
        return PaneRender(
            f"{render_custom_monitor_heading(component, context)}\n{body}",
            error_body=component.error is not None,
        )
    return PaneRender(render_custom_monitor(component, context))


def _append_custom_monitor_attachment(
    pane: TuiCustomPane,
    body: str,
    *,
    terminal: Terminal,
    now: float,
    translator: Translator,
) -> str:
    """Append the native Monitor attachment below ranking/list Dataset views."""

    if not isinstance(pane.component, CustomMonitorComponent):
        return body
    config = pane.component.accepted_config or pane.component.candidate
    attachment = pane.attachment
    renderer = pane.attachment_renderer
    if (
        not pane.attachment_enabled
        or attachment is None
        or renderer is None
        or not is_monitor_ranking_style(config.presentation.style)
    ):
        if attachment is not None:
            attachment.set_visible(False, now)
        return body
    residual_height = terminal.height - len(body.rstrip("\r\n").splitlines())
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
    return "\n".join((body, *result.rows)) if result.viable else body


def _custom_response_warning_notices(
    component: CustomHistoricalComponent, translator: Translator
) -> tuple[str, ...]:
    """Return localized notices belonging to the currently accepted chart facts."""

    return tuple(
        warning.message.zh_cn if translator.language == "zh" else warning.message.en
        for warning in component.accepted_warnings
    )


def _render_custom_projection(
    projection: CustomChartProjection,
    config: CustomChartConfig,
    translator: Translator,
    terminal: Terminal,
    *,
    accepted_at: datetime | None,
    interval: float | None,
    pending: bool,
    surface: HistoricalPresentationSurface,
    refreshing: bool | None = None,
    summary: CustomDashboardSummary | None = None,
    controls: SurfaceControls = EMPTY_SURFACE_CONTROLS,
    search_query: str = "",
    search_editing: bool = False,
    copied_entry_id: str | None = None,
    copied_all: bool = False,
    item_spacing: str = "compact",
    entry_offset: int = 0,
    entry_limit: int | None = None,
    ranking_viewport: RankingViewport | None = None,
    grouped_ranking_viewport: GroupedRankingViewport | None = None,
    scrollbar_hovered: bool = False,
) -> PaneRender:
    context = _custom_render_context(
        config,
        translator,
        terminal,
        accepted_at=accepted_at,
        interval=interval,
        pending=pending,
        surface=surface,
        refreshing=refreshing,
        controls=controls,
    )
    summary_render = ""
    if (
        summary is not None
        and summary.response is not None
        and custom_date_summary_supported(config)
    ):
        summary_render = render_custom_metrics(
            (summary.response.summary.metric,),
            context,
            period=summary.accepted_period,
            as_of_date=summary.accepted_as_of_date,
        )
        min_chart_rows = 9 + int(
            config.kind in {"timeline", "stack"} and config.presentation.legend == "below-title"
        )
        summary_rows = max(0, context.height - min_chart_rows)
        if len(summary_render.splitlines()) > summary_rows:
            compact_context = replace(context, density="compact")
            summary_render = render_custom_metrics(
                (summary.response.summary.metric,),
                compact_context,
                period=summary.accepted_period,
                as_of_date=summary.accepted_as_of_date,
            )
        summary_render = "\n".join(summary_render.splitlines()[:summary_rows])
        if summary_render:
            context = _custom_render_context(
                config,
                translator,
                terminal,
                accepted_at=accepted_at,
                interval=interval,
                pending=pending,
                surface=surface,
                refreshing=refreshing,
                controls=controls,
                reserved_summary_rows=len(summary_render.splitlines()),
            )
    grouped = projection.groups is not None
    active_viewport: RankingViewport | GroupedRankingViewport | None = (
        grouped_ranking_viewport if grouped else ranking_viewport
    )
    incompatible_viewport: RankingViewport | GroupedRankingViewport | None = (
        ranking_viewport if grouped else grouped_ranking_viewport
    )
    if active_viewport is not None:
        # Partition-mode changes invalidate the other renderer's complete
        # session state, including offsets, hits, source facts, and caches.
        if incompatible_viewport is not None:
            incompatible_viewport.clear()
        audit = render_audit(context)
        summary_rows = len(summary_render.splitlines())
        context = replace(
            context,
            height=max(
                0,
                terminal.height
                - summary_rows
                - len(audit.splitlines())
                - active_viewport.reserved_rows,
            ),
        )
        render_args = dict(
            heading=custom_heading(config, context, projection.presentation).strip(),
            descriptions_visible=config.presentation.density in {"full", "detailed"},
            search_query=search_query,
            search_editing=search_editing,
            show_visible_count=True,
            copied_entry_id=copied_entry_id,
            item_spacing=item_spacing,
            scrollbar=True,
            scrollbar_hovered=scrollbar_hovered,
            copy_all_action=True,
            copied_all=copied_all,
        )
        current_projection = replace(projection, config=config)
        if grouped:
            assert isinstance(active_viewport, GroupedRankingViewport)
            rendered = render_grouped_custom_ranking_viewport(
                current_projection, context, active_viewport, **render_args
            )
        else:
            assert isinstance(active_viewport, RankingViewport)
            rendered = render_custom_ranking_viewport(
                current_projection, context, active_viewport, **render_args
            )
        active_viewport.hits = {
            row + summary_rows: hit for row, hit in active_viewport.hits.items()
        }
        if active_viewport.copy_all_hit is not None:
            row, column = active_viewport.copy_all_hit
            active_viewport.copy_all_hit = (row + summary_rows, column)
        if active_viewport.scrollbar is not None:
            active_viewport.scrollbar = replace(
                active_viewport.scrollbar, top=active_viewport.scrollbar.top + summary_rows
            )
        rows = rendered.splitlines()
        rows.extend("" for _ in range(context.height - len(rows)))
        return PaneRender("\n".join((*summary_render.splitlines(), *rows, *audit.splitlines())))
    rendered = render_custom_projection(
        replace(projection, config=config, presentation=projection.presentation),
        context,
        descriptions_visible=config.presentation.density in {"full", "detailed"},
        search_query=search_query,
        search_editing=search_editing,
        show_visible_count=config.kind == "ranking",
        copied_entry_id=copied_entry_id,
        entry_offset=entry_offset,
        entry_limit=entry_limit,
    )
    if summary_render:
        rendered = "\n".join((summary_render, rendered))
    audit = render_audit(context)
    if audit:
        rendered = "\n".join((rendered, audit))
    return PaneRender(rendered)


def _ranking_fixed_rows(chart: str) -> int:
    """Keep Ranking chrome above the first numbered row while data scrolls."""
    for index, row in enumerate(chart.splitlines()):
        prefix, _, _ = row.lstrip().partition(" ")
        if prefix.isdecimal():
            return index
    return 0


def _custom_ranking_copyable_entries(
    pane: TuiCustomPane, translator: Translator
) -> tuple[tuple[int, str, str, str | None, str | None], ...]:
    """Return visible concrete Dataset Ranking facts in chart order."""
    component = pane.component
    if not isinstance(component, CustomHistoricalComponent) or component.model is None:
        return ()
    query = pane.ranking_search.query.casefold()
    entries = []
    for rank, series in enumerate(component.model.series, start=1):
        if series.is_other:
            continue
        label = series.label.zh_cn if translator.language == "zh" else series.label.en
        description = (
            None
            if series.description is None
            else series.description.zh_cn
            if translator.language == "zh"
            else series.description.en
        )
        search_text = f"{label} {copyable_description_text(description)}" if description else label
        if query and query not in search_text.casefold():
            continue
        entries.append((rank, series.id, label, description, series.link))
    return tuple(entries)


def _apply_custom_ranking_spacing(chart: str, *, mode: str, width: int, ascii: bool) -> str:
    """Insert presentation-only separators before numbered Custom Ranking rows."""

    if mode == "compact":
        return chart
    separator = (
        ""
        if mode == "space"
        else ("-" if ascii else "─") * width
        if mode == "line"
        else ("- " * max(1, width // 2)).rstrip()
    )
    rows: list[str] = []
    for row in chart.splitlines():
        prefix, _, _ = strip_ansi(row).lstrip().partition(" ")
        if prefix.isdecimal() and rows:
            rows.append(separator)
        rows.append(row)
    return "\n".join(rows)


def _custom_ranking_clipboard_text(
    label: str, description: str | None, project_link: str | None
) -> str:
    """Build one project copy payload, preserving every user-visible link target."""
    return "\n".join(
        part for part in (label, copyable_description_text(description or ""), project_link) if part
    )


def _custom_ranking_clipboard_all_text(
    entries: Iterable[tuple[str, str | None, str | None]],
) -> str:
    """Build a copy payload from every displayed concrete Ranking entry."""
    return "\n\n".join(
        _custom_ranking_clipboard_text(label, description, project_link)
        for label, description, project_link in entries
    )


def _custom_standalone_actions(
    component: CustomHistoricalComponent,
    translator: Translator,
) -> tuple[AdjustmentAction, ...]:
    """Return the live custom adjustments available to a standalone chart."""

    capability = _custom_capability_for_component(component)
    actions: list[tuple[str, str]] = [("p/P", "period")]
    chart = component.candidate
    if capability is not None:
        if not is_v2_custom_ranking(chart) and len(capability.granularities) > 1:
            actions.append(("g/G", "granularity"))
        if chart.kind != "calendar" and capability.group_by:
            actions.append(("b/B", "group"))
        if component.runtime is not None and component.runtime.filters:
            actions.append(("f", "filters"))
    if chart.group_by is not None or chart.kind == "ranking":
        actions.extend((("+/-", "top"), ("o", "other")))
    if chart.kind in {"timeline", "stack"}:
        actions.extend((("k", "weekdays"), ("l", "legend")))
    actions.extend(
        (
            ("d/D", "density"),
            ("t/T", "theme"),
            ("s/S", "style"),
            ("L", "custom_logs"),
        )
    )
    return _localized_actions(tuple(actions), translator)


def _custom_standalone_render(
    component: CustomHistoricalComponent,
    translator: Translator,
    terminal: Terminal,
    *,
    interval: float | None = None,
    pending: bool,
    summary: CustomDashboardSummary | None = None,
    pending_trigger: LifecycleTrigger | None = None,
) -> PaneRender:
    if component.error is not None and component.model is None:
        return _render_custom_failure(
            component,
            translator,
            terminal,
            accepted_at=component.accepted_at,
            interval=interval,
            surface=standalone_surface(component.candidate.kind),
        )
    if component.is_pending and (
        component.model is None or not _retain_custom_facts_while_pending(trigger=pending_trigger)
    ):
        active_config = component.request_config
        context = _custom_render_context(
            active_config,
            translator,
            terminal,
            accepted_at=component.accepted_at,
            interval=interval,
            pending=True,
            surface=standalone_surface(active_config.kind),
        )
        rendered = render_custom_pending(active_config, context, component.presentation)
        audit = render_audit(context)
        return PaneRender("\n".join(line for line in (rendered, audit) if line))
    if component.model is None:
        return PaneRender(translator.text("status.loading"))
    rendered = _render_custom_projection(
        component.model,
        component.accepted_config or component.candidate,
        translator,
        terminal,
        accepted_at=component.accepted_at,
        interval=interval,
        pending=component.is_pending
        and not _retain_custom_facts_while_pending(trigger=pending_trigger),
        refreshing=pending,
        surface=standalone_surface((component.accepted_config or component.candidate).kind),
        summary=summary,
    )
    return (
        PaneRender(
            rendered.chart,
            (*rendered.notices, format_error(component.error, translator, color=False)),
        )
        if component.error is not None
        else rendered
    )
