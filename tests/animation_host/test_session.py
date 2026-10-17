

from datetime import UTC, datetime, timedelta

import pytest
from term_animate.models import LogicalState, ProjectedFrame, StyledCell, StyledRow

from ccusage_viz.animation import (
    AnimationClock,
    AnimationRenderer,
    animation_spec,
    animation_style_choices,
    cycle_monitor_attachment,
    default_animation_spec,
    last_activity_label,
    new_animation_session,
    virtual_wall_time,
)
from ccusage_viz.animation_host.runtime import cycle_animation_style
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator


def test_last_activity_label_is_localized() -> None:
    wall = datetime(2026, 9, 28, 6, 42, 10, tzinfo=UTC)

    assert last_activity_label(load_translator("en"), wall) == "last activity detected: 06:42:10"
    assert last_activity_label(load_translator("zh"), wall) == "最后检测到活动：06:42:10"

@pytest.mark.parametrize("target", ("standalone", "pane", "monitor"))
def test_default_animation_spec_selects_first_eligible_style(target) -> None:
    assert default_animation_spec(target).style == animation_style_choices(target)[0]

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

def test_time_effect_receives_actual_local_callback_time(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("digital-clock"), theme="classic")
    received: list[datetime] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, None, "full")
    callback_time = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    monkeypatch.setattr(
        "ccusage_viz.animation.datetime",
        type("CallbackDateTime", (), {"now": classmethod(lambda _cls: callback_time)}),
    )
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: received.append(kwargs["wall_time"]) or frame,
    )

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=10.0, translator=translator
    )

    assert received == [callback_time.astimezone()]

def test_non_time_effect_retains_virtual_effective_wall_time(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    received: list[datetime] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, None, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: received.append(kwargs["wall_time"]) or frame,
    )

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=10.0, translator=translator
    )
    session.set_visible(False, 11.0)
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=100.0, translator=translator
    )

    assert received == [session.wall_origin, session.wall_origin + timedelta(seconds=1)]

def test_session_clock_stops_when_no_animated_frame_is_requested() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 1.0)
    assert session.clock.playing
    session.set_visible(False, 2.0)
    assert not session.clock.playing
    assert session.clock.elapsed(10.0) == 1.0
    session.set_visible(True, 10.0)
    assert session.clock.playing
    assert session.clock.elapsed(20.0) == 11.0
    session.set_playback_requested(False, 20.0)
    assert session.traversal_frozen_at == 11.0
    assert not session.clock.playing
    session.set_playback_requested(True, 30.0)
    assert session.traversal_frozen_at is None
    assert session.clock.playing
    assert session.clock.elapsed(31.0) == 12.0

def test_style_change_preserves_elapsed_time() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 1.0)
    session.set_style(animation_spec("mole-cat"), 3.0)
    assert session.spec.style == "mole-cat"
    assert session.clock.elapsed(4.0) == 3.0

def test_small_viewport_projects_a_bounded_library_frame(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, 1.0, "full")
    monkeypatch.setattr("ccusage_viz.animation.project", lambda *args, **kwargs: frame)

    result = AnimationRenderer().render(
        session, width=1, height=1, color=False, ascii=True, now=1.0, translator=translator
    )

    assert result.rows == ("x",)
    assert session.clock.playing

def test_color_disabled_adapter_emits_plain_rows(monkeypatch, translator) -> None:
    frame = ProjectedFrame((StyledRow((StyledCell("x", foreground=(1, 2, 3)),)),), 0, 9.0, "full")
    monkeypatch.setattr("ccusage_viz.animation.project", lambda *args, **kwargs: frame)
    session = new_animation_session(animation_spec("rain"), theme="classic")

    result = AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )

    assert result.rows == ("x",)
    assert result.next_deadline == 10.0
    assert session.next_deadline == 10.0

def test_idle_animation_keeps_source_frames_live_and_traversal_fixed(
    monkeypatch, translator
) -> None:
    session = new_animation_session(animation_spec("mole-cat"), theme="classic")
    received: list[tuple[float, float | None]] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, 9.0, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: received.append(
            (kwargs["monotonic_seconds"], kwargs["traversal_monotonic_seconds"])
        )
        or frame,
    )

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=10.0, translator=translator
    )
    session.set_playback_requested(False, 11.0)
    session.set_idle_animation_requested(True, 11.0)
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=12.0, translator=translator
    )
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=13.0, translator=translator
    )
    session.set_playback_requested(True, 14.0)
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=15.0, translator=translator
    )

    assert received == [(0.0, None), (2.0, 1.0), (3.0, 1.0), (5.0, None)]

def test_stateful_effects_receive_active_and_idle_state(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("snow"), theme="classic")
    states: list[LogicalState | None] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, None, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: states.append(kwargs["logical_state"]) or frame,
    )

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )
    session.set_playback_requested(False, 2.0)
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=2.0, translator=translator
    )

    assert states == [LogicalState.ACTIVE, LogicalState.IDLE]

def test_non_stateful_effects_receive_no_logical_state(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("mole-cat"), theme="classic")
    states: list[LogicalState | None] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, None, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: states.append(kwargs["logical_state"]) or frame,
    )

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )

    assert states == [None]

def test_projection_deadline_is_translated_to_host_monotonic_time(monkeypatch, translator) -> None:
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, 4.0, "full")
    monkeypatch.setattr("ccusage_viz.animation.project", lambda *args, **kwargs: frame)
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 10.0)

    result = AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=12.0, translator=translator
    )

    assert result.next_deadline == 14.0
    assert session.next_deadline == 14.0

def test_colored_rows_are_ansi_styled_and_width_safe(monkeypatch, translator) -> None:
    frame = ProjectedFrame(
        (StyledRow((StyledCell("你x", foreground=(1, 2, 3), background=(4, 5, 6)),)),),
        0,
        9.0,
        "full",
    )
    monkeypatch.setattr("ccusage_viz.animation.project", lambda *args, **kwargs: frame)
    session = new_animation_session(animation_spec("rain"), theme="classic")

    result = AnimationRenderer().render(
        session, width=60, height=24, color=True, ascii=False, now=1.0, translator=translator
    )

    assert result.rows[0].startswith("\x1b[38;2;1;2;3;48;2;4;5;6m")
    assert result.rows[0].endswith("\x1b[0m")
    assert display_width(result.rows[0]) == 3

def test_renderer_passes_the_selected_library_theme(monkeypatch, translator) -> None:
    received: list[object] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, None, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: received.append(kwargs["theme"]) or frame,
    )
    session = new_animation_session(animation_spec("rain"), theme="dracula")

    AnimationRenderer().render(
        session, width=80, height=24, color=True, ascii=False, now=1.0, translator=translator
    )

    assert received == ["dracula"]

def test_renderer_passes_idle_activity_label(monkeypatch, translator) -> None:
    received: list[object] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, None, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: received.append(kwargs["pause_label"]) or frame,
    )
    session = new_animation_session(animation_spec("rain"), theme="classic")

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )
    session.activity_label = "last activity detected: 06:42:10"
    session.set_playback_requested(False, 2.0)
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=2.0, translator=translator
    )

    assert received == [None, "last activity detected: 06:42:10"]

def test_monitor_attachment_cycle_reaches_none_then_wraps_in_both_directions() -> None:
    session = new_animation_session(
        animation_spec("digital-clock", target="monitor"), theme="classic"
    )
    session.set_visible(True, 0.0)

    assert not cycle_monitor_attachment(session, enabled=True, step=1, now=1.0)
    assert not session.visible
    assert cycle_monitor_attachment(session, enabled=False, step=1, now=2.0)
    assert session.visible
    assert session.spec.style == animation_style_choices("monitor")[0]
    assert not cycle_monitor_attachment(session, enabled=True, step=-1, now=3.0)
    assert not session.visible
    assert cycle_monitor_attachment(session, enabled=False, step=-1, now=4.0)
    assert session.visible
    assert session.spec.style == animation_style_choices("monitor")[-1]

def test_style_cycle_preserves_theme_and_elapsed_time() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 1.0)

    cycle_animation_style(session, step=1, now=3.0)
    cycle_animation_style(session, step=-1, now=3.5)

    assert session.spec.style == "rain"
    assert session.theme == "classic"
    assert session.clock.elapsed(4.0) == 3.0

def test_projection_failure_returns_unscheduled_fallback(monkeypatch, translator) -> None:
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError()),
    )
    session = new_animation_session(animation_spec("rain"), theme="classic")

    result = AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=1.0, translator=translator
    )

    assert result.next_deadline is None
    assert result.error == "projection_failed"
    assert session.next_deadline is None
