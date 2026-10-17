import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.custom_protocol.parsing import parse_custom_response
from ccusage_viz.custom_protocol.primitives import (
    V2_PROTOCOL_VERSION,
    CustomProtocolError,
)
from ccusage_viz.custom_protocol.requests import (
    V2ChartRequest,
    V2MonitorRequest,
)
from ccusage_viz.custom_protocol.responses import (
    V2MonitorResponse,
)

from .helpers import (
    chart_request,
    chart_response,
    comparison,
    probe_request,
    probe_response,
    summary_request,
    summary_response,
    text,
    v2_probe_descriptor,
)


def test_v2_monitor_response_parses_optional_group_description() -> None:
    request = V2MonitorRequest(
        "monitor-desc",
        "router",
        "tokens",
        "Asia/Shanghai",
        datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "monitor-desc",
        "request_kind": "monitor",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
        "runtime": {"filters": []},
        "observation": {
            "end_at": "2026-10-07T14:00:00+00:00",
            "total": "175",
            "groups": [
                {
                    "id": "terra",
                    "label": text("Terra", "Terra"),
                    "value": "175",
                    "description": text("Release validation", "发布验证"),
                }
            ],
        },
    }
    parsed = parse_custom_response(json.dumps(response).encode(), request)
    assert isinstance(parsed, V2MonitorResponse)
    assert parsed.observation.groups[0].description == LocalizedText(
        "Release validation", "发布验证"
    )
    assert parsed.observation.groups[0].display is None

def test_v2_monitor_response_parses_optional_group_display() -> None:
    request = V2MonitorRequest(
        "monitor-disp",
        "router",
        "tokens",
        "Asia/Shanghai",
        datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "monitor-disp",
        "request_kind": "monitor",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
        "runtime": {"filters": []},
        "observation": {
            "end_at": "2026-10-07T14:00:00+00:00",
            "total": "175",
            "groups": [
                {
                    "id": "terra",
                    "label": text("Terra", "Terra"),
                    "value": "175",
                    "display": text("69.2%", "69.2%"),
                }
            ],
        },
    }
    parsed = parse_custom_response(json.dumps(response).encode(), request)
    assert isinstance(parsed, V2MonitorResponse)
    assert parsed.observation.groups[0].display == LocalizedText("69.2%", "69.2%")
    assert parsed.observation.groups[0].description is None

def test_v2_monitor_response_normalizes_empty_group_description() -> None:
    request = V2MonitorRequest(
        "monitor-norm",
        "router",
        "tokens",
        "Asia/Shanghai",
        datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "monitor-norm",
        "request_kind": "monitor",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
        "runtime": {"filters": []},
        "observation": {
            "end_at": "2026-10-07T14:00:00+00:00",
            "total": "175",
            "groups": [
                {
                    "id": "terra",
                    "label": text("Terra", "Terra"),
                    "value": "175",
                    "description": text("   ", "\t"),
                }
            ],
        },
    }
    parsed = parse_custom_response(json.dumps(response).encode(), request)
    assert isinstance(parsed, V2MonitorResponse)
    assert parsed.observation.groups[0].description is None

def test_v2_monitor_response_rejects_malformed_group_description() -> None:
    request = V2MonitorRequest(
        "monitor-mal",
        "router",
        "tokens",
        "Asia/Shanghai",
        datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "monitor-mal",
        "request_kind": "monitor",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
        "runtime": {"filters": []},
        "observation": {
            "end_at": "2026-10-07T14:00:00+00:00",
            "total": "175",
            "groups": [
                {
                    "id": "terra",
                    "label": text("Terra", "Terra"),
                    "value": "175",
                    "description": "not localized",
                }
            ],
        },
    }
    with pytest.raises(CustomProtocolError, match="v2 monitor group description"):
        parse_custom_response(json.dumps(response).encode(), request)

def test_v2_query_response_requires_a_complete_descriptor_and_runtime_controls() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"]["timeline"] = {  # type: ignore[index]
        "granularities": ["day"],
        "group_by": [],
    }
    request = V2ChartRequest(
        "chart-v2-snapshot",
        "router",
        "tokens",
        "Asia/Shanghai",
        date(2026, 10, 1),
        date(2026, 10, 8),
        chart_kind="timeline",
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "chart-v2-snapshot",
        "request_kind": "chart",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": descriptor,
        "runtime": {
            "filters": [
                {
                    "id": "project",
                    "label": text("Project", "项目"),
                    "mode": "multi_select",
                    "options": [{"id": "core", "label": text("Core", "核心")}],
                }
            ]
        },
        "data": {"series": []},
    }

    parsed = parse_custom_response(json.dumps(response).encode(), request)

    assert parsed.descriptor.default_metric_id == "tokens"  # type: ignore[union-attr]
    assert parsed.runtime.filters[0].id == "project"  # type: ignore[union-attr]

@pytest.mark.parametrize("field", ("descriptor", "runtime"))
def test_v2_query_response_rejects_missing_snapshot_fields(field: str) -> None:
    request = V2MonitorRequest(
        "monitor-v2-required",
        "router",
        "tokens",
        "Asia/Shanghai",
        datetime(2026, 10, 7, tzinfo=UTC),
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "monitor-v2-required",
        "request_kind": "monitor",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
        "runtime": {"filters": []},
        "observation": {"end_at": "2026-10-07T00:00:00+00:00", "total": "1", "groups": []},
    }
    response.pop(field)

    with pytest.raises(CustomProtocolError, match=field):
        parse_custom_response(json.dumps(response).encode(), request)

def test_probe_response_parses_dataset_capabilities_and_defaults() -> None:
    result = parse_custom_response(json.dumps(probe_response()).encode(), probe_request())

    descriptor = result.descriptor  # type: ignore[union-attr]
    assert result.dataset_id == "weread"  # type: ignore[union-attr]
    assert descriptor.dataset.title.zh_cn == "微信读书"
    assert descriptor.defaults["ranking"].period == "1y"
    assert descriptor.defaults["ranking"].group_by == "book"
    assert descriptor.defaults["ranking"].top == 10
    assert descriptor.environment[0].required
    assert descriptor.environment[0].sensitive

def test_chart_response_accepts_exact_decimal_strings() -> None:
    result = parse_custom_response(json.dumps(chart_response()).encode(), chart_request())

    assert result.data.series[0].points[0].value == Decimal("1.25")  # type: ignore[union-attr]
    with pytest.raises(FrozenInstanceError):
        result.dataset.title.en = "Other"  # type: ignore[union-attr,misc]

@pytest.mark.parametrize("value", [1.25, "", "NaN", "Infinity", "1e3", "-2E-3"])
def test_chart_response_rejects_nonordinary_decimal_values(value: object) -> None:
    with pytest.raises(CustomProtocolError, match="decimal string"):
        parse_custom_response(json.dumps(chart_response(value)).encode(), chart_request())

def test_chart_response_does_not_require_or_accept_a_summary() -> None:
    result = parse_custom_response(json.dumps(chart_response()).encode(), chart_request())

    assert not hasattr(result, "summary")

@pytest.mark.parametrize(
    ("request_factory", "response_factory"),
    [(chart_request, chart_response), (summary_request, summary_response)],
)
def test_success_response_parses_unknown_warning_codes(
    request_factory: object, response_factory: object
) -> None:
    payload = response_factory()  # type: ignore[operator]
    payload["warnings"] = [  # type: ignore[index]
        {"code": "future_source_notice", "message": text("Heads up", "提示")}
    ]

    result = parse_custom_response(  # type: ignore[arg-type,operator]
        json.dumps(payload).encode(), request_factory()
    )

    assert result.warnings[0].code == "future_source_notice"
    assert result.warnings[0].message.zh_cn == "提示"

@pytest.mark.parametrize(
    "warning", [{"code": "notice"}, {"message": text("Heads up", "提示")}, "notice"]
)
def test_success_response_rejects_malformed_warnings(warning: object) -> None:
    response = chart_response()
    response["warnings"] = [warning]

    with pytest.raises(CustomProtocolError, match="warning"):
        parse_custom_response(json.dumps(response).encode(), chart_request())

def test_summary_response_uses_current_decimal_and_source_display() -> None:
    result = parse_custom_response(json.dumps(summary_response()).encode(), summary_request())

    metric = result.summary.metric  # type: ignore[union-attr]
    assert metric.current.value == Decimal("15")
    assert metric.current.display.zh_cn == "15 页"
    assert metric.sequential.base_value == Decimal("12")

def test_summary_response_requires_current_display() -> None:
    response = summary_response()
    del response["summary"]["metric"]["current"]["display"]  # type: ignore[index]

    with pytest.raises(CustomProtocolError, match="display"):
        parse_custom_response(json.dumps(response).encode(), summary_request())

@pytest.mark.parametrize(
    ("status", "base", "error"),
    [
        ("ready", None, "requires base_value"),
        ("pending", "12", "must omit base_value"),
        ("unavailable", "12", "must omit base_value"),
    ],
)
def test_summary_comparison_state_rules(status: str, base: str | None, error: str) -> None:
    response = summary_response()
    response["summary"]["metric"]["sequential"] = comparison(status, base)  # type: ignore[index]

    with pytest.raises(CustomProtocolError, match=error):
        parse_custom_response(json.dumps(response).encode(), summary_request())

@pytest.mark.parametrize("field", ["protocol", "request_id", "request_kind"])
def test_response_envelope_must_match_request(field: str) -> None:
    response = chart_response()
    response[field] = "other"
    with pytest.raises(CustomProtocolError):
        parse_custom_response(json.dumps(response).encode(), chart_request())

def test_chart_response_does_not_require_dataset_id_echo() -> None:
    response = chart_response()
    response.pop("dataset_id")

    assert parse_custom_response(json.dumps(response).encode(), chart_request())

def test_error_response_preserves_structured_dataset_failure() -> None:
    response = chart_response()
    response.update(
        {
            "status": "error",
            "error": {
                "code": "unsupported_query",
                "message": {"en": "Select another period.", "zh-CN": "请选择其他周期。"},
                "unsupported": {"field": "range.period", "value": "14d"},
            },
        }
    )

    with pytest.raises(CustomProtocolError) as raised:
        parse_custom_response(json.dumps(response).encode(), chart_request())

    assert raised.value.failure is not None
    assert raised.value.failure.code == "unsupported_query"
    assert raised.value.failure.message.zh_cn == "请选择其他周期。"
    assert dict(raised.value.failure.unsupported or {}) == {
        "field": "range.period",
        "value": "14d",
    }

def test_error_response_id_mismatch_explains_protocol_compatibility() -> None:
    response = chart_response()
    response.update(
        {
            "request_id": "invalid-request",
            "status": "error",
            "error": {"code": "invalid_request", "message": {"en": "Invalid.", "zh-CN": "无效。"}},
        }
    )

    with pytest.raises(
        CustomProtocolError,
        match="expected 'chart-1'.*received 'invalid-request'.*protocol-incompatible",
    ):
        parse_custom_response(json.dumps(response).encode(), chart_request())
