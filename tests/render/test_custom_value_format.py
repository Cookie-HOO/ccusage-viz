from dataclasses import replace
from decimal import Decimal

import pytest

from ccusage_viz.custom_models import CustomUnit, LocalizedText
from ccusage_viz.i18n import load_translator
from ccusage_viz.render.custom_ranking_preparation import prepare_custom_ranking
from ccusage_viz.render.summary import format_custom_value

from .helpers import _grouped_ranking_projection, context


@pytest.mark.parametrize(
    "value,expected",
    (
        ("0", "0 tokens"),
        ("999", "999 tokens"),
        ("1000", "1K tokens"),
        ("12345", "12.35K tokens"),
        ("1234567", "1.23M tokens"),
        ("1234567890", "1.23B tokens"),
        ("-1234567", "-1.23M tokens"),
    ),
)
def test_dataset_values_default_to_compact(value, expected):
    unit = CustomUnit("token", LocalizedText("tokens", "Token"), "suffix", 0)
    assert format_custom_value(Decimal(value), unit, language="en") == expected


@pytest.mark.parametrize(
    ("value", "sum_format", "language", "expected"),
    (
        ("1988", "duration-minute", "zh", "33小时8分钟"),
        ("1988", "duration-minute", "en", "33 hours 8 minutes"),
        ("1988", "duration-second", "zh", "33分钟8秒"),
        ("3665", "duration-second", "en", "1 hour 1 minute"),
        ("0", "duration-minute", "en", "0 minutes"),
        ("0", "duration-second", "zh", "0秒"),
        ("45", "duration-second", "zh", "45秒"),
        ("-60", "duration-minute", "en", "-1 hour"),
        ("59.9", "duration-second", "en", "1 minute"),
        ("3599.9", "duration-second", "en", "1 hour"),
    ),
)
def test_custom_duration_value(value, sum_format, language, expected):
    unit = CustomUnit("minute", LocalizedText("minutes", "分钟"), "suffix", 0)
    assert (
        format_custom_value(Decimal(value), unit, language=language, sum_format=sum_format)
        == expected
    )


def test_compact_values_preserve_small_precision_and_unit_placement():
    unit = CustomUnit("currency", LocalizedText("$", "¥"), "prefix", 2)
    assert format_custom_value(Decimal("1.235"), unit, language="en") == "$1.24"
    assert format_custom_value(Decimal("1234567"), unit, language="zh") == "¥1.23M"
    unit = replace(unit, decimal_places=4)
    assert format_custom_value(Decimal("1234567"), unit, language="en") == "$1.2346M"


def test_ranking_other_uses_duration_fallback_but_source_display_is_preserved():
    from ccusage_viz.processing.custom_historical import CustomProjectedSeries

    projection = _grouped_ranking_projection()
    projection = replace(
        projection,
        groups=None,
        sum_format="duration-minute",
        series=(
            CustomProjectedSeries(
                "first",
                LocalizedText("First", "第一"),
                (Decimal("9000000"),),
                display=LocalizedText("9.0M source", "来源 9.0M"),
            ),
            CustomProjectedSeries(
                "other", LocalizedText("Other", "其他"), (Decimal("1234567"),), is_other=True
            ),
        ),
    )
    prepared = prepare_custom_ranking(projection, context())
    assert prepared.full_entries[0].display == "9.0M source"
    assert prepared.full_entries[1].display == "20576 hours 7 minutes"
    assert prepared.full_entries[1].current == Decimal("1234567")
    zh = prepare_custom_ranking(projection, replace(context(), translator=load_translator("zh")))
    assert zh.full_entries[0].display == "来源 9.0M"
    assert zh.full_entries[1].display == "20576小时7分钟"
