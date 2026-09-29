"""Host-neutral term-animate discovery, projection, and session state.

This module deliberately owns no terminal I/O, input, scheduling, or provider work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from term_animate.api import curated_catalog, project
from term_animate.catalog import embedding_targets
from term_animate.models import (
    Effect,
    EffectCategory,
    LogicalState,
    StyledRow,
    TerminalCapabilities,
    Viewport,
)

from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator

AnimationTarget = Literal["standalone", "pane", "monitor"]


@dataclass(frozen=True, slots=True)
class AnimationSpec:
    """One host-selectable animation from the installed term-animate catalog."""

    style: str
    display_name: str
    effect: Effect


def _animation_specs(target: AnimationTarget) -> tuple[AnimationSpec, ...]:
    """Discover target-eligible animations in the library's curated order."""

    return tuple(
        AnimationSpec(effect.id, effect.name, effect)
        for effect in curated_catalog().effects()
        if effect.category is not None
        and effect.style is not None
        and target in embedding_targets(effect)
    )


def animation_style_choices(target: AnimationTarget = "standalone") -> tuple[str, ...]:
    """Return the currently installed catalog choices for one ccuv host."""

    return tuple(spec.style for spec in _animation_specs(target))


def animation_spec(style: str, *, target: AnimationTarget = "standalone") -> AnimationSpec:
    """Return a target-eligible animation by its catalog-wide unique effect id."""

    specs = _animation_specs(target)
    try:
        return next(spec for spec in specs if spec.style == style)
    except StopIteration as exc:
        raise UsageError(
            "error.arguments",
            detail=f"animation style must be one of: {', '.join(spec.style for spec in specs)}",
        ) from exc


def default_animation_spec(target: AnimationTarget = "standalone") -> AnimationSpec:
    """Return the first currently installed animation eligible for one host."""

    styles = animation_style_choices(target)
    if not styles:
        raise UsageError("error.arguments", detail=f"no animations are available for {target}")
    return animation_spec(styles[0], target=target)


def last_activity_label(translator: Translator, wall: datetime) -> str:
    """Format the wall-clock time of a Monitor attachment's last active interval."""

    return translator.text("status.animation_last_activity", time=wall.strftime("%H:%M:%S"))


def cycle_monitor_attachment(
    session: AnimationSessionState, *, enabled: bool, step: int, now: float
) -> bool:
    """Cycle a Monitor attachment through catalog styles and its local none state."""

    styles = animation_style_choices("monitor")
    if not enabled:
        session.set_style(animation_spec(styles[0 if step > 0 else -1], target="monitor"), now)
        session.set_visible(True, now)
        return True
    index = styles.index(session.spec.style)
    if (step > 0 and index == len(styles) - 1) or (step < 0 and index == 0):
        session.set_visible(False, now)
        return False
    session.set_style(animation_spec(styles[index + step], target="monitor"), now)
    return True


@dataclass(slots=True)
class AnimationClock:
    """A monotonic clock that counts only active playback time."""

    accumulated_active_seconds: float = 0.0
    resumed_at: float | None = None

    @property
    def playing(self) -> bool:
        return self.resumed_at is not None

    def elapsed(self, now: float) -> float:
        if self.resumed_at is None:
            return self.accumulated_active_seconds
        return self.accumulated_active_seconds + max(0.0, now - self.resumed_at)

    def resume(self, now: float) -> None:
        if self.resumed_at is None:
            self.resumed_at = now

    def freeze(self, now: float) -> None:
        if self.resumed_at is not None:
            self.accumulated_active_seconds = self.elapsed(now)
            self.resumed_at = None


@dataclass(slots=True)
class AnimationRenderResult:
    """The rows and optional repaint deadline produced by one projection."""

    rows: tuple[str, ...]
    next_deadline: float | None
    viable: bool
    error: str | None = None


@dataclass(slots=True)
class AnimationSessionState:
    """Per-instance, in-memory animation state owned by a ccuv host."""

    spec: AnimationSpec
    theme: str
    clock: AnimationClock
    wall_origin: datetime
    playback_requested: bool = True
    idle_animation_requested: bool = False
    host_paused: bool = False
    traversal_frozen_at: float | None = None
    pause_label: str | None = None
    activity_label: str | None = None
    visible: bool = True
    viable: bool = False
    next_deadline: float | None = None

    def set_style(self, spec: AnimationSpec, now: float) -> None:
        self.spec = spec
        self.reconcile_clock(now)

    def set_theme(self, theme: str, now: float) -> None:
        self.theme = theme
        self.reconcile_clock(now)

    def set_visible(self, visible: bool, now: float) -> None:
        self.visible = visible
        self.reconcile_clock(now)

    def set_viable(self, viable: bool, now: float) -> None:
        self.viable = viable
        self.reconcile_clock(now)

    def set_playback_requested(self, requested: bool, now: float) -> None:
        self.playback_requested = requested
        self.reconcile_traversal(now)
        self.reconcile_clock(now)

    def set_idle_animation_requested(self, requested: bool, now: float) -> None:
        """Keep Monitor idle frames playing without treating them as active traffic."""

        self.idle_animation_requested = requested
        self.reconcile_clock(now)

    def reconcile_traversal(self, now: float) -> None:
        """Freeze motion once while inactive or manually paused, retaining its position."""

        if not self.playback_requested or self.host_paused:
            if self.traversal_frozen_at is None:
                self.traversal_frozen_at = self.clock.elapsed(now)
        else:
            self.traversal_frozen_at = None

    def set_host_paused(self, paused: bool, now: float, *, pause_label: str | None = None) -> None:
        self.host_paused = paused
        self.pause_label = pause_label if paused else None
        self.reconcile_traversal(now)
        self.reconcile_clock(now)

    def set_pause_label(self, pause_label: str | None) -> None:
        self.pause_label = pause_label

    def reconcile_clock(self, now: float) -> None:
        if (
            (self.playback_requested or self.idle_animation_requested)
            and self.visible
            and self.viable
        ):
            self.clock.resume(now)
        else:
            self.clock.freeze(now)
            self.next_deadline = None


def _styled_row_text(row: StyledRow, *, color: bool, width: int) -> str:
    """Convert a projected row into a clipped ANSI or plain ccuv terminal row."""

    parts: list[str] = []
    for cell in row.cells:
        if not color:
            parts.append(cell.text)
            continue
        codes: list[str] = []
        if cell.foreground is not None:
            codes.append(f"38;2;{cell.foreground[0]};{cell.foreground[1]};{cell.foreground[2]}")
        if cell.background is not None:
            codes.append(f"48;2;{cell.background[0]};{cell.background[1]};{cell.background[2]}")
        parts.append(
            (f"\x1b[{';'.join(codes)}m" if codes else "") + cell.text + ("\x1b[0m" if codes else "")
        )
    return clip_width("".join(parts), width)


def _fallback_row(translator: Translator, key: str, style: str) -> str:
    """Return the ccuv-owned localized projection-failure row."""

    return translator.text(key, style=style)


class AnimationRenderer:
    """Project term-animate frames without exposing its terminal host behavior."""

    def render(
        self,
        session: AnimationSessionState,
        *,
        width: int,
        height: int,
        color: bool,
        ascii: bool,
        now: float,
        translator: Translator,
    ) -> AnimationRenderResult:
        if width < 1 or height < 1:
            session.set_viable(False, now)
            return AnimationRenderResult((), None, False)

        session.set_viable(True, now)
        viewport = Viewport(columns=width, rows=height)
        capabilities = TerminalCapabilities(
            unicode=not ascii, ascii_only=ascii, color="truecolor" if color else "none"
        )
        try:
            frame = project(
                session.spec.effect,
                viewport=viewport,
                capabilities=capabilities,
                theme=session.theme,
                monotonic_seconds=session.clock.elapsed(now),
                traversal_monotonic_seconds=session.traversal_frozen_at,
                wall_time=(
                    datetime.now().astimezone()
                    if session.spec.effect.category is EffectCategory.TIME
                    else virtual_wall_time(session, now)
                ),
                pause_label=session.pause_label
                or (
                    session.activity_label
                    if not session.playback_requested and not session.host_paused
                    else None
                ),
                logical_state=(
                    LogicalState.ACTIVE
                    if session.playback_requested and not session.host_paused
                    else LogicalState.IDLE
                )
                if session.spec.effect.supports_state
                else None,
            )
        except Exception:
            session.next_deadline = None
            return AnimationRenderResult(
                (
                    clip_width(
                        _fallback_row(
                            translator, "animation.projection_failed", session.spec.style
                        ),
                        width,
                    ),
                ),
                None,
                True,
                "projection_failed",
            )

        elapsed = session.clock.elapsed(now)
        deadline = (
            now + max(0.0, frame.next_deadline_seconds - elapsed)
            if session.clock.playing and frame.next_deadline_seconds is not None
            else None
        )
        session.next_deadline = deadline
        return AnimationRenderResult(
            tuple(_styled_row_text(row, color=color, width=width) for row in frame.rows),
            deadline,
            True,
        )


def new_animation_session(spec: AnimationSpec, *, theme: str) -> AnimationSessionState:
    """Create a frozen session with a process-local virtual wall-clock origin."""

    return AnimationSessionState(
        spec=spec,
        theme=theme,
        clock=AnimationClock(),
        wall_origin=datetime.now().astimezone(),
    )


def virtual_wall_time(session: AnimationSessionState, now: float) -> datetime:
    """Return the wall time advanced only by the session's effective clock."""

    return session.wall_origin + timedelta(seconds=session.clock.elapsed(now))
