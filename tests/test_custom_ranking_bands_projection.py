"""Classification follows current scalar facts, independently of comparisons."""

from dataclasses import replace
from decimal import Decimal

from ccusage_viz.custom_models import (
    CustomRankingBand,
    CustomRankingEntry,
    LocalizedText,
    V2RankingData,
    V2RankingGroup,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.processing.custom_ranking import process_custom_ranking
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom_ranking_preparation import prepare_custom_ranking
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from tests.test_custom_ranking_projection import config, entry, response


def classified(identifier: str, value: str, band_id: str) -> CustomRankingEntry:
    return replace(entry(identifier, value), band_id=band_id)


def test_band_fields_append_to_existing_positional_constructors() -> None:
    fact = CustomRankingEntry(
        "a", LocalizedText("A", "甲"), Decimal("1"), None, None, None, None, "band"
    )
    prepared = RankingPresentationEntry("a", "A", 1)
    assert fact.band_id == "band"
    assert prepared.band_id is None
    assert V2RankingData((fact,), None).bands == ()


def test_current_snapshot_bands_and_membership_override_comparison() -> None:
    bands = (
        CustomRankingBand("new", LocalizedText("Current", "当前")),
        CustomRankingBand("unused"),
    )
    current = response(V2RankingData((classified("a", "10", "new"), entry("b", "5")), bands=bands))
    previous = response(
        V2RankingData(
            (classified("a", "9", "old"), classified("b", "4", "old")),
            bands=(CustomRankingBand("old"),),
        )
    )
    chart = config(top=None, other="hide")
    projection = process_custom_ranking(
        current, chart, comparison_response=previous, comparison_config=chart
    )
    assert projection.bands is current.data.bands
    assert [item.band_id for item in projection.series] == ["new", None]
    assert [item.previous_total for item in projection.series] == [Decimal("9"), Decimal("4")]

    # A later snapshot with no classification must not inherit old facts.
    unclassified = process_custom_ranking(
        response(V2RankingData((entry("a", "11"),))),
        chart,
        comparison_response=current,
        comparison_config=chart,
    )
    assert unclassified.bands == ()
    assert unclassified.series[0].band_id is None


def test_top_search_and_other_preserve_declared_order_and_membership() -> None:
    bands = (CustomRankingBand("unused"), CustomRankingBand("low"), CustomRankingBand("high"))
    projection = process_custom_ranking(
        response(
            V2RankingData(
                (
                    classified("a", "9", "high"),
                    classified("b", "5", "low"),
                    classified("c", "3", "high"),
                ),
                bands=bands,
            )
        ),
        config(),
    )
    assert projection.bands == bands
    assert [(item.id, item.band_id) for item in projection.series] == [
        ("a", "high"),
        ("other", None),
    ]
    context = RenderContext(80, 24, load_translator("en"), color=False)
    prepared = prepare_custom_ranking(projection, context, search_query="a")
    assert [(item.key, item.band_id) for item in prepared.full_entries] == [
        ("a", "high"),
        ("other", None),
    ]
    assert [(item.key, item.band_id) for item in prepared.matched_entries] == [("a", "high")]
    assert projection.bands == bands


def test_group_local_ids_have_independent_current_membership_and_shared_definitions() -> None:
    bands = (CustomRankingBand("one"), CustomRankingBand("two"))
    current = response(
        V2RankingData(
            groups=(
                V2RankingGroup("g1", LocalizedText("G1", "一"), (classified("same", "9", "one"),)),
                V2RankingGroup("g2", LocalizedText("G2", "二"), (classified("same", "3", "two"),)),
            ),
            bands=bands,
        )
    )
    previous = response(
        V2RankingData(
            groups=(
                V2RankingGroup("g1", LocalizedText("G1", "一"), (classified("same", "8", "old"),)),
                V2RankingGroup("g2", LocalizedText("G2", "二"), (classified("same", "1", "old"),)),
            ),
            bands=(CustomRankingBand("old"),),
        )
    )
    chart = config(top=None, other="hide")
    projection = process_custom_ranking(
        current, chart, comparison_response=previous, comparison_config=chart
    )
    assert projection.bands == bands
    assert projection.groups is not None
    assert [group.series[0].band_id for group in projection.groups] == ["one", "two"]
    assert [group.series[0].previous_total for group in projection.groups] == [
        Decimal("8"),
        Decimal("1"),
    ]
    context = RenderContext(80, 24, load_translator("en"), color=False)
    assert [
        prepare_custom_ranking(replace(projection, series=group.series, groups=None), context)
        .full_entries[0]
        .band_id
        for group in projection.groups
    ] == ["one", "two"]
