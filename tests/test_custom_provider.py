from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest

from ccusage_viz.acquisition import custom_historical_query_intent, custom_v2_probe_query_intent
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.custom_protocol import CustomChartResponse, V2ChartResponse, V2ProbeResponse
from ccusage_viz.errors import QueryError
from ccusage_viz.lifecycle import QueryTrigger
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
    ProcessConfig,
    resolve_date_range,
)


def _command(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "collector.py"
    script.write_text(
        dedent(
            """
            import json
            import sys
            request = json.loads(sys.stdin.read())
            response = {
                "protocol": "ccuv.custom/v1",
                "request_id": request["request_id"],
                "request_kind": request["request_kind"],
                "dataset_id": request["dataset_id"],
                "status": "ok",
                "warnings": [{
                    "code": "source_timezone",
                    "message": {"en": request["timezone"], "zh-CN": request["timezone"]},
                }],
                "capabilities": {"group_by": [], "filters": [], "charts": {}},
                "dataset": {
                    "title": {"en": "Reading", "zh-CN": "阅读"},
                    "description": {"en": "Pages", "zh-CN": "页数"},
                    "unit": {"id": "page", "label": {"en": "pages", "zh-CN": "页"}, "placement": "suffix", "decimal_places": 0}
                },
                "data": {"series": []}
            }
            print(json.dumps(response))
            """
        )
    )
    return (sys.executable, str(script))


def test_custom_provider_sends_one_json_document_and_parses_response(tmp_path: Path) -> None:
    argv = _command(tmp_path)
    config = CustomChartConfig(
        "timeline",
        CustomCommandSource("weread", argv),
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 30)
        ),
    )
    intent = custom_historical_query_intent(
        config,
        timezone="Asia/Shanghai",
        owner_id="pane-1",
        generation=1,
        trigger=QueryTrigger.STARTUP,
    )

    result = build_query_runtime().acquire(intent)

    response = result.custom_response
    assert isinstance(response, CustomChartResponse)
    assert response.dataset.title.en == "Reading"
    assert intent.payload.timezone == "Asia/Shanghai"
    assert response.warnings[0].code == "source_timezone"
    assert response.warnings[0].message.en == "Asia/Shanghai"
    assert result.records == ()


def test_custom_provider_accepts_current_day_ranges(tmp_path: Path) -> None:
    config = CustomChartConfig(
        "timeline",
        CustomCommandSource("weread", _command(tmp_path)),
        resolve_date_range("timeline", period="14d", since=None, until=None, today=date.today()),
    )

    intent = custom_historical_query_intent(
        config,
        timezone="Asia/Shanghai",
        owner_id="pane-1",
        generation=1,
        trigger=QueryTrigger.STARTUP,
    )

    assert intent.payload.end_date == date.today()


def test_custom_provider_executes_a_v2_probe(tmp_path: Path) -> None:
    script = tmp_path / "probe.py"
    script.write_text(
        dedent(
            """
            import json
            import sys
            request = json.loads(sys.stdin.read())
            metric = {
                "id": "tokens", "title": {"en": "Tokens", "zh-CN": "Token"},
                "description": {"en": "Live", "zh-CN": "实时"},
                "unit": {"id": "token", "label": {"en": "tokens", "zh-CN": "Token"}, "placement": "suffix", "decimal_places": 0},
                "aggregation": "sum",
                "capabilities": {"group_by": [], "charts": {"monitor": {"window_seconds": 60, "group_by": []}}},
                "defaults": {},
            }
            print(json.dumps({
                "protocol": "ccuv.custom/v2", "request_id": request["request_id"],
                "request_kind": "probe", "dataset_id": "router", "status": "ok",
                "descriptor": {
                    "revision": "router-1", "version": "0.1.0",
                    "dataset": {"title": {"en": "Router", "zh-CN": "Router"}, "description": {"en": "Live", "zh-CN": "实时"}},
                    "metrics": [metric], "environment": []
                }
            }))
            """
        )
    )
    intent = custom_v2_probe_query_intent(
        CustomCommandSource("router", (sys.executable, str(script))),
        owner_id="probe", generation=1, trigger=QueryTrigger.STARTUP,
    )

    response = build_query_runtime().acquire(intent).custom_response

    assert isinstance(response, V2ProbeResponse)
    assert response.descriptor.metrics[0].id == "tokens"


def test_custom_provider_executes_a_v2_chart_metric(tmp_path: Path) -> None:
    script = tmp_path / "chart-v2.py"
    script.write_text(
        dedent(
            """
            import json, sys
            request = json.loads(sys.stdin.read())
            text = {"en": "Reading", "zh-CN": "阅读"}
            descriptor = {
                "revision": "reading-1", "version": "0.1.0",
                "dataset": {"title": text, "description": text},
                "metrics": [{
                    "id": "reading_time", "title": text, "description": text,
                    "unit": {"id": "minute", "label": text, "placement": "suffix", "decimal_places": 2},
                    "aggregation": "sum",
                    "capabilities": {"group_by": [], "charts": {"timeline": {"granularities": ["day"], "group_by": []}}},
                    "defaults": {}
                }], "environment": []
            }
            data = {"series": [{"id": "total", "label": text, "points": [{"date": "2026-09-17", "value": "1.25"}]}]}
            print(json.dumps({
                "protocol": "ccuv.custom/v2", "request_id": request["request_id"], "request_kind": "chart",
                "dataset_id": "weread", "metric_id": request["metric_id"], "status": "ok",
                "descriptor": descriptor, "runtime": {"filters": []}, "data": data
            }))
            """
        )
    )
    config = CustomChartConfig(
        "timeline", CustomCommandSource("weread", (sys.executable, str(script))),
        resolve_date_range("timeline", period="14d", since=None, until=None, today=date(2026, 9, 30)), metric_id="reading_time",
    )
    result = build_query_runtime().acquire(
        custom_historical_query_intent(config, timezone="Asia/Shanghai", owner_id="pane", generation=1, trigger=QueryTrigger.STARTUP)
    )

    assert isinstance(result.custom_response, V2ChartResponse)
    assert result.custom_response.metric_id == "reading_time"


def test_custom_provider_uses_process_timeout_output_limit_and_environment(tmp_path: Path) -> None:
    config = CustomChartConfig(
        "timeline",
        CustomCommandSource("weread", _command(tmp_path)),
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 30)
        ),
    )

    intent = custom_historical_query_intent(
        config,
        timezone="Asia/Shanghai",
        owner_id="pane-1",
        generation=1,
        trigger=QueryTrigger.STARTUP,
        process=ProcessConfig(
            query_timeout=7.5, output_limit=1024, environment=(("SOURCE", "test"),)
        ),
    )

    assert intent.execution_context is not None
    assert intent.execution_context.timeout == 7.5
    assert intent.execution_context.output_limit == 1024
    assert intent.execution_context.environment == (("SOURCE", "test"),)


def test_custom_provider_preserves_a_structured_dataset_failure(tmp_path: Path) -> None:
    script = tmp_path / "collector.py"
    script.write_text(
        dedent(
            """
            import json
            import sys

            request = json.loads(sys.stdin.read())
            print(json.dumps({
                "protocol": "ccuv.custom/v1",
                "request_id": request["request_id"],
                "request_kind": request["request_kind"],
                "dataset_id": request["dataset_id"],
                "status": "error",
                "error": {
                    "code": "unsupported_query",
                    "message": {"en": "Select another period.", "zh-CN": "请选择其他周期。"},
                    "unsupported": {"field": "range.period", "value": "14d"},
                },
            }))
            """
        )
    )
    config = CustomChartConfig(
        "timeline",
        CustomCommandSource("weread", (sys.executable, str(script))),
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 30)
        ),
    )
    intent = custom_historical_query_intent(
        config,
        timezone="Asia/Shanghai",
        owner_id="pane-1",
        generation=1,
        trigger=QueryTrigger.STARTUP,
    )

    with pytest.raises(QueryError) as raised:
        build_query_runtime().acquire(intent)

    failure = raised.value.values["custom_failure"]
    assert failure.code == "unsupported_query"
    assert failure.message.zh_cn == "请选择其他周期。"
    assert dict(failure.unsupported or {}) == {"field": "range.period", "value": "14d"}
