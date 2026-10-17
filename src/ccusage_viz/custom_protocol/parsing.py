from __future__ import annotations

import json

from ccusage_viz.custom_models import (
    CustomProtocolFailure,
    CustomProtocolWarning,
    V2HistoricalChartCapability,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2ProbeDescriptor,
    V2Runtime,
)
from ccusage_viz.custom_protocol.primitives import (
    _ERROR_CODES,
    PROTOCOL_VERSION,
    V2_PROTOCOL_VERSION,
    CustomProtocolError,
    _mapping,
    _parse_localized,
    _sequence,
    _string,
    _unique_ids,
)
from ccusage_viz.custom_protocol.probe import (
    _parse_capabilities,
    _parse_dataset,
    _parse_filter,
    _parse_probe_descriptor,
    parse_v2_probe_descriptor,
    validate_partition_selection,
)
from ccusage_viz.custom_protocol.requests import (
    CustomChartRequest,
    CustomRequest,
    CustomSummaryRequest,
    V2ChartRequest,
    V2MonitorRequest,
    V2ProbeRequest,
    V2SummaryRequest,
)
from ccusage_viz.custom_protocol.responses import (
    CustomChartResponse,
    CustomProbeResponse,
    CustomResponse,
    CustomSummaryResponse,
    V2ChartResponse,
    V2MonitorResponse,
    V2ProbeResponse,
    V2SummaryResponse,
)
from ccusage_viz.custom_protocol.values import (
    _parse_data,
    _parse_summary,
    _parse_v2_monitor_observation,
    _parse_v2_ranking_data,
)


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
        metric, _capability = _validate_v2_query_descriptor(
            descriptor, metric_id, request.chart_kind or "chart"
        )
        ranking_capability = (
            metric.capabilities.charts.get("ranking")
            if _is_ranking_request(request, metric)
            else None
        )
        if isinstance(ranking_capability, V2HistoricalChartCapability):
            _validate_ranking_request_partition(request, ranking_capability)
        data = (
            _parse_v2_ranking_data(
                root.get("data"),
                partitioned=request.partition_by is not None,
                max_items=ranking_capability.max_items,
            )
            if isinstance(ranking_capability, V2HistoricalChartCapability)
            else _parse_data(root.get("data"), descriptions_allowed=False)
        )
        return V2ChartResponse(
            metric_id,
            data,
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
) -> tuple[V2MetricDescriptor, V2HistoricalChartCapability | V2MonitorCapability | None]:
    metric = next((item for item in descriptor.metrics if item.id == metric_id), None)
    if metric is None:
        raise CustomProtocolError("v2 response descriptor does not declare response metric")
    supported = metric.capabilities.charts
    if chart_kind == "chart":
        historical = tuple(
            supported[kind]
            for kind in ("timeline", "calendar", "stack", "ranking")
            if kind in supported
        )
        if not historical:
            raise CustomProtocolError("v2 response descriptor does not support a historical chart")
        return metric, historical[0]
    if chart_kind not in supported:
        raise CustomProtocolError("v2 response descriptor does not support requested chart kind")
    return metric, supported[chart_kind]

def _is_ranking_request(request: V2ChartRequest, metric: V2MetricDescriptor) -> bool:
    """Identify Ranking from request-only fields and the response descriptor.

    The optional in-process chart kind disambiguates flat requests without changing the
    wire format. Legacy callers without it retain descriptor-based inference.
    """

    if request.chart_kind is not None:
        if (
            request.partition_declared or request.partition_by is not None
        ) and request.chart_kind != "ranking":
            raise CustomProtocolError("partitioned data requires a v2 ranking request")
        return request.chart_kind == "ranking"
    if request.partition_declared or request.partition_by is not None:
        if not isinstance(metric.capabilities.charts.get("ranking"), V2HistoricalChartCapability):
            raise CustomProtocolError("partitioned data requires a v2 ranking capability")
        return True
    historical_kinds = {
        kind
        for kind in ("timeline", "calendar", "stack", "ranking")
        if kind in metric.capabilities.charts
    }
    return historical_kinds == {"ranking"}

def _validate_ranking_request_partition(
    request: V2ChartRequest, capability: V2HistoricalChartCapability
) -> None:
    """Validate the issued Ranking selection against the returned descriptor."""

    if capability.partition_by is None:
        if request.partition_declared:
            raise CustomProtocolError(
                "v2 response ranking capability does not declare request partition_by"
            )
        return
    try:
        validate_partition_selection(request.partition_by, request.group_by, capability)
    except CustomProtocolError as exc:
        raise CustomProtocolError(f"v2 response ranking capability {exc}") from exc

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
