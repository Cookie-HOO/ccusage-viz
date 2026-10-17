import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_models import CustomData, CustomSeries, LocalizedText
from ccusage_viz.custom_protocol.parsing import parse_custom_response
from ccusage_viz.custom_protocol.primitives import (
    V2_PROTOCOL_VERSION,
    CustomProtocolError,
)
from ccusage_viz.custom_protocol.probe import _parse_filter, parse_v2_probe_descriptor
from ccusage_viz.custom_protocol.probe_wire import v2_probe_descriptor_to_wire
from ccusage_viz.custom_protocol.requests import (
    V2MonitorRequest,
    V2ProbeRequest,
    V2SummaryRequest,
)
from ccusage_viz.custom_protocol.responses import (
    V2MonitorResponse,
    V2ProbeResponse,
    V2SummaryResponse,
)

from .helpers import text, v2_probe_descriptor


def test_v2_probe_descriptor_parses_multiple_metrics_and_monitor_capabilities() -> None:
    descriptor = parse_v2_probe_descriptor(v2_probe_descriptor())

    assert V2_PROTOCOL_VERSION == "ccuv.custom/v2"
    assert tuple(metric.id for metric in descriptor.metrics) == (
        "tokens",
        "completed_requests",
        "average_tokens_per_request",
    )
    assert tuple(metric.title.en for metric in descriptor.metrics) == (
        "TPM",
        "QPM",
        "Average tokens per request",
    )
    assert descriptor.metrics[0].aggregation == "sum"
    assert descriptor.default_metric_id == "tokens"
    monitor = descriptor.metrics[0].capabilities.charts["monitor"]
    assert monitor.window_seconds == 60
    assert descriptor.metrics[0].defaults["monitor"].style == "ranking"
    assert descriptor.metrics[0].defaults["monitor"].window_seconds == 21600
    assert monitor.refresh_interval_seconds == 10
    assert descriptor.metrics[2].aggregation == "value"
    assert descriptor.metrics[2].capabilities.charts["monitor"].refresh_interval_seconds is None


def test_runtime_filter_defaults_to_multi_select_and_accepts_single_select() -> None:
    defaulted = _parse_filter(
        {"id": "seed_book", "label": text("Based on book", "基于图书"), "options": []}
    )
    single = _parse_filter(
        {
            "id": "seed_book",
            "label": text("Based on book", "基于图书"),
            "mode": "single_select",
            "options": [],
        }
    )

    assert defaulted.mode == "multi_select"
    assert single.mode == "single_select"


def test_runtime_filter_rejects_unknown_selection_mode() -> None:
    with pytest.raises(CustomProtocolError, match="filter mode"):
        _parse_filter(
            {
                "id": "seed_book",
                "label": text("Based on book", "基于图书"),
                "mode": "range",
                "options": [],
            }
        )


def test_v2_default_filters_round_trip_in_registration_snapshot() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["charts"] = {"ranking": {"group_by": [None], "periods": ["1h"]}}
    metric["defaults"] = {
        "ranking": {
            "period": "1h",
            "filters": {"request_activity": ["has_requests"]},
        }
    }

    descriptor = parse_v2_probe_descriptor(value)
    wire = v2_probe_descriptor_to_wire(descriptor)

    assert wire["metrics"][0]["defaults"]["ranking"]["filters"] == {  # type: ignore[index]
        "request_activity": ["has_requests"]
    }


def test_custom_data_manual_construction_enforces_flat_or_grouped_union() -> None:
    series = CustomSeries("model", LocalizedText("Model", "模型"), ())

    with pytest.raises(ValueError, match="groups and series are mutually exclusive"):
        CustomData(series=(series,), groups=())

    assert CustomData(series=(series,)).groups is None
    assert CustomData(groups=()).series == ()


def test_v2_metric_groups_and_references_round_trip() -> None:
    value = v2_probe_descriptor()
    value["metric_groups"] = [{"id": "router-throughput", "title": text("Throughput", "吞吐量")}]
    value["metrics"][0]["group_id"] = "router-throughput"

    descriptor = parse_v2_probe_descriptor(value)

    assert descriptor.metric_groups[0].id == "router-throughput"
    assert descriptor.metrics[0].group_id == "router-throughput"
    assert v2_probe_descriptor_to_wire(descriptor)["metric_groups"] == value["metric_groups"]
    assert v2_probe_descriptor_to_wire(descriptor)["metrics"][0]["group_id"] == "router-throughput"


def test_v2_metric_rejects_unknown_group_id() -> None:
    value = v2_probe_descriptor()
    value["metrics"][0]["group_id"] = "missing"

    with pytest.raises(CustomProtocolError, match="group_id"):
        parse_v2_probe_descriptor(value)


def test_v2_probe_and_monitor_wire_round_trip() -> None:
    probe = V2ProbeRequest("probe-v2", command_argv=("router", "ccuv"))
    probe_response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "probe-v2",
        "request_kind": "probe",
        "dataset_id": "router",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
    }
    parsed_probe = parse_custom_response(json.dumps(probe_response).encode(), probe)
    assert isinstance(parsed_probe, V2ProbeResponse)
    assert parsed_probe.descriptor.metrics[0].id == "tokens"

    request = V2MonitorRequest(
        "monitor-v2",
        "router",
        "tokens",
        "Asia/Shanghai",
        datetime(2026, 10, 7, 14, 0, tzinfo=UTC),
        group_by="real_model",
    )
    wire = request.to_wire()
    assert wire["range"] == {"end_at": "2026-10-07T14:00:00+00:00"}
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "monitor-v2",
        "request_kind": "monitor",
        "dataset_id": "router",
        "metric_id": "tokens",
        "status": "ok",
        "descriptor": v2_probe_descriptor(),
        "runtime": {"filters": []},
        "observation": {
            "end_at": "2026-10-07T14:00:00+00:00",
            "total": "175",
            "groups": [{"id": "terra", "label": text("Terra", "Terra"), "value": "175"}],
        },
    }
    parsed = parse_custom_response(json.dumps(response).encode(), request)
    assert isinstance(parsed, V2MonitorResponse)
    assert parsed.observation.total == Decimal("175")
    assert parsed.observation.groups[0].id == "terra"
    assert parsed.observation.groups[0].description is None
    assert parsed.observation.groups[0].display is None


def test_v2_total_summary_wire_round_trip() -> None:
    request = V2SummaryRequest(
        "summary-v2",
        "weread",
        "total_notes",
        "Asia/Shanghai",
        "total",
        DateInterval(date(1971, 1, 1), date(2026, 10, 8)),
    )
    response = {
        "protocol": V2_PROTOCOL_VERSION,
        "request_id": "summary-v2",
        "request_kind": "summary",
        "dataset_id": "weread",
        "metric_id": "total_notes",
        "status": "ok",
        "summary": {
            "metric": {
                "id": "total_notes",
                "label": text("Total notes", "总笔记数"),
                "current": {"value": "9", "display": text("9 notes", "9 条笔记")},
                "sequential": {"status": "unavailable"},
                "year_over_year": {"status": "unavailable"},
            }
        },
    }

    parsed = parse_custom_response(json.dumps(response).encode(), request)

    assert isinstance(parsed, V2SummaryResponse)
    assert parsed.summary.metric.current.value == Decimal("9")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["metrics"].append(value["metrics"][0].copy()),
            "metric IDs must be unique",
        ),
        (lambda value: value["metrics"][0].pop("aggregation"), "aggregation"),
        (lambda value: value["metrics"][0].__setitem__("aggregation", "ratio"), "aggregation"),
        (
            lambda value: value["metrics"][0]["capabilities"]["charts"]["monitor"].__setitem__(
                "window_seconds", 0
            ),
            "window_seconds",
        ),
        (lambda value: value.__setitem__("default_metric_id", "missing"), "default_metric_id"),
    ],
)
def test_v2_probe_descriptor_rejects_invalid_metric_contract(mutate: object, message: str) -> None:
    descriptor = v2_probe_descriptor()
    mutate(descriptor)  # type: ignore[operator]

    with pytest.raises(CustomProtocolError, match=message):
        parse_v2_probe_descriptor(descriptor)


def test_v2_historical_capabilities_accept_declared_periods_for_every_chart_kind() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"] = {
        kind: {
            "granularities": ["day"],
            "group_by": [],
            "periods": ["7d", "30d"],
        }
        for kind in ("timeline", "calendar", "stack", "ranking")
    }

    charts = parse_v2_probe_descriptor(descriptor).metrics[0].capabilities.charts

    assert all(charts[kind].periods == ("7d", "30d") for kind in charts)
