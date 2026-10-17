from dataclasses import replace

import pytest

import ccusage_viz.tui.custom_rendering as tui_custom_rendering
import ccusage_viz.tui.rendering as tui_rendering
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
)
from ccusage_viz.render.custom import render_custom_ranking
from ccusage_viz.render.grouped_ranking_viewport import (
    GroupedRankingViewport,
)
from ccusage_viz.render.ranking_viewport import RankingViewport

from .helpers import (
    _search_fact_projection,
    context,
    grouped_projection,
    projection,
    render,
    render_grouped,
)


@pytest.mark.parametrize("visible_rows", (1, 2, 10, 30))
def test_direct_wheel_steps_and_bounds(visible_rows: int) -> None:
    viewport = RankingViewport(total_rows=100, visible_rows=visible_rows)
    assert viewport.scroll(1)
    assert viewport.offset == 1
    assert viewport.scroll(-1)
    assert viewport.offset == 0
    assert not viewport.scroll(-1)
    maximum = viewport.total_rows - viewport.visible_rows
    viewport.offset = maximum - 1
    assert viewport.scroll(1)
    assert viewport.offset == maximum
    assert not viewport.scroll(1)
    assert viewport.scroll(-1)
    assert viewport.offset == maximum - 1
    assert not viewport.scroll(0)


def test_small_and_zero_height_viewports() -> None:
    viewport = RankingViewport(total_rows=100, visible_rows=2)
    assert viewport.scroll(1)
    assert viewport.offset == 1
    viewport.visible_rows = 0
    assert not viewport.scroll(1)
    assert viewport.offset == 1


@pytest.mark.parametrize("spacing", ("compact", "space", "line", "dashed"))
@pytest.mark.parametrize("descriptions", (False, True))
def test_isolated_wheel_moves_tracked_entry_one_screen_row(spacing, descriptions):
    model = projection(30, descriptions=descriptions)
    viewport = RankingViewport()
    ctx = context(height=24, density="detailed" if descriptions else "normal")
    render(model, viewport, ctx, spacing=spacing)
    prepared = viewport.starts

    def tracked_row():
        return next(row for row, hit in viewport.hits.items() if hit[0] == "4")

    before = tracked_row()
    # Separate reports must remain one-line moves, without burst acceleration.
    for expected_offset in (1, 2, 3):
        assert viewport.scroll(1)
        render(model, viewport, ctx, spacing=spacing)
        assert viewport.offset == expected_offset
        assert tracked_row() == before - expected_offset
        assert viewport.starts is prepared
    assert viewport.scroll(-1)
    render(model, viewport, ctx, spacing=spacing)
    assert tracked_row() == before - 2


def test_dashboard_partition_mode_switch_clears_incompatible_viewport_state() -> None:
    from ccusage_viz.terminal import Terminal

    grouped = GroupedRankingViewport()
    flat = RankingViewport(offset=3)
    model = grouped_projection()

    def dispatch(projection: CustomChartProjection) -> None:
        tui_custom_rendering._render_custom_projection(
            projection,
            projection.config,
            load_translator("en"),
            Terminal(100, 12, False, False),
            accepted_at=None,
            interval=None,
            pending=False,
            surface=tui_rendering.dashboard_pane_surface("ranking"),
            ranking_viewport=flat,
            grouped_ranking_viewport=grouped,
        )

    dispatch(model)
    assert grouped.active
    # Grouped dispatch clears all stale flat state, not merely its active bit.
    assert flat.offset == 0 and not flat.hits and not flat._geometry_cache
    grouped.offset = 2
    grouped.hits[9] = (("group", "coding"), 10, None)
    dispatch(replace(model, groups=None, series=projection(3).series))
    assert flat.active
    assert grouped.offset == 0 and not grouped.hits and not grouped.rows


def test_list_viewport_has_no_copy_actions_and_expands_labels() -> None:
    viewport = RankingViewport()

    output = strip_ansi(
        render(
            projection(20),
            viewport,
            replace(context(height=30), style="list"),
            copy_all_action=True,
        )
    )

    assert viewport.copy_all_hit is None
    assert viewport.hits == {}
    assert "⊞" not in output and "→" not in output
    assert "Project 19" in output


def test_direct_and_viewport_search_render_the_same_row_facts() -> None:
    model = _search_fact_projection()
    ctx = replace(context(height=20, width=100), style="bar")
    query = "example.com/claude"
    direct = strip_ansi(
        render_custom_ranking(model, ctx, search_query=query, show_visible_count=True)
    )
    windowed = strip_ansi(render(model, RankingViewport(), ctx, search=query))

    direct_row = next(line for line in direct.splitlines() if "Claude" in line)
    viewport_row = next(line for line in windowed.splitlines() if "Claude" in line)
    assert direct_row == viewport_row


@pytest.mark.parametrize("height", (0, 1, 2, 3))
def test_tiny_viewports_and_empty_comparison(height):
    model = projection(0, comparison=True)
    viewport = RankingViewport()
    render(model, viewport, context(height=height, density="detailed"))
    assert viewport.total_rows == 0
    assert not viewport.scroll(1)


def test_standalone_custom_ranking_does_not_use_dashboard_viewport(monkeypatch):
    from ccusage_viz.custom_component import CustomHistoricalComponent
    from ccusage_viz.terminal import Terminal

    model = projection(100)
    component = CustomHistoricalComponent(model.config)
    component.model = model
    component.accepted_config = model.config
    component.pending_generation = None
    monkeypatch.setattr(
        tui_custom_rendering,
        "render_custom_ranking_viewport",
        lambda *a, **kw: pytest.fail("standalone viewport"),
    )
    output = tui_custom_rendering._custom_standalone_render(
        component, load_translator("en"), Terminal(100, 12, False, False), pending=False
    )
    assert "Project 99" in output.chart


@pytest.mark.parametrize("ascii", (False, True))
def test_scrollbar_persists_on_overflow_and_tracks_wheel_offset(ascii):
    model = projection(100)
    viewport = RankingViewport()
    ctx = replace(context(height=22), ascii=ascii)
    initial = render(model, viewport, ctx, scrollbar=True)
    bar = viewport.scrollbar
    assert bar is not None
    assert bar.column == ctx.width - 1
    assert bar.top == viewport.body_top
    assert initial == render(model, viewport, ctx, scrollbar=True)
    assert viewport.scrollbar == bar  # Idle repaint does not hide it.
    for _ in range(40):
        viewport.scroll(1)
    moved = render(model, viewport, ctx, scrollbar=True)
    assert viewport.scrollbar.thumb_top > bar.thumb_top
    rows = moved.splitlines()
    for row in range(bar.top, bar.top + bar.height):
        assert strip_ansi(rows[row])[-1] == ("|" if ascii else "│")
    assert rows[: bar.top] == initial.splitlines()[: bar.top]
    viewport.offset = 9999
    render(model, viewport, ctx, scrollbar=True)
    bar = viewport.scrollbar
    assert bar.thumb_top + bar.thumb_size == bar.top + bar.height


@pytest.mark.parametrize("grouped", (False, True))
@pytest.mark.parametrize("ascii", (False, True))
def test_scrollbar_expands_thumb_only_while_hovered(grouped, ascii):
    ctx = replace(context(height=5), ascii=ascii, color=False)
    viewport = GroupedRankingViewport() if grouped else RankingViewport()
    model = grouped_projection() if grouped else projection(100)
    renderer = render_grouped if grouped else render
    compact = renderer(model, viewport, ctx, scrollbar=True)
    bar = viewport.scrollbar
    assert bar is not None
    hovered = renderer(model, viewport, ctx, scrollbar=True, scrollbar_hovered=True)
    assert viewport.scrollbar == bar
    compact_rows = strip_ansi(compact).splitlines()
    hovered_rows = strip_ansi(hovered).splitlines()
    line, thumb = ("|", "#") if ascii else ("│", "█")
    assert compact_rows[bar.thumb_top][-1] == line
    assert hovered_rows[bar.thumb_top][-1] == thumb
    track = next(row for row in range(bar.top, bar.top + bar.height) if not bar.on_thumb(row))
    assert compact_rows[track][-1] == hovered_rows[track][-1] == line


@pytest.mark.parametrize("spacing", ("compact", "space", "line", "dashed"))
def test_scrollbar_visibility_counts_descriptions_and_spacing(spacing):
    model = projection(5, descriptions=True)
    viewport = RankingViewport()
    ctx = context(height=100, density="detailed")
    render(model, viewport, ctx, spacing=spacing, scrollbar=True)
    assert viewport.scrollbar is None
    exact_height = viewport.body_top + viewport.total_rows
    render(model, viewport, replace(ctx, height=exact_height), spacing=spacing, scrollbar=True)
    assert viewport.scrollbar is None
    render(model, viewport, replace(ctx, height=exact_height - 1), spacing=spacing, scrollbar=True)
    assert viewport.scrollbar is not None
    render(model, viewport, ctx, search="missing", scrollbar=True)
    assert viewport.scrollbar is None
    render(projection(0), viewport, ctx, scrollbar=True)
    assert viewport.scrollbar is None


@pytest.mark.parametrize("height,width", ((0, 80), (1, 80), (24, 1)))
def test_scrollbar_not_drawn_when_no_room(height, width):
    viewport = RankingViewport()
    render(projection(100), viewport, context(height=height, width=width), scrollbar=True)
    assert viewport.scrollbar is None
