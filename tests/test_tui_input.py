from io import StringIO

import pytest

import ccusage_viz.tui_input as tui_input


def test_suspended_mouse_reporting_restores_modes() -> None:
    stream = StringIO()
    original = tui_input.sys.stdout
    tui_input.sys.stdout = stream
    try:
        with tui_input.suspended_mouse_reporting():
            assert stream.getvalue() == "\x1b[?1000l\x1b[?1006l"
    finally:
        tui_input.sys.stdout = original

    assert stream.getvalue() == "\x1b[?1000l\x1b[?1006l\x1b[?1000h\x1b[?1006h"


def test_suspended_mouse_reporting_restores_modes_after_error() -> None:
    stream = StringIO()
    original = tui_input.sys.stdout
    tui_input.sys.stdout = stream
    try:
        with (
            pytest.raises(RuntimeError, match="selection failed"),
            tui_input.suspended_mouse_reporting(),
        ):
            raise RuntimeError("selection failed")
    finally:
        tui_input.sys.stdout = original

    assert stream.getvalue().endswith("\x1b[?1000h\x1b[?1006h")
