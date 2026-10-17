from dataclasses import replace

import pytest

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.render.grouped_ranking_viewport import (
    GroupedRankingViewport,
    render_grouped_custom_ranking_viewport,
)
from ccusage_viz.render.ranking_viewport import RankingViewport

from .helpers import (
    context,
    grouped_projection,
    grouped_projection_with_visible_comparisons,
    projection,
    render,
    render_grouped,
)


def test_flat_and_grouped_dash_rendering_share_muted_separator() -> None:
    colored = replace(context(height=20, width=40), color=True)
    flat = render(projection(3), RankingViewport(), colored, spacing="dashed")
    grouped = render_grouped(
        grouped_projection(), GroupedRankingViewport(), colored, spacing="dashed"
    )
    assert "\x1b[38;5;245m" in flat and "\x1b[2m" in flat
    assert "\x1b[38;5;245m" in grouped and "\x1b[2m" in grouped

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

def test_grouped_zero_match_search_keeps_empty_width_measurement_renderable() -> None:
    viewport = GroupedRankingViewport()

    output = strip_ansi(
        render_grouped(grouped_projection(), viewport, context(density="detailed"), search="gpt4")
    )

    assert "Showing 0/3 item(s)" in output
    assert "Coding Model" not in output
    assert viewport.visible_groups == ()
    assert viewport.hits == {}

def test_grouped_scrolling_does_not_insert_a_sticky_heading() -> None:
    viewport = GroupedRankingViewport()
    ctx = context(height=5)
    model = grouped_projection()
    render_grouped(model, viewport, ctx)
    viewport.offset = next(index for index, row in enumerate(viewport.rows) if row.kind == "series")

    output = strip_ansi(render_grouped(model, viewport, ctx))

    first_body_row = output.splitlines()[viewport.body_top]
    assert first_body_row.lstrip().startswith("1 ")
    assert "Coding Model" not in first_body_row

def test_grouped_identity_scrollbar_and_copy_payloads() -> None:
    viewport = GroupedRankingViewport()
    ctx = context(height=8, density="detailed")
    render_grouped(
        grouped_projection(), viewport, ctx, spacing="line", scrollbar=True, copy_all_action=True
    )
    assert viewport.scrollbar is not None
    assert ("series", "coding", "shared") in viewport.by_id
    assert ("series", "general", "shared") in viewport.by_id
    assert any(
        identity == ("series", "coding", "shared") for identity, *_ in viewport.hits.values()
    )
    assert all(identity != ("series", "coding", "other") for identity, *_ in viewport.hits.values())
    payload = viewport.clipboard_all_text()
    assert payload.index("Coding Model") < payload.index("Seed") < payload.index("General Model")
    assert viewport.clipboard_text(("series", "coding", "shared")).startswith("Coding Model\nSeed")

def test_grouped_copy_payloads_include_rendered_numeric_fields() -> None:
    model = grouped_projection_with_visible_comparisons()
    viewport = GroupedRankingViewport()
    render_grouped(
        model,
        viewport,
        context(width=90, density="detailed", period="7d"),
        copy_all_action=True,
    )

    assert viewport.clipboard_text(("series", "coding", "shared")) == (
        "Coding Model\nSeed\n70 items\n+10 items\n70.0%\n"
        "Details for Seed\nhttps://example.com/coding/shared"
    )
    assert viewport.clipboard_text(("group", "coding")) == (
        "Coding Model\n100 items\n+20 items\n83.3%\n"
        "About Coding Model\nhttps://example.com/coding\n\n"
        "Seed\n70 items\n+10 items\n70.0%\n"
        "Details for Seed\nhttps://example.com/coding/shared\n\n"
        "Sonnet\n30 items\n+10 items\n30.0%\n"
        "Details for Sonnet\nhttps://example.com/coding/sonnet"
    )
    assert viewport.clipboard_all_text().startswith(viewport.clipboard_text(("group", "coding")))

    render_grouped(model, viewport, context(width=40, density="detailed", period="7d"))
    copied = viewport.clipboard_all_text()
    assert "+10 items" not in copied
    assert "70.0%" in copied

    list_context = replace(context(width=90, density="detailed", period="7d"), style="list")
    render_grouped(model, viewport, list_context)
    assert "+10 items" not in viewport.clipboard_all_text()
    assert "%" not in viewport.clipboard_all_text()

    rank_config = replace(model.config, ranking_comparison="rank")
    render_grouped(model, viewport, context(width=90, density="detailed", period="7d"))
    render_grouped(replace(model, config=rank_config), viewport, context(width=90, density="detailed", period="7d"))
    rank_copied = viewport.clipboard_all_text()
    assert "+10 items" not in rank_copied
    assert "·" in rank_copied

    render_grouped(model, viewport, context(width=90, density="detailed", period="7d", pending=True))
    pending = viewport.clipboard_text(("series", "coding", "shared"))
    assert "??" in pending
    assert "70.0%" not in pending

def test_grouped_list_keeps_group_copy_affordance_only() -> None:
    viewport = GroupedRankingViewport()
    model = grouped_projection()
    render_grouped(model, viewport, context(density="detailed"))
    dot_geometry_key = viewport.geometry_key

    output = strip_ansi(
        render_grouped(
            model,
            viewport,
            replace(context(), style="list", density="detailed"),
            copy_all_action=True,
        )
    )

    assert viewport.geometry_key != dot_geometry_key
    assert viewport.copy_all_hit is None
    assert "⊞" in output and "→" not in output
    assert any(hit[0] == ("group", "coding") for hit in viewport.hits.values())
    assert all(hit[0][0] == "group" for hit in viewport.hits.values())
    assert "vs prior" not in output and "Rank Δ" not in output
    # List mode retains group copy affordances while series rows stay compact.
    assert "Coding Model" in output and "About Coding Model" in output
    assert "Seed" in output and "Details for Seed" in output

    copied = strip_ansi(
        render_grouped(
            model,
            viewport,
            replace(context(), style="list", density="detailed"),
            copied=("group", "coding"),
        )
    )
    assert "✓" in copied

def test_grouped_copy_all_preserves_empty_groups_and_visible_other_exactly() -> None:
    model = grouped_projection()
    coding, general, empty = model.groups or ()
    other = replace(
        coding.series[0],
        id="other",
        label=LocalizedText("Other", "其他"),
        description=None,
        link=None,
        is_other=True,
    )
    model = replace(model, groups=(empty, coding, replace(general, series=(other,))))
    viewport = GroupedRankingViewport()
    render_grouped(model, viewport)
    assert viewport.clipboard_all_text() == (
        "Empty Unmatched Group\n"
        "0 items\n"
        "0.0%\n"
        "About Empty Unmatched Group\n"
        "https://example.com/empty\n\n"
        "Coding Model\n"
        "100 items\n"
        "83.3%\n"
        "About Coding Model\n"
        "https://example.com/coding\n\n"
        "Seed\n"
        "70 items\n"
        "70.0%\n"
        "Details for Seed\n"
        "https://example.com/coding/shared\n\n"
        "Sonnet\n"
        "30 items\n"
        "30.0%\n"
        "Details for Sonnet\n"
        "https://example.com/coding/sonnet\n\n"
        "General Model\n"
        "20 items\n"
        "16.7%\n"
        "About General Model\n"
        "https://example.com/general\n\n"
        "Other\n"
        "70 items\n"
        "350.0%"
    )
    assert viewport.clipboard_text(("group", "general")) == (
        "General Model\n20 items\n16.7%\n"
        "About General Model\nhttps://example.com/general\n\nOther\n70 items\n350.0%"
    )
    assert viewport.clipboard_text(("series", "general", "other")) == ""

    render_grouped(model, viewport, search="Seed")
    assert viewport.clipboard_all_text() == (
        "Coding Model\n"
        "100 items\n"
        "83.3%\n"
        "About Coding Model\n"
        "https://example.com/coding\n\n"
        "Seed\n"
        "70 items\n"
        "70.0%\n"
        "Details for Seed\n"
        "https://example.com/coding/shared"
    )

def test_grouped_copy_all_omits_other_when_projection_hides_it() -> None:
    model = grouped_projection()
    coding = (model.groups or ())[0]
    viewport = GroupedRankingViewport()
    render_grouped(replace(model, groups=(coding,)), viewport)
    assert "Other" not in viewport.clipboard_all_text()

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
        "Empty Unmatched Group\n0 items\nAbout Empty Unmatched Group\nhttps://example.com/empty"
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

def test_grouped_other_only_has_copy_all_payload_but_no_individual_hit() -> None:
    model = grouped_projection()
    coding = (model.groups or ())[0]
    other = replace(
        coding.series[0],
        id="other",
        label=LocalizedText("Other", "其他"),
        description=None,
        link=None,
        is_other=True,
    )
    model = replace(model, groups=(replace(coding, series=(other,)),))
    viewport = GroupedRankingViewport()
    output = strip_ansi(render_grouped(model, viewport, copy_all_action=True))
    assert output.splitlines()[1] == "0 item(s) total | ⊞"
    assert viewport.copy_all_hit is not None
    assert all(hit[0] != ("series", "coding", "other") for hit in viewport.hits.values())
    assert viewport.clipboard_all_text() == (
        "Coding Model\n100 items\n100.0%\nAbout Coding Model\n"
        "https://example.com/coding\n\nOther\n70 items\n70.0%"
    )

    searched = strip_ansi(render_grouped(model, viewport, search="Other", copy_all_action=True))
    assert "Showing 0/0 item(s)" in searched
    assert "Coding Model" not in searched and "Other" not in searched.splitlines()[3:]
    assert viewport.copy_all_hit is None
    assert viewport.clipboard_all_text() == ""

def test_grouped_plain_capacity_reaches_final_row_and_sets_truthful_scrollbar_max() -> None:
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
    assert viewport.reserved_rows == 0
    assert viewport.offset == viewport.total_rows - viewport.visible_rows
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
    assert viewport.offset + viewport.visible_rows == viewport.total_rows
    assert output.splitlines()[-1].strip().startswith("No data")
    assert viewport.scrollbar is not None
    assert viewport.scrollbar.maximum_offset == base
    assert viewport.scrollbar.thumb_top + viewport.scrollbar.thumb_size == (
        viewport.scrollbar.top + viewport.scrollbar.height
    )

def test_grouped_notice_reservation_is_stable_without_sticky_state() -> None:
    viewport = GroupedRankingViewport(reserved_rows=2)
    model = grouped_projection()
    ctx = context(height=5)
    render_grouped(model, viewport, ctx)
    viewport.offset = next(index for index, row in enumerate(viewport.rows) if row.kind == "series")
    first = render_grouped(model, viewport, ctx)
    state = (viewport.reserved_rows, viewport.visible_rows, viewport.offset)
    second = render_grouped(model, viewport, ctx)
    assert state == (2, viewport.visible_rows, viewport.offset)
    assert (viewport.reserved_rows, viewport.visible_rows, viewport.offset) == state
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
    refreshed = replace(
        model, groups=(coding, replace(general, label=LocalizedText("Changed", "Changed")), empty)
    )
    render_grouped(refreshed, viewport, detailed)
    top = viewport.rows[viewport.offset]
    assert (top.group_id, top.series_id) == ("coding", "shared")
