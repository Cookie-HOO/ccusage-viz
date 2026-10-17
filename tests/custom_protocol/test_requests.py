from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from ccusage_viz.custom_protocol.primitives import PROTOCOL_VERSION
from ccusage_viz.custom_protocol.requests import V2ChartRequest, canonical_custom_request_key

from .helpers import chart_request, probe_request, summary_request


@pytest.mark.parametrize("period", ("1d", "all"))
def test_v2_ranking_date_request_accepts_every_valid_ranking_period(period: str) -> None:
    request = V2ChartRequest(
        "chart-1",
        "router",
        "tokens",
        "UTC",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        period=period,
        chart_kind="ranking",
    )

    assert request.to_wire()["range"]["period"] == period


def test_v2_chart_request_requires_chart_kind() -> None:
    with pytest.raises(ValueError, match="requires chart_kind"):
        V2ChartRequest(
            "chart-1",
            "router",
            "tokens",
            "UTC",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
        )


def test_v2_ranking_timestamp_request_uses_half_open_timestamp_wire_and_utc_key() -> None:
    first = V2ChartRequest(
        "chart-1",
        "router",
        "tokens",
        "America/New_York",
        start_at=datetime.fromisoformat("2026-11-01T01:30:00-04:00"),
        end_at=datetime.fromisoformat("2026-11-01T01:30:00-05:00"),
        period="1h",
        chart_kind="ranking",
    )
    equivalent = replace(
        first,
        start_at=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        end_at=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    )

    assert first.to_wire()["range"] == {
        "start_at": "2026-11-01T01:30:00-04:00",
        "end_at": "2026-11-01T01:30:00-05:00",
        "period": "1h",
    }
    assert canonical_custom_request_key(first) == canonical_custom_request_key(equivalent)


def test_v2_timestamp_request_dst_fold_instants_have_distinct_keys() -> None:
    zone = ZoneInfo("America/New_York")
    first = V2ChartRequest(
        "chart-1",
        "router",
        "tokens",
        "America/New_York",
        start_at=datetime(2026, 11, 1, 0, 30, tzinfo=zone),
        end_at=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
        period="1h",
        chart_kind="ranking",
    )
    second = replace(
        first,
        start_at=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
        end_at=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1),
    )

    assert canonical_custom_request_key(first) != canonical_custom_request_key(second)


@pytest.mark.parametrize(
    "changes",
    (
        {"start_at": datetime(2026, 1, 1), "end_at": datetime(2026, 1, 2, tzinfo=UTC)},
        {"start_at": datetime(2026, 1, 1, tzinfo=UTC), "end_at": None},
        {
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 2),
            "start_at": datetime(2026, 1, 1, tzinfo=UTC),
            "end_at": datetime(2026, 1, 2, tzinfo=UTC),
        },
        {
            "start_at": datetime(2026, 1, 1, tzinfo=UTC),
            "end_at": datetime(2026, 1, 2, tzinfo=UTC),
            "chart_kind": "timeline",
        },
    ),
)
def test_v2_timestamp_request_rejects_invalid_or_out_of_scope_shapes(
    changes: dict[str, object],
) -> None:
    values = {
        "request_id": "chart-1",
        "dataset_id": "router",
        "metric_id": "tokens",
        "timezone": "UTC",
        "chart_kind": "ranking",
    }
    with pytest.raises(ValueError):
        V2ChartRequest(**(values | changes))  # type: ignore[arg-type]


def test_v2_request_omits_undeclared_partition_but_emits_declared_null() -> None:
    common = {
        "request_id": "chart-v2-partition",
        "dataset_id": "router",
        "metric_id": "tokens",
        "timezone": "Asia/Shanghai",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 8),
        "partition_by": None,
        "chart_kind": "ranking",
    }
    old = V2ChartRequest(**common, partition_declared=False)
    aware = V2ChartRequest(**common, partition_declared=True)

    assert "partition_by" not in old.to_wire()["query"]
    assert aware.to_wire()["query"]["partition_by"] is None
    assert canonical_custom_request_key(old) != canonical_custom_request_key(aware)
    assert canonical_custom_request_key(aware) != canonical_custom_request_key(
        V2ChartRequest(**{**common, "partition_by": "logical_model"}, partition_declared=True)
    )


def test_v2_request_rejects_partition_when_capability_is_undeclared() -> None:
    with pytest.raises(ValueError, match="partition_by requires partition_declared"):
        V2ChartRequest(
            request_id="chart-v2-invalid-partition",
            dataset_id="router",
            metric_id="tokens",
            timezone="Asia/Shanghai",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 8),
            partition_by="logical_model",
            partition_declared=False,
            chart_kind="ranking",
        )


def test_v2_chart_top_is_transmitted_and_distinguishes_request_identity() -> None:
    request = V2ChartRequest(
        "chart-v2",
        "example",
        "events",
        "Asia/Shanghai",
        date(2026, 10, 1),
        date(2026, 10, 8),
        group_by="project",
        top=12,
        chart_kind="timeline",
    )

    assert request.to_wire()["query"]["top"] == 12
    assert canonical_custom_request_key(request) != canonical_custom_request_key(
        V2ChartRequest(
            "chart-v2",
            "example",
            "events",
            "Asia/Shanghai",
            date(2026, 10, 1),
            date(2026, 10, 8),
            group_by="project",
            top=10,
            chart_kind="timeline",
        )
    )


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
