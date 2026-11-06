from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RefreshDeltas:
    previous: dict[Hashable, float] = field(default_factory=dict)
    current: dict[Hashable, float] = field(default_factory=dict)
    initialized: bool = False
    label_current: dict[Hashable, float] = field(default_factory=dict)

    def accept(self, values: Mapping[Any, float]) -> None:
        # Labels require an actual per-key baseline; arrows retain new-key deltas.
        self.label_current = {
            key: value - self.previous[key]
            for key, value in values.items()
            if self.initialized and key in self.previous
        }
        if not self.initialized:
            self.current = {}
            self.initialized = True
        else:
            self.current = {
                key: value - self.previous[key] if key in self.previous else value
                for key, value in values.items()
            }
        self.previous = dict(values)

    def clear(self) -> None:
        self.previous.clear()
        self.current.clear()
        self.label_current.clear()
        self.initialized = False


@dataclass(slots=True)
class RefreshRanks:
    previous: dict[Hashable, int] = field(default_factory=dict)
    current: dict[Hashable, int] = field(default_factory=dict)

    def accept(self, ordered_keys: Iterable[Hashable]) -> None:
        ranks = {key: rank for rank, key in enumerate(ordered_keys, start=1)}
        self.current = {
            key: self.previous[key] - rank for key, rank in ranks.items() if key in self.previous
        }
        self.previous = ranks

    def clear(self) -> None:
        self.previous.clear()
        self.current.clear()
