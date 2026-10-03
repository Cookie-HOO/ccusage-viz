from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from textwrap import dedent

from ccusage_viz.acquisition import custom_historical_query_intent
from ccusage_viz.bootstrap import build_query_runtime
from ccusage_viz.custom_protocol import CustomChartResponse
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
        CustomCommandSource("wechat-reading", argv),
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 30)
        ),
    )
    intent = custom_historical_query_intent(
        config, owner_id="pane-1", generation=1, trigger=QueryTrigger.STARTUP
    )

    result = build_query_runtime().acquire(intent)

    response = result.custom_response
    assert isinstance(response, CustomChartResponse)
    assert response.dataset.title.en == "Reading"
    assert result.records == ()


def test_custom_provider_uses_process_timeout_output_limit_and_environment(tmp_path: Path) -> None:
    config = CustomChartConfig(
        "timeline",
        CustomCommandSource("wechat-reading", _command(tmp_path)),
        resolve_date_range(
            "timeline", period="14d", since=None, until=None, today=date(2026, 9, 30)
        ),
    )

    intent = custom_historical_query_intent(
        config,
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
