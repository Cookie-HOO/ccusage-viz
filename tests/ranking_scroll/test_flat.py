from dataclasses import replace
from decimal import Decimal

import pytest

from ccusage_viz.custom_models import LocalizedText
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.render.custom import render_custom_ranking
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking_viewport import RankingViewport, ranking_separator

from .helpers import _search_fact_projection, _track, context, projection, render


@pytest.mark.parametrize("width", (1, 2, 5, 6, 12))
@pytest.mark.parametrize("ascii_mode", (False, True), ids=("unicode", "ascii"))
def test_dashed_separator_uses_scheme_muted_across_widths(width: int, ascii_mode: bool) -> None:
    scheme_name = "vivid"
    expected = ("- " * ((width + 1) // 2)).rstrip()
    colored_context = replace(
        context(width=width), color=True, ascii=ascii_mode, color_scheme=scheme_name
    )

    colored = ranking_separator("dashed", colored_context)

    assert f"\x1b[38;5;{get_color_scheme(scheme_name).muted}m" in colored
    assert "\x1b[2m" in colored
    assert strip_ansi(colored) == expected
    assert (
        ranking_separator(
            "dashed",
            replace(context(width=width), color=False, ascii=ascii_mode, color_scheme="no-color"),
        )
        == expected
    )


def test_flat_ranking_clipboard_includes_visible_values_and_shares() -> None:
    viewport = RankingViewport()
    model = projection(2)
    render(model, viewport, context(width=80, density="detailed"), copy_all_action=True)

    assert viewport.clipboard_text("0") == "Project 0\n2 items\n66.7%\nhttps://example.com/0"
    assert viewport.clipboard_all_text() == (
        "Project 0\n2 items\n66.7%\nhttps://example.com/0\n\n"
        "Project 1\n1 items\n33.3%\nhttps://example.com/1"
    )

    render(model, viewport, replace(context(width=80, density="detailed"), style="list"))
    assert "%" not in viewport.clipboard_all_text()


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


def test_visible_copy_marker_wins_over_checkmark_in_label():
    model = projection(1)
    model = replace(
        model, series=(replace(model.series[0], label=LocalizedText("✓ Project", "项目")),)
    )
    viewport = RankingViewport()
    output = render(model, viewport).splitlines()
    row, (_, column, _) = next(iter(viewport.hits.items()))
    assert strip_ansi(output[row])[column] == "⊞"


@pytest.mark.parametrize("width", (1, 3, 8, 20, 60))
def test_clipped_icons_do_not_create_invisible_hit_targets(width):
    viewport = RankingViewport()
    render(projection(3), viewport, context(width=width))
    for _, copy_column, link_column in viewport.hits.values():
        assert copy_column < width
        assert link_column is None or link_column < width
