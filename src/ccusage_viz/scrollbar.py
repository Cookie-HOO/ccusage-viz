"""Pure terminal-cell scrollbar geometry and captured-thumb mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scrollbar:
    column: int
    top: int
    height: int
    total_rows: int
    visible_rows: int
    offset: int

    @property
    def maximum_offset(self) -> int:
        return max(0, self.total_rows - self.visible_rows)

    @property
    def thumb_size(self) -> int:
        if self.height <= 0:
            return 0
        size = max(1, self.height * self.visible_rows // max(1, self.total_rows))
        limit = max(1, self.height - 1) if self.maximum_offset else self.height
        return min(size, limit)

    @property
    def travel(self) -> int:
        return max(0, self.height - self.thumb_size)

    @property
    def thumb_top(self) -> int:
        offset = min(max(0, self.offset), self.maximum_offset)
        return self.top + round(offset * self.travel / max(1, self.maximum_offset))

    def contains(self, x: int, y: int) -> bool:
        return x == self.column and self.top <= y < self.top + self.height

    def on_thumb(self, y: int) -> bool:
        return self.thumb_top <= y < self.thumb_top + self.thumb_size

    def page_offset(self, y: int) -> int:
        delta = -self.visible_rows if y < self.thumb_top else self.visible_rows
        if self.on_thumb(y):
            delta = 0
        return min(max(0, self.offset + delta), self.maximum_offset)

    def grab_at(self, y: int) -> int:
        """Row distance from the thumb top to the pressed cell, for drag capture."""
        return y - self.thumb_top

    def offset_at(self, y: int, grab: int = 0) -> int:
        """Clamped scroll offset placing the thumb top at y minus the captured grab."""
        if self.travel <= 0:
            return 0
        target = y - grab - self.top
        return min(max(0, round(target * self.maximum_offset / self.travel)), self.maximum_offset)
