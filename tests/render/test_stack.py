
import re
from datetime import date

import plotext as plt
import pytest

import ccusage_viz.render.stack as stack_renderer
from ccusage_viz.chart_models import (
    ChangeDirection,
    PercentChange,
    PeriodSummary,
    Series,
    StackModel,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.stack import render_stack
from ccusage_viz.render.summary import SummaryBlock, layout_summary_blocks, render_summary

from .helpers import context, usage


def test_layout_summary_blocks_stacks_facts_without_separators() -> None:
    context = RenderContext(10, 1, load_translator("zh"), color=False)

    rows = layout_summary_blocks(
        (SummaryBlock("甲乙"), SummaryBlock("\x1b[1m丙丁\x1b[0m"), SummaryBlock("戊己")),
        context,
        layout="stack",
    )

    assert rows == ("甲乙", "\x1b[1m丙丁\x1b[0m", "戊己")
    assert all(display_width(row) <= context.width for row in rows)

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

    assert "Tokens · Stack · 2026-01-01–2026-01-01" in output
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
    original_bar = plt.figure.bar

    def unexpected_bar(*args: object, **kwargs: object) -> object:
        pytest.fail("non-grouped Stack styles must use the integer-cell renderer")
        return original_bar(*args, **kwargs)

    monkeypatch.setattr(plt.figure, "bar", unexpected_bar)
    solid = render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="stacked")
    )
    pattern = render_stack(
        model, RenderContext(100, 24, load_translator("en"), color=False, style="stacked-pattern")
    )

    assert "█" in solid
    assert "/" in pattern
    assert "\\" in pattern

def test_stacked_grid_aligns_axis_and_distributes_non_divisible_slots() -> None:
    days = tuple(date(2026, 9, index) for index in range(3, 17))
    model = StackModel(
        days,
        (Series(("component", "input"), "input", tuple(usage(100) for _ in days)),),
    )
    output = render_stack(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )
    chart = output.splitlines()[2:]
    baseline = next(line for line in chart if "+" in line)
    data_row = next(line for line in chart if "|" in line)

    assert baseline.index("+") == data_row.index("|")
    assert all(display_width(line) == 80 for line in chart)

def test_stacked_bars_use_equal_cell_widths_when_plotext_pitch_is_fractional() -> None:
    days = tuple(date(2026, 1, index) for index in range(1, 8))
    model = StackModel(
        days,
        (
            Series(("component", "input"), "input", tuple(usage(100) for _ in days)),
            Series(("component", "output"), "output", tuple(usage(100) for _ in days)),
        ),
    )

    output = render_stack(
        model,
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )
    widths = [len(run) for run in re.findall(r"#+", output.splitlines()[2])]

    assert widths == [4] * 7

def test_stacked_slots_do_not_change_when_components_or_periods_are_zero() -> None:
    days = tuple(date(2026, 1, index) for index in range(1, 8))
    components = (
        Series(("component", "input"), "input", tuple(usage(100) for _ in days)),
        Series(("component", "output"), "output", tuple(usage(100) for _ in days)),
    )
    baseline = render_stack(
        StackModel(days, components),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )
    with_zeros = render_stack(
        StackModel(
            days,
            (
                Series(
                    ("component", "input"),
                    "input",
                    (
                        usage(100),
                        usage(100),
                        usage(0),
                        usage(100),
                        usage(100),
                        usage(100),
                        usage(100),
                    ),
                ),
                Series(
                    ("component", "output"),
                    "output",
                    (usage(100), usage(0), usage(0), usage(0), usage(100), usage(100), usage(0)),
                ),
            ),
        ),
        RenderContext(80, 24, load_translator("en"), color=False, ascii=True, style="stacked"),
    )

    baseline_starts = [match.start() for match in re.finditer(r"#+", baseline.splitlines()[2])]
    zero_starts = [match.start() for match in re.finditer(r"#+", with_zeros.splitlines()[-3])]

    assert zero_starts == [baseline_starts[index] for index in (0, 1, 3, 4, 5, 6)]

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

def test_grouped_stack_budgets_each_wrapped_summary_row(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = PeriodSummary(
        "day",
        date(2026, 1, 2),
        21_400_000,
        PercentChange(ChangeDirection.INCREASE, 12.4),
        PercentChange(ChangeDirection.DECREASE, 23.4),
        date(2025, 12, 26),
    )
    model = StackModel(
        (date(2026, 1, 1), date(2026, 1, 2)),
        (
            Series("input", "input", (usage(10), usage(20))),
            Series("output", "output", (usage(5), usage(10))),
        ),
        summary=summary,
    )
    context = RenderContext(28, 12, load_translator("en"), color=False, style="grouped")
    captured: dict[str, object] = {}
    original = stack_renderer.render_grouped_stack_plot

    def capture(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(stack_renderer, "render_grouped_stack_plot", capture)

    render_stack(model, context)

    assert len(render_summary(summary, context).splitlines()) == 3
    assert captured["text_rows"] == 5
