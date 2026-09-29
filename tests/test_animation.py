from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from term_animate.api import curated_catalog
from term_animate.catalog import Catalog
from term_animate.models import LogicalState, Pack, ProjectedFrame, StyledCell, StyledRow

import ccusage_viz.animate as animate_module
from ccusage_viz.animate import (
    GalleryState,
    _editor_line_end,
    _editor_line_start,
    _editor_next_word,
    _editor_previous_word,
    _editor_viewport,
    _gallery_geometry,
    _gallery_rows,
    _overlay_editor_controls,
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
from ccusage_viz.animation_overlay import AnimationOverlayRuntime, OverlayConfig
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import AnimationLaunch, ProcessConfig, StandaloneHostConfig
from ccusage_viz.terminal import FramePainter, Terminal


@pytest.fixture
def translator():
    return load_translator("en")


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
    monkeypatch.setattr(animate_module, "_terminal", lambda _options: Terminal(100, 5, False, True))
    monkeypatch.setattr(animate_module, "read_event", lambda _decoder, _timeout: next(events))

    try:
        animate_module._run_overlay_editor(
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
    monkeypatch.setattr(animate_module, "_terminal", lambda _options: Terminal(120, 8, False, True))
    monkeypatch.setattr(animate_module, "read_event", lambda _decoder, _timeout: next(events))

    try:
        animate_module._run_overlay_editor(
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
    monkeypatch.setattr(animate_module, "_terminal", lambda _options: Terminal(120, 6, False, True))
    monkeypatch.setattr(animate_module, "read_event", lambda _decoder, _timeout: next(events))

    try:
        animate_module._run_overlay_editor(
            type("Painter", (), {"paint": lambda *_args, **_kwargs: None})(),
            overlay,
            object(),
            AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain")),
            translator,
        )
        assert overlay.config.text == "Yfoo Xbar"
    finally:
        overlay.close()


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


@pytest.fixture
def animation_launch() -> AnimationLaunch:
    return AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain"))


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


def test_standalone_host_space_pauses_and_resumes(
    monkeypatch, translator, animation_launch
) -> None:
    session = new_animation_session(animation_spec("rain"), theme="classic")
    recorded_states: list[bool] = []
    events = iter((" ", " ", "q"))

    monkeypatch.setattr(animate_module, "tui_input_mode", nullcontext)
    monkeypatch.setattr(animate_module, "new_animation_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(
        animate_module, "read_adjustment_event", lambda _decoder, _timeout: next(events)
    )
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

    assert "OVERLAY" in stream.getvalue()


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
