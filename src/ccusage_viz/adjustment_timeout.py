from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

ADJUSTMENT_IDLE_TIMEOUT_SECONDS = 180.0


class AdjustmentTimeout(Exception):
    """Raised when an adjustment receives no input before its deadline."""


@dataclass(slots=True)
class AdjustmentIdleTimer:
    """Track adjustment activity with the monotonic clock."""

    clock: Callable[[], float] = time.monotonic
    timeout: float = ADJUSTMENT_IDLE_TIMEOUT_SECONDS
    deadline: float = field(init=False)

    def __post_init__(self) -> None:
        self.record_input()

    def record_input(self) -> None:
        self.deadline = self.clock() + self.timeout

    def remaining(self) -> float:
        return max(0.0, self.deadline - self.clock())

    def check(self) -> None:
        if self.remaining() == 0.0:
            raise AdjustmentTimeout
