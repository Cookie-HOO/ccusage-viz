import pytest

from ccusage_viz.formatting import (
    clip_width,
    display_width,
    format_summary_tokens,
    format_tokens,
    truncate_width,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (999, "999"),
        (1_000, "1K"),
        (1_250, "1.2K"),
        (1_000_000, "1M"),
        (2_500_000_000, "2.5B"),
    ],
)
def test_decimal_token_formatting(value: int, expected: str) -> None:
    assert format_tokens(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (999, "999"),
        (1_000, "1.0000K"),
        (1_250, "1.2500K"),
        (21_400_000, "21.4000M"),
        (153_000_000, "153.0000M"),
        (2_500_000_000, "2.5000B"),
    ],
)
def test_summary_token_formatting_has_fixed_compact_precision(value: int, expected: str) -> None:
    assert format_summary_tokens(value) == expected


def test_unicode_width_and_truncation() -> None:
    assert display_width("项目a") == 5
    assert clip_width("项目abc", 5) == "项目a"
    assert truncate_width("项目abc", 5) == "项目…"


def test_width_clipping_preserves_ansi_sequences() -> None:
    styled = "\x1b[31m项目abc\x1b[0m"
    clipped = clip_width(styled, 5)
    assert clipped == "\x1b[31m项目a\x1b[0m"
    assert display_width(clipped) == 5
