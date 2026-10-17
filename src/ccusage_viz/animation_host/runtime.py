from __future__ import annotations

import time
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import (
    HELP_IDLE_TIMEOUT_SECONDS,
    AdjustmentIdleTimer,
    AdjustmentTimeout,
)
from ccusage_viz.animation import (
    AnimationRenderer,
    AnimationSessionState,
    AnimationTarget,
    animation_spec,
    animation_style_choices,
    new_animation_session,
)
from ccusage_viz.animation_overlay import AnimationOverlayRuntime, compose_overlay_row
from ccusage_viz.i18n import Translator
from ccusage_viz.options import AnimationLaunch
from ccusage_viz.render.palette import COLOR_SCHEMES
from ccusage_viz.terminal import (
    FramePainter,
    Terminal,
    compose_frame,
    inspect_terminal,
    set_cursor_visible,
)
from ccusage_viz.terminal_ui import AdjustmentAction, adjustment_rows, controls_line
from ccusage_viz.tui_input import InputDecoder, KeyEvent, read_event, tui_input_mode

_POLL_SECONDS = 0.05

def _format_overlay_interval(seconds: float) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{int(seconds // 3600)}h"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds)}s"

def read_adjustment_event(decoder: InputDecoder, timeout: float) -> str | None:
    """Read one decoded keyboard event for the standalone animation host."""

    event = read_event(decoder, timeout)
    return event.value if isinstance(event, KeyEvent) else None

def cycle_animation_style(
    session: AnimationSessionState, *, target: AnimationTarget = "standalone", step: int, now: float
) -> None:
    """Move through one host's discovered catalog without creating a new session."""

    styles = animation_style_choices(target)
    index = styles.index(session.spec.style)
    session.set_style(animation_spec(styles[(index + step) % len(styles)], target=target), now)

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
    footer_rows: int = 1,
) -> tuple[str, ...]:
    """Project only into space not reserved for status and visible footer rows."""

    result = renderer.render(
        session,
        width=terminal.width,
        height=max(1, terminal.height - 1 - footer_rows),
        color=terminal.color,
        ascii=terminal.ascii,
        now=now,
        translator=translator,
    )
    return result.rows

def _status(session: AnimationSessionState, translator: Translator) -> str:
    return translator.text(
        "status.animation",
        style=session.spec.display_name,
        theme=session.theme,
        state=translator.text("status.animation_running"),
    )

def _paint_animation(
    screen: FramePainter,
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    translator: Translator,
    *,
    now: float,
    overlay: AnimationOverlayRuntime | None = None,
    force: bool = False,
) -> None:
    footer_count = 1
    rows = list(
        _frame_rows(
            session,
            renderer,
            terminal,
            now=now,
            translator=translator,
            footer_rows=footer_count,
        )
    )
    if overlay is not None:
        overlay.poll(now=now, translator=translator)
        for placement in overlay.placements(width=terminal.width, height=len(rows)):
            if 0 <= placement.row < len(rows):
                rows[placement.row] = compose_overlay_row(
                    rows[placement.row], placement, width=terminal.width
                )
    controls = controls_line(
        translator.text("status.animation_controls"),
        width=terminal.width,
        color=terminal.color,
    )
    footer = (controls,)
    screen.paint(
        compose_frame(
            "\n".join(rows),
            _status(session, translator),
            footer,
            height=terminal.height,
        ),
        force=force,
        atomic=True,
    )

def _run_animation_help(
    screen: FramePainter,
    decoder: InputDecoder,
    options: AnimationLaunch,
    translator: Translator,
    *,
    title_key: str = "status.animation_help_title",
    body_key: str = "status.animation_help_body",
    hint_key: str = "status.animation_help_hint",
    body_lines: tuple[str, ...] | None = None,
    close_key: str = "status.animation_help_close",
    close_events: frozenset[str] = frozenset({"h", "q", "Q", "\x1b", "\x03"}),
) -> None:
    """Show a standalone help frame until one of its local close shortcuts."""

    idle_timer = AdjustmentIdleTimer(timeout=HELP_IDLE_TIMEOUT_SECONDS)
    while True:
        terminal = _terminal(options)
        controls = controls_line(
            translator.text(close_key),
            width=terminal.width,
            color=terminal.color,
        )
        last = "\\- " if terminal.ascii else "└─ "
        hint = f"{last}{translator.text(hint_key)}" if hint_key else ""
        contents = body_lines if body_lines is not None else (translator.text(body_key),)
        body = "\n".join(part for part in (*contents, hint) if part)
        screen.paint(
            compose_frame(
                body,
                translator.text(title_key),
                (controls,),
                height=terminal.height,
            )
        )
        event = read_event(decoder, min(_POLL_SECONDS, idle_timer.remaining()))
        if event is None:
            try:
                idle_timer.check()
            except AdjustmentTimeout:
                return
        else:
            idle_timer.record_input()
        if isinstance(event, KeyEvent) and event.value in close_events:
            return

def _run_adjustment(
    screen: FramePainter,
    session: AnimationSessionState,
    renderer: AnimationRenderer,
    overlay: AnimationOverlayRuntime,
    decoder: InputDecoder,
    options: AnimationLaunch,
    translator: Translator,
) -> bool:
    """Run the local quick/advanced adjustment pages; return true to exit the host."""

    from ccusage_viz.animation_host.overlay_editor import _run_overlay_editor, _run_overlay_history

    page = "quick"
    idle_timer = AdjustmentIdleTimer()
    last_size: tuple[int, int] | None = None

    def paint(*, force: bool = False) -> None:
        nonlocal last_size
        terminal = _terminal(options)
        last_size = (terminal.width, terminal.height)
        now = time.monotonic()
        rows = list(_frame_rows(session, renderer, terminal, now=now, translator=translator))
        for placement in overlay.placements(width=terminal.width, height=len(rows)):
            rows[placement.row] = compose_overlay_row(
                rows[placement.row], placement, width=terminal.width
            )
        actions = (
            (
                AdjustmentAction("p/P", translator.text("adjustment.overlay_position"), 0),
                AdjustmentAction("t/T", translator.text("adjustment.animation_theme"), 1),
                AdjustmentAction("s/S", translator.text("adjustment.animation_style"), 2),
            )
            if page == "quick"
            else (
                AdjustmentAction("↑/↓/←/→", translator.text("adjustment.overlay_move"), 0),
                AdjustmentAction("0", translator.text("adjustment.overlay_reset"), 1),
                AdjustmentAction("e", translator.text("adjustment.overlay_edit"), 2),
                AdjustmentAction("i", translator.text("adjustment.overlay_interval"), 3),
                AdjustmentAction("L", translator.text("adjustment.overlay_history"), 4),
            )
        )
        state = translator.text(
            "status.animation_adjust_quick"
            if page == "quick"
            else (
                "status.animation_adjust_advanced_command"
                if overlay.config.command is not None
                else "status.animation_adjust_advanced"
            ),
            style=session.spec.display_name,
            style_index=animation_style_choices("standalone").index(session.spec.style) + 1,
            style_count=len(animation_style_choices("standalone")),
            theme=session.theme,
            theme_index=COLOR_SCHEMES.index(session.theme) + 1,
            theme_count=len(COLOR_SCHEMES),
            position=overlay.config.position,
            offset_x=overlay.config.offset_x,
            offset_y=overlay.config.offset_y,
            interval=_format_overlay_interval(overlay.config.interval),
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
            key = read_adjustment_event(decoder, timeout)
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
        elif page == "quick" and key in {"p", "P"}:
            overlay.cycle_position(1 if key == "p" else -1)
        elif page == "quick" and key == "t":
            _cycle_theme(session, step=1, now=now)
        elif page == "quick" and key == "T":
            _cycle_theme(session, step=-1, now=now)
        elif page == "quick" and key in {"s", "S"}:
            cycle_animation_style(
                session, target="standalone", step=1 if key == "s" else -1, now=now
            )
        elif page == "advanced" and key == "\x1b[A":
            overlay.adjust_offset(dy=-1)
        elif page == "advanced" and key == "\x1b[B":
            overlay.adjust_offset(dy=1)
        elif page == "advanced" and key == "\x1b[C":
            overlay.adjust_offset(dx=1)
        elif page == "advanced" and key == "\x1b[D":
            overlay.adjust_offset(dx=-1)
        elif page == "advanced" and key == "0":
            overlay.reset_offset()
        elif page == "advanced" and key == "e":
            _run_overlay_editor(screen, overlay, decoder, options, translator)
        elif page == "advanced" and key == "i":
            overlay.cycle_interval(now=now)
        elif page == "advanced" and key == "L":
            _run_overlay_history(screen, overlay, decoder, options, translator)
        else:
            continue
        paint()

def _wait_seconds(
    session: AnimationSessionState,
    now: float,
    *,
    overlay: AnimationOverlayRuntime | None = None,
    upper_bound: float = _POLL_SECONDS,
) -> float:
    """Bound an input wait by local animation and overlay repaint deadlines."""

    deadlines = [deadline for deadline in (session.next_deadline,) if deadline is not None]
    if overlay is not None and overlay.next_due is not None:
        deadlines.append(overlay.next_due)
    return upper_bound if not deadlines else min(upper_bound, max(0.0, min(deadlines) - now))

def run_animation(options: AnimationLaunch, translator: Translator) -> int:
    from ccusage_viz.animation_host.gallery import _run_gallery
    """Run an interactive animation without creating any provider-facing work."""

    if options.gallery:
        return _run_gallery(options, translator)
    session = new_animation_session(options.animation, theme="classic")
    renderer = AnimationRenderer()
    overlay = AnimationOverlayRuntime(options.overlay)
    screen = FramePainter()
    last_size: tuple[int, int] | None = None
    try:
        set_cursor_visible(screen.stream, False)
        with tui_input_mode() as decoder:
            while True:
                terminal = _terminal(options)
                size = (terminal.width, terminal.height)
                now = time.monotonic()
                deadline_due = session.next_deadline is not None and now >= session.next_deadline
                overlay_changed = overlay.poll(now=now)
                if last_size != size or not screen.painted:
                    _paint_animation(
                        screen,
                        session,
                        renderer,
                        terminal,
                        translator,
                        now=now,
                        overlay=overlay,
                        force=last_size is not None,
                    )
                    last_size = size
                elif deadline_due or overlay_changed:
                    _paint_animation(
                        screen, session, renderer, terminal, translator, now=now, overlay=overlay
                    )
                key = read_adjustment_event(
                    decoder, _wait_seconds(session, time.monotonic(), overlay=overlay)
                )
                if key is None:
                    continue
                now = time.monotonic()
                if key in {"q", "Q", "\x1b", "\x03"}:
                    break
                if key in {"m", "M"}:
                    if _run_adjustment(
                        screen, session, renderer, overlay, decoder, options, translator
                    ):
                        break
                elif key == "h":
                    _run_animation_help(screen, decoder, options, translator)
                else:
                    continue
                _paint_animation(
                    screen,
                    session,
                    renderer,
                    _terminal(options),
                    translator,
                    now=time.monotonic(),
                    overlay=overlay,
                )
                last_size = (get_terminal_size().columns, get_terminal_size().lines)
    except KeyboardInterrupt:
        pass
    finally:
        overlay.close()
        screen.finish()
        set_cursor_visible(screen.stream, True)
    return 0
