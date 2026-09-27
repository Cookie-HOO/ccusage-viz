"""Host-neutral term-animate catalog and session state.

This module deliberately owns no terminal I/O, input, scheduling, or provider work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from term_animate.api import select_effect
from term_animate.models import EffectCategory

from ccusage_viz.errors import UsageError


@dataclass(frozen=True, slots=True)
class AnimationSpec:
    """The immutable configuration for one explicitly supported animation."""

    style: str
    display_name: str
    category: str
    minimum_columns: int
    minimum_rows: int


_ANIMATION_SPECS = (
    AnimationSpec("mole-cat", "Mole Cat", "animal", 40, 4),
    AnimationSpec("campy-cat", "Campy Cat", "animal", 48, 18),
    AnimationSpec("rain", "Rain", "nature", 60, 10),
    AnimationSpec("analog-clock", "Analog Clock", "time", 30, 13),
    AnimationSpec("digital-clock", "Digital Clock", "time", 40, 6),
)
_SPECS_BY_STYLE = {spec.style: spec for spec in _ANIMATION_SPECS}


def animation_style_choices() -> tuple[str, ...]:
    """Return the fixed public catalog in display and cycling order."""

    return tuple(spec.style for spec in _ANIMATION_SPECS)


def animation_spec(style: str) -> AnimationSpec:
    """Return an allowed animation after verifying its host-neutral library mapping."""

    try:
        spec = _SPECS_BY_STYLE[style]
    except KeyError as exc:
        raise UsageError(
            "error.arguments",
            detail=f"animation style must be one of: {', '.join(animation_style_choices())}",
        ) from exc
    select_effect(EffectCategory(spec.category), spec.style)
    return spec


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
class AnimationSessionState:
    """Per-instance, in-memory animation state owned by a ccuv host."""

    spec: AnimationSpec
    theme: str
    clock: AnimationClock
    wall_origin: datetime
    playback_requested: bool = True
    host_paused: bool = False
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
        self.reconcile_clock(now)

    def set_host_paused(self, paused: bool, now: float) -> None:
        self.host_paused = paused
        self.reconcile_clock(now)

    def reconcile_clock(self, now: float) -> None:
        if self.playback_requested and not self.host_paused and self.visible and self.viable:
            self.clock.resume(now)
        else:
            self.clock.freeze(now)
            self.next_deadline = None


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
