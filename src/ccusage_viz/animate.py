"""Standalone, provider-free terminal host for ccuv animations."""

from __future__ import annotations

import time
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer, AdjustmentTimeout
from ccusage_viz.animation import (
    AnimationRenderer,
    AnimationSessionState,
    animation_spec,
    animation_style_choices,
    new_animation_session,
)
from ccusage_viz.i18n import Translator
from ccusage_viz.options import AnimationLaunch
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import FramePainter, Terminal, compose_frame, inspect_terminal
from ccusage_viz.terminal_ui import (
    AdjustmentAction,
    adjustment_rows,
    controls_line,
    input_mode,
    read_key,
)

_POLL_SECONDS = 0.05


def read_adjustment_event(timeout: float) -> str | None:
    """Read one ccuv-owned key event for the standalone animation host."""

    return read_key(timeout)


def cycle_animation_style(session: AnimationSessionState, *, step: int, now: float) -> None:
    """Move through the fixed public catalog without creating a new session."""

    styles = animation_style_choices()
    index = styles.index(session.spec.style)
    session.set_style(animation_spec(styles[(index + step) % len(styles)]), now)


def _cycle_theme(session: AnimationSessionState, *, step: int, now: float) -> None:
    index = COLOR_SCHEMES.index(session.theme)
    session.set_theme(COLOR_SCHEMES[(index + step) % len(COLOR_SCHEMES)], now)


def _terminal(options: AnimationLaunch) -> Terminal:
    return inspect_terminal(
        "animate",
        ascii=options.host.ascii,
        size=get_terminal_size(),
    )


def _frame_rows(
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    *,
    now: float,
    translator: Translator,
) -> tuple[str, ...]:
    """Project only into space not reserved for the status and controls rows."""

    result = renderer.render(
        session,
        width=terminal.width,
        height=max(1, terminal.height - 2),
        color=terminal.color,
        ascii=terminal.ascii,
        now=now,
        translator=translator,
    )
    return result.rows


def _status(session: AnimationSessionState, translator: Translator) -> str:
    state = translator.text(
        "status.animation_running" if session.clock.playing else "status.animation_paused"
    )
    return translator.text(
        "status.animation",
        style=session.spec.display_name,
        theme=session.theme,
        state=state,
    )


def _paint_animation(
    screen: FramePainter,
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    translator: Translator,
    *,
    now: float,
    force: bool = False,
) -> None:
    rows = _frame_rows(session, renderer, terminal, now=now, translator=translator)
    controls = controls_line(
        translator.text("status.animation_controls"), width=terminal.width, color=terminal.color
    )
    screen.paint(
        compose_frame(
            "\n".join(rows),
            _status(session, translator),
            controls,
            height=terminal.height,
        ),
        force=force,
    )


def _run_adjustment(
    screen: FramePainter,
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    options: AnimationLaunch,
    translator: Translator,
) -> bool:
    """Run the local quick/advanced adjustment pages; return true to exit the host."""

    page = "quick"
    idle_timer = AdjustmentIdleTimer()
    last_size: tuple[int, int] | None = None

    def paint(*, force: bool = False) -> None:
        nonlocal last_size
        terminal = _terminal(options)
        last_size = (terminal.width, terminal.height)
        now = time.monotonic()
        rows = _frame_rows(session, renderer, terminal, now=now, translator=translator)
        actions = (
            (
                AdjustmentAction("t/T", translator.text("adjustment.animation_theme"), 0),
                AdjustmentAction("s", translator.text("adjustment.animation_style"), 1),
            )
            if page == "quick"
            else ()
        )
        state = translator.text(
            "status.animation_adjust_quick"
            if page == "quick"
            else "status.animation_adjust_advanced",
            style=session.spec.display_name,
            style_index=animation_style_choices().index(session.spec.style) + 1,
            style_count=len(animation_style_choices()),
            theme=session.theme,
            theme_index=COLOR_SCHEMES.index(session.theme) + 1,
            theme_count=len(COLOR_SCHEMES),
        )
        controls = adjustment_rows(
            state,
            translator.text(f"adjustment.page_{page}"),
            actions,
            width=terminal.width,
            color=terminal.color,
            switch_action=translator.text(
                "adjustment.switch_advanced" if page == "quick" else "adjustment.switch_quick"
            ),
            finish_action=translator.text("adjustment.finish"),
        )
        screen.paint(
            compose_frame(
                "\n".join(rows),
                _status(session, translator),
                controls,
                height=terminal.height,
            ),
            force=force,
        )

    paint()
    while True:
        now = time.monotonic()
        timeout = _wait_seconds(
            session, now, upper_bound=min(_POLL_SECONDS, idle_timer.remaining())
        )
        try:
            key = read_adjustment_event(timeout)
        except KeyboardInterrupt:
            return True
        now = time.monotonic()
        size = get_terminal_size()
        deadline_due = session.next_deadline is not None and now >= session.next_deadline
        if (
            size.columns != (last_size or (None, None))[0]
            or size.lines != (last_size or (None, None))[1]
        ):
            paint(force=True)
        elif deadline_due:
            paint()
        if key is None:
            try:
                idle_timer.check()
            except AdjustmentTimeout:
                return False
            continue
        idle_timer.record_input()
        if key in {"q", "Q", "\x03", "\x1b"}:
            return True
        if key in {"\r", "\n", "m", "M"}:
            return False
        if key == "a":
            page = "advanced" if page == "quick" else "quick"
        elif page == "quick" and key == "t":
            _cycle_theme(session, step=1, now=now)
        elif page == "quick" and key == "T":
            _cycle_theme(session, step=-1, now=now)
        elif page == "quick" and key == "s":
            cycle_animation_style(session, step=1, now=now)
        else:
            continue
        paint()


def _wait_seconds(
    session: AnimationSessionState, now: float, *, upper_bound: float = _POLL_SECONDS
) -> float:
    """Bound an input wait by the ccuv-owned next repaint deadline."""

    if session.next_deadline is None:
        return upper_bound
    return min(upper_bound, max(0.0, session.next_deadline - now))


def run_animation(options: AnimationLaunch, translator: Translator) -> int:
    """Run an interactive animation without creating any provider-facing work."""

    session = new_animation_session(options.animation, theme="classic")
    renderer = AnimationRenderer()
    screen = FramePainter()
    last_size: tuple[int, int] | None = None
    try:
        with input_mode():
            while True:
                terminal = _terminal(options)
                size = (terminal.width, terminal.height)
                now = time.monotonic()
                deadline_due = session.next_deadline is not None and now >= session.next_deadline
                if last_size != size or not screen.painted:
                    _paint_animation(
                        screen,
                        session,
                        renderer,
                        terminal,
                        translator,
                        now=now,
                        force=last_size is not None,
                    )
                    last_size = size
                elif deadline_due:
                    _paint_animation(screen, session, renderer, terminal, translator, now=now)
                key = read_adjustment_event(_wait_seconds(session, time.monotonic()))
                if key is None:
                    continue
                now = time.monotonic()
                if key in {"q", "Q", "\x1b", "\x03"}:
                    break
                if key == " ":
                    session.set_playback_requested(not session.playback_requested, now)
                elif key in {"m", "M"}:
                    if _run_adjustment(screen, session, renderer, options, translator):
                        break
                else:
                    continue
                _paint_animation(
                    screen, session, renderer, _terminal(options), translator, now=time.monotonic()
                )
                last_size = (get_terminal_size().columns, get_terminal_size().lines)
    except KeyboardInterrupt:
        pass
    finally:
        screen.finish()
    return 0
