from dataclasses import replace

import pytest

from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_historical import render_historical_ranking

from .helpers import context


@pytest.mark.parametrize("ascii,up,down", ((False, "↑", "↓"), (True, "^", "v")))
def test_list_restores_only_value_change_icons(ascii, up, down):
    ctx = replace(
        context(ascii),
        width=70,
        style="list",
        density="detailed",
        deltas={"up": 1, "down": -1, "same": 0},
        rank_deltas={"up": -2, "down": 3},
    )
    output = render_historical_ranking(
        (
            RankingPresentationEntry("up", "Up", 10, previous=5, comparison_ready=True),
            RankingPresentationEntry("down", "Down", 8, previous=10, comparison_ready=True),
            RankingPresentationEntry("same", "Same", 5, previous=5, comparison_ready=True),
            RankingPresentationEntry("quiet", "Quiet", 2),
        ),
        heading="Ranking",
        value_formatter=str,
        context=ctx,
        total=25,
        comparison_available=True,
        show_percentage=False,
        descriptions_visible=True,
        show_new_entries=True,
    )
    rows = output.splitlines()
    up_row = next(row for row in rows if "Up" in row)
    down_row = next(row for row in rows if "Down" in row)
    same_row = next(row for row in rows if "Same" in row)
    quiet_row = next(row for row in rows if "Quiet" in row)
    assert up in up_row and down in down_row
    assert same_row.endswith("5 -")
    assert up not in quiet_row and down not in quiet_row and not quiet_row.endswith("-")
    for absent in ("Rank Δ", "Share", "New", "|", "●", "*"):
        assert absent not in output
    assert all("%" not in row for row in rows)


def test_non_list_refresh_markers_show_arrows_and_ascii_hyphen_for_unchanged():
    ctx = replace(context(True), width=70, style="dot", deltas={"up": 1, "down": -1, "same": 0})
    output = render_historical_ranking(
        (
            RankingPresentationEntry("up", "Up", 10),
            RankingPresentationEntry("down", "Down", 8),
            RankingPresentationEntry("same", "Same", 5),
            RankingPresentationEntry("quiet", "Quiet", 2),
        ),
        heading="Ranking",
        value_formatter=str,
        context=ctx,
        comparison_available=False,
        show_percentage=False,
    )

    rows = output.splitlines()
    assert next(row for row in rows if "Up" in row).endswith("10 ^")
    assert next(row for row in rows if "Down" in row).endswith("8 v")
    assert next(row for row in rows if "Same" in row).endswith("5 -")
    assert next(row for row in rows if "Quiet" in row).endswith("2  ")


def test_list_uses_dataset_period_comparison_even_without_refresh_deltas():
    ctx = replace(context(), width=60, style="list", deltas={})
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "up", "Router Token Up", 12_000_000, previous=10_000_000, comparison_ready=True
            ),
            RankingPresentationEntry(
                "down", "Router Token Down", 8_000_000, previous=9_000_000, comparison_ready=True
            ),
            RankingPresentationEntry("new", "Router Token New", 5_000_000, comparison_ready=False),
        ),
        heading="Token Ranking",
        value_formatter=str,
        context=ctx,
        comparison_available=True,
        comparison_mode="full",
        show_percentage=False,
    )
    rows = output.splitlines()
    assert next(row for row in rows if "Token Up" in row).endswith("12000000 ↑")
    assert next(row for row in rows if "Token Down" in row).endswith("8000000 ↓")
    assert next(row for row in rows if "Token New" in row).endswith("5000000  ")
    assert "New" not in output.replace("Token New", "")


@pytest.mark.parametrize("style", ("list", "dot", "dots", "bar"))
def test_refresh_highlights_name_without_activity_dot_and_keeps_value_fixed(style):
    from ccusage_viz.formatting import display_width, strip_ansi

    entries = (RankingPresentationEntry("a", "Alpha", 3_600_000_000, display="3.6B"),)
    ctx = replace(context(), width=70, style=style, color=True, density="compact")
    static = render_historical_ranking(entries, heading="Ranking", value_formatter=str, context=ctx)
    live = render_historical_ranking(
        entries, heading="Ranking", value_formatter=str, context=replace(ctx, deltas={"a": 1})
    )
    static_row = next(row for row in static.splitlines() if "Alpha" in row)
    live_row = next(row for row in live.splitlines() if "Alpha" in row)
    plain_static, plain_live = strip_ansi(static_row), strip_ansi(live_row)
    assert plain_static.index("3.6B") == plain_live.index("3.6B")
    assert display_width(plain_static) == display_width(plain_live)
    assert "\x1b[" in live_row[: live_row.index("Alpha")]
    assert "●" not in plain_live[: plain_live.index("Alpha")]
    assert "↑" in plain_live
    assert "↑" not in plain_static


def test_list_change_marker_width_is_measured_before_right_alignment():
    ctx = replace(context(), width=30, style="list", deltas={"changed": 1})
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "changed", "Long project name", 12345, previous=10000, comparison_ready=True
            ),
        ),
        heading="Ranking",
        value_formatter=lambda value: "12.35K",
        context=ctx,
        comparison_available=True,
        show_percentage=False,
    )
    row = next(row for row in output.splitlines() if "project" in row)
    assert row.endswith("12.35K ↑")
    assert len(row) == ctx.width
