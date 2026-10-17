from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, Lock

import pytest

from ccusage_viz.errors import QueryError
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.models import (
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderRef,
)

from .helpers import RecordingProvider


def test_physical_query_scheduling_metadata_does_not_change_fingerprint() -> None:
    plain = PhysicalQuery(ProviderRef("recording"), "shared", ("--value", "1"))
    scheduled = PhysicalQuery(
        ProviderRef("recording"),
        "shared",
        ("--value", "1"),
        scheduling_group="project-fallback",
        scheduling_limit=4,
        speculative=True,
    )

    assert scheduled.fingerprint == plain.fingerprint
    assert scheduled.scheduling_group == "project-fallback"
    assert scheduled.scheduling_limit == 4
    assert scheduled.speculative


@pytest.mark.parametrize(
    ("group", "limit"),
    [(None, 4), ("project-fallback", None), ("", 4), ("project-fallback", 0), ("x", -1)],
)
def test_physical_query_rejects_invalid_scheduling_metadata(
    group: str | None, limit: int | None
) -> None:
    with pytest.raises(ValueError, match="scheduling"):
        PhysicalQuery(
            ProviderRef("recording"),
            "invalid",
            scheduling_group=group,
            scheduling_limit=limit,
        )


def test_slow_irrelevant_speculation_does_not_delay_primary_result() -> None:
    slow_started = Event()
    release_slow = Event()

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            if query.operation == "slow-b":
                slow_started.set()
                release_slow.wait(2)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return ()

    provider = ResolverProvider([], Lock(), Event(), Event())
    plan = PhysicalPlan(
        "slow-irrelevant",
        (
            PhysicalQuery(provider.provider, "a"),
            PhysicalQuery(provider.provider, "slow-b", speculative=True),
        ),
    )
    try:
        started = time.monotonic()
        result = QueryCoordinator(max_parallel=2).run(plan, provider)
        assert result.records
        assert slow_started.wait(1)
        assert time.monotonic() - started < 0.5
    finally:
        release_slow.set()


def test_speculation_cannot_starve_max_parallel_primaries() -> None:
    release = Event()
    lock = Lock()
    started: list[str] = []
    primaries_started = Event()

    @dataclass(frozen=True, slots=True)
    class PriorityProvider(RecordingProvider):
        def execute(self, query, cancelled):
            with lock:
                started.append(query.operation)
                if sum(operation.startswith("a") for operation in started) == 2:
                    primaries_started.set()
            assert release.wait(1)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return tuple(query for query in plan.queries if query.speculative)

    provider = PriorityProvider([], Lock(), Event(), Event())
    queries = tuple(
        PhysicalQuery(provider.provider, f"b{index}", speculative=True) for index in range(4)
    ) + (
        PhysicalQuery(provider.provider, "a0"),
        PhysicalQuery(provider.provider, "a1"),
        PhysicalQuery(provider.provider, "a2"),
    )
    handle = QueryCoordinator(max_parallel=2).submit(PhysicalPlan("priority", queries), provider)
    assert primaries_started.wait(1)
    with lock:
        assert started == ["a0", "a1"]
    release.set()
    assert handle.result(1).records


def test_detach_while_waiting_for_execution_slot_skips_execution() -> None:
    release = Event()
    provider = RecordingProvider([], Lock(), Event(), release)
    coordinator = QueryCoordinator(max_parallel=1)
    active = coordinator.submit(
        PhysicalPlan("active", (PhysicalQuery(provider.provider, "active"),)), provider
    )
    assert provider.started.wait(1)
    waiting = coordinator.submit(
        PhysicalPlan("waiting", (PhysicalQuery(provider.provider, "waiting"),)), provider
    )
    time.sleep(0.05)
    waiting.cancel()
    with pytest.raises(QueryError):
        waiting.result(0.2)
    release.set()
    assert active.result(1).records
    time.sleep(0.1)
    assert provider.calls == ["active"]


def test_scheduling_group_limits_speculative_execution_to_four() -> None:
    lock = Lock()
    release = Event()
    four_started = Event()
    active = 0
    maximum = 0

    @dataclass(frozen=True, slots=True)
    class GroupProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            nonlocal active, maximum
            if query.operation.startswith("b"):
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                    if active == 4:
                        four_started.set()
                release.wait(2)
                with lock:
                    active -= 1
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return tuple(query for query in plan.queries if query.speculative)

    provider = GroupProvider([], Lock(), Event(), Event())
    queries = (PhysicalQuery(provider.provider, "a"),) + tuple(
        PhysicalQuery(
            provider.provider,
            f"b{index}",
            scheduling_group="b-group",
            scheduling_limit=4,
            speculative=True,
        )
        for index in range(8)
    )
    handle = QueryCoordinator(max_parallel=8).submit(PhysicalPlan("group-limit", queries), provider)
    assert four_started.wait(1)
    time.sleep(0.05)
    assert maximum == 4
    release.set()
    assert handle.result(1).records
    assert maximum == 4


def test_shared_speculation_survives_one_plan_detaching() -> None:
    b_started = Event()
    release_b = Event()
    allow_detach = Event()
    calls: list[str] = []
    shared_b = PhysicalQuery(ProviderRef("recording", "shared-b"), "shared-b", speculative=True)

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            with self.lock:
                self.calls.append(query.operation)
            if query.operation == "shared-b":
                b_started.set()
                while not release_b.wait(0.01):
                    if cancelled.is_set():
                        raise QueryError("error.ccusage_cancelled", query=query.operation)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            if plan.plan_id == "detach":
                assert allow_detach.wait(1)
                return ()
            return (shared_b,)

    provider = ResolverProvider(calls, Lock(), Event(), Event())
    coordinator = QueryCoordinator(max_parallel=3)
    detached = coordinator.submit(
        PhysicalPlan("detach", (PhysicalQuery(provider.provider, "a1"), shared_b)), provider
    )
    assert b_started.wait(1)
    retained = coordinator.submit(
        PhysicalPlan("retain", (PhysicalQuery(provider.provider, "a2"), shared_b)), provider
    )
    time.sleep(0.05)
    allow_detach.set()
    assert detached.result(1).records
    release_b.set()
    assert retained.result(1).records
    assert calls.count("shared-b") == 1


@pytest.mark.parametrize(
    ("first_scheduling", "second_scheduling"),
    (
        (("scheduled-first", 2), None),
        (None, ("scheduled-second", 2)),
        (("shared-fingerprint-group", 2), ("shared-fingerprint-group", 1)),
        (("canonical-group", 2), ("subscriber-group", 1)),
    ),
)
def test_inflight_fingerprint_shares_despite_different_scheduling_metadata(
    first_scheduling: tuple[str, int] | None,
    second_scheduling: tuple[str, int] | None,
) -> None:
    release = Event()
    provider = RecordingProvider([], Lock(), Event(), release)

    def query(payload: str, scheduling: tuple[str, int] | None) -> PhysicalQuery:
        return PhysicalQuery(
            provider.provider,
            "same",
            payload=payload,
            scheduling_group=None if scheduling is None else scheduling[0],
            scheduling_limit=None if scheduling is None else scheduling[1],
        )

    first_query = query("first", first_scheduling)
    second_query = query("second", second_scheduling)
    first = QueryCoordinator().submit(PhysicalPlan("first", (first_query,)), provider)
    assert provider.started.wait(1)
    second = QueryCoordinator().submit(PhysicalPlan("second", (second_query,)), provider)
    time.sleep(0.05)
    release.set()

    assert first.result(1).records
    assert second.result(1).records
    assert provider.calls == ["same"]


def test_scheduling_group_rejects_conflicting_limits() -> None:
    release = Event()
    provider = RecordingProvider([], Lock(), Event(), release)
    coordinator = QueryCoordinator(max_parallel=2)
    first = PhysicalQuery(provider.provider, "one", scheduling_group="conflict", scheduling_limit=1)
    second = PhysicalQuery(
        provider.provider, "two", scheduling_group="conflict", scheduling_limit=2
    )
    handle = coordinator.submit(PhysicalPlan("conflicting-groups", (first, second)), provider)
    try:
        with pytest.raises(ValueError, match="conflicting scheduling limits"):
            handle.result(1)
    finally:
        release.set()
