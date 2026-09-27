"""Host-neutral term-animate catalog and session state.

This module deliberately owns no terminal I/O, input, scheduling, or provider work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from term_animate.api import project_curated, select_effect
from term_animate.models import (
    EffectCategory,
    LogicalState,
    StyledRow,
    TerminalCapabilities,
    ThemeTokens,
    Viewport,
)

from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.render.palette import get_color_scheme


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


def _xterm_rgb(color: int) -> tuple[int, int, int]:
    """Convert a ccuv xterm palette entry to an RGB terminal color."""

    if not 0 <= color <= 255:
        raise ValueError(f"xterm color must be between 0 and 255: {color}")
    basic = (
        (0, 0, 0),
        (128, 0, 0),
        (0, 128, 0),
        (128, 128, 0),
        (0, 0, 128),
        (128, 0, 128),
        (0, 128, 128),
        (192, 192, 192),
        (128, 128, 128),
        (255, 0, 0),
        (0, 255, 0),
        (255, 255, 0),
        (0, 0, 255),
        (255, 0, 255),
        (0, 255, 255),
        (255, 255, 255),
    )
    if color < 16:
        return basic[color]
    if color < 232:
        value = color - 16
        red, remainder = divmod(value, 36)
        green, blue = divmod(remainder, 6)
        return (
            55 + 40 * red if red else 0,
            55 + 40 * green if green else 0,
            55 + 40 * blue if blue else 0,
        )
    gray = 8 + 10 * (color - 232)
    return gray, gray, gray


def animation_theme_tokens(theme: str) -> ThemeTokens:
    """Map ccuv's semantic xterm palette to term-animate theme tokens."""

    scheme = get_color_scheme(theme)
    return ThemeTokens(
        background=(0, 0, 0),
        foreground=_xterm_rgb(scheme.other),
        accent=_xterm_rgb(scheme.highlight),
        secondary_accent=_xterm_rgb(scheme.cache_creation),
        artwork=_xterm_rgb(scheme.categorical[0]),
        muted=_xterm_rgb(scheme.other),
    )


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
    """Return the ccuv-owned localized compact or projection-failure row."""

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
        if width < session.spec.minimum_columns or height < session.spec.minimum_rows:
            session.set_viable(False, now)
            return AnimationRenderResult(
                (
                    clip_width(
                        _fallback_row(translator, "animation.compact", session.spec.style), width
                    ),
                ),
                None,
                False,
            )

        session.set_viable(True, now)
        viewport = Viewport(columns=width, rows=height)
        capabilities = TerminalCapabilities(
            unicode=not ascii, ascii_only=ascii, color="truecolor" if color else "none"
        )
        try:
            if session.spec.style == "rain":
                frame = project_curated(
                    EffectCategory(session.spec.category),
                    session.spec.style,
                    viewport=viewport,
                    capabilities=capabilities,
                    theme=animation_theme_tokens(session.theme),
                    monotonic_seconds=session.clock.elapsed(now),
                    wall_time=virtual_wall_time(session, now),
                    logical_state=(
                        LogicalState.ACTIVE if session.clock.playing else LogicalState.IDLE
                    ),
                )
            else:
                frame = project_curated(
                    EffectCategory(session.spec.category),
                    session.spec.style,
                    viewport=viewport,
                    capabilities=capabilities,
                    theme=animation_theme_tokens(session.theme),
                    monotonic_seconds=session.clock.elapsed(now),
                    wall_time=virtual_wall_time(session, now),
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

        deadline = frame.next_deadline_seconds if session.clock.playing else None
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
