from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ccusage_viz.core.time import parse_period
from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomComparison,
    CustomData,
    CustomDataset,
    CustomDimension,
    CustomEnvironmentDeclaration,
    CustomFilter,
    CustomFilterOption,
    CustomPoint,
    CustomProbeDescriptor,
    CustomProtocolFailure,
    CustomProtocolWarning,
    CustomSeries,
    CustomSummary,
    CustomSummaryCurrent,
    CustomSummaryMetric,
    CustomUnit,
    LocalizedText,
)

PROTOCOL_VERSION = "ccuv.custom/v1"
_ERROR_CODES = frozenset(
    {
        "unsupported_dataset",
        "unsupported_chart_kind",
        "unsupported_query",
        "invalid_request",
        "invalid_filter",
        "range_not_available",
        "source_unavailable",
        "internal_error",
    }
)
_DECIMAL_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?$")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class CustomProtocolError(ValueError):
    """A command response violates the custom-command protocol."""

    def __init__(self, message: str, *, failure: CustomProtocolFailure | None = None) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class CustomChartRequest:
    request_id: str
    dataset_id: str
    timezone: str
    start_date: date
    end_date: date
    period: str | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    group_by: str | None = None
    granularity: str = "day"
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["chart"] = "chart"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _validate_timezone(self.timezone)
        if self.end_date < self.start_date:
            raise ValueError("custom request range end date must not precede start date")
        if self.period is not None:
            try:
                parse_period(self.period)
            except ValueError as exc:
                raise ValueError("custom request period must be a valid period") from exc
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "timezone": self.timezone,
            "range": {
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "period": self.period,
            },
            "query": {
                "filters": {key: list(values) for key, values in self.filters},
                "group_by": self.group_by,
                "granularity": self.granularity,
            },
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class CustomSummaryRequest:
    request_id: str
    dataset_id: str
    timezone: str
    scope: str
    current: DateInterval
    sequential: DateInterval | None = None
    year_over_year: DateInterval | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["summary"] = "summary"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _validate_timezone(self.timezone)
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        intervals: dict[str, object] = {"current": _interval_wire(self.current)}
        if self.sequential is not None:
            intervals["sequential"] = _interval_wire(self.sequential)
        if self.year_over_year is not None:
            intervals["year_over_year"] = _interval_wire(self.year_over_year)
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "timezone": self.timezone,
            "query": {"filters": {key: list(values) for key, values in self.filters}},
            "summary": {"scope": self.scope, "intervals": intervals},
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class CustomProbeRequest:
    request_id: str
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["probe"] = "probe"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


CustomRequest: TypeAlias = CustomChartRequest | CustomSummaryRequest | CustomProbeRequest


@dataclass(frozen=True, slots=True)
class CustomChartResponse:
    dataset: CustomDataset
    capabilities: CustomCapabilities
    data: CustomData
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class CustomSummaryResponse:
    summary: CustomSummary
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class CustomProbeResponse:
    dataset_id: str
    descriptor: CustomProbeDescriptor
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


CustomResponse: TypeAlias = CustomChartResponse | CustomSummaryResponse | CustomProbeResponse

# Internal compatibility names. The wire protocol accepts only chart/summary.
CustomPaneRequest = CustomChartRequest
CustomDashboardSummaryRequest = CustomSummaryRequest


@dataclass(frozen=True, slots=True)
class CustomPaneResponse(CustomChartResponse):
    """Legacy in-process chart fixture shape retained during the UI migration."""

    summary: object


CustomDashboardSummaryResponse = CustomSummaryResponse


def canonical_custom_request_key(request: CustomRequest) -> tuple[object, ...]:
    if isinstance(request, CustomProbeRequest):
        return (request.command_argv, request.execution_context, request.request_kind)
    common: tuple[object, ...] = (
        request.command_argv,
        request.execution_context,
        request.dataset_id,
        request.request_kind,
    )
    common += (request.timezone,)
    if isinstance(request, CustomChartRequest):
        return common + (
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.period,
            request.filters,
            request.group_by,
            request.granularity,
        )
    if isinstance(request, CustomSummaryRequest):
        return common + (
            request.filters,
            request.scope,
            _interval_key(request.current),
            _interval_key(request.sequential),
            _interval_key(request.year_over_year),
        )
    return common


def parse_custom_response(raw: bytes, request: CustomRequest) -> CustomResponse:
    try:
        root = _mapping(json.loads(raw.decode("utf-8")), "response")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CustomProtocolError("custom response must be valid UTF-8 JSON") from error
    _validate_envelope(root, request)
    status = _string(root.get("status"), "response status")
    if status == "error":
        raise _parse_failure(root)
    if status != "ok":
        raise CustomProtocolError("response status must be 'ok' or 'error'")
    warnings = _parse_warnings(root.get("warnings"))
    if isinstance(request, CustomChartRequest):
        return CustomChartResponse(
            _parse_dataset(root.get("dataset")),
            _parse_capabilities(root.get("capabilities")),
            _parse_data(root.get("data")),
            warnings=warnings,
        )
    if isinstance(request, CustomSummaryRequest):
        return CustomSummaryResponse(_parse_summary(root.get("summary")), warnings=warnings)
    return CustomProbeResponse(
        _string(root.get("dataset_id"), "probe response dataset ID"),
        _parse_probe_descriptor(root.get("descriptor")),
        warnings=warnings,
    )


def _validate_envelope(root: dict[str, object], request: CustomRequest) -> None:
    if root.get("protocol") != PROTOCOL_VERSION:
        raise CustomProtocolError(f"unsupported protocol version: {root.get('protocol')!r}")
    for field_name, expected in (
        ("request_id", request.request_id),
        ("request_kind", request.request_kind),
    ):
        received = root.get(field_name)
        if received != expected:
            detail = (
                f"response {field_name} does not match request "
                f"(expected {expected!r}, received {received!r})"
            )
            if field_name == "request_id" and root.get("status") == "error":
                detail += (
                    "; the local command did not echo this request ID, which usually means "
                    "a protocol-incompatible command version"
                )
            raise CustomProtocolError(detail)


def _parse_failure(root: dict[str, object]) -> CustomProtocolError:
    error = _mapping(root.get("error"), "error")
    code = _string(error.get("code"), "error code")
    if code not in _ERROR_CODES:
        raise CustomProtocolError(f"unknown protocol error code: {code}")
    message = _parse_localized(error.get("message"), "error message")
    detail = error.get("unsupported")
    unsupported: dict[str, str] | None = None
    if detail is not None:
        parsed = _mapping(detail, "unsupported error detail")
        if set(parsed) != {"field", "value"} or not all(
            isinstance(item, str) for item in parsed.values()
        ):
            raise CustomProtocolError(
                "unsupported error detail must contain string field and value"
            )
        unsupported = {key: value for key, value in parsed.items() if isinstance(value, str)}
    failure = CustomProtocolFailure(code, message, unsupported)
    return CustomProtocolError(f"{code}: {message.en}", failure=failure)


def _parse_warnings(value: object) -> tuple[CustomProtocolWarning, ...]:
    if value is None:
        return ()
    return tuple(
        CustomProtocolWarning(
            _string(_mapping(item, "warning").get("code"), "warning code"),
            _parse_localized(_mapping(item, "warning").get("message"), "warning message"),
        )
        for item in _sequence(value, "warnings")
    )


def _parse_dataset(value: object) -> CustomDataset:
    source = _mapping(value, "dataset")
    return CustomDataset(
        _parse_localized(source.get("title"), "dataset title"),
        _parse_localized(source.get("description"), "dataset description"),
        _parse_unit(source.get("unit")),
    )


def _parse_capabilities(value: object) -> CustomCapabilities:
    source = _mapping(value, "capabilities")
    dimensions = tuple(
        _parse_dimension(item, "group-by dimension")
        for item in _sequence(source.get("group_by"), "capabilities group_by")
    )
    filters = tuple(
        _parse_filter(item) for item in _sequence(source.get("filters"), "capabilities filters")
    )
    charts = _mapping(source.get("charts"), "capabilities charts")
    parsed: dict[str, CustomChartCapability] = {}
    for kind, item in charts.items():
        if kind not in {"timeline", "calendar", "stack", "ranking"}:
            raise CustomProtocolError(f"unsupported chart capability: {kind}")
        chart = _mapping(item, f"chart capability {kind}")
        parsed[kind] = CustomChartCapability(
            _string_tuple(chart.get("granularities"), f"chart {kind} granularities"),
            _string_tuple(chart.get("group_by"), f"chart {kind} group_by"),
            _string_tuple(chart.get("filters"), f"chart {kind} filters"),
        )
    _unique_ids(dimensions, "group-by dimensions")
    _unique_ids(filters, "filters")
    return CustomCapabilities(dimensions, filters, parsed)


def _parse_probe_descriptor(value: object) -> CustomProbeDescriptor:
    source = _mapping(value, "probe descriptor")
    revision = _string(source.get("revision"), "probe descriptor revision")
    version = _string(source.get("version"), "probe descriptor version")
    source_timezone = source.get("source_timezone")
    if source_timezone is not None:
        source_timezone = _string(source_timezone, "probe descriptor source_timezone")
        _validate_timezone(source_timezone)
    defaults_source = _mapping(source.get("defaults"), "probe descriptor defaults")
    defaults: dict[str, CustomChartDefaults] = {}
    for kind, value in defaults_source.items():
        if kind not in {"timeline", "calendar", "stack", "ranking"}:
            raise CustomProtocolError(f"unsupported chart default: {kind}")
        item = _mapping(value, f"chart default {kind}")
        if set(item) != {"period", "group_by", "top"}:
            raise CustomProtocolError(f"chart default {kind} must contain period, group_by, and top")
        period = item["period"]
        group_by = item["group_by"]
        top = item["top"]
        if period is not None:
            period = _string(period, f"chart default {kind} period")
            try:
                parse_period(period)
            except ValueError as exc:
                raise CustomProtocolError(f"chart default {kind} period must be valid") from exc
        if group_by is not None:
            group_by = _string(group_by, f"chart default {kind} group_by")
        if top is not None and (not isinstance(top, int) or isinstance(top, bool) or top < 1):
            raise CustomProtocolError(f"chart default {kind} top must be a positive integer")
        defaults[kind] = CustomChartDefaults(period, group_by, top)
    environment = tuple(
        _parse_environment_declaration(item) for item in _sequence(source.get("environment"), "environment")
    )
    if len({item.name for item in environment}) != len(environment):
        raise CustomProtocolError("environment names must be unique")
    return CustomProbeDescriptor(
        revision,
        version,
        _parse_dataset(source.get("dataset")),
        _parse_capabilities(source.get("capabilities")),
        defaults,
        environment,
        source_timezone,
    )


def parse_probe_descriptor(value: object) -> CustomProbeDescriptor:
    """Parse a persisted static Dataset descriptor without a response envelope."""

    return _parse_probe_descriptor(value)


def probe_descriptor_to_wire(descriptor: CustomProbeDescriptor) -> dict[str, object]:
    """Serialize the safe static metadata persisted for a managed Dataset."""

    def localized(value: LocalizedText) -> dict[str, str]:
        return {"en": value.en, "zh-CN": value.zh_cn}

    def unit(value: CustomUnit) -> dict[str, object]:
        return {
            "id": value.id,
            "label": localized(value.label),
            "placement": value.placement,
            "decimal_places": value.decimal_places,
        }

    def dataset(value: CustomDataset) -> dict[str, object]:
        return {
            "title": localized(value.title),
            "description": localized(value.description),
            "unit": unit(value.unit),
        }

    capabilities = {
        "group_by": [
            {"id": item.id, "label": localized(item.label)}
            for item in descriptor.capabilities.group_by
        ],
        "filters": [
            {
                "id": item.id,
                "label": localized(item.label),
                "mode": item.mode,
                "options": [
                    {"id": option.id, "label": localized(option.label)}
                    for option in item.options
                ],
            }
            for item in descriptor.capabilities.filters
        ],
        "charts": {
            kind: {
                "granularities": list(value.granularities),
                "group_by": list(value.group_by),
                "filters": list(value.filters),
            }
            for kind, value in sorted(descriptor.capabilities.charts.items())
        },
    }
    return {
        "revision": descriptor.revision,
        "version": descriptor.version,
        **(
            {"source_timezone": descriptor.source_timezone}
            if descriptor.source_timezone is not None
            else {}
        ),
        "dataset": dataset(descriptor.dataset),
        "capabilities": capabilities,
        "defaults": {
            kind: {"period": value.period, "group_by": value.group_by, "top": value.top}
            for kind, value in sorted(descriptor.defaults.items())
        },
        "environment": [
            {
                "name": item.name,
                "required": item.required,
                "sensitive": item.sensitive,
                "label": localized(item.label),
                "how_to_get": localized(item.how_to_get),
                **({"help_url": item.help_url} if item.help_url is not None else {}),
            }
            for item in descriptor.environment
        ],
    }


def _parse_environment_declaration(value: object) -> CustomEnvironmentDeclaration:
    source = _mapping(value, "environment declaration")
    expected = {"name", "required", "sensitive", "label", "how_to_get"}
    if set(source) - (expected | {"help_url"}) or not expected <= set(source):
        raise CustomProtocolError("environment declaration has invalid fields")
    required = source["required"]
    sensitive = source["sensitive"]
    if not isinstance(required, bool) or not isinstance(sensitive, bool):
        raise CustomProtocolError("environment declaration required and sensitive must be booleans")
    help_url = source.get("help_url")
    if help_url is not None:
        help_url = _string(help_url, "environment declaration help_url")
    return CustomEnvironmentDeclaration(
        _string(source["name"], "environment declaration name"),
        required,
        sensitive,
        _parse_localized(source["label"], "environment declaration label"),
        _parse_localized(source["how_to_get"], "environment declaration how_to_get"),
        help_url,
    )


def _parse_dimension(value: object, name: str) -> CustomDimension:
    source = _mapping(value, name)
    return CustomDimension(
        _string(source.get("id"), f"{name} ID"),
        _parse_localized(source.get("label"), f"{name} label"),
    )


def _parse_filter(value: object) -> CustomFilter:
    source = _mapping(value, "filter")
    if source.get("mode") != "multi_select":
        raise CustomProtocolError("custom filters must use multi_select mode")
    options = tuple(
        _parse_dimension(item, "filter option")
        for item in _sequence(source.get("options"), "filter options")
    )
    _unique_ids(options, "filter options")
    return CustomFilter(
        _string(source.get("id"), "filter ID"),
        _parse_localized(source.get("label"), "filter label"),
        tuple(CustomFilterOption(item.id, item.label) for item in options),
    )


def _parse_data(value: object) -> CustomData:
    source = _mapping(value, "data")
    series = tuple(_parse_series(item) for item in _sequence(source.get("series"), "data series"))
    _unique_ids(series, "data series")
    return CustomData(series)


def _parse_series(value: object) -> CustomSeries:
    source = _mapping(value, "series")
    points = tuple(
        _parse_point(point) for point in _sequence(source.get("points"), "series points")
    )
    if len({point.date for point in points}) != len(points):
        raise CustomProtocolError("series point dates must be unique")
    return CustomSeries(
        _string(source.get("id"), "series ID"),
        _parse_localized(source.get("label"), "series label"),
        points,
    )


def _parse_point(value: object) -> CustomPoint:
    source = _mapping(value, "point")
    return CustomPoint(
        _parse_date(source.get("date"), "point date"),
        _parse_decimal(source.get("value"), "point value"),
    )


def _parse_summary(value: object) -> CustomSummary:
    source = _mapping(value, "summary")
    metric = _mapping(source.get("metric"), "metric")
    current = _mapping(metric.get("current"), "metric current")
    return CustomSummary(
        CustomSummaryMetric(
            _string(metric.get("id"), "metric ID"),
            _parse_localized(metric.get("label"), "metric label"),
            CustomSummaryCurrent(
                _parse_decimal(current.get("value"), "metric current value"),
                _parse_localized(current.get("display"), "metric current display"),
            ),
            _parse_comparison(metric.get("sequential"), "sequential comparison"),
            _parse_comparison(metric.get("year_over_year"), "year-over-year comparison"),
        )
    )


def _parse_comparison(value: object, name: str) -> CustomComparison:
    source = _mapping(value, name)
    status = _string(source.get("status"), f"{name} status")
    if status not in {"ready", "pending", "unavailable"}:
        raise CustomProtocolError(f"invalid {name} status: {status}")
    has_base = "base_value" in source
    if status == "ready":
        if not has_base:
            raise CustomProtocolError(f"ready {name} requires base_value")
        base = _parse_decimal(source["base_value"], f"{name} base_value")
    else:
        if has_base:
            raise CustomProtocolError(f"{status} {name} must omit base_value")
        base = None
    return CustomComparison(status, base)  # type: ignore[arg-type]


def _parse_unit(value: object) -> CustomUnit:
    source = _mapping(value, "unit")
    placement = _string(source.get("placement"), "unit placement")
    decimals = source.get("decimal_places")
    if placement not in {"prefix", "suffix"}:
        raise CustomProtocolError("unit placement must be prefix or suffix")
    if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
        raise CustomProtocolError("unit decimal_places must be a non-negative integer")
    return CustomUnit(
        _string(source.get("id"), "unit ID"),
        _parse_localized(source.get("label"), "unit label"),
        placement,
        decimals,
    )  # type: ignore[arg-type]


def _parse_localized(value: object, name: str) -> LocalizedText:
    source = _mapping(value, name)
    return LocalizedText(
        _string(source.get("en"), f"{name} en"), _string(source.get("zh-CN"), f"{name} zh-CN")
    )


def _parse_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise CustomProtocolError(f"{name} must be a decimal string")
    if not _DECIMAL_RE.fullmatch(value):
        raise CustomProtocolError(f"{name} must be an ordinary decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise CustomProtocolError(f"{name} must be a decimal string") from error


def _parse_date(value: object, name: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise CustomProtocolError(f"{name} must be an ISO-8601 date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise CustomProtocolError(f"{name} must be an ISO-8601 date") from error


def _canonical_filters(
    filters: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, values in filters:
        _require_id(key, "filter ID")
        normalized[key] = tuple(sorted(set(values)))
    return tuple(sorted(normalized.items()))


def _interval_wire(interval: DateInterval) -> dict[str, str]:
    return {"start_date": interval.since.isoformat(), "end_date": interval.until.isoformat()}


def _interval_key(interval: DateInterval | None) -> tuple[str, str] | None:
    return None if interval is None else (interval.since.isoformat(), interval.until.isoformat())


def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CustomProtocolError(f"{name} must be an object")
    return value


def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise CustomProtocolError(f"{name} must be an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CustomProtocolError(f"{name} must be a non-empty string")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    values = tuple(_string(item, name) for item in _sequence(value, name))
    if len(set(values)) != len(values):
        raise CustomProtocolError(f"{name} must not contain duplicates")
    return values


def _unique_ids(
    items: tuple[CustomDimension | CustomFilter | CustomSeries, ...], name: str
) -> None:
    if len({item.id for item in items}) != len(items):
        raise CustomProtocolError(f"{name} IDs must be unique")


def _validate_timezone(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("timezone must not be empty")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"timezone must be a valid IANA timezone: {value}") from error


def _require_id(value: str, name: str) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")
