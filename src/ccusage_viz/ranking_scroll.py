"""High-rate, direct scrolling for rendered Ranking rows without inertia."""

from __future__ import annotations

from dataclasses import dataclass, replace

RANKING_SCROLL_FRAME_SECONDS = 1 / 60
RANKING_SCROLL_ACTIVE_SECONDS = 0.050
RANKING_SCROLL_MAX_PENDING_ROWS = 30


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
class RankingScrollQueue:
    """Bounded pending direct movement, discarded immediately after input stops."""

    pending_rows: int = 0
    last_input_at: float | None = None


def enqueue_ranking_scroll(
    queue: RankingScrollQueue, *, delta: int, now: float
) -> RankingScrollQueue:
    """Record one direct input row without scheduling any future inertial motion."""
    direction = 1 if delta > 0 else -1 if delta < 0 else 0
    pending = max(
        -RANKING_SCROLL_MAX_PENDING_ROWS,
        min(RANKING_SCROLL_MAX_PENDING_ROWS, queue.pending_rows + direction),
    )
    return RankingScrollQueue(pending, now)


def advance_ranking_scroll(
    viewport: RankingViewport, queue: RankingScrollQueue, *, now: float
) -> tuple[RankingViewport, RankingScrollQueue]:
    """Display at most one queued row, or drop all stale input after 50ms."""
    if queue.last_input_at is None or now - queue.last_input_at >= RANKING_SCROLL_ACTIVE_SECONDS:
        return viewport, RankingScrollQueue()
    direction = 1 if queue.pending_rows > 0 else -1 if queue.pending_rows < 0 else 0
    if direction == 0 or viewport.maximum_offset == 0:
        return replace(viewport, offset=viewport.display_offset), queue
    offset = min(viewport.maximum_offset, max(0, viewport.offset + direction))
    if offset == viewport.offset:
        return viewport, RankingScrollQueue(0, queue.last_input_at)
    return replace(viewport, offset=offset), RankingScrollQueue(
        queue.pending_rows - direction, queue.last_input_at
    )
