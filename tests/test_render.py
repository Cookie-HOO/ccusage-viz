import os
import subprocess
import sys
from datetime import date

import plotext as plt
import pytest

from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    ChangeDirection,
    DailySummary,
    PercentChange,
    RankingEntry,
    RankingModel,
    Series,
    StackModel,
    TimelineModel,
)
from ccusage_viz.domain import TokenUsage
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import DateRange
from ccusage_viz.render.base import RenderContext, isolated_plot
from ccusage_viz.render.calendar import render_calendar
from ccusage_viz.render.palette import (
    CATEGORICAL,
    COLOR_SCHEMES,
    ColorScheme,
    categorical_color,
    categorical_colors,
    get_color_scheme,
)
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.render.stack import render_stack
from ccusage_viz.render.timeline import render_timeline


def usage(total: int) -> TokenUsage:
    return TokenUsage(total, total, 0, 0, 0)


def context(ascii: bool = False) -> RenderContext:
    return RenderContext(80, 24, load_translator("en"), color=False, ascii=ascii)


def period() -> DateRange:
    return DateRange(date(2026, 1, 1), date(2026, 1, 14), None)


def test_ranking_and_custom_calendar_render_without_json_or_table() -> None:
    ranking = render_ranking(
        RankingModel((RankingEntry("a", "项目", usage(1_200)),), period()), context(True)
    )
    assert "Ranking · 2026-01-01–2026-01-14" in ranking
    assert "项目" in ranking and "1.2K" in ranking and "{" not in ranking
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(4)),)), context(True)
    )
    assert "Calendar" in calendar and "#4" in calendar


def test_empty_ranking_keeps_localized_effective_range() -> None:
    output = render_ranking(
        RankingModel((), period()),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )

    lines = output.splitlines()
    assert lines[0].strip() == "累计排名 · 2026-01-01–2026-01-14"
    assert lines[1] == "所选范围内没有 Token 用量。"


def test_calendar_absolute_style_has_stable_token_band_legend() -> None:
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(20_000)),)),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="absolute"),
    )
    assert ".≤1K" in calendar
    assert "#>100K" in calendar


def test_calendar_labels_follow_selected_language() -> None:
    calendar = render_calendar(
        CalendarModel((CalendarDay(date(2026, 1, 1), usage(4)),)),
        RenderContext(80, 24, load_translator("zh"), color=False, ascii=True),
    )
    assert "1月" in calendar
    assert "四" in calendar
    assert "Jan" not in calendar


def test_timeline_area_requires_one_visible_series() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series("a", "A", (usage(1_000),)),
            Series("b", "B", (usage(2_000),)),
        ),
    )
    with pytest.raises(UsageError) as caught:
        render_timeline(model, RenderContext(80, 24, load_translator("en"), style="area"))
    assert caught.value.key == "error.arguments"
    assert (
        caught.value.values["detail"] == "timeline area style requires exactly one visible series"
    )


def test_timeline_no_color_has_no_ansi_sequences() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (Series("total", "Total", (usage(1_000),)),),
    )
    assert "\x1b[" not in render_timeline(model, context(True))


def test_timeline_hides_only_the_sole_canonical_total_legend() -> None:
    day = (date(2026, 1, 1),)

    total = render_timeline(
        TimelineModel(day, (Series(("total",), "Total", (usage(1_000),)),)), context(True)
    )
    named = render_timeline(
        TimelineModel(day, (Series(("agent", "claude"), "claude", (usage(1_000),)),)), context(True)
    )

    assert "Timeline · Total" in total
    assert "claude" in named


def test_timeline_displays_an_explicit_legend_for_multiple_series() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series(("model", "terra"), "terra", (usage(1_000),)),
            Series(("model", "sol"), "sol", (usage(2_000),)),
            Series(("other",), "Other", (usage(500),), is_other=True),
        ),
    )

    output = render_timeline(model, context(True))

    assert ". terra · o sol · # Other" in output


def test_timeline_project_legend_uses_recognizable_safe_labels() -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series(("project", "one"), "my-app", (usage(1_000),)),
            Series(("project", "two"), "api", (usage(2_000),)),
        ),
    )

    output = render_timeline(model, context(True))

    assert ". my-app · o api" in output
    assert "Project-" not in output


@pytest.mark.parametrize("position", ("inside", "hidden"))
def test_timeline_nondefault_legend_position_hides_external_legend(position: str) -> None:
    model = TimelineModel(
        (date(2026, 1, 1),),
        (
            Series(("model", "terra"), "terra", (usage(1_000),)),
            Series(("model", "sol"), "sol", (usage(2_000),)),
        ),
    )

    output = render_timeline(
        model, RenderContext(100, 24, load_translator("en"), ascii=True, legend_position=position)
    )

    assert ". terra · o sol" not in output


def test_colored_plot_inherits_terminal_background() -> None:
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(1_000), usage(2_000))),),
    )
    output = render_timeline(model, RenderContext(100, 24, load_translator("en"), color=True))
    assert "\x1b[" in output
    assert "\x1b[48;" not in output


def test_stack_normalized_style_uses_percent_axis() -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
        ),
    )

    output = render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="normalized")
    )
    assert "100%" in output


def test_stack_legend_has_component_swatches() -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
            Series(("component", "cache"), "cache", (usage(250),)),
        ),
    )
    output = render_stack(model, context(True))
    assert "# Input" in output
    assert "= Output" in output
    assert "+ Cache" in output

    unicode_output = render_stack(model, RenderContext(100, 24, load_translator("en"), color=False))
    assert "█ Input" in unicode_output
    assert "■ Output" in unicode_output
    assert "● Cache" in unicode_output


def test_stack_hidden_legend_keeps_heading_and_omits_component_keys() -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
        ),
    )

    output = render_stack(
        model,
        RenderContext(
            100, 24, load_translator("en"), color=False, ascii=True, legend_position="hidden"
        ),
    )

    assert "Stack · 2026-01-01–2026-01-01" in output
    assert "# Input" not in output
    assert "= Output" not in output


def test_stack_style_selects_solid_or_pattern_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    model = StackModel(
        (date(2026, 1, 1),),
        (
            Series(("component", "input"), "input", (usage(1_000),)),
            Series(("component", "output"), "output", (usage(500),)),
        ),
    )
    captured: list[list[str]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        markers = kwargs["marker"]
        assert isinstance(markers, list)
        captured.append([str(marker) for marker in markers])
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="stacked"))
    render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="stacked-pattern")
    )

    assert captured[0] == ["PlotextMarker(█)", "PlotextMarker(█)"]
    assert captured[1] == ["PlotextMarker(/)", "PlotextMarker(\\)"]


def test_grouped_stack_uses_uniform_day_pitch_and_explicit_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series(("component", "input"), "input", (usage(1_000), usage(500))),
            Series(("component", "output"), "output", (usage(500), usage(1_000))),
            Series(("component", "cache"), "cache", (usage(250), usage(250))),
        ),
    )
    captured: list[dict[str, object]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        captured.append(
            {
                "x": args[0],
                "values": args[1],
                "width": kwargs["width"],
                "stacked": kwargs.get("stacked"),
            }
        )
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped"))

    assert captured == [
        {
            "x": [-0.8 / 3, 1 - 0.8 / 3],
            "values": [1_000, 500],
            "width": 0.8 / 3,
            "stacked": None,
        },
        {"x": [0.0, 1.0], "values": [500, 1_000], "width": 0.8 / 3, "stacked": None},
        {
            "x": [0.8 / 3, 1 + 0.8 / 3],
            "values": [250, 250],
            "width": 0.8 / 3,
            "stacked": None,
        },
    ]


def test_grouped_stack_keeps_component_slots_when_a_value_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)),
        (
            Series(("component", "input"), "input", (usage(100), usage(100), usage(100))),
            Series(("component", "output"), "output", (usage(0), usage(50), usage(50))),
            Series(("component", "cache"), "cache", (usage(25), usage(25), usage(0))),
        ),
    )
    captured: list[tuple[list[float], list[int], float]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        centers, values = args[:2]
        width = kwargs["width"]
        assert isinstance(centers, list)
        assert isinstance(values, list)
        assert isinstance(width, float)
        captured.append((centers, values, width))
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped"))

    assert captured == [
        ([-0.8 / 3, 1 - 0.8 / 3, 2 - 0.8 / 3], [100, 100, 100], 0.8 / 3),
        ([0.0, 1.0, 2.0], [0, 50, 50], 0.8 / 3),
        ([0.8 / 3, 1 + 0.8 / 3, 2 + 0.8 / 3], [25, 25, 0], 0.8 / 3),
    ]


def test_grouped_thin_stack_narrows_bars_without_changing_day_pitch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series(("component", "input"), "input", (usage(1_000), usage(500))),
            Series(("component", "output"), "output", (usage(500), usage(1_000))),
            Series(("component", "cache"), "cache", (usage(250), usage(250))),
        ),
    )
    captured: list[list[tuple[list[float], float]]] = []
    current: list[tuple[list[float], float]] = []
    original_bar = plt.figure.bar

    def record_bar(*args: object, **kwargs: object) -> object:
        centers = args[0]
        width = kwargs["width"]
        assert isinstance(centers, list)
        assert isinstance(width, float)
        current.append((centers, width))
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", record_bar)
    render_stack(model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped"))
    captured.append(current.copy())
    current.clear()
    render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="grouped-thin")
    )
    captured.append(current.copy())

    broad, thin = captured
    assert len(broad) == len(thin) == 3
    assert thin[0][1] < broad[0][1]
    assert thin[0][0][1] - thin[0][0][0] == broad[0][0][1] - broad[0][0][0] == 1


def test_grouped_stack_rejects_width_too_narrow_for_components() -> None:
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series(("component", "input"), "input", (usage(1_000), usage(500))),
            Series(("component", "output"), "output", (usage(500), usage(1_000))),
            Series(("component", "cache"), "cache", (usage(250), usage(250))),
        ),
    )

    with pytest.raises(UsageError) as caught:
        render_stack(
            model, RenderContext(15, 24, load_translator("en"), color=False, style="grouped")
        )
    assert caught.value.key == "error.stack_grouped_width"


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
    assert lines[1].count("●") > 1
    assert lines[2].count("●") > 1
    assert "·" in lines[2]


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


def test_wide_timeline_ticks_include_localized_weekdays() -> None:
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(1_000), usage(2_000))),),
    )
    output = render_timeline(model, RenderContext(100, 24, load_translator("en"), color=False))
    assert "Th 01-01" in output
    assert "Fr 01-02" in output


def test_color_schemes_include_curated_theme_families() -> None:
    assert COLOR_SCHEMES == (
        "classic",
        "vivid",
        "contrast",
        "dracula",
        "catppuccin",
        "solarized",
        "gruvbox",
        "nord",
        "github",
        "mono",
    )


def test_github_theme_has_stable_semantic_ansi_256_colors() -> None:
    assert get_color_scheme("github") == ColorScheme(
        categorical=(26, 166, 71, 98, 162, 160, 30, 136),
        calendar=(151, 77, 71, 23),
        other=245,
        input=26,
        output=166,
        cache=71,
        cache_read=30,
        cache_creation=98,
        highlight=26,
    )


def test_color_schemes_allocate_distinct_visible_series() -> None:
    keys = tuple(("project", str(index)) for index in range(8))
    for scheme in COLOR_SCHEMES:
        colors = categorical_colors(keys, scheme)
        assert len(set(colors.values())) == 8
        assert colors == categorical_colors(reversed(keys), scheme)


@pytest.mark.parametrize("scheme", ["classic", "vivid", "contrast"])
def test_summary_uses_fixed_semantic_colors(scheme: str) -> None:
    summary = DailySummary(
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    output = render_timeline(
        TimelineModel(
            (date(2026, 1, 1), date(2026, 1, 2)),
            (Series("total", "Total", (usage(10), usage(20))),),
            summary=summary,
        ),
        RenderContext(100, 24, load_translator("en"), color=True, color_scheme=scheme),
    )
    assert "\x1b[38;5;45m" in output
    assert "\x1b[38;5;35m" in output
    assert "\x1b[38;5;166m" in output


def test_summary_is_localized_and_color_is_foreground_only() -> None:
    days = (date(2026, 1, 1), date(2026, 1, 2))
    summary = DailySummary(
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    model = TimelineModel(
        days, (Series("total", "Total", (usage(10), usage(20))),), summary=summary
    )
    output = render_timeline(
        model, RenderContext(100, 24, load_translator("zh"), color=True, color_scheme="vivid")
    )
    plain = strip_ansi(output)
    assert "今天21.4000M，环比昨天上升12.4%，同比上周五下降23.4%" in plain
    assert "\x1b[38;5;" in output
    assert "\x1b[38;2;" not in output
    assert "\x1b[48;" not in output

    colorless = render_timeline(model, RenderContext(100, 24, load_translator("zh"), color=False))
    assert "\x1b[" not in colorless
    assert "今天21.4000M，环比昨天上升12.4%，同比上周五下降23.4%" in colorless


def test_mono_summary_uses_grayscale() -> None:
    summary = DailySummary(
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    output = render_timeline(
        TimelineModel(
            (date(2026, 1, 1), date(2026, 1, 2)),
            (Series("total", "Total", (usage(10), usage(20))),),
            summary=summary,
        ),
        RenderContext(100, 24, load_translator("en"), color=True, color_scheme="mono"),
    )
    assert "\x1b[38;5;255m" in output
    assert "\x1b[38;5;35m" not in output
    assert "\x1b[38;5;166m" not in output


def test_from_zero_summary_describes_the_transition() -> None:
    summary = DailySummary(
        date(2026, 1, 14),
        58_300_000,
        PercentChange(ChangeDirection.DECREASE, 49.1),
        PercentChange(ChangeDirection.FROM_ZERO),
        date(2026, 1, 7),
    )
    output = render_timeline(
        TimelineModel(
            (date(2026, 1, 7), date(2026, 1, 14)),
            (Series("total", "Total", (usage(0), usage(58_300_000))),),
            summary=summary,
        ),
        RenderContext(100, 24, load_translator("zh"), color=False),
    )
    assert "今天58.3000M，环比昨天下降49.1%，同比上周三从 0 增至58.3000M" in output


def test_categorical_color_follows_entity_key_not_rank() -> None:
    key = ("project", "/workspace/app")

    assert categorical_color(key, 0) == categorical_color(key, 7)


def test_categorical_color_uses_the_readable_palette() -> None:
    colors = {categorical_color(("project", str(index))) for index in range(256)}

    assert colors == set(CATEGORICAL)


def test_categorical_color_is_independent_of_python_hash_seed() -> None:
    command = [
        sys.executable,
        "-c",
        "from ccusage_viz.render.palette import categorical_color; "
        "print(categorical_color(('project', '/workspace/app')))",
    ]
    colors = []
    for seed in ("1", "2"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        colors.append(subprocess.check_output(command, env=environment, text=True).strip())

    assert colors[0] == colors[1]


def test_plotext_state_is_cleared_after_render_scope() -> None:
    with isolated_plot():
        plt.figure.title("private")
    assert "private" not in plt.figure.build()
