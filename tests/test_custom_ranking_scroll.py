from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import CustomUnit, LocalizedText
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import ChartPresentation, CustomChartConfig, CustomCommandSource
from ccusage_viz.processing.custom_historical import (
    CustomChartProjection,
    CustomProjectedRankingGroup,
    CustomProjectedSeries,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_ranking
from ccusage_viz.render.custom_ranking_viewport import render_custom_ranking_viewport
from ccusage_viz.render.grouped_ranking_viewport import (
    GroupedRankingRow,
    GroupedRankingViewport,
    render_grouped_custom_ranking_viewport,
)
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


def grouped_projection() -> CustomChartProjection:
    model = projection(0)

    def group(group_id: str, label: str, entries: tuple[tuple[str, str, str], ...]):
        series = tuple(
            CustomProjectedSeries(
                series_id,
                LocalizedText(series_label, series_label),
                (Decimal(value),),
                rank=index,
                description=LocalizedText(f"Details for {series_label}", "描述"),
                link=f"https://example.com/{group_id}/{series_id}",
            )
            for index, (series_id, series_label, value) in enumerate(entries, 1)
        )
        total = sum((item.total for item in series), start=Decimal())
        return CustomProjectedRankingGroup(
            group_id,
            LocalizedText(label, label),
            series,
            total,
            None,
            False,
            max((item.total for item in series), default=Decimal()),
            description=LocalizedText(f"About {label}", "描述"),
            link=f"https://example.com/{group_id}",
        )

    groups = (
        group("coding", "Coding Model", (("shared", "Seed", "70"), ("sonnet", "Sonnet", "30"))),
        group("general", "General Model", (("shared", "Sonnet General", "20"),)),
        group("empty", "Empty Unmatched Group", ()),
    )
    return replace(model, groups=groups, series=())


def render_grouped(
    model: CustomChartProjection,
    viewport: GroupedRankingViewport,
    ctx: RenderContext | None = None,
    *,
    search: str = "",
    spacing: str = "compact",
    scrollbar: bool = False,
    copy_all_action: bool = False,
) -> str:
    return render_grouped_custom_ranking_viewport(
        model,
        ctx or context(),
        viewport,
        heading="Grouped Ranking",
        descriptions_visible=(ctx or context()).density in {"full", "detailed"},
        search_query=search,
        search_editing=False,
        show_visible_count=True,
        copied_entry_id=None,
        item_spacing=spacing,
        scrollbar=scrollbar,
        copy_all_action=copy_all_action,
        copied_all=False,
    )


def test_grouped_search_matches_only_inner_fields_and_preserves_full_facts() -> None:
    viewport = GroupedRankingViewport()
    output = strip_ansi(render_grouped(grouped_projection(), viewport, search="sonnet"))
    assert "Coding Model" in output and "General Model" in output
    assert "Empty Unmatched Group" not in output
    coding = next(
        line for line in output.splitlines() if "Sonnet" in line and "General" not in line
    )
    assert coding.lstrip().startswith("2 ")
    assert "30.0%" in coding
    assert all(identity[0] != "group" or identity[1] != "empty" for identity in viewport.by_id)


def test_grouped_sticky_heading_is_label_only_and_has_no_hit() -> None:
    viewport = GroupedRankingViewport()
    ctx = context(height=5)
    render_grouped(grouped_projection(), viewport, ctx)
    viewport.offset = next(index for index, row in enumerate(viewport.rows) if row.kind == "series")
    output = strip_ansi(render_grouped(grouped_projection(), viewport, ctx))
    sticky_row = output.splitlines()[viewport.body_top]
    assert sticky_row.strip() == "Coding Model"
    assert not any(row == viewport.body_top for row in viewport.hits)


def test_grouped_sticky_transition_uses_heading_offset_intervals() -> None:
    viewport = GroupedRankingViewport()
    ctx = context(height=5)
    model = grouped_projection()
    render_grouped(model, viewport, ctx)
    next_heading = next(
        index
        for index, row in enumerate(viewport.rows)
        if row.kind == "group" and row.group_id == "general"
    )

    viewport.offset = next_heading - viewport.visible_rows
    output = strip_ansi(render_grouped(model, viewport, ctx))
    assert next_heading == viewport.offset + viewport.visible_rows
    assert output.splitlines()[viewport.body_top].strip() == "Coding Model"
    assert viewport.sticky_rows == 1

    viewport.offset += 1
    output = strip_ansi(render_grouped(model, viewport, ctx))
    assert next_heading < viewport.offset + viewport.visible_rows
    assert viewport.sticky_rows == 0
    assert "General Model" in output

    viewport.offset = next_heading
    output = strip_ansi(render_grouped(model, viewport, ctx))
    assert output.splitlines()[viewport.body_top].lstrip().startswith("General Model |")
    assert viewport.sticky_rows == 0


def test_grouped_identity_scrollbar_and_copy_payloads() -> None:
    viewport = GroupedRankingViewport()
    ctx = context(height=8, density="detailed")
    render_grouped(
        grouped_projection(), viewport, ctx, spacing="line", scrollbar=True, copy_all_action=True
    )
    assert viewport.scrollbar is not None
    assert ("series", "coding", "shared") in viewport.by_id
    assert ("series", "general", "shared") in viewport.by_id
    assert all(identity[0] != "other" for identity, *_ in viewport.hits.values())
    payload = viewport.clipboard_all_text()
    assert payload.index("Coding Model") < payload.index("Seed") < payload.index("General Model")
    assert viewport.clipboard_text(("series", "coding", "shared")).startswith("Coding Model\nSeed")


def test_grouped_copy_all_preserves_mixed_empty_groups_and_excludes_other() -> None:
    model = grouped_projection()
    coding, general, empty = model.groups or ()
    other = replace(coding.series[0], id="other", label=LocalizedText("Other", "其他"), is_other=True)
    model = replace(model, groups=(empty, coding, replace(general, series=(other,))))
    viewport = GroupedRankingViewport()
    render_grouped(model, viewport)
    payload = viewport.clipboard_all_text()
    assert payload.index("Empty Unmatched Group") < payload.index("Coding Model")
    assert "Seed" in payload and "Sonnet" in payload
    assert "General Model" not in payload and "Other" not in payload

    render_grouped(model, viewport, search="Seed")
    assert "Empty Unmatched Group" not in viewport.clipboard_all_text()


def test_grouped_spacing_starts_between_series_not_after_group_heading() -> None:
    viewport = GroupedRankingViewport()
    render_grouped(grouped_projection(), viewport, context(density="detailed"), spacing="line")
    coding = [row for row in viewport.rows if row.group_id == "coding"]
    first_series = next(index for index, row in enumerate(coding) if row.kind == "series")
    assert coding[first_series - 1].kind == "description"
    second_series = next(
        index
        for index, row in enumerate(coding[first_series + 1 :], first_series + 1)
        if row.kind == "series"
    )
    assert coding[second_series - 1].kind == "separator"


def test_grouped_idle_repaint_preserves_arbitrary_physical_offset() -> None:
    viewport = GroupedRankingViewport()
    model = grouped_projection()
    ctx = context(height=6, density="detailed")
    render_grouped(model, viewport, ctx, spacing="line")
    viewport.offset = next(
        index for index, row in enumerate(viewport.rows) if row.kind == "description"
    )
    expected = viewport.offset
    render_grouped(model, viewport, ctx, spacing="line")
    assert viewport.offset == expected


def test_grouped_missing_anchor_searches_old_series_outward_forward_on_tie() -> None:
    viewport = GroupedRankingViewport()
    model = grouped_projection()
    ctx = context(height=6)
    render_grouped(model, viewport, ctx)
    viewport.offset = next(
        index
        for index, row in enumerate(viewport.rows)
        if row.kind == "series" and row.group_id == "coding" and row.series_id == "sonnet"
    )
    coding, general, empty = model.groups or ()
    refreshed = replace(
        model,
        groups=(replace(coding, series=coding.series[:1]), general, empty),
    )
    render_grouped(refreshed, viewport, ctx)
    # Seed and General/shared are equally distant in old series order. The
    # documented outward tie direction is forward, so General/shared wins.
    assert (viewport.rows[viewport.offset].group_id, viewport.rows[viewport.offset].series_id) == (
        "general",
        "shared",
    )


def test_grouped_missing_series_then_falls_back_to_nearest_old_group() -> None:
    viewport = GroupedRankingViewport()
    model = grouped_projection()
    ctx = context(height=6)
    render_grouped(model, viewport, ctx)
    viewport.offset = next(
        index
        for index, row in enumerate(viewport.rows)
        if row.kind == "series" and row.group_id == "coding"
    )
    coding, general, empty = model.groups or ()
    refreshed = replace(
        model,
        groups=(replace(coding, series=()), replace(general, series=()), empty),
    )
    render_grouped(refreshed, viewport, ctx)
    assert viewport.rows[viewport.offset].kind == "group"
    assert viewport.rows[viewport.offset].group_id == "coding"


def test_grouped_warm_scroll_and_repaint_reuse_preparation_and_geometry(monkeypatch) -> None:
    import ccusage_viz.render.grouped_ranking_viewport as module

    viewport = GroupedRankingViewport()
    model = grouped_projection()
    ctx = context(height=6, density="detailed")
    render_grouped(model, viewport, ctx)

    monkeypatch.setattr(module, "_prepare_group", lambda *a, **k: pytest.fail("prepared again"))
    monkeypatch.setattr(
        module, "filter_ranking_entries", lambda *a, **k: pytest.fail("filtered again")
    )
    monkeypatch.setattr(
        module, "measure_ranking_columns", lambda *a, **k: pytest.fail("measured again")
    )
    original_render = module.render_historical_ranking
    rendered: list[str] = []

    def render_one(entries, **kwargs):
        assert len(entries) == 1, "warm rendering must not materialize a complete group"
        rendered.append(str(entries[0].key))
        return original_render(entries, **kwargs)

    monkeypatch.setattr(module, "render_historical_ranking", render_one)
    assert viewport.scroll(1)
    render_grouped(model, viewport, ctx)
    assert len(rendered) <= viewport.visible_rows
    rendered.clear()
    render_grouped(model, viewport, ctx)
    assert len(rendered) <= viewport.visible_rows


def test_grouped_cold_preparation_filters_each_group_only_once(monkeypatch) -> None:
    import ccusage_viz.render.custom_ranking_preparation as preparation
    import ccusage_viz.render.grouped_ranking_viewport as module

    calls: list[tuple[str, ...]] = []
    original_filter = module.filter_ranking_entries

    def filter_once(entries, query):
        calls.append(tuple(str(entry.key) for entry in entries))
        return original_filter(entries, query)

    monkeypatch.setattr(module, "filter_ranking_entries", filter_once)
    monkeypatch.setattr(
        preparation,
        "filter_ranking_entries",
        lambda *_args, **_kwargs: pytest.fail("empty-query preparation filtered full entries"),
    )
    render_grouped(grouped_projection(), GroupedRankingViewport(), search="sonnet")
    assert calls == [("shared", "sonnet"), ("shared",), ()]


def test_grouped_empty_search_editor_keeps_first_series_row() -> None:
    model = grouped_projection()
    viewport = GroupedRankingViewport()
    output = render_grouped_custom_ranking_viewport(
        model,
        context(height=8),
        viewport,
        heading="Grouped Ranking",
        descriptions_visible=False,
        search_query="",
        search_editing=True,
        show_visible_count=True,
        copied_entry_id=None,
        item_spacing="compact",
    )
    assert "Search: ▏" in strip_ansi(output)
    assert any(row.kind == "series" and row.series_id == "shared" for row in viewport.rows)
    assert "Seed" in strip_ansi(output)


def test_grouped_premeasures_every_visible_group_before_rendering(monkeypatch) -> None:
    import ccusage_viz.render.grouped_ranking_viewport as module

    events: list[str] = []
    original_measure = module.measure_ranking_columns
    original_render = module.render_historical_ranking

    def measure(*args, **kwargs):
        events.append(f"measure:{args[0][0].key if args[0] else 'empty'}")
        return original_measure(*args, **kwargs)

    def render_rows(*args, **kwargs):
        events.append(f"render:{args[0][0].key}")
        return original_render(*args, **kwargs)

    monkeypatch.setattr(module, "measure_ranking_columns", measure)
    monkeypatch.setattr(module, "render_historical_ranking", render_rows)
    render_grouped(grouped_projection(), GroupedRankingViewport(), context(density="detailed"))
    first_render = next(index for index, event in enumerate(events) if event.startswith("render:"))
    assert events[:first_render] == ["measure:shared", "measure:shared", "measure:empty"]


def test_grouped_other_primary_row_is_explicit_series_without_copy_hit() -> None:
    model = grouped_projection()
    coding = (model.groups or ())[0]
    other = replace(coding.series[0], id="other", is_other=True, link=None)
    model = replace(model, groups=(replace(coding, series=(other,)),))
    viewport = GroupedRankingViewport()
    render_grouped(model, viewport)
    row = next(row for row in viewport.rows if row.series_id == "other")
    assert row.kind == "series"
    assert all(hit[0] != ("series", "coding", "other") for hit in viewport.hits.values())


def test_grouped_empty_only_has_copy_all_action_and_exact_heading_payload() -> None:
    model = grouped_projection()
    empty = (model.groups or ())[-1]
    viewport = GroupedRankingViewport()
    output = strip_ansi(
        render_grouped(replace(model, groups=(empty,)), viewport, copy_all_action=True)
    )
    assert "0 item(s) total | ⊞" in output
    assert viewport.copy_all_hit is not None
    assert viewport.clipboard_all_text() == (
        "Empty Unmatched Group\n"
        "About Empty Unmatched Group\n"
        "https://example.com/empty"
    )


@pytest.mark.parametrize(
    ("height", "density", "search", "expected_hit"),
    (
        (0, "normal", "", None),
        (1, "normal", "", None),
        (2, "normal", "", 1),
        (3, "normal", "Seed", 2),
        (3, "minimal", "", None),
        (2, "normal", "Seed", None),
    ),
)
def test_grouped_tiny_height_clips_chrome_and_targets_only_rendered_count(
    height, density, search, expected_hit
) -> None:
    viewport = GroupedRankingViewport()
    output = strip_ansi(
        render_grouped(
            grouped_projection(),
            viewport,
            context(height=height, density=density),
            search=search,
            copy_all_action=True,
        )
    )
    assert len(output.splitlines()) <= height
    assert (viewport.copy_all_hit[0] if viewport.copy_all_hit else None) == expected_hit
    assert all(row < height for row in viewport.hits)
    if viewport.copy_all_hit is not None:
        row, _ = viewport.copy_all_hit
        assert "item(s)" in output.splitlines()[row]
    assert viewport.copy_all_hit is None or viewport.copy_all_hit[0] not in {0, 1 if search else -1}


def test_grouped_copy_all_requires_a_rendered_nonminimal_count_row() -> None:
    model = grouped_projection()
    for density, show_visible_count in (("minimal", True), ("normal", False)):
        viewport = GroupedRankingViewport()
        output = render_grouped_custom_ranking_viewport(
            model,
            context(height=8, density=density),
            viewport,
            heading="Grouped Ranking",
            descriptions_visible=False,
            search_query="",
            search_editing=False,
            show_visible_count=show_visible_count,
            copied_entry_id=None,
            item_spacing="compact",
            copy_all_action=True,
        )
        assert viewport.copy_all_hit is None
        assert "item(s) total |" not in strip_ansi(output)


def test_grouped_other_only_has_zero_match_count_and_no_copy_all_payload() -> None:
    model = grouped_projection()
    coding = (model.groups or ())[0]
    other = replace(coding.series[0], id="other", is_other=True, link=None)
    model = replace(model, groups=(replace(coding, series=(other,)),))
    viewport = GroupedRankingViewport()
    output = strip_ansi(render_grouped(model, viewport, copy_all_action=True))
    assert output.splitlines()[1] == "0 item(s) total"
    assert viewport.copy_all_hit is None
    assert viewport.clipboard_all_text() == ""


def test_grouped_sticky_capacity_reaches_final_row_and_sets_truthful_scrollbar_max() -> None:
    model = grouped_projection()
    coding = (model.groups or ())[0]
    series = tuple(
        replace(coding.series[0], id=str(index), label=LocalizedText(f"Item {index}", "项目"))
        for index in range(8)
    )
    model = replace(model, groups=(replace(coding, series=series),))
    viewport = GroupedRankingViewport()
    ctx = context(height=5)
    render_grouped(model, viewport, ctx, scrollbar=True)
    viewport.offset = 10_000
    output = strip_ansi(render_grouped(model, viewport, ctx, scrollbar=True))
    assert viewport.sticky_rows == 1
    assert viewport.reserved_rows == 0
    assert viewport.offset == viewport.total_rows - viewport.effective_capacity()
    assert "Item 7" in output
    assert viewport.scrollbar is not None
    assert viewport.scrollbar.maximum_offset == viewport.offset
    assert viewport.scrollbar.maximum_offset == viewport.maximum_offset()
    assert viewport.scrollbar.thumb_top + viewport.scrollbar.thumb_size == (
        viewport.scrollbar.top + viewport.scrollbar.height
    )


def test_grouped_maximum_offset_is_stable_when_base_lands_before_final_heading() -> None:
    model = grouped_projection()
    viewport = GroupedRankingViewport()
    ctx = context(height=5)
    render_grouped(model, viewport, ctx, scrollbar=True)
    base = viewport.total_rows - viewport.visible_rows
    final_heading = viewport.group_headings[-1]
    assert viewport.rows[base].kind == "separator"
    assert final_heading == base + 1

    viewport.offset = 10_000
    output = strip_ansi(render_grouped(model, viewport, ctx, scrollbar=True))
    assert viewport.offset == base
    assert viewport.effective_capacity(viewport.offset) == viewport.visible_rows
    assert viewport.offset + viewport.effective_capacity() == viewport.total_rows
    assert output.splitlines()[-1].strip().startswith("No data")
    assert viewport.scrollbar is not None
    assert viewport.scrollbar.maximum_offset == base
    assert viewport.scrollbar.thumb_top + viewport.scrollbar.thumb_size == (
        viewport.scrollbar.top + viewport.scrollbar.height
    )


def test_grouped_sticky_lookup_uses_precomputed_group_intervals(monkeypatch) -> None:
    import ccusage_viz.render.grouped_ranking_viewport as module

    group_count = 10_000
    viewport = GroupedRankingViewport(
        visible_rows=3,
        total_rows=group_count * 3,
        rows=tuple(
            GroupedRankingRow(kind, str(index), None, 0)
            for index in range(group_count)
            for kind in ("group", "series", "separator")
        ),
        group_headings=tuple(range(0, group_count * 3, 3)),
        group_has_series=(True,) * group_count,
    )
    calls = 0
    original = module.bisect_right

    def counted(headings, offset):
        nonlocal calls
        calls += 1
        return original(headings, offset)

    monkeypatch.setattr(module, "bisect_right", counted)
    assert viewport._sticky_required(viewport.total_rows - 2)
    assert viewport._group_heading(viewport.total_rows - 2) == viewport.total_rows - 3
    assert calls == 2


def test_dashboard_partition_mode_switch_clears_incompatible_viewport_state() -> None:
    import ccusage_viz.tui as tui
    from ccusage_viz.terminal import Terminal

    grouped = GroupedRankingViewport()
    flat = RankingViewport(offset=3)
    model = grouped_projection()

    def dispatch(projection: CustomChartProjection) -> None:
        tui._render_custom_projection(
            projection,
            projection.config,
            load_translator("en"),
            Terminal(100, 12, False, False),
            accepted_at=None,
            interval=None,
            pending=False,
            surface=tui.dashboard_pane_surface("ranking"),
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


def test_grouped_notice_and_sticky_reservations_are_independent_and_stable() -> None:
    viewport = GroupedRankingViewport(reserved_rows=2)
    model = grouped_projection()
    ctx = context(height=5)
    render_grouped(model, viewport, ctx)
    viewport.offset = next(index for index, row in enumerate(viewport.rows) if row.kind == "series")
    first = render_grouped(model, viewport, ctx)
    state = (viewport.reserved_rows, viewport.sticky_rows, viewport.visible_rows, viewport.offset)
    second = render_grouped(model, viewport, ctx)
    assert state == (2, 1, viewport.visible_rows, viewport.offset)
    assert (viewport.reserved_rows, viewport.sticky_rows, viewport.visible_rows, viewport.offset) == state
    assert first == second


def test_grouped_geometry_change_restores_group_and_series_anchor() -> None:
    viewport = GroupedRankingViewport()
    model = grouped_projection()
    render_grouped(model, viewport, context(height=8, density="detailed"))
    viewport.offset = next(
        index
        for index, row in enumerate(viewport.rows)
        if row.kind == "series" and row.group_id == "general" and row.series_id == "shared"
    )
    render_grouped(model, viewport, context(height=8, density="normal"))
    visible = viewport.rows[viewport.offset : viewport.offset + viewport.visible_rows]
    assert any((row.group_id, row.series_id) == ("general", "shared") for row in visible)


def test_grouped_top_series_description_keeps_its_series_on_source_change() -> None:
    viewport = GroupedRankingViewport()
    model = grouped_projection()
    detailed = context(height=8, density="detailed")
    render_grouped(model, viewport, detailed)
    viewport.offset = next(
        index
        for index, row in enumerate(viewport.rows)
        if row.kind == "series_description"
        and row.group_id == "coding"
        and row.series_id == "shared"
    )
    coding, general, empty = model.groups or ()
    refreshed = replace(model, groups=(coding, replace(general, label=LocalizedText("Changed", "Changed")), empty))
    render_grouped(refreshed, viewport, detailed)
    top = viewport.rows[viewport.offset]
    assert (top.group_id, top.series_id) == ("coding", "shared")


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
    assert "Showing 11/100 item(s)" in searched.splitlines()[search_hit[0]]

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


def _search_fact_projection() -> CustomChartProjection:
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

    return replace(
        projection(0, comparison=True),
        series=(
            item("alpha", 50, previous=20),
            item("beta", 30, previous=60),
            item("claude", 20, previous=40, description="Release notes"),
        ),
        show_percentage=True,
    )


def _track(line: str, mark: str, empty: str) -> str:
    return next(part for part in line.split() if mark in part and set(part) <= {mark, empty})


def test_direct_search_preserves_rank_share_bar_count_and_link_matching() -> None:
    model = _search_fact_projection()
    ctx = replace(context(height=20, width=100), style="bar")

    output = strip_ansi(
        render_custom_ranking(
            model,
            ctx,
            search_query="example.com/claude",
            show_visible_count=True,
        )
    )
    claude = next(line for line in output.splitlines() if "Claude" in line)
    assert claude.lstrip().startswith("3 ")
    assert "20.0%" in claude
    assert "Showing 1/3 item(s)" in output
    assert _track(claude, "█", "░").count("█") == 16

    full = strip_ansi(render_custom_ranking(model, ctx))
    alpha = next(line for line in full.splitlines() if "Alpha" in line)
    assert _track(alpha, "█", "░").count("█") == 41


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
    monkeypatch.setattr(preparation, "filter_ranking_entries", fail)
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


def test_density_change_reuses_data_and_preserves_stable_anchor():
    model = projection(100, descriptions=True)
    viewport = RankingViewport()
    render(model, viewport, context(height=16, density="detailed"))
    entries, starts = viewport.entries, viewport.starts
    viewport.offset = 100
    anchor_index = max(0, next(index for index, start in enumerate(starts) if start > 100) - 1)
    anchor_id = str(entries[anchor_index].key)

    render(model, viewport, context(height=16, density="minimal"))

    assert viewport.entries is entries
    assert viewport.starts is not starts
    new_index = next(index for index, entry in enumerate(entries) if str(entry.key) == anchor_id)
    assert viewport.offset == viewport.starts[new_index]


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
