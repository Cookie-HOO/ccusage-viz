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


def test_terminal_rejects_non_tty_and_small_size() -> None:
    with pytest.raises(UsageError, match="error.tty"):
        inspect_terminal("timeline", stream=Stream(False), size=os.terminal_size((100, 30)))
    with pytest.raises(UsageError) as caught:
        inspect_terminal("calendar", stream=Stream(True), size=os.terminal_size((71, 14)))
    assert caught.value.key == "error.terminal_size"
    assert caught.value.values["minimum_width"] == 72


def test_terminal_accepts_exact_minimum() -> None:
    terminal = inspect_terminal(
        "ranking", stream=Stream(True), size=os.terminal_size((60, 12)), no_color=True
    )
    assert (terminal.width, terminal.height, terminal.color) == (60, 12, False)


@pytest.mark.parametrize(("variable", "value"), [("NO_COLOR", "1"), ("TERM", "dumb")])
def test_terminal_environment_can_disable_color(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    terminal = inspect_terminal("timeline", stream=Stream(True), size=os.terminal_size((80, 24)))
    assert terminal.color is False
