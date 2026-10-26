from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from math import isfinite
from typing import TypeVar, cast

from ccusage_viz.animation_overlay import OverlayConfig
from ccusage_viz.core.custom_ranking_time import TimestampRange, parse_subday_period
from ccusage_viz.core.time import DateRange, parse_period, validate_timezone
from ccusage_viz.dashboard_layout import layout_bands
from ccusage_viz.options import (
    COMMAND_STYLES,
    DASHBOARD_STYLES,
    DENSITIES,
    HEADER_SUMMARIES,
    ChartPresentation,
    CustomFilters,
    DashboardHostConfig,
    Filters,
    ProcessConfig,
)

PRESET_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


class DashboardPresetValidationError(ValueError):
    """A wire preset is malformed, unsupported, or unsafe to materialize."""


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


def _date_range_wire(value: DateRange | TimestampRange) -> dict[str, object]:
    if isinstance(value, TimestampRange):
        return {
            "start_at": _timestamp_wire(value.start_at),
            "end_at": _timestamp_wire(value.end_at),
            "relative_until": value.relative_until,
            "period": value.period,
            "fixed_bounds": value.fixed_bounds,
        }
    return {
        "since": _date_wire(value.since),
        "until": _date_wire(value.until),
        "relative_until": value.relative_until,
        "period": value.period,
        "fixed_bounds": value.fixed_bounds,
        "implicit_until": value.implicit_until,
    }


def _date_range_parse(value: object) -> DateRange | TimestampRange:
    source = _expect_mapping(value, "date_range")
    if "start_at" in source or "end_at" in source:
        wire = _exact(
            source,
            frozenset(("start_at", "end_at", "relative_until", "period", "fixed_bounds")),
            "date_range",
        )
        period = _optional_string(wire["period"], "date_range.period")
        if period is not None:
            try:
                parse_subday_period(period)
            except ValueError as exc:
                raise DashboardPresetValidationError("invalid date_range.period") from exc
        try:
            return TimestampRange(
                _timestamp(wire["start_at"], "date_range.start_at"),
                _timestamp(wire["end_at"], "date_range.end_at"),
                relative_until=_boolean(wire["relative_until"], "date_range.relative_until"),
                period=period,
                fixed_bounds=_boolean(wire["fixed_bounds"], "date_range.fixed_bounds"),
            )
        except ValueError as exc:
            raise DashboardPresetValidationError(str(exc)) from exc
    wire = _exact(
        source,
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
        "columns": value.columns,
        "spotlight": value.spotlight,
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
            "columns",
            "spotlight",
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
    columns_value = _integer(wire["columns"], "host.columns", minimum=1)
    spotlight = _integer(wire["spotlight"], "host.spotlight", minimum=0)
    try:
        bands = layout_bands(columns=columns_value, spotlight=spotlight, pane_count=pane_count)
    except ValueError as exc:
        raise DashboardPresetValidationError(str(exc)) from exc
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
        columns=columns_value,
        spotlight=spotlight,
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


def _optional_int(value: object, label: str, *, minimum: int | None = None) -> int | None:
    return None if value is None else _integer(value, label, minimum=minimum)
