"""Direct, bounded wheel scrolling for rendered Ranking rows."""

from __future__ import annotations

from dataclasses import dataclass, replace


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


def advance_ranking_wheel(viewport: RankingViewport, *, delta: int) -> RankingViewport:
    """Apply one physical wheel report without retaining future movement."""
    if delta == 0 or viewport.maximum_offset == 0:
        return replace(viewport, offset=viewport.display_offset)
    step = max(1, viewport.visible_rows // 8)
    offset = viewport.offset + (step if delta > 0 else -step)
    return replace(viewport, offset=min(viewport.maximum_offset, max(0, offset)))
