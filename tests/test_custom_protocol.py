import json
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_protocol import (
    PROTOCOL_VERSION,
    CustomChartRequest,
    CustomProtocolError,
    CustomSummaryRequest,
    canonical_custom_request_key,
    parse_custom_response,
)


def text(en: str, zh_cn: str) -> dict[str, str]:
    return {"en": en, "zh-CN": zh_cn}


def chart_request(**changes: object) -> CustomChartRequest:
    values: dict[str, object] = {
        "request_id": "chart-1",
        "dataset_id": "weread",
        "start_date": date(2026, 9, 17),
        "end_date": date(2026, 9, 30),
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
        "scope": "month",
        "current": DateInterval(date(2026, 9, 1), date(2026, 9, 30)),
        "sequential": DateInterval(date(2026, 8, 1), date(2026, 8, 31)),
        "year_over_year": DateInterval(date(2025, 9, 1), date(2025, 9, 30)),
        "filters": (("category", ("literature",)),),
        "command_argv": ("reader", "ccuv"),
    }
    values.update(changes)
    return CustomSummaryRequest(**values)  # type: ignore[arg-type]


def unit() -> dict[str, object]:
    return {"id": "page", "label": text("pages", "页"), "placement": "suffix", "decimal_places": 0}


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
    assert "summary" not in chart.to_wire()
    assert summary.to_wire()["request_kind"] == "summary"
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
        chart_request(granularity="week")
    )
    assert canonical_custom_request_key(chart_request()) != canonical_custom_request_key(
        chart_request(start_date=date(2026, 9, 18))
    )


@pytest.mark.parametrize("field", ["protocol", "request_id", "dataset_id", "request_kind"])
def test_response_envelope_must_match_request(field: str) -> None:
    response = chart_response()
    response[field] = "other"
    with pytest.raises(CustomProtocolError):
        parse_custom_response(json.dumps(response).encode(), chart_request())
