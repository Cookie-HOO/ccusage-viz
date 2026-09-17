import os
from io import StringIO

import pytest

from ccusage_viz.errors import UsageError
from ccusage_viz.terminal import InteractiveScreen, inspect_terminal


class Stream(StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_interactive_screen_finishes_once_after_paint() -> None:
    stream = Stream(True)
    screen = InteractiveScreen(stream)

    screen.finish()
    assert stream.getvalue() == ""

    screen.paint("chart", "status", "controls", height=4)
    screen.finish()
    screen.finish()

    assert stream.getvalue() == "\x1b[H\x1b[2Jstatus\nchart\n\ncontrols\n"


def test_interactive_screen_places_notices_directly_above_controls() -> None:
    stream = Stream(True)
    screen = InteractiveScreen(stream)

    screen.paint("chart", "status", "controls", ("warning",), height=6)

    assert stream.getvalue() == "\x1b[H\x1b[2Jstatus\nchart\n\n\nwarning\ncontrols"


def test_interactive_screen_force_repaints_and_preserves_incremental_updates() -> None:
    stream = Stream(True)
    screen = InteractiveScreen(stream)

    screen.paint("chart", "status", "controls", height=4)
    stream.seek(0)
    stream.truncate(0)

    screen.paint("chart", "status", "controls", height=4)
    assert stream.getvalue() == ""

    screen.paint("chart", "status", "controls", height=4, force=True)
    assert stream.getvalue() == "\x1b[H\x1b[2Jstatus\nchart\n\ncontrols"

    stream.seek(0)
    stream.truncate(0)
    screen.paint("updated", "status", "controls", height=4)
    assert stream.getvalue() == "\x1b[2;1H\x1b[2Kupdated"


def test_interactive_screen_can_omit_status_row() -> None:
    stream = Stream(True)
    screen = InteractiveScreen(stream)

    screen.paint("chart\nextra", None, ("one", "two", "three"), height=5)

    assert stream.getvalue() == "\x1b[H\x1b[2Jchart\nextra\none\ntwo\nthree"


def test_interactive_screen_reserves_each_control_row() -> None:
    stream = Stream(True)
    screen = InteractiveScreen(stream)

    screen.paint(
        "chart\nextra",
        "status",
        ("pane controls", "layout controls", "appearance controls"),
        height=5,
    )

    assert stream.getvalue() == (
        "\x1b[H\x1b[2Jstatus\nchart\npane controls\nlayout controls\nappearance controls"
    )


def test_terminal_rejects_non_tty() -> None:
    with pytest.raises(UsageError, match="error.tty"):
        inspect_terminal("timeline", stream=Stream(False), size=os.terminal_size((100, 30)))


@pytest.mark.parametrize("command", ("timeline", "calendar", "stack", "ranking"))
def test_chart_commands_accept_58_by_16_and_reject_either_smaller_dimension(
    command: str,
) -> None:
    terminal = inspect_terminal(
        command, stream=Stream(True), size=os.terminal_size((58, 16)), no_color=True
    )
    assert (terminal.width, terminal.height, terminal.color) == (58, 16, False)

    for size in ((57, 16), (58, 15)):
        with pytest.raises(UsageError) as caught:
            inspect_terminal(command, stream=Stream(True), size=os.terminal_size(size))
        assert caught.value.key == "error.terminal_size"
        assert caught.value.values["minimum_width"] == 58
        assert caught.value.values["minimum_height"] == 16


def test_monitor_accepts_40_by_10_and_rejects_either_smaller_dimension() -> None:
    terminal = inspect_terminal(
        "monitor", stream=Stream(True), size=os.terminal_size((40, 10)), no_color=True
    )
    assert (terminal.width, terminal.height) == (40, 10)

    for size in ((39, 10), (40, 9)):
        with pytest.raises(UsageError) as caught:
            inspect_terminal("monitor", stream=Stream(True), size=os.terminal_size(size))
        assert caught.value.key == "error.terminal_size"
        assert caught.value.values["minimum_width"] == 40
        assert caught.value.values["minimum_height"] == 10


def test_no_color_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    terminal = inspect_terminal("timeline", stream=Stream(True), size=os.terminal_size((80, 24)))
    assert terminal.color is True


def test_dumb_terminal_disables_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "dumb")
    terminal = inspect_terminal("timeline", stream=Stream(True), size=os.terminal_size((80, 24)))
    assert terminal.color is False
