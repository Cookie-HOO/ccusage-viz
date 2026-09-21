import os
from io import StringIO

import pytest

from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.terminal import FramePainter, compose_frame, inspect_terminal
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows


class Stream(StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_frame_painter_finishes_once_after_paint() -> None:
    stream = Stream(True)
    painter = FramePainter(stream)

    painter.finish()
    assert stream.getvalue() == ""

    painter.paint(compose_frame("chart", "status", "controls", height=4))
    painter.finish()
    painter.finish()

    assert stream.getvalue() == "\x1b[H\x1b[2Jstatus\nchart\n\ncontrols\n"


def test_compose_frame_places_notices_directly_above_controls() -> None:
    frame = compose_frame("chart", "status", "controls", ("warning",), height=6)

    assert frame.rows == ("status", "chart", "", "", "warning", "controls")


def test_frame_painter_force_repaints_and_preserves_incremental_updates() -> None:
    stream = Stream(True)
    painter = FramePainter(stream)
    frame = compose_frame("chart", "status", "controls", height=4)

    painter.paint(frame)
    stream.seek(0)
    stream.truncate(0)

    painter.paint(frame)
    assert stream.getvalue() == ""

    painter.paint(frame, force=True)
    assert stream.getvalue() == "\x1b[H\x1b[2Jstatus\nchart\n\ncontrols"

    stream.seek(0)
    stream.truncate(0)
    painter.paint(compose_frame("updated", "status", "controls", height=4))
    assert stream.getvalue() == "\x1b[2;1H\x1b[2Kupdated"


def test_frame_painter_updates_only_changed_animation_rows() -> None:
    stream = Stream(True)
    painter = FramePainter(stream)

    painter.paint(compose_frame("idle\nscene", "status", "controls", height=5))
    stream.seek(0)
    stream.truncate(0)
    painter.paint(compose_frame("active\nscene", "status", "controls", height=5))

    assert stream.getvalue() == "\x1b[2;1H\x1b[2Kactive"


def test_compose_frame_can_omit_status_row() -> None:
    frame = compose_frame("chart\nextra", None, ("one", "two", "three"), height=5)

    assert frame.rows == ("chart", "extra", "one", "two", "three")


def test_compose_frame_reserves_each_control_row() -> None:
    frame = compose_frame(
        "chart\nextra",
        "status",
        ("pane controls", "layout controls", "appearance controls"),
        height=5,
    )

    assert frame.rows == (
        "status",
        "chart",
        "pane controls",
        "layout controls",
        "appearance controls",
    )


def test_adjustment_rows_keep_semantic_actions_at_wide_width() -> None:
    rows = adjustment_rows(
        "Current status: running · density compact",
        "Quick adjustment",
        (
            AdjustmentAction("d", "density", 0),
            AdjustmentAction("t/T", "theme", 1),
            AdjustmentAction("s", "style", 2),
        ),
        width=120,
        color=False,
        switch_action="a Advanced",
        finish_action="Enter/Esc finish",
    )

    assert rows == (
        "Current status: running · density compact",
        "Quick adjustment: d density · t/T theme · s style · a Advanced · Enter/Esc finish",
    )


def test_adjustment_rows_omit_whole_low_priority_actions() -> None:
    rows = adjustment_rows(
        "当前状态：运行中 · 密度 compact",
        "Quick 调整",
        (
            AdjustmentAction("d", "密度", 0),
            AdjustmentAction("t/T", "主题", 1),
            AdjustmentAction("s", "样式", 2),
            AdjustmentAction("b", "分组", 3),
        ),
        width=58,
        color=False,
        switch_action="a 高级",
        finish_action="Enter/Esc 完成",
    )

    assert display_width(rows[1]) <= 58
    assert rows[1].startswith("Quick 调整：")
    assert "a 高级" in rows[1]
    assert "Enter/Esc 完成" in rows[1]
    assert "…(+" in rows[1]
    assert not any(fragment in rows[1] for fragment in ("s 样", "b 分"))


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


def test_dumb_terminal_requires_explicit_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "dumb")
    with pytest.raises(UsageError, match="error.arguments"):
        inspect_terminal("timeline", stream=Stream(True), size=os.terminal_size((80, 24)))

    terminal = inspect_terminal(
        "timeline", stream=Stream(True), size=os.terminal_size((80, 24)), ascii=True
    )
    assert terminal.color is True
