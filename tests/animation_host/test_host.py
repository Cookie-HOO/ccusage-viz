from contextlib import nullcontext

import pytest

import ccusage_viz.animation_host.runtime as animate_module
from ccusage_viz.animation import (
    animation_spec,
    new_animation_session,
)
from ccusage_viz.animation_host.runtime import _wait_seconds
from ccusage_viz.options import AnimationLaunch, StandaloneHostConfig
from ccusage_viz.terminal import Terminal


@pytest.mark.parametrize("exit_key", ("q", "\x1b", "\x03"))
def test_standalone_host_exits_for_owned_exit_keys(
    monkeypatch, translator, animation_launch, exit_key
) -> None:
    finished = []
    monkeypatch.setattr(animate_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(
        animate_module, "read_adjustment_event", lambda _decoder, _timeout: exit_key
    )
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(80, 24, False, False)
    )
    monkeypatch.setattr(animate_module.FramePainter, "finish", lambda _self: finished.append(True))

    assert animate_module.run_animation(animation_launch, translator) == 0
    assert finished == [True]


def test_standalone_host_ignores_space(monkeypatch, translator, animation_launch) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    events = iter((" ", "q"))

    monkeypatch.setattr(animate_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(
        animate_module, "read_adjustment_event", lambda _decoder, _timeout: next(events)
    )
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(80, 24, False, False)
    )

    monkeypatch.setattr(animate_module, "_paint_animation", lambda *_args, **_kwargs: None)

    assert animate_module.run_animation(animation_launch, translator) == 0
    assert session.playback_requested
    assert session.traversal_frozen_at is None
    assert not hasattr(session, "host_paused")


def test_standalone_host_adjustment_handles_quick_controls(
    monkeypatch, translator, animation_launch
) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    events = iter(("m", "t", "T", "s", "S", "\r", "q"))

    monkeypatch.setattr(animate_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(
        animate_module, "read_adjustment_event", lambda _decoder, _timeout: next(events)
    )
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(80, 24, False, False)
    )
    monkeypatch.setattr(animate_module, "_paint_animation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(animate_module.FramePainter, "paint", lambda *_args, **_kwargs: None)

    assert animate_module.run_animation(animation_launch, translator) == 0
    assert session.theme == "classic"
    assert session.spec.style == "rain"


def test_standalone_host_advanced_adjustment_ignores_animation_controls(
    monkeypatch, translator, animation_launch
) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    events = iter(("m", "a", "t", "s", "\r", "q"))

    monkeypatch.setattr(animate_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(
        animate_module, "read_adjustment_event", lambda _decoder, _timeout: next(events)
    )
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(80, 24, False, False)
    )
    monkeypatch.setattr(animate_module, "_paint_animation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(animate_module.FramePainter, "paint", lambda *_args, **_kwargs: None)

    assert animate_module.run_animation(animation_launch, translator) == 0
    assert session.theme == "classic"
    assert session.spec.style == "rain"


def test_terminal_keeps_color_when_ascii_is_requested(monkeypatch, animation_launch) -> None:
    options = AnimationLaunch(
        animation_launch.process,
        StandaloneHostConfig(ascii=True),
        animation_launch.animation,
    )
    monkeypatch.setattr(animate_module, "get_terminal_size", lambda: (80, 24))
    calls: list[dict[str, object]] = []

    def inspect(*_args, **kwargs) -> Terminal:
        calls.append(kwargs)
        return Terminal(80, 24, True, kwargs["ascii"])

    monkeypatch.setattr(animate_module, "inspect_terminal", inspect)

    terminal = animate_module._terminal(options)

    assert terminal.color
    assert terminal.ascii
    assert "no_color" not in calls[0]


def test_frame_wait_is_bounded_and_deadline_aware() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    assert _wait_seconds(session, 1.0) == 0.05
    session.next_deadline = 1.02
    assert _wait_seconds(session, 1.0) == pytest.approx(0.02)
    assert _wait_seconds(session, 2.0) == 0.0
