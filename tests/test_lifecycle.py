from __future__ import annotations

import pytest

from ccusage_viz.lifecycle import (
    FixedIntervalScheduler,
    LifecycleCoordinator,
    LifecycleTrigger,
    OperationToken,
    query_trigger,
)
from ccusage_viz.query.models import QueryTrigger


def test_scheduler_uses_a_fixed_baseline_and_coalesces_missed_opportunities() -> None:
    scheduler = FixedIntervalScheduler(10, now=100)

    assert not scheduler.due(now=109.9)
    assert scheduler.due(now=110)
    assert scheduler.next_opportunity == 120
    assert scheduler.due(now=145)
    assert scheduler.next_opportunity == 150
    assert not scheduler.due(now=145)


def test_scheduler_pause_resume_preserves_baseline_without_backlog() -> None:
    scheduler = FixedIntervalScheduler(10, now=100)

    scheduler.pause()
    assert not scheduler.due(now=135)

    scheduler.resume(now=135)
    assert scheduler.next_opportunity == 140
    assert not scheduler.due(now=135)
    assert scheduler.due(now=140)


def test_scheduler_rebuild_starts_a_new_sequence_at_modification_time() -> None:
    scheduler = FixedIntervalScheduler(10, now=100)

    scheduler.rebuild(7, now=123)

    assert scheduler.baseline == 123
    assert scheduler.next_opportunity == 130
    assert not scheduler.due(now=129.9)
    assert scheduler.due(now=130)


@pytest.mark.parametrize("interval", (0, -1, float("nan"), float("inf")))
def test_scheduler_rejects_invalid_intervals(interval: float) -> None:
    with pytest.raises(ValueError):
        FixedIntervalScheduler(interval, now=0)


def test_coordinator_allows_one_active_and_one_pending_operation() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    assert coordinator.request(LifecycleTrigger.STARTUP, generation=0, now=0)

    first = coordinator.take_ready(now=0)
    assert first == OperationToken("pane-1", 0, 1, LifecycleTrigger.STARTUP)
    assert coordinator.take_ready(now=0) is None

    assert coordinator.request(LifecycleTrigger.PERIODIC, generation=0, now=10)
    assert coordinator.request(LifecycleTrigger.MANUAL, generation=0, now=11)
    assert coordinator.pending is not None
    assert coordinator.pending.trigger is LifecycleTrigger.MANUAL
    assert coordinator.take_ready(now=11) is None

    assert coordinator.complete(first, generation=0)
    second = coordinator.take_ready(now=11)
    assert second == OperationToken("pane-1", 0, 2, LifecycleTrigger.MANUAL)


def test_configuration_supersedes_pending_work_and_debounces_latest_generation() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    coordinator.request(LifecycleTrigger.PERIODIC, generation=2, now=0)

    coordinator.request(
        LifecycleTrigger.CONFIGURATION,
        generation=3,
        now=1,
        debounce=0.5,
    )
    coordinator.request(
        LifecycleTrigger.CONFIGURATION,
        generation=4,
        now=1.2,
        debounce=0.5,
    )

    assert coordinator.pending is not None
    assert coordinator.pending.generation == 4
    assert coordinator.take_ready(now=1.69) is None
    token = coordinator.take_ready(now=1.7)
    assert token is not None
    assert token.generation == 4
    assert token.trigger is LifecycleTrigger.CONFIGURATION


def test_stale_generation_cannot_replace_newer_pending_intent() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    assert coordinator.request(LifecycleTrigger.CONFIGURATION, generation=4, now=0)

    assert not coordinator.request(LifecycleTrigger.CONFIGURATION, generation=3, now=1)
    assert coordinator.pending is not None
    assert coordinator.pending.generation == 4


def test_same_generation_stale_operation_is_rejected() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    coordinator.request(LifecycleTrigger.PERIODIC, generation=3, now=0)
    stale = coordinator.take_ready(now=0)
    assert stale is not None

    coordinator.request(
        LifecycleTrigger.MANUAL,
        generation=3,
        now=1,
        replace_active=True,
    )
    current = coordinator.take_ready(now=1)
    assert current is not None

    assert not coordinator.complete(stale, generation=3)
    assert coordinator.active == current
    assert coordinator.complete(current, generation=3)


def test_rejected_completion_does_not_clear_active_operation() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    coordinator.request(LifecycleTrigger.STARTUP, generation=2, now=0)
    token = coordinator.take_ready(now=0)
    assert token is not None

    assert not coordinator.complete(token, generation=1)
    assert coordinator.active == token


def test_intentional_detach_cancels_subscription_without_creating_an_error() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    coordinator.request(LifecycleTrigger.PERIODIC, generation=0, now=0)
    token = coordinator.take_ready(now=0)
    assert token is not None
    cancelled: list[bool] = []
    coordinator.attach(token, lambda: cancelled.append(True))

    assert coordinator.detach_active() == token
    assert cancelled == [True]
    assert coordinator.active is None
    assert coordinator.pending is None


def test_pause_cancels_automatic_work_but_allows_manual_and_configuration_work() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    coordinator.request(LifecycleTrigger.PERIODIC, generation=0, now=0)
    automatic = coordinator.take_ready(now=0)
    assert automatic is not None
    cancelled: list[bool] = []
    coordinator.attach(automatic, lambda: cancelled.append(True))

    coordinator.pause()

    assert cancelled == [True]
    coordinator.resume()
    assert coordinator.pending is None
    coordinator.pause()
    assert not coordinator.request(LifecycleTrigger.PERIODIC, generation=0, now=1)
    assert coordinator.request(LifecycleTrigger.MANUAL, generation=0, now=1)
    manual = coordinator.take_ready(now=1)
    assert manual is not None
    assert manual.trigger is LifecycleTrigger.MANUAL
    coordinator.abandon(manual)

    assert coordinator.request(LifecycleTrigger.CONFIGURATION, generation=1, now=2)
    configuration = coordinator.take_ready(now=2)
    assert configuration is not None
    assert configuration.trigger is LifecycleTrigger.CONFIGURATION


def test_shutdown_rejects_late_completion_and_new_intent() -> None:
    coordinator = LifecycleCoordinator("pane-1")
    coordinator.request(LifecycleTrigger.STARTUP, generation=0, now=0)
    token = coordinator.take_ready(now=0)
    assert token is not None

    coordinator.shutdown()

    assert not coordinator.complete(token, generation=0)
    assert not coordinator.request(LifecycleTrigger.MANUAL, generation=0, now=1)
    assert coordinator.active is None
    assert coordinator.pending is None


@pytest.mark.parametrize(
    ("lifecycle", "query"),
    [
        (LifecycleTrigger.STARTUP, QueryTrigger.STARTUP),
        (LifecycleTrigger.PERIODIC, QueryTrigger.TICK),
        (LifecycleTrigger.MANUAL, QueryTrigger.REFRESH),
        (LifecycleTrigger.CONFIGURATION, QueryTrigger.REFRESH),
        (LifecycleTrigger.RESUME, QueryTrigger.REFRESH),
    ],
)
def test_lifecycle_triggers_map_to_existing_query_contract(
    lifecycle: LifecycleTrigger,
    query: QueryTrigger,
) -> None:
    assert query_trigger(lifecycle) is query


def test_unknown_lifecycle_trigger_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown lifecycle trigger"):
        query_trigger("unknown")  # type: ignore[arg-type]
