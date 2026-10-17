from ccusage_viz.chart_models import (
    MetricDescriptor,
    ObservedScope,
    RankingModel,
    ScalarRankingEntry,
)
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking import render_ranking

from .helpers import context


def test_observed_ranking_uses_recent_range_without_historical_percentage() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("alpha", "Alpha", 1200.0),
            ScalarRankingEntry("beta", "Beta", 800.0),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "agent"),
    )

    output = render_ranking(model, context(True))

    assert "Tokens · Ranking · by Agent · 15m window" in output
    assert "1.2K" in output and "800" in output
    assert "%" not in output
    assert "2026-01-01" not in output


def test_observed_ranking_reclaims_percentage_space_for_labels() -> None:
    label = "gpt-5.6-very-long-model-name"
    model = RankingModel(
        (),
        None,
        observed_entries=(ScalarRankingEntry("model", label, 1200.0),),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "model"),
    )

    wide = render_ranking(model, context(True)).splitlines()[-1]
    narrow = render_ranking(
        model,
        RenderContext(40, 24, load_translator("en"), color=False, ascii=True),
    )

    assert "gpt-5.6-very-long-model-name" in wide
    assert display_width(wide) <= 80
    assert all(display_width(line) <= 40 for line in narrow.splitlines())


def test_observed_ranking_uses_content_driven_label_width() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("a", "A", 1200.0),
            ScalarRankingEntry("b", "B", 800.0),
        ),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "model"),
    )

    row = render_ranking(model, context(True)).splitlines()[-2]

    assert "A #" in row
    assert "A           " not in row


def test_monitor_ranking_dot_replaces_the_middle_bar_with_a_single_dot_track() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("alpha", "Alpha", 1200.0),
            ScalarRankingEntry("beta", "Beta", 800.0),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "agent"),
    )

    dotted = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, style="ranking-dot"),
    )
    ascii_dotted = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="ranking-dot"),
    )
    ranking = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, style="ranking"),
    )

    dotted_rows = dotted.splitlines()[-2:]
    ascii_rows = ascii_dotted.splitlines()[-2:]
    ranking_rows = ranking.splitlines()[-2:]

    assert all(not row.startswith(("● ", "o ")) for row in (*dotted_rows, *ascii_rows))
    assert all("●" in row and "·" in row for row in dotted_rows)
    assert all("o" in row and "." in row for row in ascii_rows)
    assert all("█" in row for row in ranking_rows)
    assert all("●" not in row and "·" not in row for row in ranking_rows)
    assert all(display_width(row) <= 80 for row in dotted_rows)


def test_monitor_project_ranking_and_list_preserve_exact_agent_labels() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("claude-app", "claude · app", 1_200.0, agent="claude"),
            ScalarRankingEntry("codex-app", "codex · app", 800.0, agent="codex"),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(900, "project"),
        project_aggregation="exact",
    )

    ranking = render_ranking(model, context(True))
    listing = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="list"),
    )

    assert "Tokens · Ranking · by Project · 15m window" in ranking
    assert "claude · app" in ranking and "codex · app" in ranking
    assert "claude · app" in listing and "codex · app" in listing


def test_observed_ranking_does_not_compact_shared_model_prefixes() -> None:
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("terna", "gpt-5.6-terna", 1_000_000.0),
            ScalarRankingEntry("luna", "gpt-5.6-luna", 510_000.0),
            ScalarRankingEntry("sol", "gpt-5.6-sol", 0.0),
        ),
        metric=MetricDescriptor("tpm"),
        observed_scope=ObservedScope(900, "model"),
    )

    output = render_ranking(model, context(True))

    assert "gpt-5.6-terna" in output
    assert "gpt-5.6-luna" in output
    assert "gpt-5.6-sol" in output
    assert "…5.6-" not in output
