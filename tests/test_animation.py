from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from term_animate.api import curated_catalog
from term_animate.catalog import Catalog
from term_animate.models import LogicalState, Pack, ProjectedFrame, StyledCell, StyledRow

import ccusage_viz.animate as animate_module
from ccusage_viz.animate import (
    GalleryState,
    _gallery_geometry,
    _gallery_rows,
    _wait_seconds,
    cycle_animation_style,
)
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
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import AnimationLaunch, ProcessConfig, StandaloneHostConfig
from ccusage_viz.terminal import Terminal


@pytest.fixture
def translator():
    return load_translator("en")


def test_last_activity_label_is_localized() -> None:
    wall = datetime(2026, 9, 28, 6, 42, 10, tzinfo=UTC)

    assert last_activity_label(load_translator("en"), wall) == "last activity detected: 06:42:10"
    assert last_activity_label(load_translator("zh"), wall) == "最后检测到活动：06:42:10"


@pytest.mark.parametrize("target", ("standalone", "pane", "monitor"))
def test_default_animation_spec_selects_first_eligible_style(target) -> None:
    assert default_animation_spec(target).style == animation_style_choices(target)[0]


def test_default_animation_spec_rejects_empty_catalog(monkeypatch) -> None:
    monkeypatch.setattr("ccusage_viz.animation.animation_style_choices", lambda _target: ())

    with pytest.raises(UsageError):
        default_animation_spec()


def test_catalog_is_discovered_from_term_animate() -> None:
    styles = animation_style_choices()

    assert styles
    assert set(animation_style_choices("monitor")).issubset(styles)
    assert animation_spec(styles[0]).style == styles[0]
    with pytest.raises(UsageError):
        animation_spec("not-an-animation")


def test_gallery_catalog_refresh_preserves_valid_selection_and_handles_removal() -> None:
    state = GalleryState(("rain", "snow"), "snow")
    snow = state.session_for("snow", now=1.0)
    snow.set_viable(True, 1.0)

    assert state.refresh_catalog(("rain", "snow", "digital-clock"), now=2.0) is True
    assert state.selected_style == "snow"

    assert state.refresh_catalog(("rain",), now=3.0) is True
    assert state.selected_style == "rain"
    assert state.sessions == {}

    assert state.refresh_catalog((), now=4.0) is True
    assert state.selected_style == ""
    assert state.selected_index() == 0


def test_gallery_hides_off_page_sessions_without_idle_catch_up() -> None:
    state = GalleryState(("rain", "snow"), "rain")
    rain = state.session_for("rain", now=1.0)
    rain.set_viable(True, 1.0)
    assert rain.clock.elapsed(3.0) == 2.0

    state.set_visible_styles(("snow",), now=3.0)

    assert not rain.visible
    assert rain.clock.elapsed(100.0) == 2.0


def test_gallery_projects_all_visible_previews_between_deadlines(monkeypatch, translator) -> None:
    state = GalleryState(("rain", "snow"), "rain")
    terminal = Terminal(60, 12, False, False)
    renderer = AnimationRenderer()
    calls: list[str] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, 9.0, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda effect, **_kwargs: calls.append(effect.id) or frame,
    )

    _gallery_rows(state, renderer, terminal, translator, now=1.0)
    _gallery_rows(state, renderer, terminal, translator, now=2.0)

    assert calls == ["rain", "snow"]


def test_gallery_uses_two_columns_tall_cards_and_paginates_by_selection(translator) -> None:
    state = GalleryState(("rain", "snow", "digital-clock", "mole-cat"), "rain")
    terminal = Terminal(80, 24, False, False)

    columns, rows, card_width, card_height = _gallery_geometry(terminal)
    rendered, sessions = _gallery_rows(state, AnimationRenderer(), terminal, translator, now=1.0)

    assert (columns, rows, card_width, card_height) == (2, 1, 40, 21)
    assert len(sessions) == 2
    assert all(session.clock.playing for session in sessions)
    assert rendered[0] == "┌" + "─" * 38 + "┐" + "┌" + "─" * 38 + "┐"
    assert any("rain" in row and "snow" in row for row in rendered)
    state.select(2)
    rendered, sessions = _gallery_rows(state, AnimationRenderer(), terminal, translator, now=2.0)
    assert len(sessions) == 2
    assert all(
        session.visible and session.playback_requested and session.clock.playing
        for session in sessions
    )
    assert any("digital-clock" in row and "mole-cat" in row for row in rendered)


def test_gallery_uses_ascii_card_borders(translator) -> None:
    state = GalleryState(("rain",), "rain")

    rows, _ = _gallery_rows(
        state, AnimationRenderer(), Terminal(40, 24, False, True), translator, now=1.0
    )

    assert rows[0] == "+" + "-" * 18 + "+"
    assert any(row.startswith("|") and row.endswith("|") for row in rows)


def test_gallery_cards_keep_ansi_display_width_safe(monkeypatch, translator) -> None:
    state = GalleryState(("rain",), "rain")
    terminal = Terminal(60, 12, True, False)
    renderer = AnimationRenderer()
    frame = ProjectedFrame((StyledRow((StyledCell("你", foreground=(1, 2, 3)),)),), 0, None, "full")
    monkeypatch.setattr("ccusage_viz.animation.project", lambda *_args, **_kwargs: frame)

    rows, _ = _gallery_rows(state, renderer, terminal, translator, now=1.0)

    assert all(display_width(row) <= terminal.width for row in rows)


def test_catalog_extension_is_discovered_without_a_ccuv_catalog_change(monkeypatch) -> None:
    catalog = curated_catalog()
    source = catalog.effects()[0]
    added = replace(source, id="new-cat", style="new-cat", name="New Cat")
    monkeypatch.setattr(
        "ccusage_viz.animation.curated_catalog",
        lambda: Catalog((Pack("extended", "Extended", (*catalog.effects(), added)),)),
    )

    assert animation_style_choices()[-1] == "new-cat"
    assert animation_spec("new-cat").display_name == "New Cat"


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


def test_session_clock_stops_only_when_no_animated_frame_is_requested() -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    session.set_viable(True, 1.0)
    assert session.clock.playing
    session.set_visible(False, 2.0)
    assert not session.clock.playing
    assert session.clock.elapsed(10.0) == 1.0
    session.set_visible(True, 10.0)
    session.set_host_paused(True, 11.0)
    assert session.clock.playing
    assert session.clock.elapsed(20.0) == 11.0
    assert session.traversal_frozen_at == 2.0
    session.set_host_paused(False, 20.0)
    assert session.clock.playing
    assert session.traversal_frozen_at is None
    assert session.clock.elapsed(21.0) == 12.0


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


def test_manual_pause_keeps_source_frames_live_and_traversal_fixed(monkeypatch, translator) -> None:
    session = new_animation_session(animation_spec("mole-cat"), theme="classic")
    received: list[tuple[float, float | None, str | None]] = []
    frame = ProjectedFrame((StyledRow((StyledCell("x"),)),), 0, 9.0, "full")
    monkeypatch.setattr(
        "ccusage_viz.animation.project",
        lambda *_args, **kwargs: received.append(
            (
                kwargs["monotonic_seconds"],
                kwargs["traversal_monotonic_seconds"],
                kwargs["pause_label"],
            )
        )
        or frame,
    )

    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=10.0, translator=translator
    )
    session.set_host_paused(True, 11.0, pause_label="paused")
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=12.0, translator=translator
    )
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=13.0, translator=translator
    )
    session.set_host_paused(False, 14.0)
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=15.0, translator=translator
    )

    assert received == [
        (0.0, None, None),
        (2.0, 1.0, "paused"),
        (3.0, 1.0, "paused"),
        (5.0, None, None),
    ]


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


def test_renderer_prefers_explicit_pause_label_over_idle_activity(monkeypatch, translator) -> None:
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
    session.set_pause_label("paused")
    AnimationRenderer().render(
        session, width=80, height=24, color=False, ascii=False, now=3.0, translator=translator
    )

    assert received == [None, "last activity detected: 06:42:10", "paused"]


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


@pytest.fixture
def animation_launch() -> AnimationLaunch:
    return AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain"))


@pytest.mark.parametrize("exit_key", ("q", "\x1b", "\x03"))
def test_standalone_host_exits_for_owned_exit_keys(
    monkeypatch, translator, animation_launch, exit_key
) -> None:
    finished = []
    monkeypatch.setattr(animate_module, "input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "read_adjustment_event", lambda _timeout: exit_key)
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(80, 24, False, False)
    )
    monkeypatch.setattr(animate_module.FramePainter, "finish", lambda _self: finished.append(True))

    assert animate_module.run_animation(animation_launch, translator) == 0
    assert finished == [True]


def test_standalone_host_space_pauses_and_resumes(
    monkeypatch, translator, animation_launch
) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    recorded_states: list[bool] = []
    events = iter((" ", " ", "q"))

    monkeypatch.setattr(animate_module, "input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(animate_module, "read_adjustment_event", lambda _timeout: next(events))
    monkeypatch.setattr(
        animate_module, "_terminal", lambda _options: Terminal(80, 24, False, False)
    )
    monkeypatch.setattr(
        animate_module,
        "_paint_animation",
        lambda _screen, rendered_session, *_args, **_kwargs: recorded_states.append(
            rendered_session.host_paused
        ),
    )

    assert animate_module.run_animation(animation_launch, translator) == 0
    assert any(
        not before and after
        for before, after in zip(recorded_states, recorded_states[1:], strict=False)
    )
    assert any(
        before and not after
        for before, after in zip(recorded_states, recorded_states[1:], strict=False)
    )


def test_standalone_host_adjustment_handles_quick_controls(
    monkeypatch, translator, animation_launch
) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    events = iter(("m", "t", "T", "s", "S", "\r", "q"))

    monkeypatch.setattr(animate_module, "input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(animate_module, "read_adjustment_event", lambda _timeout: next(events))
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

    monkeypatch.setattr(animate_module, "input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(animate_module, "read_adjustment_event", lambda _timeout: next(events))
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
