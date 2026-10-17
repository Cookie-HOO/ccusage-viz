from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ccusage_viz.animation import animation_spec
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.options import (
    CACHE_MODES,
    CUSTOM_RANKING_ITEM_SPACINGS,
    GRANULARITIES,
    AnimationPaneConfig,
    CalendarConfig,
    ChartPaneConfig,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    EmptyPaneConfig,
    MonitorConfig,
    PaneConfig,
    RankingConfig,
    StackConfig,
    TimelineConfig,
    is_v2_custom_ranking,
)
from ccusage_viz.presets.values import (
    DashboardPresetValidationError,
    _choice,
    _custom_filters_parse,
    _custom_filters_wire,
    _date_range_parse,
    _date_range_wire,
    _exact,
    _expect_mapping,
    _filters_parse,
    _filters_wire,
    _integer,
    _optional_choice,
    _optional_int,
    _optional_string,
    _overlay_parse,
    _overlay_wire,
    _presentation_parse,
    _presentation_wire,
    _string,
    _string_list,
)
from ccusage_viz.project_identity import PROJECT_AGGREGATIONS
from ccusage_viz.render.palette import COLOR_SCHEMES

_PERSISTED_CUSTOM_EXPLICIT = frozenset(
    {
        "period",
        "since",
        "until",
        "partition_by",
        "group_by",
        "top",
        "filter",
        "granularity",
        "other",
        "style",
        "color_scheme",
        "window",
    }
)

def _chart_wire(chart: object) -> dict[str, object]:
    if isinstance(chart, CustomChartConfig):
        return {
            "kind": "custom",
            "chart_kind": chart.kind,
            "dataset_id": chart.source.dataset_id,
            "source_kind": chart.source.source_kind,
            "command_argv": list(chart.source.command_argv),
            "date_range": _date_range_wire(chart.date_range),
            "filters": _custom_filters_wire(chart.filters),
            "presentation": _presentation_wire(chart.presentation),
            "partition_by": chart.partition_by,
            "group_by": chart.group_by,
            "top": chart.top,
            "other": chart.other,
            **({} if is_v2_custom_ranking(chart) else {"granularity": chart.granularity}),
            "weekdays": chart.weekdays,
            "metric_id": chart.metric_id,
            "metric_summary": chart.metric_summary,
            "metric_periods": list(chart.metric_periods),
            "metric_titles": list(chart.metric_titles) if chart.metric_titles is not None else None,
        }
    if isinstance(chart, MonitorConfig):
        return {
            "kind": "monitor",
            "window_seconds": chart.window_seconds,
            "filters": _filters_wire(chart.filters),
            "presentation": _presentation_wire(chart.presentation),
            "by": chart.by,
            "top": chart.top,
            "project_aggregation": chart.project_aggregation,
            "day_window": chart.day_window,
            "distribution_granularity": chart.distribution_granularity,
        }
    if isinstance(chart, (TimelineConfig, CalendarConfig, StackConfig, RankingConfig)):
        base: dict[str, object] = {
            "kind": "chart",
            "chart_kind": chart.kind,
            "date_range": _date_range_wire(chart.date_range),
            "filters": _filters_wire(chart.filters),
            "presentation": _presentation_wire(chart.presentation),
        }
        if isinstance(chart, TimelineConfig):
            base["options"] = {
                "by": chart.by,
                "top": chart.top,
                "other": chart.other,
                "granularity": chart.granularity,
                "weekdays": chart.weekdays,
                "project_aggregation": chart.project_aggregation,
            }
        elif isinstance(chart, CalendarConfig):
            base["options"] = {}
        elif isinstance(chart, StackConfig):
            base["options"] = {
                "cache": chart.cache,
                "granularity": chart.granularity,
                "weekdays": chart.weekdays,
                "by": chart.by,
                "top": chart.top,
                "other": chart.other,
                "project_aggregation": chart.project_aggregation,
            }
        else:
            base["options"] = {
                "by": chart.by,
                "top": chart.top,
                "other": chart.other,
                "project_aggregation": chart.project_aggregation,
            }
        return base
    raise AssertionError(f"unsupported chart type: {type(chart)!r}")

def _attachment_wire(*, style: str | None, theme: str | None) -> dict[str, object] | None:
    if style is None and theme is None:
        return None
    return {"style": style, "theme": theme}

def _attachment_parse(value: object) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    wire = _exact(value, frozenset(("style", "theme")), "monitor attachment")
    style = _optional_string(wire["style"], "monitor attachment.style")
    if style is not None:
        try:
            animation_spec(style, target="monitor")
        except ValueError as exc:
            raise DashboardPresetValidationError("unsupported monitor attachment style") from exc
    theme = _optional_choice(wire["theme"], COLOR_SCHEMES, "monitor attachment.theme")
    return style, theme

def _pane_fields(
    wire: Mapping[str, object], fields: frozenset[str], label: str
) -> tuple[Mapping[str, object], tuple[str | None, str | None]]:
    payload = dict(wire)
    attachment = _attachment_parse(payload.pop("attachment", None))
    return _exact(payload, fields, label), attachment

def _parse_builtin_chart(value: Mapping[str, object]) -> ChartPaneConfig:
    kind = _choice(
        value["chart_kind"], ("timeline", "calendar", "stack", "ranking"), "chart.chart_kind"
    )
    presentation = _presentation_parse(value["presentation"], kind)
    date_range, filters = _date_range_parse(value["date_range"]), _filters_parse(value["filters"])
    options = _expect_mapping(value["options"], "chart.options")
    if kind == "timeline":
        wire = _exact(
            options,
            frozenset(("by", "top", "other", "granularity", "weekdays", "project_aggregation")),
            "timeline options",
        )
        chart = TimelineConfig(
            kind,
            date_range,
            filters,
            presentation,
            _optional_choice(
                wire["by"], ("composition", "agent", "model", "project"), "timeline.by"
            ),
            _optional_int(wire["top"], "timeline.top", minimum=1),
            _choice(wire["other"], ("show", "hide"), "timeline.other"),
            _choice(wire["granularity"], GRANULARITIES, "timeline.granularity"),
            _choice(wire["weekdays"], ("show", "hide"), "timeline.weekdays"),
            _choice(
                wire["project_aggregation"], PROJECT_AGGREGATIONS, "timeline.project_aggregation"
            ),
        )
    elif kind == "calendar":
        _exact(options, frozenset(), "calendar options")
        chart = CalendarConfig(kind, date_range, filters, presentation)
    elif kind == "stack":
        wire = _exact(
            options,
            frozenset(
                ("cache", "granularity", "weekdays", "by", "top", "other", "project_aggregation")
            ),
            "stack options",
        )
        chart = StackConfig(
            kind,
            date_range,
            filters,
            presentation,
            _choice(wire["cache"], CACHE_MODES, "stack.cache"),
            _choice(wire["granularity"], GRANULARITIES, "stack.granularity"),
            _choice(wire["weekdays"], ("show", "hide"), "stack.weekdays"),
            _choice(wire["by"], ("composition", "agent", "model", "project"), "stack.by"),
            _integer(wire["top"], "stack.top", minimum=1),
            _choice(wire["other"], ("show", "hide"), "stack.other"),
            _choice(wire["project_aggregation"], PROJECT_AGGREGATIONS, "stack.project_aggregation"),
        )
    else:
        wire = _exact(
            options, frozenset(("by", "top", "other", "project_aggregation")), "ranking options"
        )
        chart = RankingConfig(
            kind,
            date_range,
            filters,
            presentation,
            _choice(wire["by"], ("composition", "agent", "model", "project"), "ranking.by"),
            _integer(wire["top"], "ranking.top", minimum=1),
            _choice(wire["other"], ("show", "hide"), "ranking.other"),
            _choice(
                wire["project_aggregation"], PROJECT_AGGREGATIONS, "ranking.project_aggregation"
            ),
        )
    return ChartPaneConfig(chart)

def _parse_pane(value: object) -> PaneConfig:
    wire = _expect_mapping(value, "pane")
    kind = _string(wire.get("kind"), "pane.kind")
    if kind == "empty":
        _exact(wire, frozenset(("kind",)), "empty pane")
        return EmptyPaneConfig()
    if kind == "chart":
        chart_wire, attachment = _pane_fields(
            wire,
            frozenset(("kind", "chart_kind", "date_range", "filters", "presentation", "options")),
            "chart pane",
        )
        config = _parse_builtin_chart(chart_wire)
        return replace(
            config,
            attachment_style=attachment[0],
            attachment_theme=attachment[1],
        )
    if kind == "monitor":
        monitor_wire, attachment = _pane_fields(
            wire,
            frozenset(
                (
                    "kind",
                    "window_seconds",
                    "filters",
                    "presentation",
                    "by",
                    "top",
                    "project_aggregation",
                    "day_window",
                    "distribution_granularity",
                )
            ),
            "monitor pane",
        )
        chart = MonitorConfig(
            "monitor",
            _integer(monitor_wire["window_seconds"], "monitor.window_seconds", minimum=1),
            _filters_parse(monitor_wire["filters"]),
            _presentation_parse(monitor_wire["presentation"], "monitor"),
            _optional_choice(
                monitor_wire["by"], ("composition", "agent", "model", "project"), "monitor.by"
            ),
            _optional_int(monitor_wire["top"], "monitor.top", minimum=1),
            _choice(
                monitor_wire["project_aggregation"],
                PROJECT_AGGREGATIONS,
                "monitor.project_aggregation",
            ),
            _choice(monitor_wire["day_window"], ("today", "yesterday"), "monitor.day_window"),
            _choice(
                monitor_wire["distribution_granularity"],
                ("hour", "half-hour"),
                "monitor.distribution_granularity",
            ),
        )
        return ChartPaneConfig(chart, *attachment)
    if kind == "custom":
        fields = frozenset(
            (
                "kind",
                "chart_kind",
                "dataset_id",
                "source_kind",
                "command_argv",
                "date_range",
                "filters",
                "presentation",
                "partition_by",
                "group_by",
                "top",
                "other",
                "granularity",
                "weekdays",
                "metric_id",
                "metric_summary",
                "metric_periods",
                "metric_titles",
                "ranking_item_spacing",
            )
        )
        payload = dict(wire)
        attachment = _attachment_parse(payload.pop("attachment", None))
        if "partition_by" not in payload:
            payload["partition_by"] = None
        if "ranking_item_spacing" not in payload:
            payload["ranking_item_spacing"] = "compact"
        ranking = payload.get("chart_kind") == "ranking" and isinstance(
            payload.get("metric_id"), str
        )
        if ranking:
            payload.pop("granularity", None)
            fields = fields - {"granularity"}
        custom_wire = _exact(payload, fields, "custom pane")
        dataset_id = _string(custom_wire["dataset_id"], "custom.dataset_id")
        source_kind = _choice(
            custom_wire["source_kind"], ("command", "installed"), "custom.source_kind"
        )
        command_argv = _string_list(custom_wire["command_argv"], "custom.command_argv")
        try:
            source = CustomCommandSource(dataset_id, command_argv, source_kind)
        except ValueError as exc:
            raise DashboardPresetValidationError("invalid custom command source") from exc
        titles_value = custom_wire["metric_titles"]
        if titles_value is None:
            titles = None
        elif isinstance(titles_value, list) and len(titles_value) == 2:
            titles = (
                _string(titles_value[0], "custom.metric_titles[0]"),
                _string(titles_value[1], "custom.metric_titles[1]"),
            )
        else:
            raise DashboardPresetValidationError(
                "custom.metric_titles must contain exactly two strings"
            )
        chart_kind = _choice(
            custom_wire["chart_kind"],
            ("timeline", "calendar", "stack", "ranking", "monitor"),
            "custom.chart_kind",
        )
        group_by = _optional_string(custom_wire["group_by"], "custom.group_by")
        partition_by = _optional_string(custom_wire.get("partition_by"), "custom.partition_by")
        if partition_by is not None and chart_kind != "ranking":
            raise DashboardPresetValidationError("custom.partition_by is supported only by ranking")
        if partition_by is not None and group_by is None:
            raise DashboardPresetValidationError(
                "custom.partition_by requires a non-null custom.group_by"
            )
        if partition_by is not None and partition_by == group_by:
            raise DashboardPresetValidationError(
                "custom.partition_by and custom.group_by must differ"
            )
        date_range = _date_range_parse(custom_wire["date_range"])
        if isinstance(date_range, TimestampRange) and not ranking:
            raise DashboardPresetValidationError(
                "timestamp date_range is supported only by v2 custom ranking"
            )
        chart = CustomChartConfig(
            chart_kind,
            source,
            date_range,
            _custom_filters_parse(custom_wire["filters"]),
            _presentation_parse(custom_wire["presentation"], chart_kind),
            group_by,
            _optional_int(custom_wire["top"], "custom.top", minimum=1),
            _choice(custom_wire["other"], ("show", "hide"), "custom.other"),
            (
                "day"
                if ranking
                else _choice(custom_wire["granularity"], GRANULARITIES, "custom.granularity")
            ),
            _choice(custom_wire["weekdays"], ("show", "hide"), "custom.weekdays"),
            initial_explicit=(
                _PERSISTED_CUSTOM_EXPLICIT - {"granularity"}
                if ranking
                else _PERSISTED_CUSTOM_EXPLICIT
            ),
            metric_id=_optional_string(custom_wire["metric_id"], "custom.metric_id"),
            metric_summary=_choice(
                custom_wire["metric_summary"],
                ("comparisons", "total", "none"),
                "custom.metric_summary",
            ),
            metric_periods=_string_list(custom_wire["metric_periods"], "custom.metric_periods"),
            metric_titles=titles,
            partition_by=partition_by,
        )
        ranking_item_spacing = _choice(
            custom_wire["ranking_item_spacing"],
            CUSTOM_RANKING_ITEM_SPACINGS,
            "custom.ranking_item_spacing",
        )
        try:
            return CustomChartPaneConfig(chart, *attachment, ranking_item_spacing)
        except ValueError as exc:
            raise DashboardPresetValidationError(str(exc)) from exc
    if kind == "animation":
        _exact(wire, frozenset(("kind", "style", "overlay")), "animation pane")
        try:
            spec = animation_spec(_string(wire["style"], "animation.style"), target="pane")
        except Exception as exc:
            raise DashboardPresetValidationError("unsupported animation style") from exc
        return AnimationPaneConfig(spec, _overlay_parse(wire["overlay"]))
    raise DashboardPresetValidationError(f"unsupported pane kind: {kind}")

def _pane_wire(pane: object) -> dict[str, object]:
    if isinstance(pane, EmptyPaneConfig):
        return {"kind": "empty"}
    if isinstance(pane, AnimationPaneConfig):
        return {
            "kind": "animation",
            "style": pane.animation.style,
            "overlay": _overlay_wire(pane.overlay),
        }
    if isinstance(pane, CustomChartPaneConfig):
        wire = _chart_wire(pane.chart)
        attachment = _attachment_wire(
            style=pane.attachment_style,
            theme=pane.attachment_theme,
        )
        if attachment is not None:
            wire["attachment"] = attachment
        wire["ranking_item_spacing"] = pane.ranking_item_spacing
        return wire
    if isinstance(pane, ChartPaneConfig):
        wire = _chart_wire(pane.chart)
        attachment = _attachment_wire(
            style=pane.attachment_style,
            theme=pane.attachment_theme,
        )
        if attachment is not None:
            wire["attachment"] = attachment
        return wire
    raise AssertionError(f"unsupported pane type: {type(pane)!r}")
