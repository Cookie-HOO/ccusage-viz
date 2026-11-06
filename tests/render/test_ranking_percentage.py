from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.chart_models import RankingEntry, RankingModel
from ccusage_viz.core.time import DateRange
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    RankingConfig,
    adjust_chart,
)
from ccusage_viz.presets.values import (
    DashboardPresetValidationError,
    _presentation_parse,
    _presentation_wire,
)
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.ranking import render_ranking
from ccusage_viz.tui.adjustments import _adjustment_key_supported

from .helpers import usage


@pytest.mark.parametrize("kind", ("ranking", "timeline"))
@pytest.mark.parametrize("visible", (None, True, False))
def test_percentage_presentation_preset_roundtrip(kind, visible):
    presentation = ChartPresentation(
        style="dot" if kind == "ranking" else "linear", show_percentage=visible
    )
    assert _presentation_parse(_presentation_wire(presentation), kind) == presentation


def test_percentage_preset_rejects_non_boolean():
    wire = _presentation_wire(ChartPresentation())
    wire["show_percentage"] = "false"
    with pytest.raises(DashboardPresetValidationError):
        _presentation_parse(wire, "ranking")


def test_native_ranking_percentage_key_is_presentation_only():
    config = RankingConfig("ranking", DateRange(date(2026, 1, 1), date(2026, 1, 2)))
    assert _adjustment_key_supported("ranking", "advanced", "%", chart=config)
    hidden = adjust_chart(config, "%")
    assert hidden.presentation.show_percentage is False
    assert replace(hidden, presentation=config.presentation) == config
    assert adjust_chart(hidden, "%").presentation.show_percentage is True


@pytest.mark.parametrize("visible", (True, False))
@pytest.mark.parametrize("style", ("bars", "list"))
def test_native_ranking_percentage_render(visible, style):
    model = RankingModel(
        (
            RankingEntry(("project", "a"), "Alpha", usage(600)),
            RankingEntry(("project", "b"), "Beta", usage(400)),
        ),
        DateRange(date(2026, 1, 1), date(2026, 1, 2)),
    )
    context = RenderContext(
        100,
        24,
        load_translator("en"),
        color=False,
        style=style,
        density="full",
        show_percentage=visible,
    )
    rendered = render_ranking(model, context)
    assert ("60.0%" in rendered) == visible
    assert "600" in rendered
