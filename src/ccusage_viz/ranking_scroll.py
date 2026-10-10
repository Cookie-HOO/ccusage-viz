"""Direct, bounded wheel scrolling for rendered Ranking rows."""

from __future__ import annotations

from dataclasses import dataclass, replace

WHEEL_BURST_SECONDS = 0.080
WHEEL_BURST_MAX_MULTIPLIER = 4


@dataclass(frozen=True, slots=True)
class RankingViewport:
    """An integer row offset over the non-fixed portion of a Ranking."""

    offset: int = 0
    total_rows: int = 0
    visible_rows: int = 0

    @property
    def maximum_offset(self) -> int:
        return max(0, self.total_rows - max(0, self.visible_rows))

    @property
    def display_offset(self) -> int:
        return min(self.maximum_offset, max(0, self.offset))


@dataclass(frozen=True, slots=True)
class RankingWheelBurst:
    direction: int = 0
    at: float | None = None
    multiplier: int = 0


def advance_ranking_wheel(viewport: RankingViewport, *, delta: int) -> RankingViewport:
    """Apply one direct base step without retaining future movement."""
    return _advance(viewport, delta=delta, multiplier=1)


def advance_ranking_wheel_burst(
    viewport: RankingViewport, burst: RankingWheelBurst, *, delta: int, now: float
) -> tuple[RankingViewport, RankingWheelBurst]:
    """Apply a direct same-direction burst step, never a deferred scroll."""
    direction = 1 if delta > 0 else -1 if delta < 0 else 0
    continuing = (
        direction != 0
        and burst.direction == direction
        and burst.at is not None
        and now - burst.at < WHEEL_BURST_SECONDS
    )
    multiplier = min(WHEEL_BURST_MAX_MULTIPLIER, burst.multiplier + 1) if continuing else 1
    return _advance(viewport, delta=direction, multiplier=multiplier), RankingWheelBurst(
        direction, now, multiplier
    )


def _advance(viewport: RankingViewport, *, delta: int, multiplier: int) -> RankingViewport:
    if delta == 0 or viewport.maximum_offset == 0:
        return replace(viewport, offset=viewport.display_offset)
    step = max(1, viewport.visible_rows // 8) * multiplier
    offset = viewport.offset + (step if delta > 0 else -step)
    return replace(viewport, offset=min(viewport.maximum_offset, max(0, offset)))
