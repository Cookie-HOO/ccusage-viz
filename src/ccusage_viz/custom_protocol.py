from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, TypeAlias
from urllib.parse import urlparse
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
    V2Dataset,
    V2HistoricalChartCapability,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MetricGroup,
    V2MetricValue,
    V2MonitorCapability,
    V2MonitorObservation,
    V2ProbeDescriptor,
    V2Runtime,
)

PROTOCOL_VERSION = "ccuv.custom/v1"
V2_PROTOCOL_VERSION = "ccuv.custom/v2"
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


@dataclass(frozen=True, slots=True)
class V2ProbeRequest:
    request_id: str
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["probe"] = "probe"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2ChartRequest:
    request_id: str
    dataset_id: str
    metric_id: str
    timezone: str
    start_date: date
    end_date: date
    period: str | None = None
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    group_by: str | None = None
    granularity: str = "day"
    top: int | None = None
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["chart"] = "chart"
    partition_by: str | None = None
    partition_declared: bool = False

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _require_id(self.metric_id, "metric ID")
        _validate_timezone(self.timezone)
        if self.end_date < self.start_date:
            raise ValueError("v2 custom request range end date must not precede start date")
        if self.top is not None and self.top < 1:
            raise ValueError("v2 custom request top must be positive")
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        query: dict[str, object] = {
            "filters": {key: list(values) for key, values in self.filters},
            "group_by": self.group_by,
            "granularity": self.granularity,
            "top": self.top,
        }
        if self.partition_declared:
            query["partition_by"] = self.partition_by
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "metric_id": self.metric_id,
            "timezone": self.timezone,
            "range": {
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "period": self.period,
            },
            "query": query,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2MonitorRequest:
    request_id: str
    dataset_id: str
    metric_id: str
    timezone: str
    end_at: datetime
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    group_by: str | None = None
    command_argv: tuple[str, ...] = ()
    execution_context: tuple[tuple[str, str], ...] = ()
    request_kind: Literal["monitor"] = "monitor"

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request ID")
        _require_id(self.dataset_id, "dataset ID")
        _require_id(self.metric_id, "metric ID")
        _validate_timezone(self.timezone)
        if self.end_at.tzinfo is None:
            raise ValueError("v2 monitor end_at must be timezone aware")
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "metric_id": self.metric_id,
            "timezone": self.timezone,
            "range": {"end_at": self.end_at.isoformat()},
            "query": {
                "filters": {key: list(values) for key, values in self.filters},
                "group_by": self.group_by,
            },
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


@dataclass(frozen=True, slots=True)
class V2SummaryRequest:
    request_id: str
    dataset_id: str
    metric_id: str
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
        _require_id(self.metric_id, "metric ID")
        _validate_timezone(self.timezone)
        object.__setattr__(self, "filters", _canonical_filters(self.filters))

    def to_wire(self) -> dict[str, object]:
        intervals: dict[str, object] = {"current": _interval_wire(self.current)}
        if self.sequential is not None:
            intervals["sequential"] = _interval_wire(self.sequential)
        if self.year_over_year is not None:
            intervals["year_over_year"] = _interval_wire(self.year_over_year)
        return {
            "protocol": V2_PROTOCOL_VERSION,
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "dataset_id": self.dataset_id,
            "metric_id": self.metric_id,
            "timezone": self.timezone,
            "query": {"filters": {key: list(values) for key, values in self.filters}},
            "summary": {"scope": self.scope, "intervals": intervals},
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_wire())


CustomRequest: TypeAlias = (
    CustomChartRequest
    | CustomSummaryRequest
    | CustomProbeRequest
    | V2ProbeRequest
    | V2ChartRequest
    | V2MonitorRequest
    | V2SummaryRequest
)


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


@dataclass(frozen=True, slots=True)
class V2ProbeResponse:
    dataset_id: str
    descriptor: V2ProbeDescriptor
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class V2ChartResponse:
    metric_id: str
    data: CustomData
    descriptor: V2ProbeDescriptor
    runtime: V2Runtime
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class V2MonitorResponse:
    metric_id: str
    observation: V2MonitorObservation
    descriptor: V2ProbeDescriptor | None = None
    runtime: V2Runtime = field(default_factory=lambda: V2Runtime(()))
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class V2SummaryResponse:
    metric_id: str
    summary: CustomSummary
    warnings: tuple[CustomProtocolWarning, ...] = field(default=(), kw_only=True)


CustomResponse: TypeAlias = (
    CustomChartResponse
    | CustomSummaryResponse
    | CustomProbeResponse
    | V2ChartResponse
    | V2MonitorResponse
    | V2SummaryResponse
    | V2ProbeResponse
)

# Internal compatibility names. The wire protocol accepts only chart/summary.
CustomPaneRequest = CustomChartRequest
CustomDashboardSummaryRequest = CustomSummaryRequest


@dataclass(frozen=True, slots=True)
class CustomPaneResponse(CustomChartResponse):
    """Legacy in-process chart fixture shape retained during the UI migration."""

    summary: object


CustomDashboardSummaryResponse = CustomSummaryResponse


def canonical_custom_request_key(request: CustomRequest) -> tuple[object, ...]:
    if isinstance(request, (CustomProbeRequest, V2ProbeRequest)):
        return (request.command_argv, request.execution_context, request.request_kind)
    common: tuple[object, ...] = (
        request.command_argv,
        request.execution_context,
        request.dataset_id,
        request.request_kind,
    )
    common += (request.timezone,)
    if isinstance(request, (CustomChartRequest, V2ChartRequest)):
        return common + (
            *((request.metric_id,) if isinstance(request, V2ChartRequest) else ()),
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.period,
            request.filters,
            request.group_by,
            request.granularity,
            request.top if isinstance(request, V2ChartRequest) else None,
            *(
                (request.partition_declared, request.partition_by)
                if isinstance(request, V2ChartRequest)
                else ()
            ),
        )
    if isinstance(request, V2MonitorRequest):
        return common + (
            request.metric_id,
            request.end_at.astimezone(UTC).isoformat(),
            request.filters,
            request.group_by,
        )
    if isinstance(request, V2SummaryRequest):
        return common + (
            request.metric_id,
            request.filters,
            request.scope,
            _interval_key(request.current),
            _interval_key(request.sequential),
            _interval_key(request.year_over_year),
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
    if isinstance(request, V2ChartRequest):
        metric_id = _response_metric_id(root, request.metric_id)
        descriptor = parse_v2_probe_descriptor(root.get("descriptor"))
        _validate_v2_query_descriptor(descriptor, metric_id, "chart")
        return V2ChartResponse(
            metric_id,
            _parse_data(root.get("data"), descriptions_allowed=True),
            descriptor,
            _parse_v2_runtime(root.get("runtime")),
            warnings=warnings,
        )
    if isinstance(request, V2MonitorRequest):
        metric_id = _response_metric_id(root, request.metric_id)
        descriptor = parse_v2_probe_descriptor(root.get("descriptor"))
        _validate_v2_query_descriptor(descriptor, metric_id, "monitor")
        return V2MonitorResponse(
            metric_id,
            _parse_v2_monitor_observation(root.get("observation")),
            descriptor,
            _parse_v2_runtime(root.get("runtime")),
            warnings=warnings,
        )
    if isinstance(request, V2SummaryRequest):
        return V2SummaryResponse(
            _response_metric_id(root, request.metric_id),
            _parse_summary(root.get("summary")),
            warnings=warnings,
        )
    if isinstance(request, CustomChartRequest):
        return CustomChartResponse(
            _parse_dataset(root.get("dataset")),
            _parse_capabilities(root.get("capabilities")),
            _parse_data(root.get("data"), descriptions_allowed=True),
            warnings=warnings,
        )
    if isinstance(request, CustomSummaryRequest):
        return CustomSummaryResponse(_parse_summary(root.get("summary")), warnings=warnings)
    if isinstance(request, V2ProbeRequest):
        return V2ProbeResponse(
            _string(root.get("dataset_id"), "v2 probe response dataset ID"),
            parse_v2_probe_descriptor(root.get("descriptor")),
            warnings=warnings,
        )
    return CustomProbeResponse(
        _string(root.get("dataset_id"), "probe response dataset ID"),
        _parse_probe_descriptor(root.get("descriptor")),
        warnings=warnings,
    )


def _validate_envelope(root: dict[str, object], request: CustomRequest) -> None:
    expected_protocol = (
        V2_PROTOCOL_VERSION
        if isinstance(request, (V2ProbeRequest, V2ChartRequest, V2MonitorRequest, V2SummaryRequest))
        else None
    )
    if root.get("protocol") not in (
        {expected_protocol} if expected_protocol else {PROTOCOL_VERSION, V2_PROTOCOL_VERSION}
    ):
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


def _response_metric_id(root: dict[str, object], expected: str) -> str:
    metric_id = _string(root.get("metric_id"), "v2 response metric ID")
    if metric_id != expected:
        raise CustomProtocolError("v2 response metric ID does not match request")
    return metric_id


def _validate_v2_query_descriptor(
    descriptor: V2ProbeDescriptor, metric_id: str, chart_kind: str
) -> None:
    metric = next((item for item in descriptor.metrics if item.id == metric_id), None)
    if metric is None:
        raise CustomProtocolError("v2 response descriptor does not declare response metric")
    supported = metric.capabilities.charts
    if chart_kind == "chart":
        if not {"timeline", "calendar", "stack", "ranking"} & set(supported):
            raise CustomProtocolError("v2 response descriptor does not support a historical chart")
        return
    if chart_kind not in supported:
        raise CustomProtocolError("v2 response descriptor does not support requested chart kind")


def _parse_v2_runtime(value: object) -> V2Runtime:
    source = _mapping(value, "v2 response runtime")
    if set(source) != {"filters"}:
        raise CustomProtocolError("v2 response runtime must contain only filters")
    filters = tuple(
        _parse_filter(item) for item in _sequence(source.get("filters"), "runtime filters")
    )
    _unique_ids(filters, "runtime filters")
    return V2Runtime(filters)


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
        max_items = chart.get("max_items")
        if max_items is not None and (
            kind != "ranking"
            or not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or max_items < 1
        ):
            raise CustomProtocolError("ranking max_items must be a positive integer")
        descriptions_default = chart.get("descriptions_default", "collapsed")
        if (kind != "ranking" and "descriptions_default" in chart) or descriptions_default not in {
            "expanded",
            "collapsed",
        }:
            raise CustomProtocolError("ranking descriptions_default must be expanded or collapsed")
        comparison = chart.get("comparison", "full")
        if (kind != "ranking" and "comparison" in chart) or comparison not in {
            "full",
            "rank",
            "none",
        }:
            raise CustomProtocolError("ranking comparison must be full, rank, or none")
        show_percentage = chart.get("show_percentage", True)
        if (kind != "ranking" and "show_percentage" in chart) or not isinstance(
            show_percentage, bool
        ):
            raise CustomProtocolError("ranking show_percentage must be a boolean")
        if "sort_direction" in chart:
            raise CustomProtocolError("sort_direction is supported only by v2 ranking capabilities")
        refresh_interval_seconds = chart.get("refresh_interval_seconds")
        if refresh_interval_seconds is not None and (
            not isinstance(refresh_interval_seconds, int)
            or isinstance(refresh_interval_seconds, bool)
            or refresh_interval_seconds < 1
        ):
            raise CustomProtocolError("chart refresh_interval_seconds must be a positive integer")
        parsed[kind] = CustomChartCapability(
            _string_tuple(chart.get("granularities"), f"chart {kind} granularities"),
            _group_by_tuple(chart.get("group_by"), f"chart {kind} group_by"),
            _string_tuple(chart.get("filters"), f"chart {kind} filters"),
            max_items,
            descriptions_default,  # type: ignore[arg-type]
            (),
            comparison,  # type: ignore[arg-type]
            show_percentage,
            refresh_interval_seconds,
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
            raise CustomProtocolError(
                f"chart default {kind} must contain period, group_by, and top"
            )
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
        _parse_environment_declaration(item)
        for item in _sequence(source.get("environment"), "environment")
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


def parse_v2_probe_descriptor(value: object) -> V2ProbeDescriptor:
    """Parse a V2 Dataset descriptor with Metric-owned capabilities."""

    source = _mapping(value, "v2 probe descriptor")
    revision = _string(source.get("revision"), "v2 probe descriptor revision")
    version = _string(source.get("version"), "v2 probe descriptor version")
    source_timezone = source.get("source_timezone")
    if source_timezone is not None:
        source_timezone = _string(source_timezone, "v2 probe descriptor source_timezone")
        _validate_timezone(source_timezone)
    dataset = _mapping(source.get("dataset"), "v2 dataset")
    metric_groups = tuple(
        _parse_v2_metric_group(item)
        for item in _sequence(source.get("metric_groups", []), "v2 metric_groups")
    )
    if len({group.id for group in metric_groups}) != len(metric_groups):
        raise CustomProtocolError("v2 metric group IDs must be unique")
    metrics = tuple(
        _parse_v2_metric(item) for item in _sequence(source.get("metrics"), "v2 metrics")
    )
    if not metrics:
        raise CustomProtocolError("v2 metrics must not be empty")
    if len({metric.id for metric in metrics}) != len(metrics):
        raise CustomProtocolError("v2 metric IDs must be unique")
    group_ids = {group.id for group in metric_groups}
    for metric in metrics:
        if metric.group_id is not None and metric.group_id not in group_ids:
            raise CustomProtocolError("v2 metric group_id must reference a declared metric group")
    default_metric_id = source.get("default_metric_id")
    if default_metric_id is not None:
        default_metric_id = _string(default_metric_id, "v2 default_metric_id")
        if default_metric_id not in {metric.id for metric in metrics}:
            raise CustomProtocolError("v2 default_metric_id must reference a declared metric")
    environment = tuple(
        _parse_environment_declaration(item)
        for item in _sequence(source.get("environment"), "v2 environment")
    )
    if len({item.name for item in environment}) != len(environment):
        raise CustomProtocolError("v2 environment names must be unique")
    return V2ProbeDescriptor(
        revision,
        version,
        V2Dataset(
            _parse_localized(dataset.get("title"), "v2 dataset title"),
            _parse_localized(dataset.get("description"), "v2 dataset description"),
        ),
        metrics,
        environment,
        source_timezone,
        default_metric_id,
        metric_groups,
    )


def _parse_v2_metric_group(value: object) -> V2MetricGroup:
    source = _mapping(value, "v2 metric group")
    identifier = _string(source.get("id"), "v2 metric group ID")
    try:
        _require_id(identifier, "v2 metric group ID")
    except ValueError as error:
        raise CustomProtocolError(str(error)) from error
    return V2MetricGroup(identifier, _parse_localized(source.get("title"), "v2 metric group title"))


def _parse_v2_metric(value: object) -> V2MetricDescriptor:
    source = _mapping(value, "v2 metric")
    aggregation = _string(source.get("aggregation"), "v2 metric aggregation")
    if aggregation not in {"sum", "value"}:
        raise CustomProtocolError("v2 metric aggregation must be sum or value")
    summary = source.get("summary", "comparisons")
    if summary not in {"comparisons", "total", "none"}:
        raise CustomProtocolError("v2 metric summary must be comparisons, total, or none")
    group_id = source.get("group_id")
    if group_id is not None:
        group_id = _string(group_id, "v2 metric group_id")
        try:
            _require_id(group_id, "v2 metric group_id")
        except ValueError as error:
            raise CustomProtocolError(str(error)) from error
    return V2MetricDescriptor(
        _string(source.get("id"), "v2 metric ID"),
        _parse_localized(source.get("title"), "v2 metric title"),
        _parse_localized(source.get("description"), "v2 metric description"),
        _parse_unit(source.get("unit")),
        aggregation,  # type: ignore[arg-type]
        capabilities := _parse_v2_capabilities(source.get("capabilities")),
        _parse_v2_defaults(source.get("defaults"), capabilities),
        summary,  # type: ignore[arg-type]
        group_id,
    )


def _parse_v2_capabilities(value: object) -> V2MetricCapabilities:
    source = _mapping(value, "v2 metric capabilities")
    dimensions = tuple(
        _parse_dimension(item, "v2 group-by dimension")
        for item in _sequence(source.get("group_by"), "v2 capabilities group_by")
    )
    partition_dimensions = (
        tuple(
            _parse_dimension(item, "v2 partition-by dimension")
            for item in _sequence(source.get("partition_by"), "v2 capabilities partition_by")
        )
        if "partition_by" in source
        else None
    )
    if "filters" in source:
        raise CustomProtocolError("v2 metric capabilities must not declare filters")
    charts: dict[str, V2HistoricalChartCapability | V2MonitorCapability] = {}
    for kind, raw in _mapping(source.get("charts"), "v2 capabilities charts").items():
        chart = _mapping(raw, f"v2 chart capability {kind}")
        group_by = _group_by_tuple(chart.get("group_by"), f"v2 chart {kind} group_by")
        partition_by = (
            _group_by_tuple(chart.get("partition_by"), f"v2 chart {kind} partition_by")
            if "partition_by" in chart
            else None
        )
        if partition_by is not None and kind != "ranking":
            raise CustomProtocolError("v2 partition_by is supported only by ranking")
        if "filters" in chart:
            raise CustomProtocolError(f"v2 chart {kind} must not declare filters")
        if kind == "monitor":
            window_seconds = chart.get("window_seconds")
            refresh = chart.get("refresh_interval_seconds")
            if (
                not isinstance(window_seconds, int)
                or isinstance(window_seconds, bool)
                or window_seconds < 1
            ):
                raise CustomProtocolError("v2 monitor window_seconds must be a positive integer")
            if refresh is not None and (
                not isinstance(refresh, int) or isinstance(refresh, bool) or refresh < 1
            ):
                raise CustomProtocolError(
                    "v2 monitor refresh_interval_seconds must be a positive integer"
                )
            charts[kind] = V2MonitorCapability(window_seconds, refresh, group_by, ())
            rate_label = chart.get("rate_label")
            if rate_label is not None:
                charts[kind] = V2MonitorCapability(
                    window_seconds,
                    refresh,
                    group_by,
                    (),
                    _parse_localized(rate_label, "v2 monitor rate_label"),
                )
        elif kind in {"timeline", "calendar", "stack", "ranking"}:
            periods = _string_tuple(chart.get("periods", []), f"v2 chart {kind} periods")
            for period in periods:
                if period != "all":
                    try:
                        parse_period(period)
                    except ValueError as exc:
                        raise CustomProtocolError(f"v2 chart {kind} period must be valid") from exc
            if kind != "ranking" and "all" in periods:
                raise CustomProtocolError("v2 all period is supported only by ranking")
            if "all" in periods and periods[-1] != "all":
                raise CustomProtocolError("v2 ranking all period must be last")
            max_items = chart.get("max_items")
            if max_items is not None and (
                kind != "ranking"
                or not isinstance(max_items, int)
                or isinstance(max_items, bool)
                or max_items < 1
            ):
                raise CustomProtocolError("v2 ranking max_items must be a positive integer")
            descriptions_default = chart.get("descriptions_default", "collapsed")
            if (
                kind != "ranking" and "descriptions_default" in chart
            ) or descriptions_default not in {"expanded", "collapsed"}:
                raise CustomProtocolError(
                    "v2 ranking descriptions_default must be expanded or collapsed"
                )
            comparison = chart.get("comparison", "full")
            if (kind != "ranking" and "comparison" in chart) or comparison not in {
                "full",
                "rank",
                "none",
            }:
                raise CustomProtocolError("v2 ranking comparison must be full, rank, or none")
            show_percentage = chart.get("show_percentage", True)
            if (kind != "ranking" and "show_percentage" in chart) or not isinstance(
                show_percentage, bool
            ):
                raise CustomProtocolError("v2 ranking show_percentage must be a boolean")
            sort_direction = chart.get("sort_direction", "descending")
            if (kind != "ranking" and "sort_direction" in chart) or sort_direction not in {
                "ascending",
                "descending",
            }:
                raise CustomProtocolError(
                    "v2 ranking sort_direction must be ascending or descending"
                )
            refresh_interval_seconds = chart.get("refresh_interval_seconds")
            if refresh_interval_seconds is not None and (
                not isinstance(refresh_interval_seconds, int)
                or isinstance(refresh_interval_seconds, bool)
                or refresh_interval_seconds < 1
            ):
                raise CustomProtocolError(
                    "v2 historical refresh_interval_seconds must be a positive integer"
                )
            charts[kind] = V2HistoricalChartCapability(
                _string_tuple(chart.get("granularities"), f"v2 chart {kind} granularities"),
                group_by,
                (),
                periods,
                max_items,
                descriptions_default,  # type: ignore[arg-type]
                comparison,  # type: ignore[arg-type]
                show_percentage,
                refresh_interval_seconds,
                sort_direction,  # type: ignore[arg-type]
                partition_by,
            )
        else:
            raise CustomProtocolError(f"unsupported v2 chart capability: {kind}")
    _unique_ids(dimensions, "v2 group-by dimensions")
    if partition_dimensions is not None:
        _unique_ids(partition_dimensions, "v2 partition-by dimensions")
    partition_ids = {
        item.id
        for item in (partition_dimensions if partition_dimensions is not None else dimensions)
    }
    for capability in charts.values():
        if not isinstance(capability, V2HistoricalChartCapability):
            continue
        if capability.partition_by is not None:
            for identifier in capability.partition_by:
                if identifier is not None and identifier not in partition_ids:
                    raise CustomProtocolError(
                        "v2 ranking partition_by must reference a declared partition dimension"
                    )
    return V2MetricCapabilities(dimensions, (), charts, partition_dimensions)


def validate_partition_selection(
    partition_by: str | None,
    group_by: str | None,
    capability: V2HistoricalChartCapability | CustomChartCapability,
) -> None:
    """Validate one Ranking partition/group selection."""

    supported = capability.partition_by
    if supported is None:
        if partition_by is not None:
            raise CustomProtocolError("partition_by is not supported by this capability")
        return
    if partition_by not in supported:
        if partition_by is None:
            raise CustomProtocolError("partition_by is required by this capability")
        raise CustomProtocolError("partition_by is not supported by this capability")
    if partition_by is not None and group_by is None:
        raise CustomProtocolError("active partition_by requires a non-null group_by")
    if partition_by is not None and partition_by == group_by:
        raise CustomProtocolError("partition_by and group_by must differ")


def _parse_v2_defaults(
    value: object, capabilities: V2MetricCapabilities
) -> dict[str, CustomChartDefaults]:
    defaults: dict[str, CustomChartDefaults] = {}
    for kind, raw in _mapping(value, "v2 metric defaults").items():
        if kind not in {"timeline", "calendar", "stack", "ranking", "monitor"}:
            continue
        if not isinstance(raw, dict):
            continue
        declared = frozenset(raw)
        period = raw.get("period")
        if (
            not isinstance(period, str)
            or (period != "all" and _valid_period(period) is False)
            or (period == "all" and kind != "ranking")
        ):
            period = None
        group_by = raw.get("group_by")
        if group_by is not None and not isinstance(group_by, str):
            group_by = None
        partition_by = raw.get("partition_by")
        if "partition_by" in raw:
            if kind != "ranking":
                raise CustomProtocolError("v2 default partition_by is supported only by ranking")
            if partition_by is not None and not isinstance(partition_by, str):
                raise CustomProtocolError("v2 default partition_by must be a string or null")
            capability = capabilities.charts.get(kind)
            if not isinstance(capability, V2HistoricalChartCapability):
                raise CustomProtocolError("v2 default partition_by requires a ranking capability")
            try:
                validate_partition_selection(partition_by, group_by, capability)
            except CustomProtocolError as exc:
                raise CustomProtocolError(f"v2 default {exc}") from exc
        else:
            partition_by = None
        top = raw.get("top")
        if not isinstance(top, int) or isinstance(top, bool) or top < 1:
            top = None
        granularity = raw.get("granularity")
        if not isinstance(granularity, str):
            granularity = None
        filters = _default_filters(raw.get("filters"))
        other = raw.get("other") if raw.get("other") in {"show", "hide"} else None
        style = raw.get("style") if isinstance(raw.get("style"), str) else None
        theme = raw.get("theme") if isinstance(raw.get("theme"), str) else None
        window_seconds = _default_window_seconds(raw.get("window"))
        defaults[kind] = CustomChartDefaults(
            period,
            group_by,
            top,
            granularity,
            filters,
            other,
            style,
            theme,
            window_seconds,
            declared,
            partition_by,
        )
    return defaults


def _valid_period(value: str) -> bool:
    try:
        parse_period(value)
    except ValueError:
        return False
    return True


def _default_filters(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, dict):
        return ()
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for filter_id, option_ids in value.items():
        if not isinstance(filter_id, str) or not isinstance(option_ids, list):
            continue
        options = tuple(sorted({item for item in option_ids if isinstance(item, str)}))
        if options:
            parsed.append((filter_id, options))
    return tuple(sorted(parsed))


def _default_window_seconds(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([1-9][0-9]*)([mh])", value)
    if match is None:
        return None
    seconds = int(match.group(1)) * (60 if match.group(2) == "m" else 3600)
    return seconds if 5 * 60 <= seconds <= 24 * 3600 else None


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
                    {"id": option.id, "label": localized(option.label)} for option in item.options
                ],
            }
            for item in descriptor.capabilities.filters
        ],
        "charts": {
            kind: {
                "granularities": list(value.granularities),
                "group_by": list(value.group_by),
                "filters": list(value.filters),
                **(
                    {"descriptions_default": value.descriptions_default}
                    if kind == "ranking" and value.descriptions_default != "collapsed"
                    else {}
                ),
                **({"comparison": value.comparison} if value.comparison != "full" else {}),
                **(
                    {"show_percentage": False}
                    if kind == "ranking" and not value.show_percentage
                    else {}
                ),
                **(
                    {"refresh_interval_seconds": value.refresh_interval_seconds}
                    if value.refresh_interval_seconds is not None
                    else {}
                ),
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


def v2_probe_descriptor_to_wire(descriptor: V2ProbeDescriptor) -> dict[str, object]:
    """Serialize safe V2 descriptor metadata for a local registration snapshot."""

    def localized(value: LocalizedText) -> dict[str, str]:
        return {"en": value.en, "zh-CN": value.zh_cn}

    def unit(value: CustomUnit) -> dict[str, object]:
        return {
            "id": value.id,
            "label": localized(value.label),
            "placement": value.placement,
            "decimal_places": value.decimal_places,
        }

    def capability(value: V2HistoricalChartCapability | V2MonitorCapability) -> dict[str, object]:
        common = {"group_by": list(value.group_by)}
        if isinstance(value, V2MonitorCapability):
            return {
                **common,
                "window_seconds": value.window_seconds,
                **(
                    {"refresh_interval_seconds": value.refresh_interval_seconds}
                    if value.refresh_interval_seconds is not None
                    else {}
                ),
                **(
                    {"rate_label": localized(value.rate_label)}
                    if value.rate_label is not None
                    else {}
                ),
            }
        return {
            **common,
            "granularities": list(value.granularities),
            **(
                {"partition_by": list(value.partition_by)} if value.partition_by is not None else {}
            ),
            **({"periods": list(value.periods)} if value.periods else {}),
            **({"max_items": value.max_items} if value.max_items is not None else {}),
            **(
                {"descriptions_default": value.descriptions_default}
                if value.descriptions_default != "collapsed"
                else {}
            ),
            **({"comparison": value.comparison} if value.comparison != "full" else {}),
            **({"show_percentage": False} if not value.show_percentage else {}),
            **(
                {"sort_direction": value.sort_direction}
                if value.sort_direction != "descending"
                else {}
            ),
            **(
                {"refresh_interval_seconds": value.refresh_interval_seconds}
                if value.refresh_interval_seconds is not None
                else {}
            ),
        }

    return {
        "revision": descriptor.revision,
        "version": descriptor.version,
        **({"source_timezone": descriptor.source_timezone} if descriptor.source_timezone else {}),
        "dataset": {
            "title": localized(descriptor.dataset.title),
            "description": localized(descriptor.dataset.description),
        },
        **(
            {
                "metric_groups": [
                    {"id": group.id, "title": localized(group.title)}
                    for group in descriptor.metric_groups
                ]
            }
            if descriptor.metric_groups
            else {}
        ),
        "metrics": [
            {
                "id": metric.id,
                "title": localized(metric.title),
                "description": localized(metric.description),
                "unit": unit(metric.unit),
                "aggregation": metric.aggregation,
                "capabilities": {
                    "group_by": [
                        {"id": item.id, "label": localized(item.label)}
                        for item in metric.capabilities.group_by
                    ],
                    **(
                        {
                            "partition_by": [
                                {"id": item.id, "label": localized(item.label)}
                                for item in metric.capabilities.partition_by
                            ]
                        }
                        if metric.capabilities.partition_by is not None
                        else {}
                    ),
                    "charts": {
                        kind: capability(item) for kind, item in metric.capabilities.charts.items()
                    },
                },
                "defaults": {
                    kind: _defaults_to_wire(item) for kind, item in metric.defaults.items()
                },
                "summary": metric.summary,
                **({"group_id": metric.group_id} if metric.group_id is not None else {}),
            }
            for metric in descriptor.metrics
        ],
        **(
            {"default_metric_id": descriptor.default_metric_id}
            if descriptor.default_metric_id
            else {}
        ),
        "environment": [
            {
                "name": item.name,
                "required": item.required,
                "sensitive": item.sensitive,
                "label": localized(item.label),
                "how_to_get": localized(item.how_to_get),
                **({"help_url": item.help_url} if item.help_url else {}),
            }
            for item in descriptor.environment
        ],
    }


def _defaults_to_wire(value: CustomChartDefaults) -> dict[str, object]:
    declared = value.declared or frozenset({"period", "group_by", "top"})
    fields: dict[str, object] = {}
    for name, item in (
        ("period", value.period),
        ("group_by", value.group_by),
        ("partition_by", value.partition_by),
        ("top", value.top),
        ("granularity", value.granularity),
        ("other", value.other),
        ("style", value.style),
        ("theme", value.theme),
    ):
        if name in declared:
            fields[name] = item
    if "window" in declared and value.window_seconds is not None:
        suffix = "h" if value.window_seconds % 3600 == 0 else "m"
        divisor = 3600 if suffix == "h" else 60
        fields["window"] = f"{value.window_seconds // divisor}{suffix}"
    return fields


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
    mode = source.get("mode", "multi_select")
    if mode not in {"multi_select", "single_select"}:
        raise CustomProtocolError("custom filter mode must be multi_select or single_select")
    options = tuple(
        _parse_dimension(item, "filter option")
        for item in _sequence(source.get("options"), "filter options")
    )
    _unique_ids(options, "filter options")
    return CustomFilter(
        _string(source.get("id"), "filter ID"),
        _parse_localized(source.get("label"), "filter label"),
        tuple(CustomFilterOption(item.id, item.label) for item in options),
        mode,  # type: ignore[arg-type]
    )


def _parse_data(value: object, *, descriptions_allowed: bool = False) -> CustomData:
    source = _mapping(value, "data")
    series = tuple(
        _parse_series(item, descriptions_allowed=descriptions_allowed)
        for item in _sequence(source.get("series"), "data series")
    )
    _unique_ids(series, "data series")
    return CustomData(series)


def _normalized_localized(source: object, key: str) -> LocalizedText | None:
    """Parse an optional localized field, normalising whitespace-only values to None."""
    value = source.get(key, None) if isinstance(source, dict) else None
    if value is None:
        return None
    result = _parse_localized(value, f"v2 monitor group {key}")
    if not (result.en.strip() or result.zh_cn.strip()):
        return None
    return result


def _parse_v2_monitor_observation(value: object) -> V2MonitorObservation:
    source = _mapping(value, "v2 monitor observation")
    end_at = _parse_timestamp(source.get("end_at"), "v2 monitor observation end_at")
    groups = tuple(
        V2MetricValue(
            _string(item.get("id"), "v2 monitor group ID"),
            _parse_localized(item.get("label"), "v2 monitor group label"),
            _parse_decimal(item.get("value"), "v2 monitor group value"),
            _normalized_localized(item, "description"),
            _normalized_localized(item, "display"),
        )
        for raw in _sequence(source.get("groups"), "v2 monitor observation groups")
        for item in (_mapping(raw, "v2 monitor group"),)
    )
    if len({group.id for group in groups}) != len(groups):
        raise CustomProtocolError("v2 monitor group IDs must be unique")
    return V2MonitorObservation(
        end_at,
        _parse_decimal(source.get("total"), "v2 monitor observation total"),
        groups,
    )


def _parse_series(value: object, *, descriptions_allowed: bool) -> CustomSeries:
    source = _mapping(value, "series")
    if not descriptions_allowed and (
        {"description", "display", "comparison_display", "link"} & source.keys()
    ):
        raise CustomProtocolError("series presentation fields are supported only by ranking")
    points = tuple(
        _parse_point(point) for point in _sequence(source.get("points"), "series points")
    )
    if len({point.date for point in points}) != len(points):
        raise CustomProtocolError("series point dates must be unique")
    return CustomSeries(
        _string(source.get("id"), "series ID"),
        _parse_localized(source.get("label"), "series label"),
        points,
        _parse_localized(source["description"], "series description")
        if "description" in source
        else None,
        _parse_localized(source["display"], "series display") if "display" in source else None,
        _parse_localized(source["comparison_display"], "series comparison display")
        if "comparison_display" in source
        else None,
        _parse_https_url(source["link"], "series link") if "link" in source else None,
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


def _parse_https_url(value: object, name: str) -> str:
    url = _string(value, name)
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or any(ord(character) < 32 or ord(character) == 127 for character in url)
    ):
        raise CustomProtocolError(f"{name} must be an absolute https URL")
    return url


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


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise CustomProtocolError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise CustomProtocolError(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise CustomProtocolError(f"{name} must include a timezone")
    return parsed


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


def _group_by_tuple(value: object, name: str) -> tuple[str | None, ...]:
    values = tuple(item if item is None else _string(item, name) for item in _sequence(value, name))
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
