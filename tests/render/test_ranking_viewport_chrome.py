from dataclasses import replace

import pytest

from ccusage_viz.render.custom_ranking_viewport import render_custom_ranking_viewport
from ccusage_viz.render.grouped_ranking_viewport import (
    GroupedRankingViewport,
    render_grouped_custom_ranking_viewport,
)
from ccusage_viz.render.ranking_viewport import RankingViewport

from .helpers import _grouped_ranking_projection, context


@pytest.mark.parametrize("grouped", (False, True))
@pytest.mark.parametrize("style", ("list", "dot", "dots", "bars"))
@pytest.mark.parametrize("density", ("minimal", "full", "detailed"))
@pytest.mark.parametrize("search", (False, True))
def test_ranking_viewport_has_no_phantom_column_header_chrome(
    grouped: bool, style: str, density: str, search: bool
) -> None:
    projection = _grouped_ranking_projection()
    if not grouped:
        projection = replace(projection, series=projection.groups[0].series, groups=())
    ctx = replace(context(True), width=100, height=8, style=style, density=density)
    viewport = GroupedRankingViewport() if grouped else RankingViewport()
    render = render_grouped_custom_ranking_viewport if grouped else render_custom_ranking_viewport
    output = render(
        projection,
        ctx,
        viewport,
        heading="Ranking",
        descriptions_visible=False,
        search_query="coding" if search else "",
        search_editing=search,
        show_visible_count=True,
        copied_entry_id=None,
        item_spacing="compact",
    )
    lines = output.splitlines()
    expected_chrome = 1 + int(search) + int(density != "minimal")

    assert lines[0].strip() == "Ranking"
    assert "Current" not in output and "vs prior" not in output and "Rank Δ" not in output
    assert viewport.body_top == expected_chrome
    assert viewport.visible_rows == ctx.height - expected_chrome
    first_body_label = "Coding Model" if grouped else "coding-a"
    assert first_body_label in lines[expected_chrome]
    assert "coding-a" in output and "coding-b" in output
    assert len(lines) <= ctx.height
    if density != "minimal":
        total = 3 if grouped else 2
        expected_count = f"Showing 2/{total} item(s)" if search else f"{total} item(s) total"
        assert lines[expected_chrome - 1] == expected_count
    if not search and grouped:
        assert "General Model" in output
