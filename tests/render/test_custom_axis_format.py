from dataclasses import replace
from decimal import Decimal

import pytest

from ccusage_viz.i18n import load_translator
from ccusage_viz.render.base import RenderContext
from ccusage_viz.render.custom import _custom_y_tick_spec, render_custom_timeline
from ccusage_viz.render.summary import format_custom_value

from .test_custom_timeline_parity import router_projection


@pytest.mark.parametrize("unit_id", ("token", "bytes", "requests", "arbitrary"))
@pytest.mark.parametrize("places", (0, 2, 3))
def test_number_axis_reuses_ranking_formatter_without_unit(unit_id, places):
    projection = router_projection(unit_id, places)
    context = RenderContext(80, 16, load_translator("en"), color=False)
    positions, labels = _custom_y_tick_spec(list(projection.series[0].values), projection, context)
    assert labels == [
        format_custom_value(value, projection.unit, language="en", include_unit=False)
        for value in positions
    ]
    assert "1.2B" in labels
    assert all(unit_id not in label for label in labels)


@pytest.mark.parametrize("language", ("en", "zh"))
@pytest.mark.parametrize("sum_format", ("duration-minute", "duration-second"))
def test_duration_axis_obeys_metric_format(language, sum_format):
    projection = replace(router_projection("arbitrary", 2, (60, 120)), sum_format=sum_format)
    context = RenderContext(80, 16, load_translator(language), color=False)
    positions, labels = _custom_y_tick_spec(list(projection.series[0].values), projection, context)
    assert labels == [
        format_custom_value(value, projection.unit, language=language, sum_format=sum_format)
        for value in positions
    ]
    expected_unit = (
        ("小时" if language == "zh" else "hours")
        if sum_format == "duration-minute"
        else ("分钟" if language == "zh" else "minutes")
    )
    assert expected_unit in labels[-1]
    output = render_custom_timeline(projection, context)
    assert labels[-1] in output
    assert "09-01" in output and "09-02" in output


def test_axis_preserves_decimal_tick_positions_and_half_up_rounding():
    projection = router_projection("arbitrary", 2, ("1.25", "2.50"))
    positions, labels = _custom_y_tick_spec(
        list(projection.series[0].values),
        projection,
        RenderContext(80, 16, load_translator("en"), color=False),
    )
    assert positions[1] == Decimal("0.625")
    assert labels[1] == "0.63"
