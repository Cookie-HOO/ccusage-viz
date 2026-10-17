import json

import pytest

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.custom_protocol.parsing import parse_custom_response
from ccusage_viz.custom_protocol.primitives import (
    CustomProtocolError,
)

from .helpers import (
    chart_request,
    chart_response,
    partitioned_ranking_request,
    text,
    v2_ranking_response_root,
)


def test_v2_ranking_response_rejects_grouped_request_when_partition_capability_is_removed() -> None:
    request = partitioned_ranking_request()
    root = v2_ranking_response_root(request)
    ranking = root["descriptor"]["metrics"][0]["capabilities"]["charts"]["ranking"]  # type: ignore[index]
    del ranking["partition_by"]  # type: ignore[attr-defined]

    with pytest.raises(
        CustomProtocolError,
        match="response ranking capability does not declare request partition_by",
    ):
        parse_custom_response(json.dumps(root).encode(), request)


def test_v2_ranking_response_rejects_grouped_request_with_unsupported_partition_id() -> None:
    request = partitioned_ranking_request(partition_by="unsupported")
    root = v2_ranking_response_root(request)

    with pytest.raises(
        CustomProtocolError,
        match="response ranking capability partition_by is not supported",
    ):
        parse_custom_response(json.dumps(root).encode(), request)


def test_v2_ranking_response_rejects_declared_null_when_partition_is_required() -> None:
    request = partitioned_ranking_request(partition_by=None)
    root = v2_ranking_response_root(request)
    ranking = root["descriptor"]["metrics"][0]["capabilities"]["charts"]["ranking"]  # type: ignore[index]
    ranking["partition_by"] = ["logical_model"]  # type: ignore[index]
    root["data"] = {"series": []}

    with pytest.raises(
        CustomProtocolError,
        match="response ranking capability partition_by is required",
    ):
        parse_custom_response(json.dumps(root).encode(), request)


@pytest.mark.parametrize(("declared", "descriptor_declared"), ((False, False), (True, True)))
def test_v2_ranking_response_accepts_old_and_declared_flat_requests(
    declared: bool, descriptor_declared: bool
) -> None:
    request = partitioned_ranking_request(
        partition_by=None,
        partition_declared=declared,
        chart_kind="ranking",
    )
    root = v2_ranking_response_root(request)
    ranking = root["descriptor"]["metrics"][0]["capabilities"]["charts"]["ranking"]  # type: ignore[index]
    if not descriptor_declared:
        del ranking["partition_by"]  # type: ignore[attr-defined]
    root["data"] = {"series": []}

    response = parse_custom_response(json.dumps(root).encode(), request)

    assert response.data.groups is None  # type: ignore[union-attr]


def test_v2_ranking_response_enforces_flat_or_grouped_shape_from_request() -> None:
    partitioned = partitioned_ranking_request()
    grouped_root = v2_ranking_response_root(partitioned)
    grouped_root["data"] = {"series": []}
    with pytest.raises(CustomProtocolError, match="data groups"):
        parse_custom_response(json.dumps(grouped_root).encode(), partitioned)

    flat = partitioned_ranking_request(partition_by=None)
    flat_root = v2_ranking_response_root(flat)
    flat_root["data"] = {"groups": []}
    with pytest.raises(CustomProtocolError, match="data series"):
        parse_custom_response(json.dumps(flat_root).encode(), flat)

    flat_root["data"] = {"series": [], "groups": []}
    with pytest.raises(CustomProtocolError, match="mutually exclusive"):
        parse_custom_response(json.dumps(flat_root).encode(), flat)


def test_ranking_response_parses_a_localized_description() -> None:
    payload = chart_response()
    payload["data"]["series"][0]["description"] = text("Release validation", "发布验证")  # type: ignore[index]

    parsed = parse_custom_response(json.dumps(payload).encode(), chart_request())

    assert parsed.data.series[0].description == LocalizedText("Release validation", "发布验证")  # type: ignore[union-attr]


def test_ranking_response_parses_a_dataset_owned_display() -> None:
    payload = chart_response()
    payload["data"]["series"][0]["display"] = text("15 pages", "15 页")  # type: ignore[index]

    parsed = parse_custom_response(json.dumps(payload).encode(), chart_request())

    assert parsed.data.series[0].display == LocalizedText("15 pages", "15 页")  # type: ignore[union-attr]


def test_ranking_response_accepts_only_absolute_https_project_links() -> None:
    payload = chart_response()
    payload["data"]["series"][0]["link"] = "https://example.com/books/book-001"  # type: ignore[index]

    parsed = parse_custom_response(json.dumps(payload).encode(), chart_request())

    assert parsed.data.series[0].link == "https://example.com/books/book-001"  # type: ignore[union-attr]

    payload["data"]["series"][0]["link"] = "http://example.com/books/book-001"  # type: ignore[index]
    with pytest.raises(CustomProtocolError, match="absolute https"):
        parse_custom_response(json.dumps(payload).encode(), chart_request())

    payload["data"]["series"][0]["link"] = "https://example.com/\x1b]8;;evil"  # type: ignore[index]
    with pytest.raises(CustomProtocolError, match="absolute https"):
        parse_custom_response(json.dumps(payload).encode(), chart_request())

    payload["data"]["series"][0]["link"] = "https://example.com/book\x9c\x9d8;;evil"  # type: ignore[index]
    with pytest.raises(CustomProtocolError, match="absolute https"):
        parse_custom_response(json.dumps(payload).encode(), chart_request())


def test_chart_response_preserves_a_ranking_source_limit() -> None:
    request = chart_request()
    response = chart_response()
    response["capabilities"]["charts"]["ranking"]["max_items"] = 10  # type: ignore[index]

    parsed = parse_custom_response(json.dumps(response).encode(), request)

    assert parsed.capabilities.charts["ranking"].max_items == 10  # type: ignore[union-attr]
