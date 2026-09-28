"""Standalone, provider-free terminal host for ccuv animations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from shutil import get_terminal_size

from ccusage_viz.adjustment_timeout import AdjustmentIdleTimer, AdjustmentTimeout
from ccusage_viz.animation import (
    AnimationRenderer,
    AnimationSessionState,
    AnimationTarget,
    animation_spec,
    animation_style_choices,
    new_animation_session,
)
from ccusage_viz.formatting import clip_width, pad_width
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
from ccusage_viz.tui_input import KeyEvent, read_event, tui_input_mode

_POLL_SECONDS = 0.05


def read_adjustment_event(timeout: float) -> str | None:
    """Read one ccuv-owned key event for the standalone animation host."""

    return read_key(timeout)


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
        "status.animation_paused" if session.host_paused else "status.animation_running"
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
        translator.text(
            "status.animation_controls",
            action=translator.text("status.resume" if session.host_paused else "status.pause"),
        ),
        width=terminal.width,
        color=terminal.color,
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
                AdjustmentAction("s/S", translator.text("adjustment.animation_style"), 1),
            )
            if page == "quick"
            else ()
        )
        state = translator.text(
            "status.animation_adjust_quick"
            if page == "quick"
            else "status.animation_adjust_advanced",
            style=session.spec.display_name,
            style_index=animation_style_choices("standalone").index(session.spec.style) + 1,
            style_count=len(animation_style_choices("standalone")),
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
        elif page == "quick" and key in {"s", "S"}:
            cycle_animation_style(
                session, target="standalone", step=1 if key == "s" else -1, now=now
            )
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


@dataclass(slots=True)
class GalleryState:
    """Live card sessions and selection for the provider-free animation gallery."""

    styles: tuple[str, ...]
    selected_style: str
    playback_requested: bool = True
    sessions: dict[str, AnimationSessionState] = field(default_factory=dict)
    frames: dict[tuple[str, int, int, bool, bool, str], tuple[str, ...]] = field(
        default_factory=dict
    )
    dirty_styles: set[str] = field(default_factory=set)

    def selected_index(self) -> int:
        return self.styles.index(self.selected_style) if self.selected_style in self.styles else 0

    def refresh_catalog(self, styles: tuple[str, ...], *, now: float) -> bool:
        """Reconcile discovery and discard sessions for removed effects."""

        if styles == self.styles:
            return False
        previous = self.selected_style
        self.styles = styles
        self.sessions = {
            style: session for style, session in self.sessions.items() if style in styles
        }
        self.frames = {key: rows for key, rows in self.frames.items() if key[0] in styles}
        self.dirty_styles.update(styles)
        if not styles:
            self.selected_style = ""
            return True
        self.selected_style = previous if previous in styles else styles[0]
        for session in self.sessions.values():
            session.set_visible(False, now)
        return True

    def select(self, index: int) -> None:
        if self.styles:
            self.selected_style = self.styles[index % len(self.styles)]

    def session_for(self, style: str, *, now: float) -> AnimationSessionState:
        session = self.sessions.get(style)
        if session is None:
            session = new_animation_session(
                animation_spec(style, target="standalone"), theme="classic"
            )
            self.sessions[style] = session
        session.set_visible(True, now)
        session.set_playback_requested(self.playback_requested, now)
        return session

    def set_visible_styles(self, styles: tuple[str, ...], *, now: float) -> None:
        """Make the page's sessions immediately eligible for playback."""

        visible = frozenset(styles)
        for style, session in self.sessions.items():
            if style not in visible:
                session.set_visible(False, now)
        for style in styles:
            was_visible = style in self.sessions and self.sessions[style].visible
            self.session_for(style, now=now)
            if not was_visible:
                self.dirty_styles.add(style)

    def set_playback_requested(self, requested: bool, *, now: float) -> None:
        self.playback_requested = requested
        self.dirty_styles.update(self.sessions)
        for session in self.sessions.values():
            session.set_playback_requested(requested, now)

    def mark_theme_changed(self, style: str) -> None:
        self.dirty_styles.add(style)


def _gallery_geometry(terminal: Terminal) -> tuple[int, int, int, int]:
    """Return a fixed two-column, large-card gallery viewport."""

    columns = 1 if terminal.width < 2 else 2
    card_width = max(1, terminal.width // columns)
    available_height = max(1, terminal.height - 3)
    rows = max(1, available_height // 18)
    card_height = max(1, available_height // rows)
    return columns, rows, card_width, card_height


def _gallery_card(
    rows: tuple[str, ...],
    style: str,
    *,
    selected: bool,
    width: int,
    height: int,
    ascii: bool,
) -> tuple[str, ...]:
    """Frame a gallery card without measuring ANSI escape sequences as content."""

    if width < 4 or height < 3:
        return (clip_width(f"> {style}" if selected else style, width),)
    left, right, horizontal, vertical, bottom_left, bottom_right = (
        ("+", "+", "-", "|", "+", "+") if ascii else ("┌", "┐", "─", "│", "└", "┘")
    )
    interior_width = width - 2
    marker = ">" if selected else " "
    title = clip_width(f"{marker} {style}", interior_width)
    body = [title, *rows[: max(0, height - 3)]]
    body.extend("" for _ in range(max(0, height - 2 - len(body))))
    return (
        left + horizontal * interior_width + right,
        *(vertical + pad_width(item, interior_width) + vertical for item in body),
        bottom_left + horizontal * interior_width + bottom_right,
    )


def _gallery_rows(
    state: GalleryState,
    renderer: AnimationRenderer,
    terminal: Terminal,
    translator: Translator,
    *,
    now: float,
) -> tuple[tuple[str, ...], tuple[AnimationSessionState, ...]]:
    if not state.styles:
        return (translator.text("status.animation_gallery_empty"),), ()

    columns, row_count, card_width, card_height = _gallery_geometry(terminal)
    page_size = columns * row_count
    selected_index = state.selected_index()
    page = selected_index // page_size
    start = page * page_size
    visible = state.styles[start : start + page_size]
    state.set_visible_styles(visible, now=now)
    sessions: list[AnimationSessionState] = []
    cards: list[tuple[str, ...]] = []
    for style in visible:
        session = state.session_for(style, now=now)
        sessions.append(session)
        key = (
            style,
            max(1, card_width - 2),
            max(1, card_height - 3),
            terminal.color,
            terminal.ascii,
            session.theme,
        )
        if (
            style in state.dirty_styles
            or key not in state.frames
            or (session.next_deadline is not None and now >= session.next_deadline)
        ):
            state.frames[key] = renderer.render(
                session,
                width=max(1, card_width - 2),
                height=max(1, card_height - 3),
                color=terminal.color,
                ascii=terminal.ascii,
                now=now,
                translator=translator,
            ).rows
            state.dirty_styles.discard(style)
        cards.append(
            _gallery_card(
                state.frames[key],
                style,
                selected=style == state.selected_style,
                width=card_width,
                height=card_height,
                ascii=terminal.ascii,
            )
        )
    output: list[str] = []
    for row in range(row_count):
        group = cards[row * columns : (row + 1) * columns]
        for line in range(card_height):
            output.append(
                clip_width(
                    "".join(pad_width(card[line], card_width) for card in group), terminal.width
                )
            )
    pages = max(1, (len(state.styles) + page_size - 1) // page_size)
    output.append(
        translator.text(
            "status.animation_gallery_page",
            page=page + 1,
            pages=pages,
            start=start + 1,
            end=min(start + len(visible), len(state.styles)),
            count=len(state.styles),
        )
    )
    return tuple(output), tuple(sessions)


def _gallery_wait_seconds(sessions: tuple[AnimationSessionState, ...], now: float) -> float:
    deadlines = tuple(
        session.next_deadline for session in sessions if session.next_deadline is not None
    )
    return _POLL_SECONDS if not deadlines else min(_POLL_SECONDS, max(0.0, min(deadlines) - now))


def _run_gallery(options: AnimationLaunch, translator: Translator) -> int:
    state = GalleryState(animation_style_choices("standalone"), options.animation.style)
    renderer = AnimationRenderer()
    screen = FramePainter()
    last_size: tuple[int, int] | None = None
    try:
        with tui_input_mode() as decoder:
            while True:
                terminal = _terminal(options)
                size = (terminal.width, terminal.height)
                now = time.monotonic()
                state.refresh_catalog(animation_style_choices("standalone"), now=now)
                rows, sessions = _gallery_rows(state, renderer, terminal, translator, now=now)
                status = translator.text(
                    "status.animation_gallery",
                    state=translator.text(
                        "status.animation_running"
                        if state.playback_requested
                        else "status.animation_paused"
                    ),
                )
                screen.paint(
                    compose_frame(
                        "\n".join(rows),
                        status,
                        translator.text("status.animation_gallery_controls"),
                        height=terminal.height,
                    ),
                    force=last_size is not None and last_size != size,
                )
                last_size = size
                event = read_event(decoder, _gallery_wait_seconds(sessions, time.monotonic()))
                if not isinstance(event, KeyEvent):
                    continue
                key = event.value
                now = time.monotonic()
                if key in {"q", "Q", "\x03"}:
                    break
                if key == " ":
                    state.set_playback_requested(not state.playback_requested, now=now)
                elif key in {"t", "T"} and state.selected_style:
                    session = state.session_for(state.selected_style, now=now)
                    _cycle_theme(session, step=1 if key == "t" else -1, now=now)
                    state.mark_theme_changed(state.selected_style)
                elif key in {"j", "\x1b[C"}:
                    state.select(state.selected_index() + 1)
                elif key in {"k", "\x1b[D"}:
                    state.select(state.selected_index() - 1)
                elif key == "\x1b[B":
                    columns, _, _, _ = _gallery_geometry(terminal)
                    state.select(state.selected_index() + columns)
                elif key == "\x1b[A":
                    columns, _, _, _ = _gallery_geometry(terminal)
                    state.select(state.selected_index() - columns)
    except KeyboardInterrupt:
        pass
    finally:
        screen.finish()
    return 0


def run_animation(options: AnimationLaunch, translator: Translator) -> int:
    """Run an interactive animation without creating any provider-facing work."""

    if options.gallery:
        return _run_gallery(options, translator)
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
                    session.set_host_paused(
                        not session.host_paused,
                        now,
                        pause_label=translator.text("status.animation_paused"),
                    )
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
