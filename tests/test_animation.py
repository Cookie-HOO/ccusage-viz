from datetime import timedelta

import pytest
from term_animate.models import ProjectedFrame, StyledCell, StyledRow

from ccusage_viz.animation import (
    AnimationClock,
    AnimationRenderer,
    _xterm_rgb,
    animation_spec,
    animation_style_choices,
    new_animation_session,
    virtual_wall_time,
)
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator


@pytest.fixture
def translator():
    return load_translator("en")


def test_catalog_is_explicit_and_stable() -> None:
    assert animation_style_choices() == (
        "mole-cat",
        "campy-cat",
        "rain",
        "analog-clock",
        "digital-clock",
    )
    assert animation_spec("rain").display_name == "Rain"
    with pytest.raises(UsageError):
        animation_spec("snow")


def test_clock_freezes_without_idle_catch_up() -> None:
    clock = AnimationClock()
    assert clock.elapsed(10.0) == 0.0
    clock.resume(10.0)
    assert clock.elapsed(12.5) == 2.5
    clock.freeze(12.5)
    clock.freeze(99.0)
    assert clock.elapsed(99.0) == 2.5
    clock.resume(100.0)
    assert clock.elapsed(101.0) == 3.5


def test_clock_does_not_move_backward_when_given_an_older_time() -> None:
    clock = AnimationClock()
    clock.resume(10.0)
    assert clock.elapsed(5.0) == 0.0
    clock.freeze(5.0)
    assert clock.elapsed(100.0) == 0.0


def test_virtual_wall_time_stops_while_frozen() -> None:
    session = new_animation_session(animation_spec("digital-clock"), theme="classic")
    session.set_viable(True, 10.0)
    session.set_playback_requested(True, 10.0)
    assert virtual_wall_time(session, 15.0) == session.wall_origin + timedelta(seconds=5)
    session.set_playback_requested(False, 15.0)
    assert virtual_wall_time(session, 3600.0) == session.wall_origin + timedelta(seconds=5)


def test_session_clock_requires_all_playback_conditions() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 1.0)
    assert session.clock.playing
    session.set_visible(False, 2.0)
    assert not session.clock.playing
    assert session.clock.elapsed(10.0) == 1.0
    session.set_visible(True, 10.0)
    session.set_host_paused(True, 11.0)
    assert not session.clock.playing
    session.set_host_paused(False, 20.0)
    assert session.clock.playing
    assert session.clock.elapsed(21.0) == 3.0


def test_style_change_preserves_elapsed_time() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 1.0)
    session.set_style(animation_spec("mole-cat"), 3.0)
    assert session.spec.style == "mole-cat"
    assert session.clock.elapsed(4.0) == 3.0


def test_small_viewport_never_projects_or_schedules(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    monkeypatch.setattr("ccusage_viz.animation.project_curated", pytest.fail)

    result = AnimationRenderer().render(
        session, width=1, height=1, color=False, ascii=True, now=1.0, translator=translator
    )

    assert result.next_deadline is None
    assert not session.clock.playing
    assert result.rows[0]
    assert "\x1b[" not in result.rows[0]


def test_color_disabled_adapter_emits_plain_rows(monkeypatch, translator) -> None:
    frame = ProjectedFrame(
        (StyledRow((StyledCell("x", foreground=(1, 2, 3)),)),), 0, 9.0, "full"
    )
    monkeypatch.setattr("ccusage_viz.animation.project_curated", lambda *args, **kwargs: frame)
    session = new_animation_session(animation_spec("rain"), theme="classic")

    result = AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )

    assert result.rows == ("x",)
    assert result.next_deadline is not None


def test_colored_rows_are_ansi_styled_and_width_safe(monkeypatch, translator) -> None:
    frame = ProjectedFrame(
        (StyledRow((StyledCell("你x", foreground=(1, 2, 3), background=(4, 5, 6)),)),),
        0,
        9.0,
        "full",
    )
    monkeypatch.setattr("ccusage_viz.animation.project_curated", lambda *args, **kwargs: frame)
    session = new_animation_session(animation_spec("rain"), theme="classic")

    result = AnimationRenderer().render(
        session, width=60, height=24, color=True, ascii=False, now=1.0, translator=translator
    )

    assert result.rows[0].startswith("\x1b[38;2;1;2;3;48;2;4;5;6m")
    assert result.rows[0].endswith("\x1b[0m")
    assert display_width(result.rows[0]) == 3


def test_xterm_rgb_rejects_out_of_range_palette_entries() -> None:
    with pytest.raises(ValueError):
        _xterm_rgb(-1)
    with pytest.raises(ValueError):
        _xterm_rgb(256)


def test_projection_failure_returns_unscheduled_fallback(monkeypatch, translator) -> None:
    monkeypatch.setattr(
        "ccusage_viz.animation.project_curated", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError())
    )
    session = new_animation_session(animation_spec("rain"), theme="classic")

    result = AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )

    assert result.next_deadline is None
    assert result.error == "projection_failed"
    assert session.next_deadline is None
