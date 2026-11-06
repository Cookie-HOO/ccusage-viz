from dataclasses import replace

import pytest

from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.render.grouped_ranking import render_grouped_custom_ranking
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_historical import render_historical_ranking

from .helpers import _grouped_ranking_projection, context


@pytest.mark.parametrize("width", (38, 60, 100))
@pytest.mark.parametrize("visible", (True, False))
@pytest.mark.parametrize("comparison", (True, False))
@pytest.mark.parametrize("density", ("compact", "full", "detailed"))
@pytest.mark.parametrize("style", ("dot", "dots", "bars", "list"))
def test_flat_ranking_last_field_reaches_right_edge(width, visible, comparison, density, style):
    ctx = replace(context(True), width=width, density=density, style=style)
    entries = (
        RankingPresentationEntry("a", "Alpha", 600, 500, comparison_ready=True),
        RankingPresentationEntry("b", "Beta", 400, 350, comparison_ready=True),
    )
    rendered = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=ctx,
        total=1000,
        show_percentage=visible,
        comparison_available=comparison,
    )
    rows = [strip_ansi(row) for row in rendered.splitlines() if "Alpha" in row or "Beta" in row]
    assert len(rows) == 2
    assert all(display_width(row) == ctx.width for row in rows)
    assert all(display_width(row.rstrip()) >= ctx.width - 2 for row in rows)


@pytest.mark.parametrize("visible", (True, False))
@pytest.mark.parametrize("comparison", (True, False))
@pytest.mark.parametrize("density", ("compact", "full"))
def test_grouped_headings_and_entries_share_right_edge(visible, comparison, density):
    ctx = replace(context(True), width=100, density=density, style="dot")
    projection = replace(
        _grouped_ranking_projection(), show_percentage=visible, comparison_available=comparison
    )
    rendered = render_grouped_custom_ranking(projection, ctx, heading="Ranking")
    rows = [
        strip_ansi(row)
        for row in rendered.splitlines()
        if "requests" in row or "source-owned total" in row
    ]
    assert rows
    assert all(display_width(row) == ctx.width for row in rows)
