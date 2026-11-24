from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ccusage_viz.chart_models import Series, TimelineModel
from ccusage_viz.core.time import DateRange
from ccusage_viz.custom_models import (
    CustomDataset,
    CustomPresentationDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.formatting import strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CustomChartConfig, CustomCommandSource
from ccusage_viz.processing.custom_historical import CustomChartProjection, CustomProjectedSeries
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import render_custom_stack, render_custom_timeline
from ccusage_viz.render.palette import categorical_colors, get_color_scheme
from ccusage_viz.render.timeline import render_timeline

from .helpers import usage


def router_projection(unit_id="token", decimal_places=0, values=(903375959, 1200000000)):
    days = (date(2026, 9, 1), date(2026, 9, 2))
    unit = CustomUnit(unit_id, LocalizedText(unit_id, unit_id), "suffix", decimal_places)
    interval = DateRange(*days)
    return CustomChartProjection(
        "timeline",
        days,
        (
            CustomProjectedSeries(
                "total", LocalizedText("Total", "总计"), tuple(Decimal(v) for v in values)
            ),
        ),
        unit,
        interval,
        "day",
        CustomChartConfig("timeline", CustomCommandSource("router", ("router-dataset",)), interval),
        CustomPresentationDescriptor(
            CustomDataset(
                LocalizedText("Router Token Count", "Router Token 数"), LocalizedText("", ""), unit
            ),
            {},
        ),
    )


@pytest.mark.parametrize("unit_id", ("token", "tokens", "count"))
@pytest.mark.parametrize("native_key", ("total", "Total", ("total",)))
@pytest.mark.parametrize("theme", ("classic", "vivid", "mono"))
def test_custom_count_timeline_matches_native_axes_and_total_color(unit_id, native_key, theme):
    projection = router_projection(unit_id)
    context = RenderContext(80, 16, load_translator("zh"), color_scheme=theme)
    native = render_timeline(
        TimelineModel(
            projection.days,
            (
                Series(
                    native_key, "Total", tuple(usage(int(v)) for v in projection.series[0].values)
                ),
            ),
        ),
        context,
    )
    custom = render_custom_timeline(projection, context)
    # Source title differs intentionally; every plot row, including axes/colors, agrees.
    assert custom.splitlines()[1:] == native.splitlines()[1:]
    assert "Router Token 数" in strip_ansi(custom.splitlines()[0])
    assert "1.2B" in strip_ansi(custom)
    assert "903375959" not in strip_ansi(custom)
    assert "09-01" in custom and "09-02" in custom
    assert f"\x1b[38;5;{get_color_scheme(theme).total}m" in custom
    assert len(custom.splitlines()) == context.height


@pytest.mark.parametrize(
    "unit_id,places,values,expected",
    (
        ("percent", 2, ("1.25", "2.50"), "0.63"),
        ("ms", 3, ("1.25", "2.50"), "0.625"),
        ("currency", 2, ("1.25", "2.50"), "0.63"),
        ("count", 2, ("1.25", "2.50"), "0.63"),
        ("arbitrary", 0, (1000000, 2000000), "2M"),
    ),
)
def test_custom_non_count_axes_preserve_declared_precision(unit_id, places, values, expected):
    output = render_custom_timeline(
        router_projection(unit_id, places, values),
        RenderContext(80, 16, load_translator("en"), color=False),
    )
    assert expected in output


def test_custom_single_total_stack_uses_shared_semantic_color():
    projection = router_projection()
    projection = replace(projection, kind="stack", config=replace(projection.config, kind="stack"))
    output = render_custom_stack(projection, RenderContext(80, 16, load_translator("en")))
    assert "1.2B" in strip_ansi(output)
    assert f"\x1b[38;5;{get_color_scheme('classic').total}m" in output


def test_non_total_timeline_keeps_stable_categorical_color():
    projection = router_projection()
    projection = replace(projection, series=(replace(projection.series[0], id="model-a"),))
    output = render_custom_timeline(projection, RenderContext(80, 16, load_translator("en")))
    color = categorical_colors(("model-a",))["model-a"]
    assert f"\x1b[38;5;{color}m" in output
