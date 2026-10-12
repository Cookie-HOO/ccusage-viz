from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomUnit, LocalizedText
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_ranking
from ccusage_viz.render.custom_ranking_viewport import render_custom_ranking_viewport
from ccusage_viz.render.ranking_viewport import RankingViewport


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


def projection(count=100, *, descriptions=False, comparison=False):
    day = date(2026, 9, 1)
    config = CustomChartConfig(
        "ranking",
        CustomCommandSource("test", ("unused",)),
        DateRange(day, day),
        presentation=ChartPresentation(density="detailed" if descriptions else "normal"),
    )
    return CustomChartProjection(
        "ranking",
        (day,),
        tuple(
            CustomProjectedSeries(
                str(index),
                LocalizedText(f"Project {index}", f"项目 {index}"),
                (Decimal(count - index),),
                description=LocalizedText("First line\nSecond line\nHidden third", "描述")
                if descriptions
                else None,
                previous_total=Decimal(index + 1) if comparison else None,
                comparison_ready=comparison,
                link=f"https://example.com/{index}",
            )
            for index in range(count)
        ),
        CustomUnit("count", LocalizedText("items", "项"), "suffix", 0),
        config.date_range,
        "day",
        config,
        comparison_available=comparison,
    )


def context(*, height=12, width=100, density="normal", color=False):
    return RenderContext(
        width, height, load_translator("en"), density=density, style="dot", color=color
    )


def render(
    model,
    viewport,
    ctx=None,
    *,
    search="",
    spacing="compact",
    copied=None,
    scrollbar=False,
    copy_all_action=False,
    copied_all=False,
    search_editing=False,
):
    ctx = ctx or context()
    return render_custom_ranking_viewport(
        model,
        ctx,
        viewport,
        heading="Ranking",
        descriptions_visible=ctx.density in {"full", "detailed"},
        search_query=search,
        search_editing=search_editing,
        show_visible_count=True,
        copied_entry_id=copied,
        item_spacing=spacing,
        scrollbar=scrollbar,
        copy_all_action=copy_all_action,
        copied_all=copied_all,
    )


def test_copy_all_marker_follows_count_row_and_hides_without_it():
    model = projection(100)
    viewport = RankingViewport()
    initial = render(model, viewport, copy_all_action=True)
    hit = viewport.copy_all_hit
    assert hit is not None
    row, column = hit
    assert initial.splitlines()[row] == "100 item(s) total | ⊞"
    assert initial.splitlines()[row][column] == "⊞"

    viewport.scroll(10)
    moved = render(model, viewport, copy_all_action=True)
    assert viewport.copy_all_hit == hit
    assert moved.splitlines()[row][column] == "⊞"
    copied = render(model, viewport, copy_all_action=True, copied_all=True)
    assert copied.splitlines()[row][column] == "✓"

    searched = render(model, viewport, search="Project 9", copy_all_action=True)
    search_hit = viewport.copy_all_hit
    assert search_hit is not None
    assert search_hit[0] == row + 1
    assert "Showing 11/11 item(s)" in searched.splitlines()[search_hit[0]]

    render(model, viewport, context(density="minimal"), copy_all_action=True)
    assert viewport.copy_all_hit is None
    render(model, viewport, search="missing", copy_all_action=True)
    assert viewport.copy_all_hit is None
    render(projection(0), viewport, copy_all_action=True)
    assert viewport.copy_all_hit is None


@pytest.mark.parametrize("spacing", ("compact", "space", "line", "dashed"))
@pytest.mark.parametrize("comparison", (False, True))
def test_line_window_matches_full_output_with_partial_descriptions(spacing, comparison):
    model = projection(30, descriptions=True, comparison=comparison)
    viewport = RankingViewport()
    ctx = context(height=200, density="detailed", color=True)
    full = render(model, viewport, ctx, spacing=spacing).splitlines()
    chrome_count = len(full) - viewport.total_rows
    assert chrome_count >= 2
    body = full[chrome_count:]
    for offset in (0, 1, 2, 3, 7, 23, len(body) - 6, len(body) + 100):
        viewport.offset = offset
        window = render(
            model, viewport, replace(ctx, height=chrome_count + 6), spacing=spacing
        ).splitlines()
        assert window[:chrome_count] == full[:chrome_count]
        assert window[chrome_count:] == body[viewport.offset : viewport.offset + 6]
        for row, (entry_id, copy_column, link_column) in viewport.hits.items():
            assert row >= chrome_count
            assert f"Project {entry_id}" in strip_ansi(window[row])
            assert strip_ansi(window[row])[copy_column] == "⊞"
            assert strip_ansi(window[row])[link_column] == "→"


@pytest.mark.parametrize("density", ("minimal", "normal", "full", "detailed"))
def test_first_window_preserves_unwindowed_custom_body(density):
    model = projection(20, descriptions=True, comparison=True)
    ctx = context(height=300, density=density)
    viewport = RankingViewport()
    actual = render(model, viewport, ctx)
    expected = render_custom_ranking(
        model, ctx, descriptions_visible=density in {"full", "detailed"}, show_visible_count=True
    )
    # The caller owns the title. Body and table geometry remain identical.
    assert actual.splitlines()[1:] == expected.splitlines()[1:]


def test_search_reset_and_hit_identity_and_feedback():
    model = projection(100)
    viewport = RankingViewport()
    render(model, viewport)
    viewport.offset = 60
    output = render(model, viewport, search="Project 9")
    assert viewport.offset == 0
    ids = [hit[0] for hit in viewport.hits.values()]
    assert ids[0] == "9"
    assert ids[1] == "90"
    assert "Showing 11" in output or "11/11" in output
    layout = viewport.starts
    output = render(model, viewport, search="Project 9", copied="90")
    assert "✓" in output
    assert viewport.starts is layout
    assert viewport.by_id["90"].project_link == "https://example.com/90"
    output = render(model, viewport, search="missing")
    assert "No ranking entries" in output
    assert viewport.offset == viewport.total_rows == 0
    assert viewport.hits == {}


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
    viewport.offset = 17

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
    import ccusage_viz.render.custom_ranking_viewport as module
    import ccusage_viz.render.ranking_presentation as presentation

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
    monkeypatch.setattr(module, "filter_ranking_entries", fail)
    monkeypatch.setattr(RankingViewport, "prepare_lines", fail)
    viewport.offset = 20_000
    output = render(model, viewport, ctx)
    assert viewport.entries is prepared_entries
    assert viewport.starts is starts
    assert 1 < len(formatted) <= viewport.visible_rows + 2
    assert len(output.splitlines()) == ctx.height
    assert len(viewport.hits) <= viewport.visible_rows


@pytest.mark.parametrize("changed", ("style", "density"))
def test_presentation_change_renders_only_current_window(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    import ccusage_viz.render.custom_ranking_viewport as module

    viewport = RankingViewport()
    model = projection(10_000, descriptions=True, comparison=True)
    initial = context(height=24, density="detailed")
    render(model, viewport, initial)
    viewport.offset = 8_000
    calls: list[int] = []
    formatted: list[object] = []
    original_render = module.render_historical_ranking
    original_format = module.format_custom_value

    def record(entries, *args, **kwargs):
        calls.append(len(entries))
        return original_render(entries, *args, **kwargs)

    def record_format(*args, **kwargs):
        formatted.append(args[0])
        return original_format(*args, **kwargs)

    monkeypatch.setattr(module, "render_historical_ranking", record)
    monkeypatch.setattr(module, "format_custom_value", record_format)
    changed_context = (
        replace(initial, style="list")
        if changed == "style"
        else replace(initial, density="minimal")
    )
    render(model, viewport, changed_context)

    # Chrome measures one entry; all other rendering is the display window.
    # Density geometry consumes scalar facts prepared with the stable entries.
    assert calls
    assert max(calls) <= viewport.visible_rows + 2
    assert sum(calls) <= viewport.visible_rows + 3
    assert not formatted
    assert viewport.offset > 0


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


def test_zero_values_do_not_divide_by_zero():
    model = projection(1)
    model = replace(model, series=(replace(model.series[0], values=(Decimal(0),)),))
    assert "Project 0" in render(model, RankingViewport())


def test_zero_growth_values_do_not_divide_by_zero():
    model = projection(1, comparison=True)
    series = replace(model.series[0], values=(Decimal(10), Decimal(10)), previous_total=Decimal(0))
    model = replace(model, series=(series,))

    output = render(model, RankingViewport(), context(density="detailed"))

    assert "Project 0" in output


@pytest.mark.parametrize("height", (0, 1, 2, 3))
def test_tiny_viewports_and_empty_comparison(height):
    model = projection(0, comparison=True)
    viewport = RankingViewport()
    render(model, viewport, context(height=height, density="detailed"))
    assert viewport.total_rows == 0
    assert not viewport.scroll(1)


def test_style_and_theme_changes_reuse_data_and_geometry(monkeypatch):
    model = projection(100)
    viewport = RankingViewport()
    render(model, viewport)
    viewport.offset = 40
    entries, starts = viewport.entries, viewport.starts
    monkeypatch.setattr(
        RankingViewport, "prepare_lines", lambda *a, **kw: pytest.fail("rebuilt layout")
    )
    styled = replace(context(), style="list")
    render(model, viewport, styled, copied="1")
    render(model, viewport, replace(styled, color=True, color_scheme="dracula"))
    assert viewport.entries is entries
    assert viewport.starts is starts
    assert viewport.offset == 40


def test_density_change_reuses_data_and_preserves_offset_then_clamps():
    model = projection(100, descriptions=True)
    viewport = RankingViewport()
    render(model, viewport, context(height=16, density="detailed"))
    entries, starts = viewport.entries, viewport.starts
    viewport.offset = 100

    render(model, viewport, context(height=16, density="minimal"))

    assert viewport.entries is entries
    assert viewport.starts is not starts
    assert viewport.offset == min(100, viewport.total_rows - viewport.visible_rows)


def test_standalone_custom_ranking_does_not_use_dashboard_viewport(monkeypatch):
    import ccusage_viz.tui as tui
    from ccusage_viz.custom_component import CustomHistoricalComponent
    from ccusage_viz.terminal import Terminal

    model = projection(100)
    component = CustomHistoricalComponent(model.config)
    component.model = model
    component.accepted_config = model.config
    component.pending_generation = None
    monkeypatch.setattr(
        tui, "render_custom_ranking_viewport", lambda *a, **kw: pytest.fail("standalone viewport")
    )
    output = tui._custom_standalone_render(
        component, load_translator("en"), Terminal(100, 12, False, False), pending=False
    )
    assert "Project 99" in output.chart


def test_visible_copy_marker_wins_over_checkmark_in_label():
    model = projection(1)
    model = replace(
        model, series=(replace(model.series[0], label=LocalizedText("✓ Project", "项目")),)
    )
    viewport = RankingViewport()
    output = render(model, viewport).splitlines()
    row, (_, column, _) = next(iter(viewport.hits.items()))
    assert strip_ansi(output[row])[column] == "⊞"


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
        expected = (
            ("#" if ascii else "█") if viewport.scrollbar.on_thumb(row) else ("|" if ascii else "│")
        )
        assert strip_ansi(rows[row])[-1] == expected
    assert rows[: bar.top] == initial.splitlines()[: bar.top]
    viewport.offset = 9999
    render(model, viewport, ctx, scrollbar=True)
    bar = viewport.scrollbar
    assert bar.thumb_top + bar.thumb_size == bar.top + bar.height


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


@pytest.mark.parametrize("height,width", ((0, 80), (1, 80), (24, 1)))
def test_scrollbar_not_drawn_when_no_room(height, width):
    viewport = RankingViewport()
    render(projection(100), viewport, context(height=height, width=width), scrollbar=True)
    assert viewport.scrollbar is None


@pytest.mark.parametrize("width", (1, 3, 8, 20, 60))
def test_clipped_icons_do_not_create_invisible_hit_targets(width):
    viewport = RankingViewport()
    render(projection(3), viewport, context(width=width))
    for _, copy_column, link_column in viewport.hits.values():
        assert copy_column < width
        assert link_column is None or link_column < width
