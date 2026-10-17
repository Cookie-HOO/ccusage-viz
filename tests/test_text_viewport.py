from ccusage_viz.formatting import display_width
from ccusage_viz.text_viewport import (
    next_text_offset,
    render_text_viewport,
    text_viewport_overflows,
    wrap_text_rows,
)


def test_text_viewport_moves_and_clamps_at_both_boundaries() -> None:
    text = "\n".join(f"line {number}" for number in range(5))

    viewport = render_text_viewport(text, offset=0, visible_rows=2)
    assert viewport.body == "line 0\nline 1"
    assert next_text_offset("\x1b[A", offset=0, line_count=5, visible_rows=2) == 0
    assert next_text_offset("\x1b[B", offset=0, line_count=5, visible_rows=2) == 1
    assert next_text_offset("h", offset=2, line_count=5, visible_rows=2) == 0
    assert next_text_offset("\x1b[H", offset=2, line_count=5, visible_rows=2) == 0
    assert next_text_offset("e", offset=0, line_count=5, visible_rows=2) == 3
    assert next_text_offset("H", offset=0, line_count=5, visible_rows=2) is None
    assert next_text_offset("\x1b[B", offset=3, line_count=5, visible_rows=2) == 3


def test_text_viewport_clamps_stale_offsets_and_handles_empty_viewports() -> None:
    viewport = render_text_viewport("one\ntwo", offset=12, visible_rows=1)
    assert viewport.offset == 1
    assert viewport.body == "two"

    empty = render_text_viewport("one\ntwo", offset=12, visible_rows=0)
    assert empty.offset == 2
    assert empty.body == ""

    short = render_text_viewport("one", offset=4, visible_rows=3)
    assert short.offset == 0
    assert short.body == "one"


def test_text_viewport_overflow_uses_visible_row_count() -> None:
    assert text_viewport_overflows(line_count=3, visible_rows=2)
    assert not text_viewport_overflows(line_count=2, visible_rows=2)
    assert not text_viewport_overflows(line_count=1, visible_rows=2)
    assert text_viewport_overflows(line_count=1, visible_rows=0)


def test_wrap_text_rows_preserves_paragraphs_and_display_width() -> None:
    rows = wrap_text_rows("first paragraph\n\n中文错误详情 token-without-break", width=8)

    assert rows[0] == "first pa"
    assert "" in rows
    assert all(display_width(row) <= 8 for row in rows)


def test_text_viewport_accepts_pre_wrapped_rows() -> None:
    rows = wrap_text_rows("long-error-token-without-whitespace", width=6)

    viewport = render_text_viewport(rows, offset=1, visible_rows=2)

    assert viewport.line_count == len(rows)
    assert viewport.body == "\n".join(rows[1:3])
