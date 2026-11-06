from dataclasses import replace

import pytest

from ccusage_viz.formatting import strip_ansi
from ccusage_viz.render.grouped_ranking import render_grouped_custom_ranking
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_historical import render_historical_ranking

from .helpers import _grouped_ranking_projection, context


@pytest.mark.parametrize("style", ("dot", "dots", "bars"))
def test_ranking_prefix_has_only_one_rank_change_slot(style):
    ctx = replace(context(True), width=80, style=style, rank_deltas={"a": 1})
    output = render_historical_ranking(
        (RankingPresentationEntry("a", "Alpha", 10), RankingPresentationEntry("b", "Beta", 5)),
        heading="Ranking",
        value_formatter=str,
        context=ctx,
        total=15,
    )
    alpha = next(row for row in output.splitlines() if "Alpha" in row)
    beta = next(row for row in output.splitlines() if "Beta" in row)
    assert "1 ^ Alpha" in alpha
    assert "2   Beta" in beta
    assert "1 ^   Alpha" not in alpha


def test_list_prefix_places_label_immediately_after_rank():
    ctx = replace(context(True), width=50, style="list", rank_deltas={"a": 1})
    output = render_historical_ranking(
        (RankingPresentationEntry("a", "Alpha", 10),),
        heading="Ranking",
        value_formatter=str,
        context=ctx,
        total=10,
        show_percentage=False,
    )
    row = next(row for row in output.splitlines() if "Alpha" in row)
    assert row.startswith(" 1 Alpha")
    assert "^" not in row


def test_grouped_ranking_uses_same_compact_prefix():
    projection = replace(
        _grouped_ranking_projection(), show_percentage=False, comparison_available=False
    )
    output = strip_ansi(
        render_grouped_custom_ranking(
            projection, replace(context(True), width=80, style="dot"), heading="Ranking"
        )
    )
    row = next(row for row in output.splitlines() if "coding-a" in row)
    assert row.startswith(" 1   coding-a")
    assert not row.startswith(" 1     coding-a")
