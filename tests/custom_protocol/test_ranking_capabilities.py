import json
from dataclasses import replace
from decimal import Decimal

import pytest

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.custom_protocol.parsing import parse_custom_response
from ccusage_viz.custom_protocol.primitives import (
    CustomProtocolError,
)
from ccusage_viz.custom_protocol.probe import parse_v2_probe_descriptor
from ccusage_viz.custom_protocol.probe_wire import v2_probe_descriptor_to_wire
from ccusage_viz.custom_protocol.requests import (
    canonical_custom_request_key,
)

from .helpers import (
    partitioned_ranking_request,
    probe_request,
    probe_response,
    ranking_group,
    ranking_series,
    text,
    v2_probe_descriptor,
    v2_ranking_response_root,
)


def test_v2_subday_periods_are_ranking_only_and_preserve_declaration_order() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["charts"] = {
        "ranking": {"group_by": [None], "periods": ["90s", "15s", "2h", "1d", "all"]}
    }
    metric["defaults"] = {"ranking": {"period": "15s"}}

    descriptor = parse_v2_probe_descriptor(value)
    ranking = descriptor.metrics[0].capabilities.charts["ranking"]

    assert ranking.periods == ("90s", "15s", "2h", "1d", "all")  # type: ignore[union-attr]
    assert descriptor.metrics[0].defaults["ranking"].period == "15s"

    metric["capabilities"]["charts"] = {
        "timeline": {"granularities": ["day"], "group_by": [], "periods": ["15s"]}
    }
    with pytest.raises(CustomProtocolError, match="period"):
        parse_v2_probe_descriptor(value)

def test_v2_ranking_sort_direction_parses_and_round_trips() -> None:
    value = v2_probe_descriptor()
    value["metrics"][0]["capabilities"]["charts"] = {
        "ranking": {"group_by": [None], "sort_direction": "ascending"}
    }

    descriptor = parse_v2_probe_descriptor(value)
    ranking = descriptor.metrics[0].capabilities.charts["ranking"]

    assert ranking.sort_direction == "ascending"  # type: ignore[union-attr]
    assert (
        v2_probe_descriptor_to_wire(descriptor)["metrics"][0]["capabilities"]["charts"]["ranking"][
            "sort_direction"
        ]
        == "ascending"
    )  # type: ignore[index]

def test_v2_ranking_parses_partition_catalog_capability_and_default() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["partition_by"] = [
        {"id": "logical_model", "label": text("Logical model", "逻辑模型")}
    ]
    metric["capabilities"]["charts"] = {
        "ranking": {
            "granularities": ["day"],
            "group_by": ["real_model"],
            "partition_by": [None, "logical_model"],
        }
    }
    metric["defaults"] = {
        "ranking": {
            "period": "14d",
            "group_by": "real_model",
            "partition_by": "logical_model",
            "top": 3,
        }
    }

    descriptor = parse_v2_probe_descriptor(value)
    parsed = descriptor.metrics[0]

    assert parsed.capabilities.partition_by[0].id == "logical_model"
    assert parsed.capabilities.charts["ranking"].partition_by == (None, "logical_model")
    assert parsed.defaults["ranking"].partition_by == "logical_model"

def test_v2_ranking_partition_catalog_falls_back_to_grouping_catalog() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["group_by"].append(
        {"id": "logical_model", "label": text("Logical model", "逻辑模型")}
    )
    metric["capabilities"]["charts"] = {
        "ranking": {
            "granularities": ["day"],
            "group_by": ["real_model"],
            "partition_by": [None, "logical_model"],
        }
    }

    parsed = parse_v2_probe_descriptor(value).metrics[0]

    assert parsed.capabilities.partition_by is None
    assert parsed.capabilities.charts["ranking"].partition_by == (None, "logical_model")

def test_v2_ranking_explicit_partition_catalog_takes_precedence() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["group_by"].append(
        {"id": "group_only", "label": text("Group only", "仅分组")}
    )
    metric["capabilities"]["partition_by"] = [
        {"id": "partition_only", "label": text("Partition only", "仅分区")}
    ]
    metric["capabilities"]["charts"] = {
        "ranking": {
            "granularities": ["day"],
            "group_by": ["real_model"],
            "partition_by": ["group_only"],
        }
    }

    with pytest.raises(CustomProtocolError, match="partition_by.*declared"):
        parse_v2_probe_descriptor(value)

def test_v2_partition_rejects_unknown_ids_and_nonranking_declarations() -> None:
    value = v2_probe_descriptor()
    value["metrics"][0]["capabilities"]["charts"] = {
        "ranking": {
            "granularities": ["day"],
            "group_by": ["real_model"],
            "partition_by": ["missing"],
        }
    }
    with pytest.raises(CustomProtocolError, match="partition_by.*declared"):
        parse_v2_probe_descriptor(value)

    value = v2_probe_descriptor()
    value["metrics"][0]["capabilities"]["charts"] = {
        "timeline": {
            "granularities": ["day"],
            "group_by": ["real_model"],
            "partition_by": [None],
        }
    }
    with pytest.raises(CustomProtocolError, match="partition_by.*ranking"):
        parse_v2_probe_descriptor(value)

def test_v2_ranking_rejects_invalid_partition_defaults() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["group_by"].append(
        {"id": "logical_model", "label": text("Logical model", "逻辑模型")}
    )
    metric["capabilities"]["charts"] = {
        "ranking": {
            "granularities": ["day"],
            "group_by": [None, "real_model", "logical_model"],
            "partition_by": ["logical_model"],
        }
    }

    metric["defaults"] = {"ranking": {"partition_by": "logical_model", "group_by": None}}
    with pytest.raises(CustomProtocolError, match="requires.*group_by"):
        parse_v2_probe_descriptor(value)

    metric["defaults"] = {"ranking": {"partition_by": "logical_model", "group_by": "logical_model"}}
    with pytest.raises(CustomProtocolError, match="must differ"):
        parse_v2_probe_descriptor(value)

    metric["defaults"] = {"ranking": {"partition_by": "missing", "group_by": "real_model"}}
    with pytest.raises(CustomProtocolError, match="partition_by.*supported"):
        parse_v2_probe_descriptor(value)

def test_v2_required_partition_rejects_null_default_and_nonranking_default() -> None:
    value = v2_probe_descriptor()
    metric = value["metrics"][0]
    metric["capabilities"]["group_by"].append(
        {"id": "logical_model", "label": text("Logical model", "逻辑模型")}
    )
    metric["capabilities"]["charts"] = {
        "ranking": {
            "granularities": ["day"],
            "group_by": ["real_model"],
            "partition_by": ["logical_model"],
        }
    }
    metric["defaults"] = {"ranking": {"partition_by": None, "group_by": "real_model"}}
    with pytest.raises(CustomProtocolError, match="partition_by.*required"):
        parse_v2_probe_descriptor(value)

    value = v2_probe_descriptor()
    value["metrics"][0]["capabilities"]["charts"] = {
        "timeline": {"granularities": ["day"], "group_by": ["real_model"]}
    }
    value["metrics"][0]["defaults"] = {
        "timeline": {"partition_by": "real_model", "group_by": "real_model"}
    }
    with pytest.raises(CustomProtocolError, match="partition_by.*ranking"):
        parse_v2_probe_descriptor(value)

def test_flat_v2_ranking_parses_scalar_metadata_and_rejects_points() -> None:
    request = partitioned_ranking_request(
        partition_by=None, partition_declared=False, chart_kind="ranking"
    )
    root = v2_ranking_response_root(request)
    item = ranking_series("route-a", "185.2")
    item.update(
        description=text("Route A requests", "路由 A 请求"),
        display=text("185 requests", "185 次请求"),
        comparison_display=text("+12 requests", "+12 次请求"),
        link="https://example.com/routes/a",
    )
    root["data"] = {"series": [item]}

    response = parse_custom_response(json.dumps(root).encode(), request)
    parsed = response.data.series[0]  # type: ignore[union-attr]

    assert parsed.value == Decimal("185.2")
    assert not hasattr(parsed, "points")
    assert not hasattr(parsed, "date")
    assert parsed.description == LocalizedText("Route A requests", "路由 A 请求")
    assert parsed.link == "https://example.com/routes/a"

    for malformed in (
        {**item, "points": [{"date": "2026-10-08", "value": "185.2"}]},
        {key: value for key, value in item.items() if key != "value"}
        | {"points": [{"date": "2026-10-08", "value": "185.2"}]},
    ):
        root["data"] = {"series": [malformed]}
        with pytest.raises(CustomProtocolError, match="must use scalar value"):
            parse_custom_response(json.dumps(root).encode(), request)

def test_partitioned_v2_ranking_parses_ordered_groups_and_repeated_inner_ids() -> None:
    request = partitioned_ranking_request()
    root = v2_ranking_response_root(request)
    root["data"] = {
        "groups": [
            ranking_group("coding", "Coding", [ranking_series("shared", "7")]),
            ranking_group("general", "General", [ranking_series("shared", "5")]),
        ]
    }

    response = parse_custom_response(json.dumps(root).encode(), request)

    assert response.data.groups is not None  # type: ignore[union-attr]
    assert [group.id for group in response.data.groups] == ["coding", "general"]  # type: ignore[union-attr]
    assert response.data.groups[0].series[0].id == response.data.groups[1].series[0].id  # type: ignore[union-attr]
    assert response.data.groups[0].series[0].value == Decimal("7")  # type: ignore[union-attr]
    assert not hasattr(response.data.groups[0].series[0], "points")  # type: ignore[union-attr]
    assert response.data.series == ()  # type: ignore[union-attr]

def test_partitioned_v2_ranking_parses_group_metadata_and_empty_groups() -> None:
    request = partitioned_ranking_request()
    root = v2_ranking_response_root(request)
    group = ranking_group("coding", "Coding", [])
    group.update(
        description=text("Routes coding workloads", "路由代码任务"),
        display=text("12 requests", "12 次请求"),
        comparison_display=text("+2 requests", "+2 次请求"),
        link="https://example.com/router/coding",
    )
    root["data"] = {"groups": [group]}

    response = parse_custom_response(json.dumps(root).encode(), request)
    parsed = response.data.groups[0]  # type: ignore[union-attr,index]

    assert parsed.description == LocalizedText("Routes coding workloads", "路由代码任务")
    assert parsed.display == LocalizedText("12 requests", "12 次请求")
    assert parsed.comparison_display == LocalizedText("+2 requests", "+2 次请求")
    assert parsed.link == "https://example.com/router/coding"
    assert parsed.series == ()

def test_grouped_v2_ranking_rejects_duplicate_ids_and_unsafe_metadata() -> None:
    request = partitioned_ranking_request()
    root = v2_ranking_response_root(request)
    root["data"] = {"groups": [ranking_group("same", "One", []), ranking_group("same", "Two", [])]}
    with pytest.raises(CustomProtocolError, match="data groups IDs must be unique"):
        parse_custom_response(json.dumps(root).encode(), request)

    duplicate = ranking_series("same")
    root["data"] = {"groups": [ranking_group("one", "One", [duplicate, ranking_series("same")])]}
    with pytest.raises(CustomProtocolError, match=r"data\.groups\[0\]\.series IDs must be unique"):
        parse_custom_response(json.dumps(root).encode(), request)

    unsafe = ranking_group("one", "One", [])
    unsafe["link"] = "http://example.com/one"
    root["data"] = {"groups": [unsafe]}
    with pytest.raises(CustomProtocolError, match=r"data\.groups\[0\]\.link.*https"):
        parse_custom_response(json.dumps(root).encode(), request)

    unsafe["link"] = "https://example.com/one\x9c\x9d8;;https://evil.example"
    with pytest.raises(CustomProtocolError, match=r"data\.groups\[0\]\.link.*https"):
        parse_custom_response(json.dumps(root).encode(), request)

def test_grouped_v2_ranking_errors_include_the_complete_failing_path() -> None:
    request = partitioned_ranking_request()
    root = v2_ranking_response_root(request)
    malformed = ranking_series(value=7)
    root["data"] = {"groups": [ranking_group("one", "One", [malformed])]}

    with pytest.raises(
        CustomProtocolError,
        match=r"data\.groups\[0\]\.series\[0\]\.value must be a decimal string",
    ):
        parse_custom_response(json.dumps(root).encode(), request)

    group = ranking_group("one", "One", [])
    group["description"] = {"en": "English only"}
    root["data"] = {"groups": [group]}
    with pytest.raises(CustomProtocolError, match=r"data\.groups\[0\]\.description zh-CN"):
        parse_custom_response(json.dumps(root).encode(), request)

def test_flat_v2_ranking_applies_max_items_with_multiple_historical_capabilities() -> None:
    request = partitioned_ranking_request(
        partition_by=None,
        partition_declared=False,
        chart_kind="ranking",
    )
    assert "partition_by" not in request.to_wire()["query"]
    assert request.to_wire()["chart_kind"] == "ranking"
    assert "granularity" not in request.to_wire()["query"]
    assert canonical_custom_request_key(request) == canonical_custom_request_key(
        replace(request, granularity="legacy")
    )
    assert canonical_custom_request_key(request) != canonical_custom_request_key(
        replace(request, chart_kind="timeline")
    )

    root = v2_ranking_response_root(request, max_items=2)
    metric = root["descriptor"]["metrics"][0]  # type: ignore[index]
    metric["capabilities"]["charts"]["timeline"] = {  # type: ignore[index]
        "granularities": ["day"],
        "group_by": ["real_model"],
    }
    root["data"] = {"series": [ranking_series("a"), ranking_series("b"), ranking_series("c")]}

    with pytest.raises(CustomProtocolError, match="data must not contain more than 2 series"):
        parse_custom_response(json.dumps(root).encode(), request)

def test_grouped_v2_ranking_applies_max_items_globally() -> None:
    request = partitioned_ranking_request()
    root = v2_ranking_response_root(request, max_items=2)
    root["data"] = {
        "groups": [
            ranking_group("one", "One", [ranking_series("a"), ranking_series("b")]),
            ranking_group("two", "Two", [ranking_series("a")]),
        ]
    }

    with pytest.raises(CustomProtocolError, match="data must not contain more than 2 series"):
        parse_custom_response(json.dumps(root).encode(), request)

def test_v2_ranking_rejects_invalid_sort_direction() -> None:
    value = v2_probe_descriptor()
    value["metrics"][0]["capabilities"]["charts"] = {
        "ranking": {"group_by": [None], "sort_direction": "sideways"}
    }

    with pytest.raises(CustomProtocolError, match="sort_direction"):
        parse_v2_probe_descriptor(value)

def test_v2_ranking_capability_accepts_a_positive_source_limit() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"]["ranking"] = {  # type: ignore[index]
        "granularities": ["day"],
        "group_by": ["real_model"],
        "max_items": 10,
    }

    capability = parse_v2_probe_descriptor(descriptor).metrics[0].capabilities.charts["ranking"]

    assert capability.max_items == 10  # type: ignore[union-attr]

def test_ranking_capabilities_accept_description_defaults_and_reject_them_elsewhere() -> None:
    descriptor = probe_response()
    descriptor["descriptor"]["capabilities"]["charts"]["ranking"][  # type: ignore[index]
        "descriptions_default"
    ] = "expanded"

    parsed = parse_custom_response(json.dumps(descriptor).encode(), probe_request())

    assert parsed.descriptor.capabilities.charts["ranking"].descriptions_default == "expanded"  # type: ignore[union-attr]

    descriptor["descriptor"]["capabilities"]["charts"]["timeline"][  # type: ignore[index]
        "descriptions_default"
    ] = "expanded"
    with pytest.raises(CustomProtocolError, match="descriptions_default"):
        parse_custom_response(json.dumps(descriptor).encode(), probe_request())

def test_v2_ranking_capability_accepts_a_description_default() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"] = {  # type: ignore[index]
        "ranking": {
            "group_by": ["real_model"],
            "descriptions_default": "expanded",
        }
    }

    capability = parse_v2_probe_descriptor(descriptor).metrics[0].capabilities.charts["ranking"]

    assert capability.descriptions_default == "expanded"  # type: ignore[union-attr]

def test_v2_ranking_default_all_is_allowed_and_invalid_defaults_are_ignored() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"] = {
        "ranking": {"group_by": [], "periods": ["all"]}
    }
    descriptor["metrics"][0]["defaults"] = {
        "ranking": {"period": "all", "group_by": None, "top": None}
    }

    assert parse_v2_probe_descriptor(descriptor).metrics[0].defaults["ranking"].period == "all"

    descriptor["metrics"][0]["defaults"] = {
        "timeline": {"period": "all", "group_by": None, "top": None}
    }
    parsed = parse_v2_probe_descriptor(descriptor)
    assert parsed.metrics[0].defaults["timeline"].period is None

@pytest.mark.parametrize("comparison", ("full", "rank", "none"))
def test_v2_ranking_capability_accepts_comparison_presentation(comparison: str) -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"] = {  # type: ignore[index]
        "ranking": {
            "group_by": [],
            "comparison": comparison,
        }
    }

    capability = parse_v2_probe_descriptor(descriptor).metrics[0].capabilities.charts["ranking"]

    assert capability.comparison == comparison  # type: ignore[union-attr]

def test_v2_ranking_comparison_rejects_invalid_or_nonranking_values() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["capabilities"]["charts"] = {  # type: ignore[index]
        "ranking": {"group_by": [], "comparison": "growth"}
    }
    with pytest.raises(CustomProtocolError, match="comparison"):
        parse_v2_probe_descriptor(descriptor)

    descriptor["metrics"][0]["capabilities"]["charts"] = {  # type: ignore[index]
        "timeline": {"granularities": ["day"], "group_by": [], "comparison": "rank"}
    }
    with pytest.raises(CustomProtocolError, match="comparison"):
        parse_v2_probe_descriptor(descriptor)
