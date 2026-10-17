



from dataclasses import replace

import pytest

from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.monitor_distribution import render_monitor_distribution

from .helpers import _distribution_model, context


def test_distribution_renderer_keeps_observation_metadata_outside_the_chart() -> None:
    output = render_monitor_distribution(_distribution_model(), context(True))

    assert "Tokens · Cumulative bars · 1d window" in output
    assert "Today" not in output.splitlines()[0]
    assert "Hourly" not in output.splitlines()[0]
    assert "observed from" not in output
    assert "not observed" in output
    assert "#" in output
    assert "09" in output and "11" in output
    assert "09:00" not in output and "11:00" not in output

def test_distribution_renderer_centers_hour_labels_on_bar_columns() -> None:
    model = _distribution_model()
    output = render_monitor_distribution(
        model,
        RenderContext(80, 16, load_translator("en"), color=False, ascii=True),
    )
    lines = output.splitlines()
    second_bar = next(line.index("+") for line in lines[2:-2] if "+" in line)
    second_tick = lines[-1].index("10")

    assert second_tick + 1 == second_bar + 1

def test_distribution_renderer_keeps_half_hour_tick_precision() -> None:
    model = replace(_distribution_model(), granularity="half-hour")
    output = render_monitor_distribution(model, context(True))

    assert "09:00" in output and "11:00" in output

def test_distribution_renderer_uses_available_panel_height() -> None:
    output = render_monitor_distribution(
        _distribution_model(),
        RenderContext(80, 20, load_translator("en"), color=False, ascii=True),
    )

    assert len(output.splitlines()) == 20

@pytest.mark.parametrize(
    ("legend", "expected", "missing"),
    [
        ("below-title", "Alpha", "Alpha 60"),
        ("inside", "Alpha", "Alpha 60"),
        ("values", "Alpha 60", "not observed"),
        ("hidden", "", "Alpha"),
    ],
)
def test_distribution_renderer_honors_every_monitor_legend_mode(
    legend: str, expected: str, missing: str
) -> None:
    output = render_monitor_distribution(
        _distribution_model(),
        RenderContext(
            80, 16, load_translator("en"), color=False, ascii=True, legend_position=legend
        ),
    )

    assert expected in output
    if missing:
        assert missing not in output

def test_distribution_renderer_ascii_no_color_is_safe_and_width_bounded() -> None:
    output = render_monitor_distribution(
        _distribution_model(),
        RenderContext(40, 16, load_translator("en"), color=False, ascii=True),
    )

    assert "\x1b[" not in output
    assert all(display_width(line) <= 40 for line in output.splitlines())
    assert "▒" not in output and "░" not in output and "█" not in output
