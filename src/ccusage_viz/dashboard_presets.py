"""Strict Dashboard preset wire models and runtime adapters.

Presets are user-local trusted automation. They preserve declarative Dashboard
configuration, including local command argv and executable Overlay commands, but
never process environments, query results, or live TUI state.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from math import isfinite
from typing import TypeAlias, TypeVar, cast

from ccusage_viz.animation import animation_spec
from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.core.time import DateRange, parse_period, validate_timezone
from ccusage_viz.dashboard_layout import layout_bands, parse_layout
from ccusage_viz.options import (
    CACHE_MODES,
    COMMAND_STYLES,
    DASHBOARD_STYLES,
    DENSITIES,
    GRANULARITIES,
    HEADER_SUMMARIES,
    AnimationPaneConfig,
    CalendarConfig,
    ChartPaneConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomChartPaneConfig,
    CustomCommandSource,
    CustomFilters,
    DashboardHostConfig,
    DashboardLaunch,
    EmptyPaneConfig,
    Filters,
    MonitorConfig,
    PaneConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    TimelineConfig,
)
from ccusage_viz.project_identity import PROJECT_AGGREGATIONS

PRESET_SCHEMA = "ccuv.dashboard-presets/v1"
PRESET_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_PERSISTED_CUSTOM_EXPLICIT = frozenset(
    {
        "period",
        "since",
        "until",
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


class DashboardPresetValidationError(ValueError):
    """A wire preset is malformed, unsupported, or unsafe to materialize."""


DatasetSourceResolver: TypeAlias = Callable[[str], CustomCommandSource]
Choice = TypeVar("Choice", bound=str)


def validate_preset_name(name: str) -> str:
    """Return a safe Dashboard preset identifier or raise a precise validation error."""

    if not isinstance(name, str) or PRESET_NAME_PATTERN.fullmatch(name) is None:
        raise DashboardPresetValidationError(
            "preset name must start with a lowercase letter and contain only lowercase "
            "letters, digits, or hyphens"
        )
    return name


def _expect_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise DashboardPresetValidationError(f"{label} must be an object")
    return value


def _exact(value: object, fields: frozenset[str], label: str) -> Mapping[str, object]:
    mapping = _expect_mapping(value, label)
    actual = frozenset(mapping)
    if actual != fields:
        missing = ", ".join(sorted(fields - actual))
        extra = ", ".join(sorted(actual - fields))
        detail = "; ".join(
            part
            for part in (
                f"missing: {missing}" if missing else "",
                f"unknown: {extra}" if extra else "",
            )
            if part
        )
        raise DashboardPresetValidationError(f"{label} has invalid fields ({detail})")
    return mapping


def _string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise DashboardPresetValidationError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise DashboardPresetValidationError(f"{label} must be a boolean")
    return value


def _integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DashboardPresetValidationError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise DashboardPresetValidationError(f"{label} must be at least {minimum}")
    return value


def _number(value: object, label: str, *, minimum: float | None = None) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)):
        raise DashboardPresetValidationError(f"{label} must be a finite number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise DashboardPresetValidationError(f"{label} must be at least {minimum}")
    return result


def _choice(
    value: object, choices: Sequence[Choice] | set[Choice] | frozenset[Choice], label: str
) -> Choice:
    text = _string(value, label)
    if text not in choices:
        raise DashboardPresetValidationError(f"unsupported {label}: {text}")
    return cast(Choice, text)


def _optional_choice(
    value: object, choices: Sequence[Choice] | set[Choice] | frozenset[Choice], label: str
) -> Choice | None:
    if value is None:
        return None
    return _choice(value, choices, label)


def _timestamp(value: object, label: str) -> datetime:
    text = _string(value, label)
    if not text.endswith("Z"):
        raise DashboardPresetValidationError(f"{label} must be a UTC RFC3339 timestamp")
    try:
        result = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise DashboardPresetValidationError(f"invalid {label}") from exc
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise DashboardPresetValidationError(f"{label} must be UTC")
    return result.astimezone(UTC)


def _timestamp_wire(value: datetime) -> str:
    if value.tzinfo is None:
        raise DashboardPresetValidationError("preset timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _date(value: object, label: str) -> date:
    text = _string(value, label)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DashboardPresetValidationError(f"invalid {label}") from exc


def _date_wire(value: date) -> str:
    return value.isoformat()


def _weights(value: object, label: str) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise DashboardPresetValidationError(f"{label} must be an array or null")
    result = tuple(_integer(item, f"{label} item", minimum=1) for item in value)
    if not result:
        raise DashboardPresetValidationError(f"{label} must not be empty")
    return result


def _weights_wire(value: tuple[int, ...] | None) -> list[int] | None:
    return list(value) if value is not None else None


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DashboardPresetValidationError(f"{label} must be an array")
    return tuple(_string(item, f"{label} item") for item in value)


def _filters_wire(value: Filters) -> dict[str, list[str]]:
    return {
        "agents": list(value.agents),
        "models": list(value.models),
        "projects": list(value.projects),
    }


def _filters_parse(value: object) -> Filters:
    wire = _exact(value, frozenset(("agents", "models", "projects")), "filters")
    return Filters(
        agents=_string_list(wire["agents"], "filters.agents"),
        models=_string_list(wire["models"], "filters.models"),
        projects=_string_list(wire["projects"], "filters.projects"),
    )


def _presentation_wire(value: ChartPresentation) -> dict[str, str]:
    return {
        "theme": value.theme,
        "style": value.style,
        "legend": value.legend,
        "density": value.density,
    }


def _presentation_parse(value: object, kind: str) -> ChartPresentation:
    wire = _exact(value, frozenset(("theme", "style", "legend", "density")), "presentation")
    style = _choice(wire["style"], COMMAND_STYLES[kind], "presentation.style")
    return ChartPresentation(
        theme=_string(wire["theme"], "presentation.theme"),
        style=style,
        legend=_string(wire["legend"], "presentation.legend"),
        density=_choice(wire["density"], DENSITIES, "presentation.density"),  # type: ignore[arg-type]
    )


def _date_range_wire(value: DateRange) -> dict[str, object]:
    return {
        "since": _date_wire(value.since),
        "until": _date_wire(value.until),
        "relative_until": value.relative_until,
        "period": value.period,
        "fixed_bounds": value.fixed_bounds,
        "implicit_until": value.implicit_until,
    }


def _date_range_parse(value: object) -> DateRange:
    wire = _exact(
        value,
        frozenset(("since", "until", "relative_until", "period", "fixed_bounds", "implicit_until")),
        "date_range",
    )
    since, until = (
        _date(wire["since"], "date_range.since"),
        _date(wire["until"], "date_range.until"),
    )
    if since > until:
        raise DashboardPresetValidationError("date_range.since must not be after date_range.until")
    relative_until = _boolean(wire["relative_until"], "date_range.relative_until")
    period = _optional_string(wire["period"], "date_range.period")
    if period == "all":
        if not relative_until:
            raise DashboardPresetValidationError("date_range all period must be relative")
    elif period is not None:
        try:
            parse_period(period)
        except ValueError as exc:
            raise DashboardPresetValidationError("invalid date_range.period") from exc
        if not relative_until:
            raise DashboardPresetValidationError("date_range period must be relative")
    elif relative_until:
        raise DashboardPresetValidationError("relative date_range requires a period")
    return DateRange(
        since,
        until,
        relative_until=relative_until,
        period=period,
        fixed_bounds=_boolean(wire["fixed_bounds"], "date_range.fixed_bounds"),
        implicit_until=_boolean(wire["implicit_until"], "date_range.implicit_until"),
    )


def _custom_filters_wire(value: CustomFilters) -> list[dict[str, object]]:
    return [{"id": identifier, "values": list(values)} for identifier, values in value]


def _custom_filters_parse(value: object) -> CustomFilters:
    if not isinstance(value, list):
        raise DashboardPresetValidationError("custom filters must be an array")
    result: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        wire = _exact(item, frozenset(("id", "values")), f"custom filters[{index}]")
        identifier = _string(wire["id"], f"custom filters[{index}].id")
        if identifier in seen:
            raise DashboardPresetValidationError("custom filter IDs must be unique")
        seen.add(identifier)
        result.append((identifier, _string_list(wire["values"], f"custom filters[{index}].values")))
    return tuple(result)


def _overlay_wire(value: OverlayConfig) -> dict[str, object]:
    return {
        "text": value.text,
        "command": value.command,
        "time_band": value.time_band,
        "position": value.position,
        "color": value.color,
        "interval": value.interval,
        "max_width": value.max_width,
        "offset_x": value.offset_x,
        "offset_y": value.offset_y,
    }


def _overlay_parse(value: object) -> OverlayConfig:
    wire = _exact(
        value,
        frozenset(
            (
                "text",
                "command",
                "time_band",
                "position",
                "color",
                "interval",
                "max_width",
                "offset_x",
                "offset_y",
            )
        ),
        "overlay",
    )
    try:
        return OverlayConfig(
            text=_optional_string(wire["text"], "overlay.text"),
            command=_optional_string(wire["command"], "overlay.command"),
            time_band=_boolean(wire["time_band"], "overlay.time_band"),
            position=_string(wire["position"], "overlay.position"),
            color=_string(wire["color"], "overlay.color"),
            interval=_number(wire["interval"], "overlay.interval", minimum=5),
            max_width=_integer(wire["max_width"], "overlay.max_width", minimum=1),
            offset_x=_integer(wire["offset_x"], "overlay.offset_x"),
            offset_y=_integer(wire["offset_y"], "overlay.offset_y"),
        )
    except ValueError as exc:
        raise DashboardPresetValidationError("invalid overlay") from exc


def _process_wire(value: ProcessConfig) -> dict[str, object]:
    return {
        "ccusage_bin": value.ccusage_bin,
        "query_timeout": value.query_timeout,
        "output_limit": value.output_limit,
    }


def _process_parse(value: object) -> ProcessConfig:
    wire = _exact(value, frozenset(("ccusage_bin", "query_timeout", "output_limit")), "process")
    return ProcessConfig(
        ccusage_bin=_string(wire["ccusage_bin"], "process.ccusage_bin"),
        query_timeout=_number(wire["query_timeout"], "process.query_timeout", minimum=0.001),
        output_limit=_integer(wire["output_limit"], "process.output_limit", minimum=1),
    )


def _host_wire(value: DashboardHostConfig) -> dict[str, object]:
    return {
        "provider": value.provider,
        "ascii": value.ascii,
        "demo_size": value.demo_size,
        "demo_seed": value.demo_seed,
        "timezone": value.timezone,
        "grid": value.grid,
        "layout": value.layout,
        "column_weights": _weights_wire(value.column_weights),
        "row_weights": _weights_wire(value.row_weights),
        "refresh_interval": value.refresh_interval,
        "sampling_interval": value.sampling_interval,
        "header_style": value.header_style,
        "header_summary": value.header_summary,
        "header_interval": value.header_interval,
        "theme": value.theme,
        "style": value.style,
    }


def _host_parse(value: object, pane_count: int) -> DashboardHostConfig:
    fields = frozenset(
        (
            "provider",
            "ascii",
            "demo_size",
            "demo_seed",
            "timezone",
            "grid",
            "layout",
            "column_weights",
            "row_weights",
            "refresh_interval",
            "sampling_interval",
            "header_style",
            "header_summary",
            "header_interval",
            "theme",
            "style",
        )
    )
    wire = _exact(value, fields, "host")
    provider = _choice(wire["provider"], ("ccusage",), "host.provider")
    timezone = _optional_string(wire["timezone"], "host.timezone")
    if timezone is not None:
        try:
            validate_timezone(timezone)
        except ValueError as exc:
            raise DashboardPresetValidationError("invalid host.timezone") from exc
    demo_seed = wire["demo_seed"]
    if demo_seed is not None:
        demo_seed = _integer(demo_seed, "host.demo_seed")
    grid = _string(wire["grid"], "host.grid")
    layout = _optional_string(wire["layout"], "host.layout")
    configured_layout = layout or grid
    if parse_layout(configured_layout, pane_count) is None:
        raise DashboardPresetValidationError("host grid/layout cannot display every pane")
    bands = layout_bands(configured_layout, pane_count)
    columns, rows = (
        _weights(wire["column_weights"], "host.column_weights"),
        _weights(wire["row_weights"], "host.row_weights"),
    )
    if columns is not None and len(columns) != bands.columns:
        raise DashboardPresetValidationError("host.column_weights do not match layout columns")
    if rows is not None and len(rows) != bands.rows:
        raise DashboardPresetValidationError("host.row_weights do not match layout rows")
    return DashboardHostConfig(
        provider=provider,
        ascii=_boolean(wire["ascii"], "host.ascii"),
        demo_size=_optional_string(wire["demo_size"], "host.demo_size"),
        demo_seed=demo_seed,
        timezone=timezone,
        grid=grid,
        layout=layout,
        column_weights=columns,
        row_weights=rows,
        refresh_interval=_number(wire["refresh_interval"], "host.refresh_interval", minimum=0.001),
        sampling_interval=_number(
            wire["sampling_interval"], "host.sampling_interval", minimum=0.001
        ),
        header_style=_string(wire["header_style"], "host.header_style"),
        header_summary=_choice(wire["header_summary"], HEADER_SUMMARIES, "host.header_summary"),
        header_interval=_number(wire["header_interval"], "host.header_interval", minimum=0.001),
        theme=_string(wire["theme"], "host.theme"),
        style=_choice(wire["style"], DASHBOARD_STYLES, "host.style"),
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
            "group_by": chart.group_by,
            "top": chart.top,
            "other": chart.other,
            "granularity": chart.granularity,
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


def _optional_int(value: object, label: str, *, minimum: int | None = None) -> int | None:
    return None if value is None else _integer(value, label, minimum=minimum)


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
        _exact(
            wire,
            frozenset(("kind", "chart_kind", "date_range", "filters", "presentation", "options")),
            "chart pane",
        )
        return _parse_builtin_chart(wire)
    if kind == "monitor":
        _exact(
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
            _integer(wire["window_seconds"], "monitor.window_seconds", minimum=1),
            _filters_parse(wire["filters"]),
            _presentation_parse(wire["presentation"], "monitor"),
            _optional_choice(
                wire["by"], ("composition", "agent", "model", "project"), "monitor.by"
            ),
            _optional_int(wire["top"], "monitor.top", minimum=1),
            _choice(
                wire["project_aggregation"], PROJECT_AGGREGATIONS, "monitor.project_aggregation"
            ),
            _choice(wire["day_window"], ("today", "yesterday"), "monitor.day_window"),
            _choice(
                wire["distribution_granularity"],
                ("hour", "half-hour"),
                "monitor.distribution_granularity",
            ),
        )
        return ChartPaneConfig(chart)
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
                "group_by",
                "top",
                "other",
                "granularity",
                "weekdays",
                "metric_id",
                "metric_summary",
                "metric_periods",
                "metric_titles",
            )
        )
        _exact(wire, fields, "custom pane")
        dataset_id = _string(wire["dataset_id"], "custom.dataset_id")
        source_kind = _choice(wire["source_kind"], ("command", "installed"), "custom.source_kind")
        command_argv = _string_list(wire["command_argv"], "custom.command_argv")
        try:
            source = CustomCommandSource(dataset_id, command_argv, source_kind)
        except ValueError as exc:
            raise DashboardPresetValidationError(
                "invalid custom command source"
            ) from exc
        titles_value = wire["metric_titles"]
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
        chart = CustomChartConfig(
            _choice(
                wire["chart_kind"],
                ("timeline", "calendar", "stack", "ranking", "monitor"),
                "custom.chart_kind",
            ),
            source,
            _date_range_parse(wire["date_range"]),
            _custom_filters_parse(wire["filters"]),
            _presentation_parse(
                wire["presentation"], _string(wire["chart_kind"], "custom.chart_kind")
            ),
            _optional_string(wire["group_by"], "custom.group_by"),
            _optional_int(wire["top"], "custom.top", minimum=1),
            _choice(wire["other"], ("show", "hide"), "custom.other"),
            _choice(wire["granularity"], GRANULARITIES, "custom.granularity"),
            _choice(wire["weekdays"], ("show", "hide"), "custom.weekdays"),
            initial_explicit=_PERSISTED_CUSTOM_EXPLICIT,
            metric_id=_optional_string(wire["metric_id"], "custom.metric_id"),
            metric_summary=_choice(
                wire["metric_summary"], ("comparisons", "total", "none"), "custom.metric_summary"
            ),
            metric_periods=_string_list(wire["metric_periods"], "custom.metric_periods"),
            metric_titles=titles,
        )
        return CustomChartPaneConfig(chart)
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
        return _chart_wire(pane.chart)
    if isinstance(pane, ChartPaneConfig):
        return _chart_wire(pane.chart)
    raise AssertionError(f"unsupported pane type: {type(pane)!r}")


@dataclass(frozen=True, slots=True)
class DashboardPresetRecord:
    """One validated, version-independent user preset declaration."""

    name: str
    created_at: datetime
    updated_at: datetime
    process: ProcessConfig
    host: DashboardHostConfig
    panes: tuple[PaneConfig, ...]

    def __post_init__(self) -> None:
        validate_preset_name(self.name)
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise DashboardPresetValidationError("preset timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise DashboardPresetValidationError("preset updated_at cannot precede created_at")
        if not self.panes:
            raise DashboardPresetValidationError("a Dashboard preset requires at least one pane")
        _host_parse(_host_wire(self.host), len(self.panes))

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "created_at": _timestamp_wire(self.created_at),
            "updated_at": _timestamp_wire(self.updated_at),
            "process": _process_wire(self.process),
            "host": _host_wire(self.host),
            "panes": [_pane_wire(pane) for pane in self.panes],
        }

    @classmethod
    def parse(
        cls, value: object
    ) -> DashboardPresetRecord:
        wire = _exact(
            value,
            frozenset(("name", "created_at", "updated_at", "process", "host", "panes")),
            "preset",
        )
        name = validate_preset_name(_string(wire["name"], "preset.name"))
        created_at, updated_at = (
            _timestamp(wire["created_at"], "preset.created_at"),
            _timestamp(wire["updated_at"], "preset.updated_at"),
        )
        if updated_at < created_at:
            raise DashboardPresetValidationError("preset updated_at cannot precede created_at")
        if not isinstance(wire["panes"], list) or not wire["panes"]:
            raise DashboardPresetValidationError("preset.panes must be a non-empty array")
        panes = tuple(_parse_pane(pane) for pane in wire["panes"])
        return cls(
            name,
            created_at,
            updated_at,
            _process_parse(wire["process"]),
            _host_parse(wire["host"], len(panes)),
            panes,
        )

    def materialize(self) -> DashboardLaunch:
        return DashboardLaunch(self.process, self.host, self.panes)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DashboardPresetDocument:
    """The complete strict, versioned collection stored in one private file."""

    presets: tuple[DashboardPresetRecord, ...]
    schema: str = PRESET_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PRESET_SCHEMA:
            raise DashboardPresetValidationError("unsupported dashboard preset schema")
        names = [record.name for record in self.presets]
        if len(names) != len(set(names)):
            raise DashboardPresetValidationError("preset names must be unique")

    @classmethod
    def empty(cls) -> DashboardPresetDocument:
        return cls(())

    def to_wire(self) -> dict[str, object]:
        return {"schema": self.schema, "presets": [record.to_wire() for record in self.presets]}

    @classmethod
    def parse(cls, value: object) -> DashboardPresetDocument:
        wire = _exact(value, frozenset(("schema", "presets")), "preset collection")
        if wire["schema"] != PRESET_SCHEMA:
            raise DashboardPresetValidationError("unsupported dashboard preset schema")
        if not isinstance(wire["presets"], list):
            raise DashboardPresetValidationError("preset collection presets must be an array")
        records = tuple(DashboardPresetRecord.parse(item) for item in wire["presets"])
        return cls(records)

    def with_saved(
        self, record: DashboardPresetRecord, clock: Callable[[], datetime]
    ) -> DashboardPresetDocument:
        now = clock().astimezone(UTC)
        existing = next((item for item in self.presets if item.name == record.name), None)
        saved = replace(record, created_at=existing.created_at if existing else now, updated_at=now)
        return DashboardPresetDocument(
            tuple(saved if item.name == saved.name else item for item in self.presets)
            if existing
            else (*self.presets, saved)
        )

    def with_deleted(self, name: str) -> DashboardPresetDocument:
        return DashboardPresetDocument(
            tuple(record for record in self.presets if record.name != name)
        )


def preset_from_launch(
    name: str, launch: DashboardLaunch, *, now: datetime | None = None
) -> DashboardPresetRecord:
    """Create a complete user-local trusted Dashboard preset record."""
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    return DashboardPresetRecord(
        validate_preset_name(name),
        timestamp,
        timestamp,
        launch.process,
        launch.host,
        tuple(launch.panes),
    )


def materialize_preset(
    record: DashboardPresetRecord, source_resolver: DatasetSourceResolver
) -> DashboardLaunch:
    """Resolve durable Dataset IDs and return a fresh ordinary Dashboard launch."""

    panes: list[PaneConfig] = []
    for pane in record.panes:
        if isinstance(pane, CustomChartPaneConfig):
            if pane.chart.source.source_kind == "command":
                panes.append(pane)
                continue
            source = source_resolver(pane.chart.source.dataset_id)
            if (
                source.dataset_id != pane.chart.source.dataset_id
                or source.source_kind != "installed"
            ):
                raise DashboardPresetValidationError(
                    "custom Dataset resolver returned an unsafe source"
                )
            panes.append(CustomChartPaneConfig(replace(pane.chart, source=source)))
        else:
            panes.append(pane)
    return DashboardLaunch(record.process, record.host, tuple(panes))  # type: ignore[arg-type]


def empty_preset_launch(launch: DashboardLaunch) -> DashboardLaunch:
    """Keep a resolved preset's topology/settings while replacing all pane content."""

    return replace(launch, panes=tuple(EmptyPaneConfig() for _ in launch.panes))
