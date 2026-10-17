from io import StringIO

import pytest

from ccusage_viz.terminal import Frame, FramePainter


def repaint(old: str, new: str) -> str:
    stream = StringIO()
    painter = FramePainter(stream)
    painter.paint(Frame((old,)))
    stream.seek(0)
    stream.truncate()
    painter.paint(Frame((new,)))
    return stream.getvalue()


def test_parallel_data_pane_is_not_written() -> None:
    assert repaint("clock 12:00 | data 123", "clock 12:01 | data 123") == "\x1b[1;11H1"


def test_disjoint_changes_do_not_write_middle_pane() -> None:
    assert repaint("a | static | b", "c | static | d") == "\x1b[1;1Hc\x1b[1;14Hd"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("中文 | data", "中好 | data", "\x1b[1;3H好"),
        ("中 | data", "ab | data", "\x1b[1;1Hab"),
        ("ab | data", "中 | data", "\x1b[1;1H中"),
        ("e\u0301 | data", "e\u0300 | data", "\x1b[1;1He\u0300"),
        ("long", "lo", "\x1b[1;3H  "),
    ],
)
def test_glyph_boundaries_and_erasure(old: str, new: str, expected: str) -> None:
    assert repaint(old, new) == expected


def test_style_only_change_is_painted_and_reset() -> None:
    output = repaint("\x1b[31ma\x1b[0m | data", "\x1b[32ma\x1b[0m | data")
    assert "data" not in output
    assert output == "\x1b[1;1H\x1b[32ma\x1b[0m"


def test_multiple_sgr_attributes_are_preserved() -> None:
    output = repaint("\x1b[31m\x1b[1ma\x1b[0m | data", "\x1b[31m\x1b[1mb\x1b[0m | data")
    assert output == "\x1b[1;1H\x1b[31m\x1b[1mb\x1b[0m"


def test_hyperlink_is_closed_after_partial_output() -> None:
    opening = "\x1b]8;;https://example.com\x1b\\"
    closing = "\x1b]8;;\x1b\\"
    output = repaint(f"{opening}abc{closing} | data", f"{opening}axc{closing} | data")
    assert output == f"\x1b[1;2H{opening}x{closing}"


def test_unknown_controls_fall_back_to_row_replacement() -> None:
    assert repaint("a", "\x1b[2Cb") == "\x1b[1;1H\x1b[2K\x1b[2Cb"
