
















from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_historical import render_historical_ranking


def test_historical_ranking_list_keeps_label_and_value_columns_aligned() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="list")
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "A", 10),
            RankingPresentationEntry("b", "A much longer project name", 5, display="five units"),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        summary="Today Units 15",
    )
    summary, heading, header, *rows = output.splitlines()

    assert summary == "Today Units 15"
    assert heading.strip() == "Ranking"
    assert "Current" in header
    assert "Scale" not in header
    project_start = header.index("Project")
    current_start = header.index("Current")
    assert rows[0].index("A") == project_start
    assert rows[0].index("10") + len("10") == current_start + len("Current")
    assert "A" in rows[0]
    assert "A much longer" in rows[1]
    assert rows[0].endswith("10")
    assert rows[1].endswith("five units")
    assert display_width(rows[0]) == display_width(rows[1])

def test_historical_ranking_list_prioritizes_labels_and_omits_auxiliary_indicators() -> None:
    context = RenderContext(
        80,
        24,
        load_translator("en"),
        color=False,
        ascii=True,
        style="list",
        density="detailed",
        deltas={"api": 2},
        rank_deltas={"api": 1},
    )
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "api",
                "a deliberately long project label that should use list space",
                10,
                previous=5,
                comparison_ready=True,
                previous_rank=2,
                copy_marker="⊞",
                project_link="https://example.com/api",
            ),
        ),
        heading="Ranking",
        value_formatter=str,
        delta_formatter=lambda value: f"{value:+}",
        context=context,
        total=10,
    )
    header, row = output.splitlines()[1:]

    assert row.startswith(" 1 ")
    assert "a deliberately long project label" in row
    assert "⊞" not in output and "→" not in output
    assert "^" not in output and "*" not in output
    assert "vs prior" not in output and "Rank Δ" not in output and "%" not in output
    assert "Current" in header and "Scale" not in header

def test_historical_ranking_list_keeps_native_compactable_labels_and_fits_wide_value() -> None:
    entries = (
        RankingPresentationEntry("a", "prefix/shared-project-a | native", 10),
        RankingPresentationEntry("b", "prefix/shared-project-b | native", 5),
        RankingPresentationEntry("c", "prefix/shared-project-c | native", 1, display="value-too-wide"),
    )
    wide_output = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=RenderContext(80, 24, load_translator("en"), color=False, style="list"),
    )
    narrow_context = RenderContext(18, 24, load_translator("en"), color=False, style="list")
    narrow_output = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=narrow_context,
    )
    _heading, _header, *wide_rows = wide_output.splitlines()
    _heading, _header, *narrow_rows = narrow_output.splitlines()

    assert all("…" not in row for row in wide_rows)
    assert all("prefix/shared-project-" in row and " | native" in row for row in wide_rows)
    assert all(display_width(row) <= narrow_context.width for row in narrow_output.splitlines())
    assert narrow_rows[2].startswith(" 3 p")
