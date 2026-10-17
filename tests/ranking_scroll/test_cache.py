from dataclasses import replace
from decimal import Decimal

import pytest

from ccusage_viz.custom_models import CustomUnit, LocalizedText
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomCommandSource
from ccusage_viz.processing.custom_historical import (
    CustomProjectedSeries,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_ranking
from ccusage_viz.render.ranking_viewport import RankingViewport

from .helpers import _search_fact_projection, context, projection, render


def test_viewport_search_preserves_full_facts_and_anchor_after_refresh() -> None:
    def item(
        key: str,
        value: int,
        *,
        previous: int,
        description: str | None = None,
    ) -> CustomProjectedSeries:
        return CustomProjectedSeries(
            key,
            LocalizedText(key.title(), key),
            (Decimal(value),),
            previous_total=Decimal(previous),
            comparison_ready=True,
            description=LocalizedText(description, description) if description else None,
            link=f"https://example.com/{key}",
        )

    model = _search_fact_projection()
    viewport = RankingViewport()
    ctx = context(height=20, width=100, density="detailed")

    output = strip_ansi(render(model, viewport, ctx, search="example.com/claude"))
    claude = next(line for line in output.splitlines() if "Claude" in line)
    assert claude.lstrip().startswith("3 ")
    assert "20.0%" in claude
    assert "●" in claude and "·" in claude
    assert "↓" in claude
    assert "Showing 1/3 item(s)" in output
    assert viewport.full_total == Decimal(100)
    assert viewport.full_maximum == Decimal(50)
    assert viewport.by_id["claude"].previous_rank == 2

    # Reapply the same search to fresh full facts and retain the matched ID at
    # the top of the viewport rather than the old numeric line offset.
    viewport.offset = viewport.starts[0]
    refreshed = replace(
        model,
        series=(
            item("claude", 60, previous=40, description="Release notes"),
            item("alpha", 35, previous=20),
            item("beta", 5, previous=60),
        ),
    )
    output = strip_ansi(render(refreshed, viewport, ctx, search="example.com/claude"))
    claude = next(line for line in output.splitlines() if "Claude" in line)
    assert claude.lstrip().startswith("1 ")
    assert "60.0%" in claude
    assert viewport.full_total == Decimal(100)
    assert viewport.full_maximum == Decimal(60)
    assert viewport.offset == viewport.starts[0]

def test_refresh_restores_top_visible_entry_by_stable_id() -> None:
    model = projection(30)
    viewport = RankingViewport()
    ctx = context(height=8)
    render(model, viewport, ctx)
    anchor_index = 12
    viewport.offset = viewport.starts[anchor_index]
    anchor_id = str(viewport.entries[anchor_index].key)

    refreshed = replace(model, series=(model.series[0], *model.series[10:]))
    render(refreshed, viewport, ctx)

    refreshed_index = next(
        index for index, entry in enumerate(viewport.entries) if str(entry.key) == anchor_id
    )
    assert viewport.offset == viewport.starts[refreshed_index]

def test_refresh_missing_anchor_falls_back_to_nearest_surviving_row_start() -> None:
    model = projection(30)
    viewport = RankingViewport()
    ctx = context(height=8)
    render(model, viewport, ctx)
    anchor_index = 12
    viewport.offset = viewport.starts[anchor_index] + 1

    refreshed = replace(
        model,
        series=tuple(
            entry for index, entry in enumerate(model.series) if index not in {11, 12, 13}
        ),
    )
    render(refreshed, viewport, ctx)

    nearest_index = next(
        index for index, entry in enumerate(viewport.entries) if str(entry.key) == "14"
    )
    assert viewport.offset == viewport.starts[nearest_index]

def test_geometry_change_restores_stable_anchor_at_new_row_start() -> None:
    model = projection(30, descriptions=True)
    viewport = RankingViewport()
    detailed = context(height=14, density="detailed")
    render(model, viewport, detailed, spacing="line")
    anchor_index = 12
    viewport.offset = viewport.starts[anchor_index] + 1
    anchor_id = str(viewport.entries[anchor_index].key)

    render(model, viewport, replace(detailed, density="minimal"), spacing="compact")

    new_index = next(
        index for index, entry in enumerate(viewport.entries) if str(entry.key) == anchor_id
    )
    assert viewport.offset == viewport.starts[new_index]

def test_refresh_shrink_resize_top_and_source_reset():
    model = projection(100)
    viewport = RankingViewport()
    render(model, viewport)
    viewport.offset = 80
    render(replace(model, series=model.series[:30]), viewport)
    assert viewport.offset == 20
    render(replace(model, series=model.series[:30]), viewport, context(height=22))
    assert viewport.offset == 10
    changed = replace(
        model, config=replace(model.config, source=CustomCommandSource("different", ("unused",)))
    )
    render(changed, viewport)
    assert viewport.offset == 0

def test_geometry_cache_restores_copied_columns_and_evicts_lru() -> None:
    viewport = RankingViewport()
    viewport.columns.widths["right"] = 12
    viewport.columns.description_width = 40
    viewport.starts = (0, 1)
    viewport.heights = (1,)
    viewport.total_rows = 1
    viewport.remember_geometry("a")

    viewport.columns.widths["right"] = 99
    assert viewport.restore_geometry("a")
    assert viewport.columns.widths == {"right": 12}
    assert viewport.columns.description_width == 40
    assert viewport.starts == (0, 1)
    assert viewport.heights == (1,)
    assert viewport.total_rows == 1

    # Restores must create fresh mutable columns from the immutable snapshot.
    viewport.columns.widths["right"] = 15
    assert viewport.restore_geometry("a")
    assert viewport.columns.widths == {"right": 12}

    viewport.remember_geometry("b")
    viewport.remember_geometry("c")
    assert not viewport.restore_geometry("a")
    assert viewport.restore_geometry("c")
    assert viewport.restore_geometry("b")

    # Restoring b marked it recent, so adding d evicts c and proves capacity two.
    viewport.remember_geometry("d")
    assert viewport.restore_geometry("b")
    assert not viewport.restore_geometry("c")
    assert viewport.restore_geometry("d")

def test_two_warm_widths_skip_all_geometry_work(monkeypatch: pytest.MonkeyPatch) -> None:
    import ccusage_viz.render.custom_ranking_viewport as module

    viewport = RankingViewport()
    model = projection(10_000, descriptions=True, comparison=True)
    wide = context(width=100, height=24, density="detailed")
    narrow = replace(wide, width=98)
    render(model, viewport, wide, spacing="line", scrollbar=True)
    render(model, viewport, narrow, spacing="line", scrollbar=True)

    monkeypatch.setattr(
        RankingViewport,
        "prepare_lines",
        lambda *args, **kwargs: pytest.fail("rebuilt lines"),
    )
    monkeypatch.setattr(
        module,
        "measure_ranking_columns",
        lambda *args, **kwargs: pytest.fail("remeasured columns"),
    )
    # With scrollbar gutters these exercise effective geometry widths 99 and 97.
    render(model, viewport, wide, spacing="line", scrollbar=True)
    render(model, viewport, narrow, spacing="line", scrollbar=True)

def test_cached_geometry_clamps_with_new_visible_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ccusage_viz.render.custom_ranking_viewport as module

    viewport = RankingViewport()
    model = projection(100)
    tall = context(height=30)

    # Warm both chrome geometries, then leave the non-editing geometry active.
    render(model, viewport, tall)
    render(model, viewport, tall, search_editing=True)
    render(model, viewport, tall)

    monkeypatch.setattr(
        RankingViewport,
        "prepare_lines",
        lambda *args, **kwargs: pytest.fail("rebuilt lines"),
    )
    monkeypatch.setattr(
        module,
        "measure_ranking_columns",
        lambda *args, **kwargs: pytest.fail("remeasured columns"),
    )
    original = viewport.total_rows - 2
    viewport.offset = original

    # Restoring editing chrome while shrinking the context must not clamp with
    # the tall viewport's stale, larger visible_rows before render recalculates it.
    render(model, viewport, replace(tall, height=8), search_editing=True)

    assert viewport.visible_rows < tall.height - 2
    assert viewport.offset == min(original, viewport.total_rows - viewport.visible_rows)

def test_cached_geometry_matches_first_render_at_each_width() -> None:
    viewport = RankingViewport()
    model = projection(100, descriptions=True, comparison=True)
    wide = context(width=100, height=24, density="detailed")
    narrow = replace(wide, width=98)

    render(model, viewport, wide, spacing="line", scrollbar=True, copied="5")
    viewport.offset = viewport.starts[5]

    def capture(ctx: RenderContext):
        output = render(model, viewport, ctx, spacing="line", scrollbar=True, copied="5")
        return (
            output,
            viewport.total_rows,
            viewport.scrollbar,
            viewport.starts,
            viewport.heights,
            viewport.hits.copy(),
            viewport.offset,
        )

    expected_wide = capture(wide)
    expected_narrow = capture(narrow)
    assert "✓" in expected_wide[0]
    assert expected_wide[-1] > 0
    assert capture(wide) == expected_wide
    assert capture(narrow) == expected_narrow

@pytest.mark.parametrize("change", ("series", "search", "language", "unit"))
def test_stable_data_changes_invalidate_all_geometry_snapshots(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    viewport = RankingViewport()
    model = projection(100, descriptions=True, comparison=True)
    wide = context(width=100, density="detailed")
    narrow = replace(wide, width=98)
    render(model, viewport, wide, spacing="line", scrollbar=True)
    render(model, viewport, narrow, spacing="line", scrollbar=True)
    stale_starts = viewport.starts

    calls = 0
    original = RankingViewport.prepare_lines

    def count_prepare(self, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, **kwargs)

    monkeypatch.setattr(RankingViewport, "prepare_lines", count_prepare)
    changed_model = model
    changed_context = wide
    search = ""
    if change == "series":
        changed_model = replace(model, series=model.series[:-1])
    elif change == "search":
        search = "Project 9"
    elif change == "language":
        changed_context = replace(wide, translator=load_translator("zh"))
    else:
        changed_model = replace(
            model,
            unit=CustomUnit("tokens", LocalizedText("tokens", "令牌"), "suffix", 0),
        )

    render(
        changed_model,
        viewport,
        changed_context,
        search=search,
        spacing="line",
        scrollbar=True,
    )
    assert calls == 1
    assert viewport.starts is not stale_starts

    # The other formerly warm width was invalidated along with the active one.
    other_context = replace(changed_context, width=98)
    render(
        changed_model,
        viewport,
        other_context,
        search=search,
        spacing="line",
        scrollbar=True,
    )
    assert calls == 2

def test_warm_large_ranking_only_formats_visible_entries(monkeypatch):
    import ccusage_viz.render.custom_ranking_preparation as preparation
    import ccusage_viz.render.ranking_historical as presentation

    model = projection(10_000, descriptions=True, comparison=True)
    viewport = RankingViewport()
    ctx = context(density="detailed")
    render(model, viewport, ctx)
    prepared_entries = viewport.entries
    starts = viewport.starts
    formatted = []
    original = presentation._refresh_markers

    def record(entry, **kwargs):
        formatted.append(entry.key)
        return original(entry, **kwargs)

    def fail(*args, **kwargs):
        pytest.fail("warm scrolling must not prepare/filter the full list")

    monkeypatch.setattr(presentation, "_refresh_markers", record)
    monkeypatch.setattr(preparation, "filter_ranking_entries", fail)
    monkeypatch.setattr(RankingViewport, "prepare_lines", fail)
    viewport.offset = 20_000
    output = render(model, viewport, ctx)
    assert viewport.entries is prepared_entries
    assert viewport.starts is starts
    assert 1 < len(formatted) <= viewport.visible_rows + 2
    assert len(output.splitlines()) == ctx.height
    assert len(viewport.hits) <= viewport.visible_rows

def test_density_rebuild_preserves_window_body_scrollbar_and_hits():
    model = projection(30, descriptions=True, comparison=True)
    viewport = RankingViewport()
    detailed = context(height=14, density="detailed")
    render(model, viewport, detailed, spacing="line", scrollbar=True)
    viewport.offset = 7

    minimal = replace(detailed, density="minimal")
    actual = render(model, viewport, minimal, spacing="line", scrollbar=True).splitlines()
    expected = render_custom_ranking(
        model,
        replace(minimal, width=minimal.width - 1),
        descriptions_visible=False,
        show_visible_count=True,
    ).splitlines()

    # The viewport caller owns its shorter title; the remaining chrome and
    # density-specific geometry match the unwindowed Custom Ranking.
    assert actual[1 : viewport.body_top] == expected[1 : viewport.body_top]
    assert viewport.scrollbar is not None
    for row, (entry_id, copy_column, link_column) in viewport.hits.items():
        assert f"Project {entry_id}" in strip_ansi(actual[row])
        assert strip_ansi(actual[row])[copy_column] == "⊞"
        assert link_column is not None and strip_ansi(actual[row])[link_column] == "→"

def test_style_and_theme_changes_reuse_data_and_rebuild_style_geometry() -> None:
    model = projection(100)
    viewport = RankingViewport()
    dot = context()
    render(model, viewport, dot)
    viewport.offset = 40
    entries = viewport.entries
    dot_geometry_key = viewport.geometry_key

    styled = replace(dot, style="list")
    render(model, viewport, styled, copied="1", copy_all_action=True)

    assert viewport.entries is entries
    assert viewport.geometry_key != dot_geometry_key
    assert viewport.copy_all_hit is None
    assert viewport.hits == {}
    assert viewport.offset > 0

    list_starts = viewport.starts
    render(model, viewport, replace(styled, color=True, color_scheme="dracula"))
    assert viewport.entries is entries
    assert viewport.starts is list_starts

def test_scrollbar_gutter_reuses_warm_layout_and_does_not_overlap_hits(monkeypatch):
    viewport = RankingViewport()
    model = projection(10_000)
    ctx = context(width=80)
    render(model, viewport, ctx, scrollbar=True)
    prepared = viewport.entries
    monkeypatch.setattr(
        RankingViewport, "prepare_lines", lambda **kw: pytest.fail("layout rebuilt")
    )
    viewport.offset = 9990
    render(model, viewport, ctx, scrollbar=True)
    assert viewport.entries is prepared
    for _, copy_column, link_column in viewport.hits.values():
        assert copy_column < 79
        assert link_column is None or link_column < 79
