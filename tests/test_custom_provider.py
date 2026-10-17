from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest

from ccusage_viz.acquisition import (
    custom_historical_query_intent,
    custom_v2_probe_query_intent,
    custom_v2_summary_query_intent,
)
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.configuration import apply_custom_probe_defaults, v2_metric_probe_descriptor
from ccusage_viz.core.custom_ranking_time import TimestampRange
from ccusage_viz.custom_models import V2RankingData
from ccusage_viz.custom_protocol.requests import V2ChartRequest
from ccusage_viz.custom_protocol.responses import (
    CustomChartResponse,
    V2ChartResponse,
    V2ProbeResponse,
)
from ccusage_viz.errors import QueryError
from ccusage_viz.lifecycle import QueryTrigger
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
    ProcessConfig,
    resolve_date_range,
)
from ccusage_viz.processing.summaries import summary_query_plan
from ccusage_viz.providers.custom_command import CUSTOM_COMMAND_DEFINITION
from ccusage_viz.query.models import DataResolution


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


def test_timestamp_physical_identity_uses_exact_utc_bounds() -> None:
    end = datetime(2026, 10, 15, 12, tzinfo=UTC)

    def physical(interval: TimestampRange):
        config = CustomChartConfig(
            "ranking",
            CustomCommandSource("router", ("router",)),
            interval,
            metric_id="tokens",
        )
        intent = custom_historical_query_intent(
            config,
            timezone="UTC",
            owner_id="pane-1",
            generation=1,
            trigger=QueryTrigger.STARTUP,
        )
        return CUSTOM_COMMAND_DEFINITION.provider.compile(intent).queries[0]

    base = physical(TimestampRange(end - timedelta(minutes=10), end, period="10m"))
    equivalent = physical(
        TimestampRange(
            datetime.fromisoformat("2026-10-15T19:50:00+08:00"),
            datetime.fromisoformat("2026-10-15T20:00:00+08:00"),
            period="10m",
        )
    )
    shifted = physical(
        TimestampRange(end - timedelta(minutes=9), end + timedelta(minutes=1), period="10m")
    )

    assert base.fingerprint == equivalent.fingerprint
    assert base.fingerprint != shifted.fingerprint


def test_v2_timestamp_ranking_rejects_date_only_summary_planning() -> None:
    end = datetime(2026, 10, 15, 12, tzinfo=UTC)
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        TimestampRange(end - timedelta(minutes=10), end, period="10m"),
        metric_id="tokens",
    )

    with pytest.raises(ValueError, match="date-only summaries"):
        custom_v2_summary_query_intent(
            config,
            summary_query_plan(date(2026, 10, 15), "day"),
            timezone="UTC",
            owner_id="pane-1:summary",
            generation=1,
            trigger=QueryTrigger.STARTUP,
        )


def test_v2_ranking_timestamp_intent_preserves_precision_and_identity() -> None:
    end = datetime(2026, 10, 15, 12, 0, 0, 123456, tzinfo=UTC)
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        TimestampRange(end - timedelta(seconds=15), end, relative_until=True, period="15s"),
        metric_id="tokens",
    )

    intent = custom_historical_query_intent(
        config,
        timezone="UTC",
        owner_id="pane-1",
        generation=1,
        trigger=QueryTrigger.STARTUP,
    )

    assert intent.resolution is DataResolution.TIMESTAMP
    assert intent.scope.intervals == ()
    assert intent.missing_intervals == ()
    assert intent.payload.start_date is None
    assert intent.payload.start_at == end - timedelta(seconds=15)
    assert intent.execution_options == (
        ("end_at", end.isoformat()),
        ("start_at", (end - timedelta(seconds=15)).isoformat()),
    )


def test_coalesced_v2_probes_validate_against_the_executed_request_id(tmp_path: Path) -> None:
    script = tmp_path / "probe.py"
    script.write_text(
        dedent(
            """
            import json
            import sys
            import time
            request = json.loads(sys.stdin.read())
            time.sleep(0.1)
            text = {"en": "Router", "zh-CN": "Router"}
            print(json.dumps({
                "protocol": "ccuv.custom/v2", "request_id": request["request_id"],
                "request_kind": "probe", "dataset_id": "router", "status": "ok",
                "descriptor": {
                    "revision": "router-1", "version": "0.1.0",
                    "dataset": {"title": text, "description": text},
                    "metrics": [{
                        "id": "requests", "title": text, "description": text,
                        "unit": {"id": "request", "label": text, "placement": "suffix", "decimal_places": 0},
                        "aggregation": "sum", "summary": "none",
                        "capabilities": {"group_by": [], "charts": {"monitor": {"window_seconds": 60, "group_by": []}}},
                        "defaults": {}
                    }], "environment": []
                }
            }))
            """
        )
    )
    source = CustomCommandSource("router", (sys.executable, str(script)))
    runtime = build_query_runtime()
    first = runtime.submit(custom_v2_probe_query_intent(
        source, owner_id="dashboard:pane:2:0", generation=1, trigger=QueryTrigger.STARTUP,
    ))
    second = runtime.submit(custom_v2_probe_query_intent(
        source, owner_id="dashboard:pane:3:1", generation=1, trigger=QueryTrigger.STARTUP,
    ))

    assert isinstance(first.result().custom_response, V2ProbeResponse)
    assert isinstance(second.result().custom_response, V2ProbeResponse)


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


def test_custom_provider_executes_probe_declared_subday_ranking_end_to_end(
    tmp_path: Path,
) -> None:
    script = tmp_path / "subday-ranking.py"
    script.write_text(
        dedent(
            """
            import json
            import sys

            request = json.loads(sys.stdin.read())
            text = {"en": "Requests", "zh-CN": "请求"}
            descriptor = {
                "revision": "router-1", "version": "0.1.0",
                "dataset": {"title": text, "description": text},
                "metrics": [{
                    "id": "requests", "title": text, "description": text,
                    "unit": {"id": "request", "label": text, "placement": "suffix", "decimal_places": 2},
                    "aggregation": "sum", "summary": "none",
                    "capabilities": {"group_by": [], "charts": {
                        "ranking": {"group_by": [None], "periods": ["15s", "90s", "10m", "1h", "1d"]}
                    }},
                    "defaults": {"ranking": {"period": "15s"}},
                }],
                "environment": [],
            }
            if request["request_kind"] == "probe":
                response = {
                    "protocol": "ccuv.custom/v2", "request_id": request["request_id"],
                    "request_kind": "probe", "dataset_id": "router", "status": "ok",
                    "descriptor": descriptor,
                }
            else:
                expected_range = {
                    "start_at": "2026-10-15T11:59:45.123456+00:00",
                    "end_at": "2026-10-15T12:00:00.123456+00:00",
                    "period": "15s",
                }
                assert request["request_kind"] == "chart"
                assert request["chart_kind"] == "ranking"
                assert request["range"] == expected_range
                assert "start_date" not in request["range"]
                assert "end_date" not in request["range"]
                assert "granularity" not in request["query"]
                response = {
                    "protocol": "ccuv.custom/v2", "request_id": request["request_id"],
                    "request_kind": "chart", "dataset_id": "router",
                    "metric_id": "requests", "status": "ok", "descriptor": descriptor,
                    "runtime": {"filters": []},
                    "data": {"series": [{"id": "api", "label": text, "value": "185.20"}]},
                }
            print(json.dumps(response))
            """
        )
    )
    source = CustomCommandSource("router", (sys.executable, str(script)))
    probe = build_query_runtime().acquire(
        custom_v2_probe_query_intent(
            source, owner_id="probe", generation=1, trigger=QueryTrigger.STARTUP
        )
    ).custom_response
    assert isinstance(probe, V2ProbeResponse)

    initial = CustomChartConfig(
        "ranking",
        source,
        resolve_date_range("ranking", period="14d", since=None, until=None),
        metric_id="requests",
    )
    anchor = datetime(2026, 10, 15, 12, 0, 0, 123456, tzinfo=UTC)
    config = apply_custom_probe_defaults(
        initial,
        v2_metric_probe_descriptor(probe.descriptor, "requests"),
        timezone="UTC",
        now=anchor,
    )
    assert config.date_range == TimestampRange(
        anchor - timedelta(seconds=15), anchor, relative_until=True, period="15s"
    )

    result = build_query_runtime().acquire(
        custom_historical_query_intent(
            config,
            timezone="UTC",
            owner_id="pane",
            generation=1,
            trigger=QueryTrigger.STARTUP,
        )
    )

    assert result.resolution is DataResolution.TIMESTAMP
    response = result.custom_response
    assert isinstance(response, V2ChartResponse)
    assert isinstance(response.data, V2RankingData)
    assert response.data.series[0].value == Decimal("185.20")


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


def test_v2_partitioned_ranking_request_includes_chart_kind_and_declaration() -> None:
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("router", ("router",)),
        resolve_date_range("ranking", period="14d", since=None, until=None),
        group_by="real_model",
        top=3,
        metric_id="tokens",
        partition_by="logical_model",
    )

    intent = custom_historical_query_intent(
        config,
        timezone="UTC",
        owner_id="pane",
        generation=1,
        trigger=QueryTrigger.STARTUP,
        partition_declared=True,
    )

    assert isinstance(intent.payload, V2ChartRequest)
    assert intent.payload.chart_kind == "ranking"
    assert intent.payload.partition_declared
    assert intent.payload.partition_by == "logical_model"
    assert intent.payload.to_wire()["query"]["partition_by"] == "logical_model"


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
