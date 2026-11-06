"""Additive V2 Ranking semantic classification validation."""

import json
from dataclasses import FrozenInstanceError

import pytest

from ccusage_viz.custom_models import CustomRankingBand, LocalizedText, V2RankingData
from ccusage_viz.custom_protocol.parsing import parse_custom_response
from ccusage_viz.custom_protocol.primitives import CustomProtocolError
from ccusage_viz.custom_protocol.responses import V2ChartResponse

from .helpers import (
    partitioned_ranking_request,
    ranking_group,
    ranking_series,
    text,
    v2_ranking_response_root,
)

_MISSING = object()


def parse_bands(
    *, grouped: bool, bands: object = _MISSING, band_id: object = _MISSING
) -> V2RankingData:
    request = partitioned_ranking_request(partition_by="logical_model" if grouped else None)
    root = v2_ranking_response_root(request)
    entry = ranking_series("same")
    if band_id is not _MISSING:
        entry["band_id"] = band_id
    data: dict[str, object] = (
        {"groups": [ranking_group("one", "One", [entry]), ranking_group("two", "Two", [entry])]}
        if grouped
        else {"series": [entry]}
    )
    if bands is not _MISSING:
        data["bands"] = bands
    root["data"] = data
    response = parse_custom_response(json.dumps(root).encode(), request)
    assert isinstance(response, V2ChartResponse)
    assert isinstance(response.data, V2RankingData)
    return response.data


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("bands", [_MISSING, None, []])
@pytest.mark.parametrize("band_id", [_MISSING, None])
def test_omitted_null_and_empty_bands_preserve_old_payloads(
    grouped: bool, bands: object, band_id: object
) -> None:
    data = parse_bands(grouped=grouped, bands=bands, band_id=band_id)
    assert data.bands == ()
    entries = data.groups[0].series if data.groups is not None else data.series
    assert entries[0].band_id is None


@pytest.mark.parametrize("grouped", [False, True])
def test_ordered_mixed_bands_use_ids_not_labels(grouped: bool) -> None:
    data = parse_bands(
        grouped=grouped,
        bands=[
            {"id": "second", "label": text("Qualified", "晋级")},
            {"id": "first"},
            {"id": "third", "label": None},
            {"id": "fourth", "label": text("Qualified", "晋级")},
        ],
        band_id="first",
    )
    assert data.bands == (
        CustomRankingBand("second", LocalizedText("Qualified", "晋级")),
        CustomRankingBand("first"),
        CustomRankingBand("third"),
        CustomRankingBand("fourth", LocalizedText("Qualified", "晋级")),
    )
    entries = data.groups[0].series if data.groups is not None else data.series
    assert entries[0].band_id == "first"
    if data.groups is not None:
        assert data.groups[1].series[0].band_id == "first"
    with pytest.raises(FrozenInstanceError):
        data.bands[0].id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("grouped", [False, True])
def test_all_unnamed_bands_are_valid(grouped: bool) -> None:
    data = parse_bands(grouped=grouped, bands=[{"id": "a"}, {"id": "b"}], band_id="b")
    assert [band.label for band in data.bands] == [None, None]


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize(
    ("bands", "band_id", "error"),
    [
        ([{"id": "a"}, {"id": "a"}], None, "data bands IDs must be unique"),
        ([{"id": "a"}], "unknown", "references unknown band ID"),
        (None, "a", "references unknown band ID"),
        ([], "a", "references unknown band ID"),
        ([{"id": ""}], None, r"data.bands\[0\].id must be a non-empty string"),
        ([{"id": 1}], None, r"data.bands\[0\].id must be a non-empty string"),
        ([{}], None, r"data.bands\[0\].id must be a non-empty string"),
        ([{"id": "a", "label": {"en": "A"}}], None, "label zh-CN"),
        ([{"id": "a", "label": {"zh-CN": "甲"}}], None, "label en"),
        ([{"id": "a", "label": text("", "甲")}], None, "label en"),
        ([{"id": "a", "label": "A"}], None, "label must be an object"),
        ({"id": "a"}, None, "data bands must be an array"),
        ([None], None, r"data.bands\[0\] must be an object"),
        ([{"id": "a"}], "", "band_id must be a non-empty string"),
        ([{"id": "a"}], 1, "band_id must be a non-empty string"),
    ],
)
def test_invalid_band_definitions_and_membership_reject_response(
    grouped: bool, bands: object, band_id: object, error: str
) -> None:
    with pytest.raises(CustomProtocolError, match=error):
        parse_bands(grouped=grouped, bands=bands, band_id=band_id)
