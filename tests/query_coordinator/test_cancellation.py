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
    ProviderResult,
    ProviderResultFragment,
)

from .helpers import RecordingProvider


def test_handle_cancellation_detaches_only_its_plan_on_shared_coordinator() -> None:
    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    query = PhysicalQuery(provider.provider, "shared")
    plan = PhysicalPlan("plan", (query,))
    coordinator = QueryCoordinator(max_parallel=1)

    cancelled = coordinator.submit(plan, provider)
    assert provider.started.wait(1)
    active = coordinator.submit(plan, provider)
    time.sleep(0.05)
    cancelled.cancel()
    provider.release.set()

    with pytest.raises(QueryError) as caught:
        cancelled.result(1)
    assert caught.value.key == "error.ccusage_cancelled"
    assert active.result(1).records
    assert calls == ["shared"]

def test_last_subscriber_cancellation_reaches_physical_execution() -> None:
    cancellation_observed = Event()

    @dataclass(frozen=True, slots=True)
    class CancellationProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            with self.lock:
                self.calls.append(query.operation)
                self.started.set()
            assert cancelled.wait(1)
            cancellation_observed.set()
            raise QueryError("error.ccusage_cancelled", query=query.operation)

    provider = CancellationProvider([], Lock(), Event(), Event())
    handle = QueryCoordinator().submit(
        PhysicalPlan("plan", (PhysicalQuery(provider.provider, "shared"),)), provider
    )
    assert provider.started.wait(1)

    handle.cancel()

    with pytest.raises(QueryError) as caught:
        handle.result(0.1)
    assert caught.value.key == "error.ccusage_cancelled"
    assert cancellation_observed.wait(1)

def test_subscriber_launches_when_original_registrant_detaches_before_launch() -> None:
    original_registered = Event()
    subscriber_registered = Event()
    allow_original_launch = Event()
    allow_subscriber_launch = Event()

    class OriginalCoordinator(QueryCoordinator):
        def _launch_initial_batch(self, subscriptions, provider):
            original_registered.set()
            assert allow_original_launch.wait(1)
            super()._launch_initial_batch(subscriptions, provider)

    class SubscriberCoordinator(QueryCoordinator):
        def _launch_initial_batch(self, subscriptions, provider):
            subscriber_registered.set()
            assert allow_subscriber_launch.wait(1)
            super()._launch_initial_batch(subscriptions, provider)

    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    provider.release.set()
    query = PhysicalQuery(provider.provider, "shared")
    plan = PhysicalPlan("owner-loss", (query,))
    original = OriginalCoordinator(max_parallel=1).submit(plan, provider)
    assert original_registered.wait(1)
    subscriber = SubscriberCoordinator(max_parallel=1).submit(plan, provider)
    assert subscriber_registered.wait(1)

    original.cancel()
    allow_subscriber_launch.set()

    with pytest.raises(QueryError) as caught:
        original.result(1)
    assert caught.value.key == "error.ccusage_cancelled"
    assert subscriber.result(1).records
    allow_original_launch.set()
    assert calls == ["shared"]

def test_plan_failure_does_not_cancel_an_unrelated_plan() -> None:
    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    coordinator = QueryCoordinator(max_parallel=2)
    shared = PhysicalQuery(provider.provider, "shared")
    shared_plan = PhysicalPlan("shared-plan", (shared,))
    failing_plan = PhysicalPlan(
        "failing-plan",
        (PhysicalQuery(ProviderRef("other"), "invalid"),),
    )

    active = coordinator.submit(shared_plan, provider)
    assert provider.started.wait(1)
    failing = coordinator.submit(failing_plan, provider)
    with pytest.raises(ValueError, match="another provider"):
        failing.result(1)
    provider.release.set()

    assert active.result(1).records
    assert calls == ["shared"]

def test_cancelled_handle_settles_while_provider_assembly_is_blocked() -> None:
    assembly_started = Event()
    release_assembly = Event()

    @dataclass(frozen=True, slots=True)
    class BlockingAssemblyProvider(RecordingProvider):
        def assemble(
            self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
        ) -> ProviderResult:
            assembly_started.set()
            release_assembly.wait(1)
            return super().assemble(plan, fragments)

    provider = BlockingAssemblyProvider([], Lock(), Event(), Event())
    handle = QueryCoordinator().submit(PhysicalPlan("empty", ()), provider)
    assert assembly_started.wait(1)

    handle.cancel()

    with pytest.raises(QueryError) as caught:
        handle.result(0.1)
    assert caught.value.key == "error.ccusage_cancelled"
    release_assembly.set()

def test_required_failure_settles_before_cancellation_resistant_sibling() -> None:
    sibling_started = Event()
    release_sibling = Event()

    @dataclass(frozen=True, slots=True)
    class ResistantProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            if query.operation == "failure":
                assert sibling_started.wait(1)
                raise QueryError("error.ccusage_failed", query=query.operation)
            sibling_started.set()
            release_sibling.wait(1)
            return PhysicalResult(query, query.operation.encode())

    provider = ResistantProvider([], Lock(), Event(), Event())
    handle = QueryCoordinator(max_parallel=2).submit(
        PhysicalPlan(
            "plan",
            (
                PhysicalQuery(provider.provider, "failure"),
                PhysicalQuery(provider.provider, "resistant"),
            ),
        ),
        provider,
    )

    with pytest.raises(QueryError) as caught:
        handle.result(0.2)
    assert caught.value.key == "error.ccusage_failed"
    release_sibling.set()

def test_cancelled_coordinator_rejects_new_work() -> None:
    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    coordinator = QueryCoordinator()
    coordinator.cancel()

    with pytest.raises(RuntimeError, match="coordinator is cancelled"):
        coordinator.submit(
            PhysicalPlan("plan", (PhysicalQuery(provider.provider, "query"),)), provider
        )
