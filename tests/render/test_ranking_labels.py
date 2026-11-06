from dataclasses import replace
from decimal import Decimal

import pytest

from ccusage_viz.custom_models import CustomRankingBand, LocalizedText
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.palette import COLOR_SCHEMES, get_color_scheme
from ccusage_viz.render.ranking_entries import RankingPresentationEntry, _refresh_markers
from ccusage_viz.render.ranking_historical import render_historical_ranking
from ccusage_viz.render.ranking_labels import (
    band_colors,
    group_label_deltas,
    label_change,
    ranking_band_legend,
    ranking_label,
)


def context(**kwargs):
    return replace(RenderContext(80, 24, load_translator("en")), **kwargs)


@pytest.mark.parametrize("mode", ["change", "increase", "decrease", "direction", "band", "none"])
@pytest.mark.parametrize("delta", [Decimal("1"), Decimal("-1"), Decimal("0"), None])
def test_six_label_modes_numeric_direction(mode, delta):
    entry = RankingPresentationEntry("a", "Alpha", Decimal("10"))
    ctx = context(label_color_mode=mode, deltas={} if delta is None else {"a": delta})
    rendered = ranking_label("Alpha", entry, ctx)
    expected = (
        delta is not None
        and delta != 0
        and (
            mode in {"change", "direction"}
            or mode == "increase"
            and delta > 0
            or mode == "decrease"
            and delta < 0
        )
    )
    assert ("\x1b[" in rendered) == expected
    assert strip_ansi(rendered) == "Alpha"
    if expected:
        scheme = get_color_scheme(ctx.color_scheme)
        color = (
            scheme.highlight
            if mode == "change"
            else scheme.trend_increase
            if delta > 0
            else scheme.trend_decrease
        )
        assert f"38;5;{color}m" in rendered
    else:
        assert rendered == "Alpha"


@pytest.mark.parametrize("color_scheme", COLOR_SCHEMES)
@pytest.mark.parametrize("ascii_mode", [False, True])
@pytest.mark.parametrize("source", ["refresh", "comparison"])
@pytest.mark.parametrize("delta", [1, -1])
@pytest.mark.parametrize("mode", ["increase", "decrease", "direction", "change"])
def test_label_color_matches_numeric_refresh_marker_style(
    color_scheme, ascii_mode, source, delta, mode
):
    entry = RankingPresentationEntry("a", "Alpha", 10, 10 - delta, True)
    ctx = context(
        color_scheme=color_scheme,
        ascii=ascii_mode,
        label_color_mode=mode,
        deltas={"a": delta} if source == "refresh" else None,
    )
    _, activity, value_marker = _refresh_markers(
        entry, context=ctx, deltas={"a": delta}, rank_deltas={}
    )
    rendered = ranking_label(entry.label, entry, ctx)
    if mode == "increase" and delta < 0 or mode == "decrease" and delta > 0:
        assert rendered == "Alpha"
    else:
        # change retains highlight (the activity style); directional modes use
        # exactly the numeric arrow's foreground and bold ANSI styling.
        marker = activity if mode == "change" else value_marker
        assert rendered == marker.replace(strip_ansi(marker), "Alpha")


@pytest.mark.parametrize("style", ["list", "bars", "dot"])
def test_refresh_zero_authoritative_and_comparison_fallback_across_styles(style):
    entry = RankingPresentationEntry("a", "Alpha", Decimal("10.01"), Decimal("10"), True)
    ctx = context(style=style)
    assert label_change(entry, ctx) == Decimal(".01")
    assert "\x1b[" in ranking_label(entry.label, entry, ctx)
    zero = replace(ctx, deltas={"a": 0})
    assert label_change(entry, zero) == 0
    assert ranking_label(entry.label, entry, zero) == "Alpha"
    assert label_change(entry, ctx, comparison_available=False) is None
    assert label_change(entry, replace(ctx, period="all")) is None
    fallback = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=lambda _: "same display", context=ctx
    )
    authoritative = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=lambda _: "same display", context=zero
    )
    assert "\x1b[1mAlpha" in fallback
    assert "\x1b[1mAlpha" not in authoritative
    assert ranking_label("Alpha", replace(entry, comparison_ready=False), ctx) == "Alpha"


def test_grouped_remapping_does_not_invent_zero_or_confuse_shared_ids():
    entries = (RankingPresentationEntry("shared", "A", 3, 1, True),)
    ctx = context(deltas={("second", "shared"): -1})
    assert group_label_deltas("first", entries, ctx) == {}
    first = replace(ctx, deltas=group_label_deltas("first", entries, ctx))
    assert label_change(entries[0], first) == 2
    second = replace(ctx, deltas=group_label_deltas("second", entries, ctx))
    assert label_change(entries[0], second) == -1


def test_band_mapping_full_order_named_only_pending_other_and_search():
    bands = (
        CustomRankingBand("unused", LocalizedText("Unused", "未使用")),
        CustomRankingBand("named", LocalizedText("Qualification", "晋级")),
        CustomRankingBand("unnamed"),
    )
    ctx = context(label_color_mode="band", ranking_bands=bands, pending=True)
    entry = RankingPresentationEntry("a", "Alpha Beta", 1, band_id="named")
    colors = band_colors(ctx)
    assert colors["named"] == get_color_scheme("classic").categorical[1]
    assert ranking_band_legend((entry,), ctx) == (
        f"\x1b[38;5;{colors['named']}m●\x1b[0m Qualification",
    )
    text = ranking_label(entry.label, entry, ctx, query="Beta")
    assert f"38;5;{colors['named']}m" in text
    assert f"38;5;{get_color_scheme('classic').highlight}m" in text
    assert strip_ansi(text) == entry.label
    assert ranking_label("Alpha", replace(entry, is_other=True), ctx) == "Alpha"
    assert ranking_band_legend((replace(entry, band_id="unnamed"),), ctx) == ()
    assert ranking_band_legend((entry,), replace(ctx, legend_position="hidden")) == ()
    assert ranking_band_legend((entry,), replace(ctx, color=False, ascii=True)) == (
        "o Qualification",
    )
    assert ranking_band_legend(
        (entry,), replace(ctx, translator=load_translator("zh"), color=False)
    ) == ("● 晋级",)


def test_palette_repeats_and_narrow_cjk_legend_is_bounded():
    bands = tuple(
        CustomRankingBand(str(i), LocalizedText("晋级球队" * 3, "晋级球队" * 3)) for i in range(20)
    )
    ctx = context(width=18, height=8, label_color_mode="band", ranking_bands=bands, color=False)
    entries = tuple(RankingPresentationEntry(str(i), "x", 1, band_id=str(i)) for i in range(20))
    colors = band_colors(ctx)
    assert colors["0"] == colors["8"]
    rows = ranking_band_legend(entries, ctx)
    assert len(rows) == 1
    assert all(display_width(row) <= 18 for row in rows)


@pytest.mark.parametrize("style", ["list", "bars", "dot"])
def test_label_modes_leave_plain_rows_and_arrows_unchanged(style):
    entry = RankingPresentationEntry(
        "a",
        "Alpha",
        10,
        8,
        True,
        copy_marker="⊞",
        project_link="https://example.com",
        band_id="band",
    )
    ctx = context(
        style=style, density="detailed", deltas={"a": 2}, ranking_bands=(CustomRankingBand("band"),)
    )
    outputs = [
        render_historical_ranking(
            (entry,),
            heading="Ranking",
            value_formatter=str,
            context=replace(ctx, label_color_mode=mode),
        )
        for mode in ("change", "increase", "decrease", "direction", "band", "none")
    ]
    assert len({strip_ansi(output) for output in outputs}) == 1
    assert "38;5;33m⊞" not in outputs[4]
    assert ranking_label("Alpha", entry, replace(ctx, pending=True)) == "Alpha"
    assert "38;5;33m" in ranking_label(
        "Alpha", entry, replace(ctx, pending=True, label_color_mode="band")
    )
