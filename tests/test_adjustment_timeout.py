from __future__ import annotations

import pytest

from ccusage_viz.adjustment_timeout import (
    ADJUSTMENT_IDLE_TIMEOUT_SECONDS,
    HELP_IDLE_TIMEOUT_SECONDS,
    AdjustmentIdleTimer,
    AdjustmentTimeout,
)


def test_adjustment_idle_timer_expires_after_three_minutes() -> None:
    now = 10.0

    def clock() -> float:
        return now

    timer = AdjustmentIdleTimer(clock=clock)
    assert timer.remaining() == ADJUSTMENT_IDLE_TIMEOUT_SECONDS

    now += ADJUSTMENT_IDLE_TIMEOUT_SECONDS - 0.1
    timer.check()

    now += 0.1
    with pytest.raises(AdjustmentTimeout):
        timer.check()


def test_adjustment_idle_timer_only_resets_for_input() -> None:
    now = 10.0

    def clock() -> float:
        return now

    timer = AdjustmentIdleTimer(clock=clock)
    now += 100.0
    assert timer.remaining() == 80.0

    timer.record_input()
    assert timer.remaining() == ADJUSTMENT_IDLE_TIMEOUT_SECONDS

    now += ADJUSTMENT_IDLE_TIMEOUT_SECONDS
    with pytest.raises(AdjustmentTimeout):
        timer.check()


def test_adjustment_idle_timer_restores_remaining_deadline() -> None:
    now = 10.0

    def clock() -> float:
        return now

    timer = AdjustmentIdleTimer.from_remaining(42.0, clock=clock)
    assert timer.remaining() == 42.0

    now += 42.0
    with pytest.raises(AdjustmentTimeout):
        timer.check()


def test_help_idle_timeout_is_ten_minutes() -> None:
    assert HELP_IDLE_TIMEOUT_SECONDS == 600.0
