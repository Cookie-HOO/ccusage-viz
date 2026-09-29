import pytest

from ccusage_viz.formatting import (
    clip_width,
    display_width,
    format_summary_tokens,
    format_tokens,
    slice_width,
    truncate_width,
    wrap_width,
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
        (1_000, "1K"),
        (1_250, "1.25K"),
        (21_400_000, "21.4M"),
        (153_000_000, "153M"),
        (2_500_000_000, "2.5B"),
    ],
)
def test_summary_token_formatting_has_at_most_two_decimals(value: int, expected: str) -> None:
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


def test_slice_width_obeys_display_cell_boundaries_for_wide_and_ansi_text() -> None:
    value = "ab界cd"

    assert slice_width(value, 2, 2) == "界"
    assert slice_width(value, 3, 3) == "cd"
    assert slice_width(value, 2, 1) == ""
    assert slice_width("\x1b[31mab界cd\x1b[0m", 3, 3) == "\x1b[31mcd\x1b[0m"
    assert display_width(slice_width(value, 3, 3)) == 2


def test_wrap_width_preserves_word_boundaries_and_wide_character_widths() -> None:
    assert wrap_width("one two three", 7) == ("one two", "three")
    assert wrap_width("项目项目项目", 4) == ("项目", "项目", "项目")
    assert all(display_width(row) <= 4 for row in wrap_width("项目项目项目", 4))
