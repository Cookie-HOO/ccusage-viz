from __future__ import annotations

from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderAudit, RenderContext
from ccusage_viz.render.headings import (
    HeadingSpec,
    chart_name,
    compose_heading,
    heading_with_querying,
    monitor_view_name,
)


def context(language: str = "en", *, width: int = 80, color: bool = False) -> RenderContext:
    return RenderContext(width, 20, load_translator(language), color=color)


def test_chart_names_use_canonical_localized_terms() -> None:
    zh = load_translator("zh")
    en = load_translator("en")

    assert [chart_name(kind, zh) for kind in ("timeline", "calendar", "stack", "ranking")] == [
        "时间趋势",
        "活跃日历",
        "分组构成",
        "累计排名",
    ]
    assert [chart_name(kind, en) for kind in ("timeline", "calendar", "stack", "ranking")] == [
        "Timeline",
        "Calendar",
        "Stack",
        "Ranking",
    ]


def test_monitor_styles_collapse_to_four_view_families() -> None:
    zh = load_translator("zh")
    en = load_translator("en")

    for style in ("bars", "line", "step", "points", "line-points"):
        assert monitor_view_name(style, zh) == "趋势"
        assert monitor_view_name(style, en) == "Trend"
    for style in ("ranking", "ranking-dot"):
        assert monitor_view_name(style, zh) == "排名"
        assert monitor_view_name(style, en) == "Ranking"
    assert monitor_view_name("list", zh) == "列表"
    assert monitor_view_name("list", en) == "List"
    assert monitor_view_name("cumulative-bars", zh) == "累计柱"
    assert monitor_view_name("cumulative-bars", en) == "Cumulative bars"


def test_historical_heading_places_metric_chart_dimension_and_period_in_order() -> None:
    assert (
        compose_heading(
            HeadingSpec("Token", "累计排名", dimension="项目", period="30d"),
            context("zh"),
        )
        == "Token · 累计排名 · by 项目 · 30d"
    )


def test_heading_without_metric_starts_with_chart_and_keeps_optional_metadata() -> None:
    assert (
        compose_heading(
            HeadingSpec(None, "Timeline", dimension="project", period="30d", status="Unavailable"),
            context("en"),
        )
        == "Timeline · by Project · 30d(Unavailable)"
    )


def test_heading_without_metric_remains_width_and_query_safe() -> None:
    render_context = RenderContext(
        20,
        20,
        load_translator("en"),
        color=False,
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying(
        compose_heading(HeadingSpec(None, "Timeline", period="30d"), render_context),
        render_context,
    )

    assert heading == "Timeline · querying"
    assert not heading.startswith(" · ")
    assert display_width(heading) <= render_context.width


def test_partitioned_heading_uses_directional_dimension_relationship() -> None:
    assert (
        compose_heading(
            HeadingSpec("Star", "累计排名", dimension="仓库", partition="语言", period="30d"),
            context("zh"),
        )
        == "Star · 累计排名 · by 语言 → 仓库 · 30d"
    )


def test_heading_localizes_known_dimension_keys() -> None:
    assert (
        compose_heading(HeadingSpec("Token", "累计排名", dimension="model"), context("zh"))
        == "Token · 累计排名 · by 模型"
    )


def test_partitioned_heading_localizes_each_known_dimension_key() -> None:
    assert (
        compose_heading(
            HeadingSpec("Token", "累计排名", dimension="project", partition="model"),
            context("zh"),
        )
        == "Token · 累计排名 · by 模型 → 项目"
    )


def test_monitor_window_is_labeled_but_ungrouped_total_is_omitted() -> None:
    assert (
        compose_heading(HeadingSpec("TPM", "趋势", period="1h", window=True), context("zh"))
        == "TPM · 趋势 · 1h 窗口"
    )
    assert (
        compose_heading(
            HeadingSpec("Tokens", "Ranking", dimension="project", period="1h", window=True),
            context("en"),
        )
        == "Tokens · Ranking · by Project · 1h window"
    )


def test_heading_reduction_removes_dimension_before_period() -> None:
    spec = HeadingSpec("Token", "累计排名", dimension="非常长的项目维度", period="30d")

    assert compose_heading(spec, context("zh", width=31)) == "Token · 累计排名 · 30d"
    assert compose_heading(spec, context("zh", width=20)) == "Token · 累计排名"


def test_heading_truncates_metric_only_after_optional_segments_are_removed() -> None:
    heading = compose_heading(
        HeadingSpec("非常非常长的指标名称", "累计排名", dimension="项目", period="30d"),
        context("zh", width=18),
    )

    assert "累计排名" in heading
    assert "项目" not in heading
    assert "30d" not in heading
    assert display_width(heading) <= 18


def test_heading_falls_back_safely_when_viewport_is_exceptionally_narrow() -> None:
    heading = compose_heading(HeadingSpec("Token", "累计排名"), context("zh", width=1))

    assert heading == ""
    assert display_width(heading) <= 1


def test_heading_truncates_ansi_colored_cjk_metric_without_broken_escapes() -> None:
    heading = compose_heading(
        HeadingSpec("\x1b[31m非常非常长的指标名称\x1b[0m", "累计排名"),
        context("zh", width=18),
    )

    assert strip_ansi(heading) == "非…称 · 累计排名"
    assert display_width(heading) <= 18
    assert heading.count("\x1b[31m") == 2
    assert heading.count("\x1b[0m") == 2
    assert heading.endswith("\x1b[0m · 累计排名")


def test_monitor_status_is_inline_localized_and_muted_when_color_is_enabled() -> None:
    spec = HeadingSpec("TPM", "趋势", period="1h", window=True, status="建立基线中")
    plain = compose_heading(spec, context("zh", color=False))
    colored = compose_heading(spec, context("zh", color=True))

    assert plain == "TPM · 趋势 · 1h 窗口（建立基线中）"
    assert strip_ansi(colored) == plain
    assert "\x1b[2m" in colored
    assert "\n" not in colored


def test_reduction_preserves_monitor_status_before_optional_window() -> None:
    heading = compose_heading(
        HeadingSpec("TPM", "趋势", dimension="模型", period="1h", window=True, status="采样中"),
        context("zh", width=22),
    )

    assert heading == "TPM · 趋势（采样中）"


def test_heading_with_querying_omits_filter_summary_and_mutes_marker() -> None:
    render_context = RenderContext(
        80,
        20,
        load_translator("en"),
        color=True,
        filter_summary="project = app",
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying("Tokens · Timeline", render_context)

    assert strip_ansi(heading) == "Tokens · Timeline · querying"
    assert "project = app" not in heading
    assert "\x1b[2m" in heading


def test_heading_with_querying_does_not_append_a_second_marker() -> None:
    render_context = RenderContext(
        80,
        20,
        load_translator("en"),
        color=False,
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying("Tokens · Timeline · querying", render_context)

    assert heading == "Tokens · Timeline · querying"
    assert heading.count("querying") == 1


def test_querying_heading_reserves_marker_width_before_ascii_reduction() -> None:
    render_context = RenderContext(
        20,
        20,
        load_translator("en"),
        color=False,
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying(
        compose_heading(HeadingSpec("Tokens", "Timeline", period="30d"), render_context),
        render_context,
    )

    assert heading == "Timeline · querying"
    assert heading.count("querying") == 1
    assert display_width(heading) <= render_context.width


def test_querying_heading_reserves_marker_width_for_cjk() -> None:
    render_context = RenderContext(
        17,
        20,
        load_translator("zh"),
        color=False,
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying(
        compose_heading(HeadingSpec("Token", "累计排名", period="30d"), render_context),
        render_context,
    )

    assert heading == "累计排名 · 查询中"
    assert display_width(heading) <= render_context.width


def test_querying_heading_keeps_color_ansi_intact_at_narrow_width() -> None:
    render_context = RenderContext(
        20,
        20,
        load_translator("en"),
        color=True,
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying(
        compose_heading(HeadingSpec("Tokens", "Timeline", period="30d"), render_context),
        render_context,
    )

    assert strip_ansi(heading) == "Timeline · querying"
    assert display_width(heading) <= render_context.width
    assert "\x1b[2m" in heading
    assert heading.endswith("\x1b[0m")


def test_querying_marker_wider_than_viewport_is_safely_clipped() -> None:
    render_context = RenderContext(
        4,
        20,
        load_translator("en"),
        color=True,
        audit=RenderAudit(querying=True),
    )

    heading = heading_with_querying(
        compose_heading(HeadingSpec("Tokens", "Timeline"), render_context),
        render_context,
    )

    assert strip_ansi(heading) == "quer"
    assert display_width(heading) <= render_context.width
    assert heading.endswith("\x1b[0m")
