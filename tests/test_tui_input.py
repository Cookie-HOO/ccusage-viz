from io import StringIO

import pytest

import ccusage_viz.tui_input as tui_input_module
from ccusage_viz.tui_input import (
    InputDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
    WheelEvent,
)


def test_tui_input_decodes_keys_and_fragmented_mouse_press() -> None:
    decoder = InputDecoder()
    decoder.feed("r")
    assert decoder.next(now=0.0) == KeyEvent("r")
    decoder.feed("\x1b[<0;20")
    assert decoder.next() is None
    decoder.feed(";5M")
    assert decoder.next() == MouseEvent(0, 20, 5, True, 0)


def test_tui_input_preserves_control_keys() -> None:
    decoder = InputDecoder()
    decoder.feed("\r\n\x0b\x15\x19")

    assert decoder.next() == KeyEvent("\r")
    assert decoder.next() == KeyEvent("\n")
    assert decoder.next() == KeyEvent("\x0b")
    assert decoder.next() == KeyEvent("\x15")
    assert decoder.next() == KeyEvent("\x19")


def test_tui_input_decodes_trackpad_wheel_reports() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<64;20;5M\x1b[<65;20;5M")

    assert decoder.next() == WheelEvent(-1, 20, 5)
    assert decoder.next() == WheelEvent(1, 20, 5)
    assert decoder.buffer == ""


@pytest.mark.parametrize("button", (66, 67, 96, 97, 128, 129))
def test_tui_input_does_not_scroll_horizontal_motion_or_extended_buttons(button: int) -> None:
    decoder = InputDecoder()
    decoder.feed(f"\x1b[<{button};20;5M")
    assert not isinstance(decoder.next(), WheelEvent)


def test_tui_input_wheel_fragment_modifiers_and_release() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<85;20;")
    assert decoder.next(now=0) is None
    decoder.feed("5M\x1b[<65;20;5m")
    assert decoder.next(now=0.01) == WheelEvent(1, 20, 5, 20)
    assert decoder.next(now=0.01) is None


def test_tui_input_drains_wheels_without_pacing_or_consuming_click_key_or_paste() -> None:
    for tail in ("q", "\x1b[<0;20;5M", "\x1b[200~paste\x1b[201~", "\x1b[<65;20;"):
        decoder = InputDecoder()
        decoder.feed("\x1b[<65;20;5M" * 100 + tail)
        assert decoder.next(now=0) == WheelEvent(1, 20, 5)
        assert list(decoder.drain_wheel()) == [WheelEvent(1, 20, 5)] * 99
        assert decoder.buffer == tail


def test_tui_input_preserves_wheel_direction_order() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<65;20;5M\x1b[<64;20;5M\x1b[<65;60;5M")
    assert list(decoder.drain_wheel()) == [
        WheelEvent(1, 20, 5),
        WheelEvent(-1, 20, 5),
        WheelEvent(1, 60, 5),
    ]


def test_tui_input_decodes_bracketed_paste_as_one_event() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[200~echo one\n\x1b\x03\x1b[201~")

    assert decoder.next() == PasteEvent("echo one\n\x1b\x03")
    assert decoder.buffer == ""


def test_tui_input_waits_for_fragmented_bracketed_paste() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[200~echo")
    assert decoder.next() is None

    decoder.feed(" two\x1b[201~")
    assert decoder.next() == PasteEvent("echo two")


def test_tui_input_times_out_incomplete_mouse_report_and_recovers() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<0;20")

    assert decoder.next(now=1.0) is None
    assert decoder.next(now=1.11) is None

    decoder.feed("r")
    assert decoder.next(now=1.11) == KeyEvent("r")


@pytest.mark.parametrize("malformed", ("\x1b[<0;;3M", "\x1b[<0;7;3;M"))
def test_tui_input_recovers_after_malformed_mouse_report(malformed: str) -> None:
    decoder = InputDecoder()
    decoder.feed(malformed + "\x1b[<0;7;3M")

    assert decoder.next() == MouseEvent(0, 7, 3, True, 0)
    assert decoder.buffer == ""


def test_tui_input_keeps_ordinary_key_after_malformed_mouse_report() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<0;;3Mq")

    assert decoder.next() == KeyEvent("q")


def test_tui_input_mode_disables_mouse_and_restores_terminal_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios
    import tty

    class Stdin:
        def isatty(self) -> bool:
            return True

        def fileno(self) -> int:
            return 7

    previous = [termios.ICRNL | termios.IXON, 0, 0, termios.ISIG, 0, 0, 0]
    attributes = list(previous)
    output = StringIO()
    tcset_calls: list[tuple[object, ...]] = []
    setcbreak_fds: list[int] = []
    tcget_calls = 0

    def tcgetattr(_descriptor: int) -> list[int]:
        nonlocal tcget_calls
        tcget_calls += 1
        return previous if tcget_calls == 1 else attributes

    monkeypatch.setattr(tui_input_module.sys, "stdin", Stdin())
    monkeypatch.setattr(tui_input_module.sys, "stdout", output)
    monkeypatch.setattr(tui_input_module.os, "name", "posix")
    monkeypatch.setattr(termios, "tcgetattr", tcgetattr)
    monkeypatch.setattr(termios, "tcsetattr", lambda *args: tcset_calls.append(args))
    monkeypatch.setattr(tty, "setcbreak", lambda descriptor: setcbreak_fds.append(descriptor))

    with (
        pytest.raises(RuntimeError, match="body failure"),
        tui_input_module.tui_input_mode() as decoder,
    ):
        assert isinstance(decoder, InputDecoder)
        raise RuntimeError("body failure")

    assert output.getvalue() == tui_input_module._MOUSE_ENABLE + tui_input_module._MOUSE_DISABLE
    assert setcbreak_fds == [7]
    assert tcset_calls[0][0:2] == (7, termios.TCSADRAIN)
    assert tcset_calls[0][2][0] == previous[0] & ~(termios.ICRNL | termios.IXON)
    assert tcset_calls[0][2][3] == previous[3] & ~termios.ISIG
    assert tcset_calls[-1] == (7, termios.TCSADRAIN, previous)
