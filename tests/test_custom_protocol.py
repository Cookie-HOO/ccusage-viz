import json
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_protocol import (
    PROTOCOL_VERSION,
    V2_PROTOCOL_VERSION,
    CustomChartRequest,
    CustomProbeRequest,
    CustomProtocolError,
    CustomSummaryRequest,
    canonical_custom_request_key,
    parse_custom_response,
    parse_v2_probe_descriptor,
)


def text(en: str, zh_cn: str) -> dict[str, str]:
    return {"en": en, "zh-CN": zh_cn}


def chart_request(**changes: object) -> CustomChartRequest:
    values: dict[str, object] = {
        "request_id": "chart-1",
        "dataset_id": "weread",
        "timezone": "Asia/Shanghai",
        "start_date": date(2026, 9, 17),
        "end_date": date(2026, 9, 30),
        "period": "14d",
        "filters": (("category", ("literature",)),),
        "group_by": "book",
        "granularity": "day",
        "command_argv": ("reader", "ccuv"),
        "execution_context": (("timeout", "30"),),
    }
    values.update(changes)
    return CustomChartRequest(**values)  # type: ignore[arg-type]


def summary_request(**changes: object) -> CustomSummaryRequest:
    values: dict[str, object] = {
        "request_id": "summary-1",
        "dataset_id": "weread",
        "timezone": "Asia/Shanghai",
        "scope": "month",
        "current": DateInterval(date(2026, 9, 1), date(2026, 9, 30)),
        "sequential": DateInterval(date(2026, 8, 1), date(2026, 8, 31)),
        "year_over_year": DateInterval(date(2025, 9, 1), date(2025, 9, 30)),
        "filters": (("category", ("literature",)),),
        "command_argv": ("reader", "ccuv"),
    }
    values.update(changes)
    return CustomSummaryRequest(**values)  # type: ignore[arg-type]


def probe_request(**changes: object) -> CustomProbeRequest:
    values: dict[str, object] = {
        "request_id": "probe-1",
        "command_argv": ("reader", "ccuv"),
    }
    values.update(changes)
    return CustomProbeRequest(**values)  # type: ignore[arg-type]


def unit() -> dict[str, object]:
    return {"id": "page", "label": text("pages", "页"), "placement": "suffix", "decimal_places": 0}


def v2_probe_descriptor() -> dict[str, object]:
    return {
        "revision": "router-1",
        "version": "0.1.0",
        "dataset": {
            "title": text("Local Router", "本地 Router"),
            "description": text("Live Router metrics", "实时 Router 指标"),
        },
        "metrics": [
            {
                "id": "tokens",
                "title": text("Token throughput", "Token 吞吐"),
                "description": text("Recent token usage", "近期 Token 用量"),
                "unit": {"id": "token", "label": text("tokens", "Token"), "placement": "suffix", "decimal_places": 0},
                "aggregation": "sum",
                "capabilities": {
                    "group_by": [{"id": "real_model", "label": text("Real model", "真实模型")}],
                    "filters": [],
                    "charts": {
                        "monitor": {
                            "window_seconds": 60,
                            "refresh_interval_seconds": 10,
                            "group_by": ["real_model"],
                            "filters": [],
                        }
                    },
                },
                "defaults": {},
            },
            {
                "id": "average_tokens_per_request",
                "title": text("Average tokens per request", "平均每请求 Token"),
                "description": text("Recent request average", "近期请求均值"),
                "unit": {"id": "token-per-request", "label": text("tokens/request", "Token/请求"), "placement": "suffix", "decimal_places": 1},
                "aggregation": "value",
                "capabilities": {
                    "group_by": [{"id": "agent", "label": text("Agent", "Agent")}],
                    "filters": [],
                    "charts": {
                        "monitor": {
                            "window_seconds": 60,
                            "group_by": ["agent"],
                            "filters": [],
                        }
                    },
                },
                "defaults": {},
            },
        ],
        "environment": [],
    }


def test_v2_probe_descriptor_parses_multiple_metrics_and_monitor_capabilities() -> None:
    descriptor = parse_v2_probe_descriptor(v2_probe_descriptor())

    assert V2_PROTOCOL_VERSION == "ccuv.custom/v2"
    assert tuple(metric.id for metric in descriptor.metrics) == (
        "tokens",
        "average_tokens_per_request",
    )
    assert descriptor.metrics[0].aggregation == "sum"
    monitor = descriptor.metrics[0].capabilities.charts["monitor"]
    assert monitor.window_seconds == 60
    assert monitor.refresh_interval_seconds == 10
    assert descriptor.metrics[1].aggregation == "value"
    assert descriptor.metrics[1].capabilities.charts["monitor"].refresh_interval_seconds is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["metrics"].append(value["metrics"][0].copy()), "metric IDs must be unique"),
        (lambda value: value["metrics"][0].pop("aggregation"), "aggregation"),
        (lambda value: value["metrics"][0].__setitem__("aggregation", "ratio"), "aggregation"),
        (lambda value: value["metrics"][0]["capabilities"]["charts"]["monitor"].__setitem__("window_seconds", 0), "window_seconds"),
    ],
)
def test_v2_probe_descriptor_rejects_invalid_metric_contract(
    mutate: object, message: str
) -> None:
    descriptor = v2_probe_descriptor()
    mutate(descriptor)  # type: ignore[operator]

    with pytest.raises(CustomProtocolError, match=message):
        parse_v2_probe_descriptor(descriptor)


def capabilities() -> dict[str, object]:
    return {
        "group_by": [{"id": "book", "label": text("Book", "书籍")}],
        "filters": [
            {
                "id": "category",
                "label": text("Category", "分类"),
                "mode": "multi_select",
                "options": [{"id": "literature", "label": text("Literature", "文学")}],
            }
        ],
        "charts": {
            kind: {"granularities": ["day", "week"], "group_by": ["book"], "filters": ["category"]}
            for kind in ("timeline", "stack", "calendar", "ranking")
        },
    }


def probe_response() -> dict[str, object]:
    request = probe_request()
    return {
        "protocol": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "request_kind": "probe",
        "dataset_id": "weread",
        "status": "ok",
        "descriptor": {
            "revision": "weread-1",
            "version": "0.1.0",
            "source_timezone": "Asia/Shanghai",
            "dataset": {
                "title": text("WeRead", "微信读书"),
                "description": text("Daily reading time", "每日阅读时长"),
                "unit": unit(),
            },
            "capabilities": capabilities(),
            "defaults": {
                "timeline": {"period": "14d", "group_by": None, "top": None},
                "calendar": {"period": "14d", "group_by": None, "top": None},
                "stack": {"period": "14d", "group_by": None, "top": None},
                "ranking": {"period": "1y", "group_by": "book", "top": 10},
            },
            "environment": [{
                "name": "WEREAD_API_KEY",
                "required": True,
                "sensitive": True,
                "label": text("WeRead API key", "微信读书 API 密钥"),
                "how_to_get": text("Set the key in your environment.", "请通过环境变量设置密钥。"),
            }],
        },
    }


def chart_response(point_value: object = "1.25") -> dict[str, object]:
    request = chart_request()
    return {
        "protocol": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "request_kind": "chart",
        "dataset_id": request.dataset_id,
        "status": "ok",
        "dataset": {
            "title": text("WeRead", "微信读书"),
            "description": text("Daily pages", "每日页数"),
            "unit": unit(),
        },
        "capabilities": capabilities(),
        "data": {
            "series": [
                {
                    "id": "book-001",
                    "label": text("A book", "一本书"),
                    "points": [{"date": "2026-09-17", "value": point_value}],
                }
            ]
        },
    }


def comparison(status: str = "ready", base_value: str | None = "12") -> dict[str, str]:
    result = {"status": status}
    if base_value is not None:
        result["base_value"] = base_value
    return result


def summary_response() -> dict[str, object]:
    request = summary_request()
    return {
        "protocol": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "request_kind": "summary",
        "dataset_id": request.dataset_id,
        "status": "ok",
        "summary": {
            "metric": {
                "id": "pages-read",
                "label": text("Pages read", "阅读页数"),
                "current": {"value": "15", "display": text("15 pages", "15 页")},
                "sequential": comparison(),
                "year_over_year": comparison(),
            }
        },
    }


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


def test_probe_request_has_no_query_or_timezone() -> None:
    request = probe_request()

    assert request.to_wire() == {
        "protocol": PROTOCOL_VERSION,
        "request_id": "probe-1",
        "request_kind": "probe",
    }
    assert canonical_custom_request_key(request) == (
        ("reader", "ccuv"),
        (),
        "probe",
    )


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


def test_request_wire_shapes_keep_chart_and_summary_inputs_separate() -> None:
    chart = chart_request()
    summary = summary_request()

    assert chart.to_wire()["request_kind"] == "chart"
    assert chart.to_wire()["timezone"] == "Asia/Shanghai"
    assert chart.to_wire()["range"] == {
        "start_date": "2026-09-17",
        "end_date": "2026-09-30",
        "period": "14d",
    }
    assert "summary" not in chart.to_wire()
    assert summary.to_wire()["request_kind"] == "summary"
    assert summary.to_wire()["timezone"] == "Asia/Shanghai"
    assert "range" not in summary.to_wire()
    assert summary.to_wire()["summary"] == {
        "scope": "month",
        "intervals": {
            "current": {"start_date": "2026-09-01", "end_date": "2026-09-30"},
            "sequential": {"start_date": "2026-08-01", "end_date": "2026-08-31"},
            "year_over_year": {"start_date": "2025-09-01", "end_date": "2025-09-30"},
        },
    }


def test_canonical_summary_identity_excludes_chart_inputs_and_request_id() -> None:
    first = summary_request()
    second = summary_request(request_id="other")

    assert canonical_custom_request_key(first) == canonical_custom_request_key(second)
    assert canonical_custom_request_key(first) != canonical_custom_request_key(
        summary_request(filters=())
    )
    assert canonical_custom_request_key(first) != canonical_custom_request_key(
        summary_request(scope="week", year_over_year=None)
    )


def test_chart_identity_contains_graph_inputs() -> None:
    assert canonical_custom_request_key(chart_request()) != canonical_custom_request_key(
        chart_request(period="1w")
    )
    assert canonical_custom_request_key(chart_request()) != canonical_custom_request_key(
        chart_request(granularity="week")
    )
    assert canonical_custom_request_key(chart_request()) != canonical_custom_request_key(
        chart_request(start_date=date(2026, 9, 18))
    )
    assert canonical_custom_request_key(chart_request()) != canonical_custom_request_key(
        chart_request(timezone="America/Los_Angeles")
    )


@pytest.mark.parametrize("request_factory", [chart_request, summary_request])
@pytest.mark.parametrize("timezone", ["", "Mars/Olympus"])
def test_requests_require_a_valid_iana_timezone(request_factory: object, timezone: str) -> None:
    with pytest.raises(ValueError, match="timezone"):
        request_factory(timezone=timezone)  # type: ignore[operator]


@pytest.mark.parametrize("period", ["week", "0d", "1W"])
def test_chart_request_rejects_invalid_period(period: str) -> None:
    with pytest.raises(ValueError, match="period"):
        chart_request(period=period)


def test_fixed_chart_request_serializes_null_period() -> None:
    assert chart_request(period=None).to_wire()["range"]["period"] is None


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
