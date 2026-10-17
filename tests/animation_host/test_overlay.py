from contextlib import nullcontext
from io import StringIO

import pytest

import ccusage_viz.animation_host.overlay_editor as overlay_editor_module
import ccusage_viz.animation_host.runtime as animate_module
from ccusage_viz.animation import (
    AnimationRenderer,
    animation_spec,
    new_animation_session,
)
from ccusage_viz.animation_host.overlay_editor import (
    _editor_line_end,
    _editor_line_start,
    _editor_next_word,
    _editor_previous_word,
    _editor_viewport,
    _overlay_editor_controls,
)
from ccusage_viz.animation_overlay import AnimationOverlayRuntime, OverlayConfig
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import AnimationLaunch, ProcessConfig, StandaloneHostConfig
from ccusage_viz.terminal import FramePainter, Terminal


def test_overlay_editor_viewport_keeps_cursor_visible_without_shifting_text() -> None:
    visible, start = _editor_viewport("ab界cd", 4, 4, cursor_visible=True)

    assert visible == "界c\x1b[7md\x1b[0m"
    assert start == 2
    assert display_width(visible) == 4

    visible, start = _editor_viewport("ab界cd", 3, 4, cursor_visible=True)
    assert visible == "b界\x1b[7mc\x1b[0m"
    assert start == 1
    assert display_width(visible) == 4

    hidden, _ = _editor_viewport("ab界cd", 3, 4, cursor_visible=False)
    assert hidden == "b界c"
    assert "▏" not in visible

def test_overlay_editor_viewport_marks_end_of_line_without_overflow() -> None:
    visible, start = _editor_viewport("abcd", 4, 4, cursor_visible=True)

    assert visible == "bcd\x1b[7m \x1b[0m"
    assert start == 1
    assert display_width(visible) == 4

@pytest.mark.parametrize(
    ("draft", "cursor", "previous", "next_word"),
    [
        ("alpha beta", 10, 6, 10),
        ("alpha beta", 7, 6, 10),
        ("alpha--beta", 11, 7, 11),
        ("alpha_beta", 10, 0, 10),
        ("alpha\nbeta", 10, 6, 10),
        ("", 0, 0, 0),
    ],
)
def test_overlay_editor_word_motions(
    draft: str, cursor: int, previous: int, next_word: int
) -> None:
    assert _editor_previous_word(draft, cursor) == previous
    assert _editor_next_word(draft, cursor) == next_word

def test_overlay_editor_line_motions_stay_on_current_physical_line() -> None:
    assert _editor_line_start("alpha\nbeta", 9) == 6
    assert _editor_line_end("alpha\nbeta", 7) == 10

def test_standalone_overlay_editor_ctrl_u_clears_active_draft(monkeypatch, translator) -> None:
    class RecordingPainter:
        def __init__(self) -> None:
            self.frames: list[tuple[str, ...]] = []

        def paint(self, frame) -> None:
            self.frames.append(frame.rows)

    overlay = AnimationOverlayRuntime(OverlayConfig(text="before"))
    painter = RecordingPainter()
    events = iter(
        (
            animate_module.KeyEvent("\x15"),
            animate_module.KeyEvent("x"),
            animate_module.KeyEvent("\r"),
        )
    )
    monkeypatch.setattr(overlay_editor_module, "_terminal", lambda _options: Terminal(100, 5, False, True))
    monkeypatch.setattr(overlay_editor_module, "read_event", lambda _decoder, _timeout: next(events))

    try:
        overlay_editor_module._run_overlay_editor(
            painter,
            overlay,
            object(),
            AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain")),
            translator,
        )
        assert overlay.config.text == "x"
        painted = "\n".join(row for frame in painter.frames for row in frame)
        assert "Ctrl-U clear" in painted
        assert translator.text("status.overlay_editor_cleared") in painted
        assert "NAV ·" in painted
        assert "DRAFT" in painted
        assert "COMPLETE" in painted
        assert "Ctrl-A home" in painted
        assert "Ctrl-B previous word" in painted
        assert "Ctrl-W next word" in painted
    finally:
        overlay.close()

def test_standalone_overlay_editor_ctrl_h_opens_help_and_del_deletes(
    monkeypatch, translator
) -> None:
    class RecordingPainter:
        def __init__(self) -> None:
            self.frames: list[tuple[str, ...]] = []

        def paint(self, frame) -> None:
            self.frames.append(frame.rows)

    overlay = AnimationOverlayRuntime(OverlayConfig(text="ab"))
    painter = RecordingPainter()
    events = iter(
        (
            animate_module.KeyEvent("\x08"),
            animate_module.KeyEvent("h"),
            animate_module.KeyEvent("\x7f"),
            animate_module.KeyEvent("h"),
            animate_module.KeyEvent("\r"),
        )
    )
    monkeypatch.setattr(overlay_editor_module, "_terminal", lambda _options: Terminal(120, 8, False, True))
    monkeypatch.setattr(animate_module, "_terminal", lambda _options: Terminal(120, 8, False, True))
    monkeypatch.setattr(overlay_editor_module, "read_event", lambda _decoder, _timeout: next(events))
    monkeypatch.setattr(animate_module, "read_event", lambda _decoder, _timeout: next(events))

    try:
        overlay_editor_module._run_overlay_editor(
            painter,
            overlay,
            object(),
            AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain")),
            translator,
        )
        assert overlay.config.text == "ah"
        painted = "\n".join(row for frame in painter.frames for row in frame)
        assert translator.text("status.tui_help_editor_title") in painted
        assert "TEXT MODE: edit literal content displayed directly" in painted
        assert "COMMAND MODE: edit the shell command whose stdout is displayed" in painted
        assert "NAVIGATION" in painted
        assert "DRAFT" in painted
        assert "COMPLETE" in painted
        assert "Animation overlay commands time out after 30 seconds." not in painted
        assert "Ctrl-H/Enter/Esc close" in painted
    finally:
        overlay.close()

def test_standalone_overlay_editor_word_motions_position_insertions(
    monkeypatch, translator
) -> None:
    overlay = AnimationOverlayRuntime(OverlayConfig(text="foo bar"))
    events = iter(
        (
            animate_module.KeyEvent("\x01"),
            animate_module.KeyEvent("\x17"),
            animate_module.KeyEvent("X"),
            animate_module.KeyEvent("\x02"),
            animate_module.KeyEvent("\x02"),
            animate_module.KeyEvent("Y"),
            animate_module.KeyEvent("\r"),
        )
    )
    monkeypatch.setattr(overlay_editor_module, "_terminal", lambda _options: Terminal(120, 6, False, True))
    monkeypatch.setattr(overlay_editor_module, "read_event", lambda _decoder, _timeout: next(events))

    try:
        overlay_editor_module._run_overlay_editor(
            type("Painter", (), {"paint": lambda *_args, **_kwargs: None})(),
            overlay,
            object(),
            AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain")),
            translator,
        )
        assert overlay.config.text == "Yfoo Xbar"
    finally:
        overlay.close()

def test_overlay_editor_controls_distinguish_standalone_and_dashboard() -> None:
    translator = load_translator("en")

    standalone = _overlay_editor_controls(translator, width=200, color=False)
    dashboard = _overlay_editor_controls(translator, width=200, color=False, dashboard=True)

    assert standalone[0].startswith("DRAFT ·")
    assert standalone[1].startswith("NAV ·")
    assert "Ctrl-B previous word" in standalone[1]
    assert "Ctrl-W next word" in standalone[1]
    assert standalone[2].startswith("COMPLETE ·")
    assert not any("OVERALL" in row for row in standalone)
    assert dashboard[:2] == standalone[:2]
    assert dashboard[2].startswith("OVERALL ·")
    assert "Ctrl-J / Ctrl-K pane height" in dashboard[2]

def test_standalone_help_shows_overlay_timeout_hint(
    monkeypatch, translator, animation_launch
) -> None:
    frames = []
    events = iter(("h", "\x03", "\x03"))

    monkeypatch.setattr(animate_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(
        animate_module, "read_adjustment_event", lambda _decoder, _timeout: next(events)
    )
    monkeypatch.setattr(
        animate_module,
        "read_event",
        lambda _decoder, _timeout: animate_module.KeyEvent(next(events)),
    )
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(100, 24, False, False)
    )
    monkeypatch.setattr(
        animate_module.FramePainter, "paint", lambda _self, frame, **_kwargs: frames.append(frame)
    )

    assert animate_module.run_animation(animation_launch, translator) == 0
    help_text = "\n".join(
        "\n".join(frame.rows) for frame in frames if "Animation help" in "\n".join(frame.rows)
    )
    assert "└─ Overlay commands time out after 30 seconds." in help_text

def test_standalone_animation_paints_text_overlay_in_final_frame(translator) -> None:
    stream = StringIO()
    overlay = AnimationOverlayRuntime(OverlayConfig(text="OVERLAY"))
    try:
        animate_module._paint_animation(
            FramePainter(stream),
            new_animation_session(animation_spec("rain"), theme="classic"),
            AnimationRenderer(),
            Terminal(80, 24, False, True),
            translator,
            now=1.0,
            overlay=overlay,
        )
    finally:
        overlay.close()

    output = stream.getvalue()
    assert "OVERLAY" in output
    assert output.startswith("\x1b[?2026h")
    assert output.endswith("\x1b[?2026l")
