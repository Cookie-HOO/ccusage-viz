from dataclasses import replace

import pytest

from ccusage_viz.chart_models import (
    MetricDescriptor,
    ObservedScope,
    RankingModel,
    ScalarRankingEntry,
)
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.ranking_columns import render_ranking_heading_row
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_historical import render_historical_ranking


@pytest.mark.parametrize("style", ("ranking", "ranking-dot"))
def test_monitor_ranking_description_starts_with_label_column(style: str) -> None:
    label = "Provider quota"
    description = "Models available through this quota pool and its current routing policy."
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("quota", label, 69.2, description=description, display="69.2%"),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(20, "model"),
    )
    render_context = RenderContext(
        56,
        24,
        load_translator("en"),
        color=False,
        ascii=True,
        style=style,
        density="detailed",
    )

    output = render_ranking(model, render_context)
    primary = next(row for row in output.splitlines() if label in row)
    description_rows = [
        row for row in output.splitlines() if "Models available" in row or "routing policy" in row
    ]

    label_start = display_width(primary.split(label, maxsplit=1)[0])
    assert description_rows
    assert display_width(description_rows[0]) <= render_context.width
    assert (
        display_width(description_rows[0].split("Models available", maxsplit=1)[0]) == label_start
    )


def test_historical_ranking_search_filters_casefolded_fields_and_reports_visible_count() -> None:
    context = RenderContext(
        80, 20, load_translator("en"), color=False, style="dot", density="normal"
    )
    entries = (
        RankingPresentationEntry("a", "Alpha", 12),
        RankingPresentationEntry("b", "Claude worker", 8, description="Release validation"),
    )
    output = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=context,
        search_query="claude",
        show_visible_count=True,
    )
    assert "Search: claude" in output
    assert "Showing 1/2 item(s)" in output
    assert "Alpha" not in output
    assert any(line.lstrip().startswith("2 ") for line in output.splitlines())

    description = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
        search_query="VALIDATION",
        show_visible_count=True,
    )
    assert "Claude worker" in description
    assert "Release validation" in description

    empty = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=context,
        search_query="missing",
        show_visible_count=True,
    )
    assert 'No ranking entries match "missing".' in empty

    minimal = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        context=replace(context, density="minimal"),
        show_visible_count=True,
    )
    assert "Showing" not in minimal


def test_historical_ranking_descriptions_are_muted_wrapped_and_density_aware() -> None:
    context = RenderContext(36, 24, load_translator("en"), color=False, style="dot")
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "api",
                "API",
                10,
                description="Release validation and regression testing account for most activity.",
            ),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
    )

    rows = output.splitlines()
    description_rows = rows[-2:]
    assert len(description_rows) == 2
    assert all(row.startswith(" " * 7) for row in description_rows)
    assert all(display_width(row) <= context.width for row in description_rows)
    assert description_rows[-1].endswith("…")

    minimal = render_historical_ranking(
        (RankingPresentationEntry("api", "API", 10, description="Release validation"),),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, density="minimal"),
        descriptions_visible=True,
    )
    assert "Release validation" not in minimal


def test_historical_ranking_wraps_plain_description_before_styling() -> None:
    context = RenderContext(
        50, 24, load_translator("en"), color=True, style="dot", density="detailed"
    )
    description = "The remarkable Paper Pro drinks your ink and answers in a flowing hand"
    output = render_historical_ranking(
        (RankingPresentationEntry("paper-pro", "Paper Pro", 10, description=description),),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
    )

    rows = [row for row in output.splitlines() if "remarkable" in row or "flowing" in row]
    assert len(rows) == 2
    assert all(display_width(row) <= context.width for row in rows)
    assert all("\x1b" in row for row in rows)


def test_historical_ranking_description_links_are_clickable_and_searchable() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="Read [release notes](https://example.com/openai/release) now.",
    )
    escaped_link = "\x1b]8;;https://example.com/openai/release\x1b\\"

    plain = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )
    assert "release notes" in strip_ansi(plain)
    assert "https://example.com/openai/release" not in strip_ansi(plain)
    assert plain.count(escaped_link) == 2
    assert all(display_width(row) <= context.width for row in plain.splitlines())

    linked = render_historical_ranking(
        (entry,),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, color=True),
        descriptions_visible=True,
    )
    assert "\x1b[38;5;245m\x1b[2;4mrelease notes\x1b[0m" in linked
    assert "release notes ↗" in strip_ansi(linked)

    label_match = render_historical_ranking(
        (entry,),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, color=True),
        descriptions_visible=True,
        search_query="notes",
    )
    assert "\x1b]8;;https://example.com/openai/release\x1b\\" in label_match
    assert "\x1b]8;;\x1b\\" in label_match
    assert "\x1b[38;5;245m\x1b[2;4mrelease notes\x1b[0m" in label_match
    assert "release notes ↗" in strip_ansi(label_match)

    target_match = render_historical_ranking(
        (entry,),
        heading="Ranking",
        value_formatter=str,
        context=replace(context, color=True),
        descriptions_visible=True,
        search_query="openai",
    )
    assert "release notes ↗" in strip_ansi(target_match)
    assert target_match.count(escaped_link) == 2


def test_historical_ranking_description_links_reject_unsafe_markup_and_controls() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="[local](file:///secret) [broken](https://) \x1b[2Jsafe",
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    assert "[local](file:///secret) [broken](https://) safe" in strip_ansi(output)
    assert "\x1b]8;;" not in output
    assert "\x1b[2J" not in output


def test_historical_ranking_description_sanitizes_c1_osc_and_dcs_before_parsing() -> None:
    context = RenderContext(100, 24, load_translator("en"), color=True, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description=(
            "Safe **bold** \x9d52;c;attack\x9c"
            "[*release notes*](https://example.com/release)"
            "\x90malicious payload\x9c tail"
        ),
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    visible = strip_ansi(output)
    assert "Safe bold release notes ↗ tail" in visible
    assert "attack" not in visible
    assert "malicious payload" not in visible
    assert not any(0x7F <= ord(character) <= 0x9F for character in output)
    assert "\x1b[2;1mbold\x1b[0m" in output
    assert "\x1b[4;2;3mrelease notes\x1b[0m" in output
    assert output.count("\x1b]8;;https://example.com/release\x1b\\") == 2


def test_historical_ranking_description_preserves_source_lines_and_removes_c1() -> None:
    context = RenderContext(100, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="First line\n\x9d52;c;attack\x9cSecond line",
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    visible_lines = strip_ansi(output).splitlines()
    first_index = next(
        index for index, line in enumerate(visible_lines) if line.strip() == "First line"
    )
    assert visible_lines[first_index + 1].strip() == "Second line"
    assert "attack" not in output
    assert not any(0x7F <= ord(character) <= 0x9F for character in output)


def test_historical_ranking_description_supports_star_emphasis_only() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=True, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description=(
            "Use **important steps** and *carefully review* "
            "[*release notes*](https://example.com/release)."
        ),
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    visible = strip_ansi(output)
    assert "Use important steps and carefully review release notes ↗." in visible
    assert "**" not in visible and "*release notes*" not in visible
    assert "\x1b[2;1mimportant steps\x1b[0m" in output
    assert "\x1b[2;3mcarefully review\x1b[0m" in output
    assert "\x1b[4;2;3mrelease notes\x1b[0m" in output
    assert output.count("\x1b]8;;https://example.com/release\x1b\\") == 2
    assert all(display_width(row) <= context.width for row in output.splitlines())


def test_historical_ranking_description_keeps_unsupported_star_markup_literal() -> None:
    context = RenderContext(100, 24, load_translator("en"), color=False, style="dot")
    entry = RankingPresentationEntry(
        "api",
        "API",
        10,
        description="__underlined__ **nested *stars*** * unclosed ** ** **",
    )
    output = render_historical_ranking(
        (entry,), heading="Ranking", value_formatter=str, context=context, descriptions_visible=True
    )

    assert "__underlined__ **nested *stars*** * unclosed ** ** **" in strip_ansi(output)


def test_historical_ranking_project_link_follows_the_copy_marker() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    linked = RankingPresentationEntry(
        "api",
        "API",
        10,
        copy_marker="⊞",
        project_link="https://example.com/projects/api",
    )
    output = render_historical_ranking(
        (linked,), heading="Ranking", value_formatter=str, context=context
    )

    assert "API | ⊞ · →" in strip_ansi(output)
    assert output.count("\x1b]8;;https://example.com/projects/api\x1b\\") == 1
    assert all(display_width(row) <= context.width for row in output.splitlines())


def test_ranking_heading_row_list_preserves_pipe_label_and_description() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="list")

    rows = render_ranking_heading_row(
        label="Group | native label",
        value="10",
        delta="+2",
        share="100.0%",
        description="Visible heading description",
        context=context,
        link="https://example.com/group",
        descriptions_visible=True,
    )

    assert len(rows) == 2
    assert "Group | native label" in rows[0] and "10" in rows[0]
    assert "→" not in rows[0]
    assert "+2" not in rows[0] and "100.0%" not in rows[0]
    assert (
        display_width(rows[0].split("Group | native label", maxsplit=1)[0])
        == display_width(rows[1].split("Visible heading description", maxsplit=1)[0])
        == 0
    )
    assert rows[1] == "Visible heading description"


def test_historical_ranking_description_starts_with_its_label_column() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style="dot")
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "A", 10, description="First item description."),
            RankingPresentationEntry("b", "Longer label", 5),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
    )
    _heading, _columns, primary, description, *_rest = output.splitlines()

    label_start = primary.index("A")
    assert description.index("First item description.") == label_start


def test_historical_ranking_list_description_starts_with_label_display_column() -> None:
    context = RenderContext(80, 24, load_translator("en"), color=True, style="list")
    label = "界 Label"
    description = "**Styled description**"
    output = render_historical_ranking(
        (RankingPresentationEntry("entry", label, 10, description=description, rank=12),),
        heading="Ranking",
        value_formatter=str,
        context=context,
        descriptions_visible=True,
        total_entry_count=12,
    )
    primary = next(row for row in output.splitlines() if label in strip_ansi(row))
    description_row = next(
        row for row in output.splitlines() if "Styled description" in strip_ansi(row)
    )
    visible_primary = strip_ansi(primary)
    visible_description = strip_ansi(description_row)

    assert primary.lstrip().startswith("12 ")
    assert "\x1b[" in description_row
    assert display_width(visible_primary.split(label, maxsplit=1)[0]) == display_width(
        visible_description.split("Styled description", maxsplit=1)[0]
    )
