from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.bootstrap import build_chart_registry
from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    ChangeDirection,
    PercentChange,
    PeriodSummary,
    RankingEntry,
    RankingModel,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.formatting import display_width
from ccusage_viz.historical_component import HistoricalChartComponent, UsageSnapshot
from ccusage_viz.historical_render import render_historical_component
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    ProcessConfig,
    RankingConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.calendar import render_calendar
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.ranking_entries import RankingPresentationEntry
from ccusage_viz.render.ranking_historical import render_historical_ranking
from ccusage_viz.terminal import Terminal

from .helpers import context, period, usage


@pytest.mark.parametrize(
    ("language", "identity"),
    (("en", "Agent → Project"), ("zh", "Agent → 项目")),
)
def test_pending_exact_project_ranking_uses_accepted_canonical_identity(
    language: str, identity: str
) -> None:
    config = RankingConfig(
        "ranking",
        period(),
        presentation=ChartPresentation(theme="no-color", style="bar"),
        project_aggregation="exact",
    )
    accepted = StandaloneLaunch(ProcessConfig(), StandaloneHostConfig(), config)
    component = HistoricalChartComponent(
        accepted, owner_id="pending-exact-heading", runtime=None, registry=build_chart_registry()
    )
    component.seed(accepted, UsageSnapshot((), (), 0.1))
    component.configure(
        replace(
            accepted,
            chart=replace(
                config,
                date_range=DateRange(
                    date(2026, 2, 1), date(2026, 2, 14), period="14d", relative_until=True
                ),
            ),
        ),
        data_affecting=True,
    )

    translator = load_translator(language)
    output = render_historical_component(
        component, translator, Terminal(100, 30, False, False), normalize_titles=True
    ).chart

    assert identity in output
    assert translator.text("status.querying") in output
    assert translator.text("message.data_loading") in output


def test_historical_ranking_heading_is_centered_once() -> None:
    context = RenderContext(80, 24, load_translator("zh"), color=False, period="14d")
    model = RankingModel((RankingEntry("a", "A", usage(1_200)),), period())

    heading = render_ranking(model, context).splitlines()[0]

    assert heading.lstrip() == "Token · 累计排名 · 14d"
    assert (
        len(heading) - len(heading.lstrip())
        == (context.width - display_width(heading.lstrip())) // 2
    )


def test_ranking_heading_shows_hidden_top_coverage() -> None:
    model = RankingModel(
        (RankingEntry("a", "A", usage(60)),),
        period(),
        denominator=usage(100),
        top=1,
        top_share=0.6,
    )

    output = render_ranking(model, context(True))

    assert "Tokens · Ranking · 2026-01-01–2026-01-14 · Top 1 · 60.0% of total" in output


def test_pending_historical_ranking_masks_stale_figures() -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 14),
        60,
        PercentChange(ChangeDirection.INCREASE, 20),
        PercentChange(ChangeDirection.DECREASE, 10),
        date(2026, 1, 7),
    )
    model = RankingModel(
        (RankingEntry("a", "A", usage(60)),),
        period(),
        summary=summary,
        denominator=usage(100),
        top=1,
        top_share=0.6,
    )

    output = render_ranking(
        model,
        RenderContext(
            100,
            24,
            load_translator("en"),
            color=False,
            pending=True,
            deltas={"a": 1},
            rank_deltas={"a": 1},
        ),
    )

    assert "??" in output
    assert "60.0% of total" not in output
    assert " 60 " not in output
    assert "60.0%" not in output


def test_ranking_and_custom_calendar_render_without_json_or_table() -> None:
    ranking = render_ranking(
        RankingModel((RankingEntry("a", "项目", usage(1_200)),), period()), context(True)
    )
    assert "Ranking · 2026-01-01–2026-01-14" in ranking
    assert "项目" in ranking and "1.2K" in ranking and "{" not in ranking
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(4)),)), context(True)
    )
    assert "Calendar" in calendar and "Less" in calendar and "#" in calendar


def test_exact_project_ranking_qualifies_safe_labels_and_title() -> None:
    model = RankingModel(
        (
            RankingEntry(
                ("project", "exact", "claude", "-private-work-py-ccusage-viz"),
                "py-ccusage-viz",
                usage(1_200),
            ),
            RankingEntry(
                ("project", "exact", "codex", "/private/work/py-ccusage-viz"),
                "py-ccusage-viz",
                usage(800),
            ),
            RankingEntry("Other", "Other", usage(500), is_other=True),
        ),
        period(),
        project_aggregation="exact",
    )

    output = render_ranking(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, period="14d"),
    )
    rows = output.splitlines()[-3:]

    assert "Tokens · Ranking · by Agent → Project · 14d" in output
    assert "claude · py-ccusage-viz" not in rows[0]
    assert "codex · py-ccusage-viz" not in rows[1]
    assert "claude" in rows[0] and "py-ccusage-viz" in rows[0]
    assert "codex" in rows[1] and "py-ccusage-viz" in rows[1]
    assert "Other" in rows[2]
    assert "-private-work-py-ccusage-viz" not in output
    assert "/private/work/py-ccusage-viz" not in output


def test_name_project_ranking_keeps_plain_label_for_exact_identity() -> None:
    model = RankingModel(
        (RankingEntry(("project", "exact", "claude", "-private-work-app"), "app", usage(1_200)),),
        period(),
    )

    output = render_ranking(model, context(True))

    assert "Ranking · 2026-01-01–2026-01-14" in output
    assert "claude app" not in output
    assert "app" in output


def test_exact_project_ranking_keeps_agent_visible_in_narrow_context() -> None:
    model = RankingModel(
        (
            RankingEntry(
                ("project", "exact", "claude", "-private-work-very-long-project"),
                "very-long-project",
                usage(1_200),
            ),
            RankingEntry(
                ("project", "exact", "codex", "/private/work/very-long-project"),
                "very-long-project",
                usage(800),
            ),
        ),
        period(),
        project_aggregation="exact",
    )
    output = render_ranking(
        model,
        RenderContext(40, 24, load_translator("en"), color=False, ascii=True),
    )

    rows = output.splitlines()[-2:]
    assert "claude" in rows[0]
    assert "codex" in rows[1]
    assert all("claude ·" not in row and "codex ·" not in row for row in rows)
    assert all("very-long-project" not in row for row in rows)


def test_historical_ranking_derives_comparison_markers_from_entry_facts() -> None:
    model = RankingModel(
        (
            RankingEntry(
                ("project", "api"),
                "api",
                usage(300),
                previous_usage=usage(100),
                comparison_ready=True,
                previous_rank=2,
            ),
            RankingEntry(
                ("project", "app"),
                "app",
                usage(100),
                previous_usage=usage(200),
                comparison_ready=True,
                previous_rank=1,
            ),
        ),
        period(),
    )

    output = render_ranking(model, context(True))

    header = next(line for line in output.splitlines() if "Rank Δ" in line)
    api_line = next(line for line in output.splitlines() if "api" in line)
    app_line = next(line for line in output.splitlines() if "app" in line)
    assert "vs prior" in header
    assert "+200" in api_line
    assert "^" in api_line
    assert "-100" in app_line
    assert "v" in app_line


def test_historical_ranking_full_uses_labeled_value_delta_without_rank_comparison() -> None:
    entries = (
        RankingPresentationEntry(
            "api", "api", 300, previous=100, comparison_ready=True, previous_rank=2
        ),
        RankingPresentationEntry(
            "app", "app", 100, previous=200, comparison_ready=True, previous_rank=1
        ),
        RankingPresentationEntry("other", "Other", 20, is_other=True),
    )
    output = render_historical_ranking(
        entries,
        heading="Ranking",
        value_formatter=str,
        delta_formatter=lambda value: f"{value:+}",
        context=RenderContext(
            100, 24, load_translator("en"), color=False, ascii=True, density="full"
        ),
        total=420,
    )
    header, api, app, other = output.splitlines()[1:]

    assert "Rank" in header and "Current" in header and "vs prior" in header
    assert "Rank Δ" not in header
    assert "+200" in api and "^" not in api
    assert "-100" in app and "v" not in app
    assert "—" in other
    assert all(display_width(row) <= 100 for row in output.splitlines())


def test_historical_ranking_all_period_omits_comparison_columns_and_uses_available_width() -> None:
    context = RenderContext(
        120, 24, load_translator("en"), color=False, style="dot", density="detailed", period="all"
    )
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "Alpha", 100),
            RankingPresentationEntry("b", "Beta", 50),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
    )
    _heading, *rows = output.splitlines()

    assert all("vs prior" not in row and "Rank Δ" not in row for row in rows)
    assert all(display_width(row) == context.width for row in rows)


def test_historical_ranking_rank_comparison_hides_growth_but_retains_rank_delta() -> None:
    output = render_historical_ranking(
        (
            RankingPresentationEntry(
                "api", "API", 300, previous=100, comparison_ready=True, previous_rank=2
            ),
            RankingPresentationEntry(
                "app", "App", 100, previous=200, comparison_ready=True, previous_rank=1
            ),
        ),
        heading="Ranking",
        value_formatter=str,
        delta_formatter=lambda value: f"{value:+}",
        context=RenderContext(
            100, 24, load_translator("en"), color=False, ascii=True, density="detailed"
        ),
        total=400,
        comparison_mode="rank",
    )

    header, api, app = output.splitlines()[1:]
    assert "vs prior" not in header
    assert "Rank Δ" in header
    assert "+200" not in api and "-100" not in app
    assert "^" in api and "v" in app


def test_historical_ranking_none_comparison_hides_all_comparison_columns() -> None:
    output = render_historical_ranking(
        (RankingPresentationEntry("api", "API", 300, previous=100, comparison_ready=True),),
        heading="Ranking",
        value_formatter=str,
        context=RenderContext(100, 24, load_translator("en"), color=False, density="detailed"),
        comparison_mode="none",
    )

    assert "vs prior" not in output
    assert "Rank Δ" not in output


def test_historical_ranking_shows_refresh_activity_and_rank_changes() -> None:
    model = RankingModel(
        (
            RankingEntry(("project", "app"), "app", usage(1_200)),
            RankingEntry(("project", "api"), "api", usage(800)),
        ),
        period(),
    )

    static = render_ranking(model, context(True))
    live = render_ranking(
        model,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            ascii=True,
            deltas={("project", "app"): 100, ("project", "api"): -10},
            rank_deltas={("project", "app"): 1, ("project", "api"): -1},
        ),
    )

    assert "^" not in static.splitlines()[-1]
    assert "v" not in static.splitlines()[-1]
    app_line = next(line for line in live.splitlines() if "app" in line)
    api_line = next(line for line in live.splitlines() if "api" in line)
    assert "1 ^ * app" in app_line
    assert "1.2K ^" in app_line
    assert "2 v * api" in api_line
    assert "800 v" in api_line


def test_historical_ranking_other_ignores_refresh_activity() -> None:
    other = RankingModel(
        (RankingEntry("Other", "Other", usage(500), is_other=True),),
        period(),
    )

    output = render_ranking(
        other,
        RenderContext(
            80,
            24,
            load_translator("en"),
            color=False,
            ascii=True,
            deltas={"Other": 10},
            rank_deltas={"Other": 1},
        ),
    )

    line = next(line for line in output.splitlines() if "Other" in line)
    assert "^" not in line
    assert "*" not in line


def test_empty_ranking_keeps_localized_effective_range() -> None:
    output = render_ranking(
        RankingModel((), period()),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )

    lines = output.splitlines()
    assert lines[0].strip() == "Token · 累计排名 · 2026-01-01–2026-01-14"
    assert lines[1] == "所选范围内没有 Token 用量。"


def test_ranking_dots_style_repeats_marks_to_the_scaled_value() -> None:
    model = RankingModel(
        (
            RankingEntry("a", "A", usage(1_000)),
            RankingEntry("b", "B", usage(500)),
        ),
        period(),
    )

    output = render_ranking(
        model, RenderContext(60, 24, load_translator("en"), color=False, style="dots")
    )

    lines = output.splitlines()
    rows = lines[2:]
    assert rows[0].count("●") > 1
    assert rows[1].count("●") > 1
    assert "·" in rows[1]


@pytest.mark.parametrize("style", ("dot", "dots", "bars"))
def test_historical_ranking_aligns_tracks_and_right_value_column(style: str) -> None:
    context = RenderContext(80, 24, load_translator("en"), color=False, style=style)
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

    track_marks = {"dot": ("●", "·"), "dots": ("●", "·"), "bars": ("█", "░")}[style]
    track_starts = [min(row.index(mark) for mark in track_marks if mark in row) for row in rows]
    assert summary == "Today Units 15"
    assert heading.strip() == "Ranking"
    assert "Current" in header
    assert "vs prior" in header
    assert len(heading) - len(heading.lstrip()) == (context.width - display_width("Ranking")) // 2
    assert track_starts[0] == track_starts[1]
    assert "10" in rows[0] and "—" in rows[0] and rows[0].endswith("66.7%")
    assert "five units" in rows[1] and "—" in rows[1] and rows[1].endswith("33.3%")


def test_historical_ranking_deemphasizes_fixed_project_buckets_like_other() -> None:
    scheme = get_color_scheme("classic")
    model = RankingModel(
        (
            RankingEntry(("project", "real"), "real-project", usage(100)),
            RankingEntry(("project", "fixed", "unassigned"), "Unassigned", usage(50)),
            RankingEntry(("other",), "Other", usage(25), is_other=True),
        ),
        period(),
    )

    output = render_ranking(
        model, RenderContext(80, 24, load_translator("en"), color=True, style="dot")
    )

    rows = output.splitlines()[2:]
    assert f"\x1b[38;5;{scheme.highlight}m●" in rows[0]
    assert f"\x1b[38;5;{scheme.other}m●" in rows[1]
    assert f"\x1b[38;5;{scheme.other}m●" in rows[2]


def test_ranking_compacts_common_opaque_prefixes() -> None:
    model = RankingModel(
        (
            RankingEntry("a", "-home-example-projects-project-a", usage(1_200)),
            RankingEntry("b", "-home-example-projects-project-b", usage(1_000)),
            RankingEntry("c", "-private-var-folders-unrelated", usage(500)),
        ),
        period(),
    )
    output = render_ranking(model, context(True))
    assert "…project-a" in output
    assert "…project-b" in output
    assert "-home-example-projects" not in output
    assert "-private-var-folders" in output
