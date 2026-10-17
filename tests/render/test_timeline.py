




from datetime import date, timedelta

import plotext as plt
import pytest

import ccusage_viz.render.timeline as timeline_renderer
from ccusage_viz.chart_models import (
    ChangeDirection,
    PercentChange,
    PeriodSummary,
    Series,
    TimelineModel,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext, isolated_plot
from ccusage_viz.render.summary import render_summary
from ccusage_viz.render.surfaces import (
    SurfaceControls,
    SurfacePresentation,
    dashboard_pane_surface,
    standalone_surface,
)
from ccusage_viz.render.timeline import render_timeline
from ccusage_viz.terminal import Terminal

from .helpers import context, usage


def test_timeline_surfaces_have_independent_axis_and_control_budgets() -> None:
    presentation = SurfacePresentation(
        "timeline",
        "no-color",
        "linear",
        "below-title",
        "detailed",
        "show",
        "14d",
        "Total",
        None,
        None,
        None,
        60,
    )
    terminal = Terminal(80, 20, color=False, ascii=True)
    controls = SurfaceControls(rows=("standalone controls",), reserves_prompt=True)

    standalone = standalone_surface("timeline").context(
        terminal, load_translator("en"), presentation, notices=1, controls=controls
    )
    dashboard = dashboard_pane_surface("timeline").context(
        terminal, load_translator("en"), presentation, notices=1
    )

    assert not standalone.hide_upper_right_axes
    assert dashboard.hide_upper_right_axes
    assert standalone.height == 15
    assert dashboard.height == 18

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
    assert caught.value.key == "error.timeline_area_series"

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

    assert "Tokens · Timeline · 2026-01-01–2026-01-01" in total
    assert "Total" not in total.splitlines()[0]
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

def test_wide_timeline_ticks_include_localized_weekdays() -> None:
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(1_000), usage(2_000))),),
    )
    output = render_timeline(model, RenderContext(100, 24, load_translator("en"), color=False))
    assert "Th 01-01" in output
    assert "Fr 01-02" in output

def test_timeline_budgets_each_wrapped_summary_row(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    model = TimelineModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (Series("total", "Total", (usage(10), usage(20))),),
        summary=summary,
    )
    context = RenderContext(28, 12, load_translator("en"), color=False)
    captured: dict[str, object] = {}
    original = timeline_renderer.render_timeline_plot

    def capture(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(timeline_renderer, "render_timeline_plot", capture)

    output = render_timeline(model, context)

    assert len(render_summary(summary, context).splitlines()) == 3
    assert captured["text_rows"] == 4
    assert len(output.splitlines()) == context.height
    assert "01-01" in output.splitlines()[-1]
    assert "01-02" in output.splitlines()[-1]

def test_timeline_ignores_plotext_ambient_terminal_height_limit() -> None:
    days = tuple(date(2026, 9, 20) + timedelta(days=index) for index in range(14))
    model = TimelineModel(
        days,
        (
            Series(
                "total",
                "Total",
                tuple(usage(100_000 * (index + 1)) for index in range(len(days))),
            ),
        ),
        summary=PeriodSummary(
            "day",
            days[-1],
            1_400_000,
            PercentChange(ChangeDirection.DECREASE, 35.0),
            PercentChange(ChangeDirection.DECREASE, 40.2),
            days[-8],
        ),
    )
    context = RenderContext(
        108,
        25,
        load_translator("zh"),
        color=False,
        style="points",
        density="detailed",
        weekday_mode="show",
        period="14d",
        title_content="总量",
        hide_upper_right_axes=True,
    )

    output = render_timeline(model, context)

    assert len(output.splitlines()) == context.height
    assert days[0].strftime("%m-%d") in output.splitlines()[-1]
    assert days[-2].strftime("%m-%d") in output.splitlines()[-1]

def test_plotext_state_is_cleared_after_render_scope() -> None:
    original_limits = tuple(plt.terminal._limit)
    with isolated_plot():
        plt.figure.title("private")
        plt.terminal.limit(False, False)
    assert "private" not in plt.figure.build()
    assert tuple(plt.terminal._limit) == original_limits
