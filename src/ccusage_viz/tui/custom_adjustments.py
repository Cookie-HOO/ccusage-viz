from __future__ import annotations

from dataclasses import replace

from ccusage_viz.custom_component import CustomHistoricalComponent
from ccusage_viz.custom_models import (
    CustomChartCapability,
    CustomFilter,
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_monitor_component import CustomMonitorComponent
from ccusage_viz.custom_monitor_models import custom_monitor_styles
from ccusage_viz.historical_component import HistoricalChartComponent
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    CustomChartConfig,
    adjust_custom_chart,
    compatible_styles,
    is_monitor_ranking_style,
)
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows
from ccusage_viz.tui.controls import (
    _COMMON_PANE_QUICK_ACTIONS,
    _PANE_POSITION_ACTIONS,
    _cycle,
    _localized_actions,
    _management_row,
    _pane_content_actions,
    _pane_management_divider,
)
from ccusage_viz.tui.datasets.chooser import _dataset_title
from ccusage_viz.tui.models import TuiChartPane, TuiCustomPane, TuiPane, _custom_metric_periods


def _accepted_custom_metric_help_node(
    pane: TuiCustomPane, translator: Translator
) -> tuple[str, tuple[tuple[str, tuple[object, ...]], ...]] | None:
    """Return help metadata for the Custom Pane's committed V2 Metric only."""

    accepted_config = pane.component.accepted_config
    descriptor = pane.component.v2_descriptor
    if (
        accepted_config is None
        or accepted_config.metric_id is None
        or not isinstance(descriptor, V2ProbeDescriptor)
    ):
        return None
    metric = next(
        (item for item in descriptor.metrics if item.id == accepted_config.metric_id), None
    )
    if metric is None:
        return None
    return (
        translator.text("status.tui_help_current_metric"),
        (
            (
                _dataset_title(metric.title, translator),
                ((_dataset_title(metric.description, translator), ()),),
            ),
        ),
    )


def _custom_metric_group_switch_available(pane: TuiCustomPane) -> bool:
    """Whether the accepted V2 Metric belongs to one declared Metric Group."""

    accepted_config = pane.component.accepted_config
    descriptor = pane.component.v2_descriptor
    if (
        accepted_config is None
        or accepted_config.metric_id is None
        or not isinstance(descriptor, V2ProbeDescriptor)
    ):
        return False
    metric = next(
        (item for item in descriptor.metrics if item.id == accepted_config.metric_id), None
    )
    return (
        metric is not None
        and metric.group_id is not None
        and any(group.id == metric.group_id for group in descriptor.metric_groups)
    )


def _cycle_dimension(
    values: tuple[str | None, ...],
    current: str | None,
    blocked: str | None,
    step: int,
) -> str | None:
    """Cycle declared values in either direction while skipping one conflict."""
    if not values:
        return current
    start = values.index(current) if current in values else 0
    for distance in range(1, len(values) + 1):
        candidate = values[(start + step * distance) % len(values)]
        if blocked is None or candidate != blocked:
            return candidate
    return current


def _cycle_custom_partitioning(
    config: CustomChartConfig,
    partitions: tuple[str | None, ...],
    groupings: tuple[str | None, ...],
    *,
    step: int = 1,
) -> CustomChartConfig:
    """Cycle partitions without changing an existing legal grouping."""
    if not partitions:
        return config
    if config.partition_by in partitions:
        start = partitions.index(config.partition_by)
        candidates = tuple(
            partitions[(start + step * distance) % len(partitions)]
            for distance in range(1, len(partitions) + 1)
        )
    else:
        candidates = partitions if step > 0 else tuple(reversed(partitions))

    current_group_is_legal = config.group_by is not None and config.group_by in groupings
    for partition_by in candidates:
        if current_group_is_legal:
            if partition_by == config.group_by:
                continue
            group_by = config.group_by
        elif partition_by is not None:
            group_by = next(
                (choice for choice in groupings if choice is not None and choice != partition_by),
                None,
            )
            if group_by is None:
                continue
        else:
            group_by = None
        if (partition_by, group_by) == (config.partition_by, config.group_by):
            continue
        presentation = config.presentation
        styles = compatible_styles(config.kind, group_by)
        if presentation.style not in styles:
            presentation = replace(presentation, style=styles[0])
        return replace(
            config,
            partition_by=partition_by,
            group_by=group_by,
            top=(config.top or 3) if group_by else None,
            presentation=presentation,
        )
    return config


def _cycle_custom_grouping(
    config: CustomChartConfig, groupings: tuple[str | None, ...], *, step: int = 1
) -> CustomChartConfig:
    """Advance grouping while skipping the active partition dimension."""

    if not groupings:
        return config
    values = (
        tuple(choice for choice in groupings if choice is not None)
        if config.partition_by is not None
        else groupings
    )
    group_by = _cycle_dimension(values, config.group_by, config.partition_by, step)
    if group_by == config.group_by:
        return config
    if config.kind == "monitor":
        return replace(config, group_by=group_by, top=config.top)
    presentation = config.presentation
    styles = compatible_styles(config.kind, group_by)
    if presentation.style not in styles:
        presentation = replace(presentation, style=styles[0])
    return replace(
        config,
        group_by=group_by,
        top=config.top,
        presentation=presentation,
    )


_CUSTOM_MONITOR_WINDOWS = (300, 900, 1800, 3600, 21600, 43200, 86400)


def _cycle_custom_monitor_window(window_seconds: int, *, step: int = 1) -> int:
    nearest = min(_CUSTOM_MONITOR_WINDOWS, key=lambda value: abs(value - window_seconds))
    return _CUSTOM_MONITOR_WINDOWS[
        (_CUSTOM_MONITOR_WINDOWS.index(nearest) + step) % len(_CUSTOM_MONITOR_WINDOWS)
    ]


def _custom_capability_for_component(
    component: CustomHistoricalComponent | CustomMonitorComponent,
) -> CustomChartCapability | V2MonitorCapability | None:
    """Return capabilities only when they describe the active custom source."""

    if isinstance(component, CustomMonitorComponent):
        config = component.accepted_config or component.candidate
        if component.capability is None or config.metric_id is None:
            return None
        return component.capability.charts.get("monitor")  # ty: ignore[invalid-return-type]

    return component.capability


def _custom_capability(pane: TuiCustomPane) -> CustomChartCapability | V2MonitorCapability | None:
    """Return the active Dashboard custom pane capability."""

    return _custom_capability_for_component(pane.component)


def _custom_period_adjustment_chart(
    chart: CustomChartConfig,
    capability: CustomChartCapability | V2MonitorCapability | None,
) -> CustomChartConfig:
    """Use the live historical capability as the period-cycle authority."""

    if isinstance(capability, CustomChartCapability):
        return replace(chart, metric_periods=capability.periods)
    return chart


def _custom_period_adjustment_target(
    component: CustomHistoricalComponent,
) -> CustomChartConfig:
    """Resolve period controls against a pending target Metric when present."""

    chart = component.request_config
    descriptor = component.v2_descriptor
    if component.switch_target_config is not None and descriptor is not None:
        metric = next(
            (item for item in descriptor.metrics if item.id == chart.metric_id),
            None,
        )
        if metric is not None:
            return replace(chart, metric_periods=_custom_metric_periods(metric, chart.kind))
    return _custom_period_adjustment_chart(chart, component.capability)


def _ranking_search_eligible(pane: TuiPane) -> bool:
    """Whether a pane can own an in-memory historical Ranking search query."""
    if not isinstance(pane, (TuiChartPane, TuiCustomPane)) or pane.body_view != "chart":
        return False
    if isinstance(pane, TuiCustomPane):
        return (
            isinstance(pane.component, CustomHistoricalComponent)
            and pane.component.candidate.kind == "ranking"
        )
    return (
        isinstance(pane.component, HistoricalChartComponent)
        and pane.component.candidate.chart.kind == "ranking"
    )


def _finish_ranking_search_editing(pane: TuiPane | None) -> None:
    """Leave a pane-local Ranking search editor without clearing its filter."""
    if isinstance(pane, (TuiChartPane, TuiCustomPane)):
        pane.ranking_search.editing = False


def _custom_top_refresh_required(
    component: CustomHistoricalComponent,
    updated: CustomChartConfig,
) -> bool:
    """Request wider V2 ranking coverage only when the display Top outgrows it."""

    if (
        updated.metric_id is None
        or updated.kind != "ranking"
        or updated.top is None
        or updated.top <= (component.retrieval_top or 0)
    ):
        return False
    capability = component.capability
    return capability is None or capability.max_items is None or updated.top <= capability.max_items


def _custom_top_limit_notice(pane: TuiCustomPane, translator: Translator) -> tuple[str, ...]:
    """Return the active Dataset source bound as a notice below its chart."""

    if pane.body_view != "chart" or not isinstance(pane.component, CustomHistoricalComponent):
        return ()
    chart = pane.component.candidate
    capability = pane.component.capability
    if (
        chart.kind != "ranking"
        or chart.top is None
        or capability is None
        or capability.max_items is None
        or chart.top <= capability.max_items
    ):
        return ()
    return (translator.text("status.custom_top_source_limit", max=capability.max_items),)


def _custom_runtime_filters(
    component: CustomHistoricalComponent | CustomMonitorComponent,
) -> tuple[CustomFilter, ...]:
    """Return only controls accepted with the current Dataset query snapshot."""

    runtime = component.runtime
    return runtime.filters if runtime is not None else ()


def _custom_pane_adjustment_bindings(pane: TuiCustomPane, page: str) -> tuple[tuple[str, str], ...]:
    """Return the active custom actions for one Dashboard adjustment page."""

    capability = _custom_capability(pane)
    chart = pane.component.candidate
    if isinstance(pane.component, CustomMonitorComponent):
        if page == "quick":
            actions: list[tuple[str, str]] = []
            if _custom_metric_group_switch_available(pane):
                actions.append(("m/M", "metric"))
            config = pane.component.accepted_config or pane.component.candidate
            if not is_monitor_ranking_style(config.presentation.style):
                actions.append(("w", "window"))
            if isinstance(capability, V2MonitorCapability) and capability.group_by:
                actions.append(("b/B", "group"))
            if chart.group_by is not None:
                actions.append(("+/-", "top"))
            return (*actions, *_COMMON_PANE_QUICK_ACTIONS)
        actions = [("l", "legend"), ("L", "custom_logs")]
        if _custom_runtime_filters(pane.component):
            actions.insert(0, ("f", "filters"))
        if chart.group_by is not None and pane.component.aggregation == "sum":
            actions.insert(0, ("o", "other"))
        config = pane.component.accepted_config or pane.component.candidate
        if pane.attachment is not None and is_monitor_ranking_style(config.presentation.style):
            actions.extend((("t/T", "animation_theme"), ("s/S", "animation_style")))
        return tuple(actions)
    if page == "quick":
        actions: list[tuple[str, str]] = [("p/P", "period")]
        if _custom_metric_group_switch_available(pane):
            actions.insert(0, ("m/M", "metric"))
        if capability is not None:
            partitions = capability.partition_by  # ty: ignore[unresolved-attribute]
            if (
                chart.kind == "ranking"
                and partitions is not None
                and (
                    _cycle_custom_partitioning(chart, partitions, capability.group_by, step=1)
                    != chart
                    or _cycle_custom_partitioning(chart, partitions, capability.group_by, step=-1)
                    != chart
                )
            ):
                actions.append(("g/G", "partition"))
            elif chart.kind != "ranking" and len(capability.granularities) > 1:  # ty: ignore[unresolved-attribute]
                actions.append(("g/G", "granularity"))
            if chart.kind != "calendar":
                actions.append(("b/B", "group"))
        if chart.group_by is not None or chart.kind == "ranking":
            actions.append(("+/-", "top"))
        return (*actions, *_COMMON_PANE_QUICK_ACTIONS)

    actions = []
    if chart.kind == "ranking":
        actions.append(("s/S", "spacing"))
    if _custom_runtime_filters(pane.component):
        actions.append(("f", "filters"))
    if chart.group_by is not None:
        actions.append(("o", "other"))
    if chart.kind in {"timeline", "stack"}:
        actions.extend((("l", "legend"), ("k", "weekdays")))
    actions.append(("L", "custom_logs"))
    return tuple(actions)


def _adjust_custom_monitor_chart(
    chart: CustomChartConfig, key: str, *, aggregation: str = "sum"
) -> CustomChartConfig:
    """Cycle the Dataset Monitor's supported source-owned presentations."""

    if key in {"s", "S"}:
        styles = custom_monitor_styles(aggregation, chart.group_by)
        current = chart.presentation.style
        return replace(
            chart,
            presentation=replace(
                chart.presentation,
                style=_cycle(
                    styles,
                    current if current in styles else styles[0],
                    1 if key == "s" else -1,
                ),
            ),
        )
    if key in {"d", "D", "t", "T", "l"}:
        return adjust_custom_chart(chart, key)
    return chart


def _custom_pane_adjustment_actions(
    pane: TuiCustomPane, page: str, translator: Translator
) -> tuple[AdjustmentAction, ...]:
    return _localized_actions(_custom_pane_adjustment_bindings(pane, page), translator)


def _custom_pane_adjustment_keys(pane: TuiCustomPane, page: str) -> frozenset[str]:
    return frozenset(
        character
        for binding, _label in _custom_pane_adjustment_bindings(pane, page)
        for character in binding
        if character not in {"/", " "}
    )


def _custom_pane_adjustment_state(pane: TuiCustomPane, page: str, translator: Translator) -> str:
    chart = pane.component.candidate
    if page == "quick":
        values = [
            chart.kind,
            chart.presentation.density,
            chart.presentation.theme,
            chart.presentation.style,
        ]
        if chart.group_by is not None:
            values.append(f"Group {chart.group_by}")
        if chart.group_by is not None or chart.kind == "ranking":
            values.append(f"Top {chart.top or translator.text('label.all')}")
        values.append("chart")
        settings = " · ".join(values)
    else:
        settings = []
        if chart.group_by is not None:
            settings.append(f"Other {chart.other}")
        if chart.kind in {"timeline", "stack"}:
            settings.extend((f"Legend {chart.presentation.legend}", f"Weekdays {chart.weekdays}"))
        settings.extend((chart.source.dataset_id, " ".join(chart.source.command_argv)))
        settings = " · ".join(settings)
    return translator.text(
        "status.tui_current_state",
        runtime=translator.text("status.tui_running"),
        settings=settings,
    )


def _custom_adjustment_footer(
    pane: TuiCustomPane,
    page: str,
    translator: Translator,
    width: int,
    *,
    color: bool,
) -> tuple[str, ...]:
    shared = adjustment_rows(
        _custom_pane_adjustment_state(pane, page, translator),
        translator.text(f"status.tui_adjust_{page}"),
        _custom_pane_adjustment_actions(pane, page, translator),
        width=width,
        color=False,
        switch_action=translator.text(
            "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
        ),
        finish_action=translator.text("adjustment.finish"),
    )
    return (
        *shared,
        _pane_management_divider(translator, width, color=color),
        _management_row(
            translator.text("status.tui_pane_content"),
            _pane_content_actions("chart"),
            translator,
            width,
        ),
        _management_row(
            translator.text("status.tui_pane_position"),
            _PANE_POSITION_ACTIONS,
            translator,
            width,
        ),
    )
