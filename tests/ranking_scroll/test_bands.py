from dataclasses import replace

from ccusage_viz.custom_models import CustomRankingBand, LocalizedText
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.processing.custom_ranking import (
    CustomProjectedRankingEntry,
    CustomProjectedScalarRankingGroup,
    CustomRankingProjection,
)
from ccusage_viz.render.grouped_ranking_viewport import GroupedRankingViewport
from ccusage_viz.render.ranking_viewport import RankingViewport

from .helpers import context, grouped_projection_with_visible_comparisons, render, render_grouped


def projection():
    legacy = grouped_projection_with_visible_comparisons()
    bands = (
        CustomRankingBand("unused", LocalizedText("Unused", "未使用")),
        CustomRankingBand("first", LocalizedText("Qualification", "晋级")),
        CustomRankingBand("second", LocalizedText("Playoff", "附加赛")),
        CustomRankingBand("unnamed"),
    )
    groups = tuple(
        CustomProjectedScalarRankingGroup(
            group.id,
            group.label,
            tuple(
                CustomProjectedRankingEntry(
                    item.id,
                    item.label,
                    item.total,
                    previous_total=item.previous_total,
                    comparison_ready=item.comparison_ready,
                    description=item.description,
                    link=item.link,
                    rank=item.rank,
                    band_id="first" if index == 0 else "second",
                )
                for index, item in enumerate(group.series)
            ),
            group.total,
            group.previous_total,
            group.comparison_ready,
            group.maximum,
            description=group.description,
            link=group.link,
        )
        for group in legacy.groups
    )
    return CustomRankingProjection(
        "ranking",
        (),
        legacy.unit,
        legacy.config,
        legacy.presentation,
        comparison_available=True,
        groups=groups,
        bands=bands,
    )


def test_grouped_band_rows_geometry_hits_and_search_snapshot():
    model = projection()
    viewport = GroupedRankingViewport()
    ctx = replace(
        context(height=8, width=100, density="compact", period="all", color=True),
        label_color_mode="band",
    )
    output = strip_ansi(render_grouped(model, viewport, ctx, scrollbar=True))
    lines = output.splitlines()
    heading = next(i for i, line in enumerate(lines) if "Coding Model" in line)
    assert "Qualification" in lines[heading + 1] and "Playoff" in lines[heading + 1]
    assert "Unused" not in output and "unnamed" not in output
    legends = [i for i, row in enumerate(viewport.rows) if row.kind == "legend"]
    assert len(legends) == 2
    assert viewport.scrollbar is not None
    assert viewport.scrollbar.total_rows == viewport.total_rows
    assert heading in viewport.hits and heading + 1 not in viewport.hits
    assert "Qualification" not in viewport.clipboard_all_text()
    original_widths = dict(viewport.columns.widths)
    original_rows = viewport.rows
    for width in (100, 65, 100):
        resized = replace(ctx, width=width)
        warm = render_grouped(model, viewport, resized, scrollbar=True)
        cold = render_grouped(model, GroupedRankingViewport(), resized, scrollbar=True)
        assert warm == cold
    assert viewport.rows == original_rows
    assert viewport.columns.widths == original_widths
    filtered = strip_ansi(render_grouped(model, viewport, ctx, search="Sonnet"))
    assert "Qualification" in filtered and "Playoff" in filtered
    assert "Seed" not in filtered
    hidden = strip_ansi(render_grouped(model, viewport, replace(ctx, legend_position="hidden")))
    assert "Qualification" not in hidden
    assert not any(row.kind == "legend" for row in viewport.rows)


def test_multi_line_legend_height_resize_and_description_source_offsets():
    model = projection()
    model = replace(
        model,
        bands=tuple(
            replace(band, label=LocalizedText("Qualification tournament", "晋级比赛"))
            if band.id == "first"
            else replace(band, label=LocalizedText("Playoff tournament", "附加比赛"))
            if band.id == "second"
            else band
            for band in model.bands
        ),
    )
    viewport = GroupedRankingViewport()
    ctx = replace(context(height=20, width=32, density="detailed"), label_color_mode="band")
    output = render_grouped(model, viewport, ctx)
    assert sum(row.kind == "legend" and row.group_id == "coding" for row in viewport.rows) == 2
    assert "About Coding Model" in output
    tall_rows = viewport.rows
    short = replace(ctx, height=8)
    short_output = render_grouped(model, viewport, short)
    assert sum(row.kind == "legend" and row.group_id == "coding" for row in viewport.rows) == 1
    assert len(short_output.splitlines()) <= 8
    restored = render_grouped(model, viewport, ctx)
    assert restored == output
    assert viewport.rows == tall_rows


def test_grouped_classification_replacement_and_theme_invalidation():
    model = projection()
    viewport = GroupedRankingViewport()
    ctx = replace(context(height=30, color=True), label_color_mode="band")
    first = render_grouped(model, viewport, ctx)
    themed = render_grouped(model, viewport, replace(ctx, color_scheme="vivid"))
    assert themed != first and strip_ansi(themed) == strip_ansi(first)
    assert themed == render_grouped(
        model, GroupedRankingViewport(), replace(ctx, color_scheme="vivid")
    )
    changed = replace(
        model,
        bands=tuple(
            replace(band, label=LocalizedText("New", "新")) if band.id == "first" else band
            for band in model.bands
        ),
    )
    output = strip_ansi(render_grouped(changed, viewport, ctx))
    assert "New" in output and "Qualification" not in output
    assert output == strip_ansi(render_grouped(changed, GroupedRankingViewport(), ctx))


def test_flat_title_legend_stable_search_copy_all_and_clipping():
    grouped = projection()
    model = replace(grouped, groups=None, series=grouped.groups[0].series)
    viewport = RankingViewport()
    ctx = replace(context(height=12, color=False), label_color_mode="band")
    output = render(model, viewport, ctx, copy_all_action=True)
    rows = output.splitlines()
    assert "Ranking" in rows[0]
    assert "Qualification" in rows[1] and "Playoff" in rows[1]
    assert viewport.copy_all_hit[0] == 2
    assert 1 not in viewport.hits
    filtered = render(model, viewport, ctx, search="Sonnet", copy_all_action=True)
    assert "Qualification" in filtered and "Playoff" in filtered
    assert viewport.copy_all_hit[0] == 3
    for height in (4, 15, 4):
        current = replace(ctx, height=height, width=25)
        warm = render(model, viewport, current)
        cold = render(model, RankingViewport(), current)
        assert warm == cold
        assert len(warm.splitlines()) <= height
