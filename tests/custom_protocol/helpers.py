

from datetime import date

from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_protocol.primitives import PROTOCOL_VERSION, V2_PROTOCOL_VERSION
from ccusage_viz.custom_protocol.requests import (
    CustomChartRequest,
    CustomProbeRequest,
    CustomSummaryRequest,
    V2ChartRequest,
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
        "default_metric_id": "tokens",
        "dataset": {
            "title": text("Local Router", "本地 Router"),
            "description": text("Live Router metrics", "实时 Router 指标"),
        },
        "metrics": [
            {
                "id": "tokens",
                "title": text("TPM", "TPM"),
                "description": text("Recent token usage", "近期 Token 用量"),
                "unit": {
                    "id": "token",
                    "label": text("tokens", "Token"),
                    "placement": "suffix",
                    "decimal_places": 0,
                },
                "aggregation": "sum",
                "capabilities": {
                    "group_by": [{"id": "real_model", "label": text("Real model", "真实模型")}],
                    "charts": {
                        "monitor": {
                            "window_seconds": 60,
                            "refresh_interval_seconds": 10,
                            "group_by": ["real_model"],
                        }
                    },
                },
                "defaults": {"monitor": {"style": "ranking", "window": "6h"}},
            },
            {
                "id": "completed_requests",
                "title": text("QPM", "QPM"),
                "description": text("Recent completed requests", "近期完成请求"),
                "unit": {
                    "id": "request",
                    "label": text("requests", "请求"),
                    "placement": "suffix",
                    "decimal_places": 0,
                },
                "aggregation": "sum",
                "capabilities": {
                    "group_by": [{"id": "public_model", "label": text("Public model", "公开模型")}],
                    "charts": {
                        "monitor": {
                            "window_seconds": 60,
                            "refresh_interval_seconds": 10,
                            "group_by": ["public_model"],
                        }
                    },
                },
                "defaults": {"monitor": {"style": "ranking", "window": "6h"}},
            },
            {
                "id": "average_tokens_per_request",
                "title": text("Average tokens per request", "平均每请求 Token"),
                "description": text("Recent request average", "近期请求均值"),
                "unit": {
                    "id": "token-per-request",
                    "label": text("tokens/request", "Token/请求"),
                    "placement": "suffix",
                    "decimal_places": 1,
                },
                "aggregation": "value",
                "capabilities": {
                    "group_by": [{"id": "agent", "label": text("Agent", "Agent")}],
                    "charts": {
                        "monitor": {
                            "window_seconds": 60,
                            "group_by": ["agent"],
                        }
                    },
                },
                "defaults": {"monitor": {"style": "ranking", "window": "6h"}},
            },
        ],
        "environment": [],
    }

def partitioned_ranking_request(**changes: object) -> V2ChartRequest:
    values: dict[str, object] = {
        "request_id": "chart-v2-grouped",
        "dataset_id": "router",
        "metric_id": "tokens",
        "timezone": "Asia/Shanghai",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 8),
        "group_by": "real_model",
        "partition_by": "logical_model",
        "partition_declared": True,
        "chart_kind": "ranking",
    }
    values.update(changes)
    return V2ChartRequest(**values)  # type: ignore[arg-type]

def ranking_series(
    identifier: str = "model", value: object = "7", *, date_value: str = "2026-10-08"
) -> dict[str, object]:
    del date_value
    return {
        "id": identifier,
        "label": text(identifier.title(), identifier),
        "value": value,
    }

def ranking_group(
    identifier: str, label: str, series: list[dict[str, object]]
) -> dict[str, object]:
    return {"id": identifier, "label": text(label, label), "series": series}

def v2_ranking_response_root(
    request: V2ChartRequest, *, max_items: int | None = None
) -> dict[str, object]:
    descriptor = v2_probe_descriptor()
    metric = descriptor["metrics"][0]
    metric["capabilities"]["partition_by"] = [
        {"id": "logical_model", "label": text("Logical model", "逻辑模型")}
    ]
    ranking: dict[str, object] = {
        "group_by": ["real_model"],
        "partition_by": [None, "logical_model"],
    }
    if max_items is not None:
        ranking["max_items"] = max_items
    metric["capabilities"]["charts"] = {"ranking": ranking}
    metric["defaults"] = {}
    return {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": request.request_id,
        "request_kind": "chart",
        "dataset_id": request.dataset_id,
        "metric_id": request.metric_id,
        "status": "ok",
        "descriptor": descriptor,
        "runtime": {"filters": []},
        "data": {"groups": []},
    }

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
            "environment": [
                {
                    "name": "WEREAD_API_KEY",
                    "required": True,
                    "sensitive": True,
                    "label": text("WeRead API key", "微信读书 API 密钥"),
                    "how_to_get": text(
                        "Set the key in your environment.", "请通过环境变量设置密钥。"
                    ),
                }
            ],
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
