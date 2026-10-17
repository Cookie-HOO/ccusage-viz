from __future__ import annotations

import os
import signal
import sys
import threading
import time
from dataclasses import FrozenInstanceError, dataclass
from datetime import date
from threading import Event, Lock

import pytest

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage_definition import CCUSAGE_DEFINITION
from ccusage_viz.providers.demo import DEMO_DEFINITION
from ccusage_viz.query.coordinator import QueryCoordinator
from ccusage_viz.query.models import (
    DataResolution,
    ExecutionContext,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderRef,
    ProviderResult,
    ProviderResultFragment,
)
from ccusage_viz.query.provider import ProviderCapabilities, ProviderDefinition


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


def test_demo_provider_executes_deterministically_in_process() -> None:
    interval = DateInterval(date(2026, 1, 2), date(2026, 1, 3))
    query = PhysicalQuery(
        ProviderRef("demo"),
        "generate",
        ("small", "2026-01-02", "2026-01-03"),
        coverage=DateCoverage((interval,)),
    )

    result = QueryCoordinator().run(PhysicalPlan("demo-plan", (query,)), DEMO_DEFINITION.provider)

    assert result.records
    assert result.coverage == DateCoverage((interval,))
    assert result.provenance == (ProviderProvenance(query.provider, query.fingerprint),)


def test_ccusage_execution_honors_environment_and_output_limit() -> None:
    provider = CCUSAGE_DEFINITION.provider
    context = ExecutionContext(
        sys.executable,
        2,
        128,
        (("CCUSAGE_TEST_VALUE", "visible"),),
    )
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", "import os; print(os.environ['CCUSAGE_TEST_VALUE'])"),
        context,
    )
    result = provider.execute(query, Event())
    assert result.payload == b"visible\n"

    oversized = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", "print('x' * 129)"),
        context,
    )
    with pytest.raises(QueryError) as caught:
        provider.execute(oversized, Event())
    assert caught.value.key == "error.ccusage_output_limit"


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_ccusage_timeout_does_not_wait_for_escaped_pipe_descendant(tmp_path) -> None:
    pid_path = tmp_path / "escaped-child.pid"
    script = (
        "import os, time; "
        "pid = os.fork(); "
        f"pid_path = {str(pid_path)!r}; "
        "pid and (open(pid_path, 'w').write(str(pid)), os._exit(0)); "
        "os.setsid(); time.sleep(30)"
    )
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", script),
        ExecutionContext(sys.executable, 0.1, 1024),
    )
    completed = Event()
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            CCUSAGE_DEFINITION.provider.execute(query, Event())
        except BaseException as exc:
            errors.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    try:
        assert completed.wait(1)
        assert len(errors) == 1
        assert isinstance(errors[0], QueryError)
        assert errors[0].key == "error.ccusage_timeout"
    finally:
        deadline = time.monotonic() + 1
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if pid_path.exists():
            os.kill(int(pid_path.read_text()), signal.SIGKILL)
        thread.join(1)


@dataclass(frozen=True, slots=True)
class RecordingProvider:
    provider = ProviderRef("recording")
    capabilities = ProviderCapabilities((DataResolution.DATE.value,), ())
    calls: list[str]
    lock: Lock
    started: Event
    release: Event

    def compile(self, intent):
        raise AssertionError("not used")

    def fingerprint(self, query: PhysicalQuery) -> str:
        return query.fingerprint

    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
        with self.lock:
            self.calls.append(query.operation)
            self.started.set()
        while not self.release.wait(0.01):
            if cancelled.is_set():
                raise QueryError("error.ccusage_cancelled", query=query.operation)
        return PhysicalResult(query, query.operation.encode())

    def normalize(self, result: PhysicalResult) -> ProviderResultFragment:
        record = UsageRecord(
            date(2026, 1, 2),
            "claude",
            TokenUsage.zero(),
            SourceKind.UNIFIED_DAILY,
        )
        return ProviderResultFragment(
            (record,),
            (ProviderProvenance(result.query.provider, result.query.fingerprint),),
            DataResolution.DATE,
            result.query.coverage,
        )

    def assemble(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> ProviderResult:
        return ProviderResult(
            tuple(record for fragment in fragments for record in fragment.records),
            tuple(item for fragment in fragments for item in fragment.provenance),
            DataResolution.DATE,
            DateCoverage(),
        )


def test_coordinator_shares_only_inflight_work_and_preserves_subscribers() -> None:
    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    query = PhysicalQuery(provider.provider, "shared")
    plan = PhysicalPlan("plan", (query,))
    cancelled = QueryCoordinator(max_parallel=1)
    active = QueryCoordinator(max_parallel=1)
    errors: list[BaseException] = []
    results: list[ProviderResult] = []

    def run_cancelled() -> None:
        try:
            cancelled.run(plan, provider)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run_cancelled)
    first.start()
    assert provider.started.wait(1)
    second = threading.Thread(target=lambda: results.append(active.run(plan, provider)))
    second.start()
    time.sleep(0.05)
    cancelled.cancel()
    provider.release.set()
    first.join(1)
    second.join(1)

    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1
    assert errors and isinstance(errors[0], QueryError)
    assert len(results) == 1

    provider.started.clear()
    provider.release.set()
    active.run(plan, provider)
    assert len(calls) == 2


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


@pytest.mark.parametrize(
    ("first", "second"),
    (
        (
            PhysicalQuery(ProviderRef("recording", "first"), "shared"),
            PhysicalQuery(ProviderRef("recording", "second"), "shared"),
        ),
        (
            PhysicalQuery(ProviderRef("recording"), "shared", ("--since", "2026-01-02")),
            PhysicalQuery(ProviderRef("recording"), "shared", ("--since", "2026-01-03")),
        ),
        (
            PhysicalQuery(
                ProviderRef("recording"),
                "shared",
                execution_context=ExecutionContext("first", 1, 1024),
            ),
            PhysicalQuery(
                ProviderRef("recording"),
                "shared",
                execution_context=ExecutionContext("second", 1, 1024),
            ),
        ),
    ),
)
def test_non_equivalent_physical_queries_do_not_share(
    first: PhysicalQuery, second: PhysicalQuery
) -> None:
    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    coordinator = QueryCoordinator(max_parallel=2)

    first_handle = coordinator.submit(PhysicalPlan("first", (first,)), provider)
    assert provider.started.wait(1)
    second_handle = coordinator.submit(PhysicalPlan("second", (second,)), provider)
    deadline = time.monotonic() + 1
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls == ["shared", "shared"]
    provider.release.set()

    assert first_handle.result(1).records
    assert second_handle.result(1).records


def test_shared_result_is_rebound_to_each_subscriber_query() -> None:
    first_interval = DateInterval(date(2026, 1, 1), date(2026, 1, 2))
    second_interval = DateInterval(date(2026, 2, 1), date(2026, 2, 2))

    @dataclass(frozen=True, slots=True)
    class CoverageProvider(RecordingProvider):
        def normalize(self, result):
            fragment = RecordingProvider.normalize(self, result)
            return ProviderResultFragment(
                fragment.records,
                fragment.provenance,
                fragment.resolution,
                fragment.coverage,
                provider_metadata=(("payload", result.query.payload),),
            )

        def assemble(self, plan, fragments):
            return ProviderResult(
                (),
                tuple(item for fragment in fragments for item in fragment.provenance),
                DataResolution.DATE,
                fragments[0].coverage,
                provider_metadata=fragments[0].provider_metadata,
            )

    provider = CoverageProvider([], Lock(), Event(), Event())
    first_query = PhysicalQuery(
        provider.provider,
        "shared",
        coverage=DateCoverage((first_interval,)),
        payload="first",
    )
    second_query = PhysicalQuery(
        provider.provider,
        "shared",
        coverage=DateCoverage((second_interval,)),
        payload="second",
    )
    first = QueryCoordinator(max_parallel=1).submit(PhysicalPlan("first", (first_query,)), provider)
    assert provider.started.wait(1)
    second = QueryCoordinator(max_parallel=1).submit(
        PhysicalPlan("second", (second_query,)), provider
    )
    provider.release.set()

    first_result = first.result(1)
    second_result = second.result(1)
    assert provider.calls == ["shared"]
    assert first_result.coverage == first_query.coverage
    assert second_result.coverage == second_query.coverage
    assert first_result.provider_metadata == (("payload", "first"),)
    assert second_result.provider_metadata == (("payload", "second"),)


def test_immediate_duplicate_fingerprint_in_one_plan_executes_once() -> None:
    provider = RecordingProvider([], Lock(), Event(), Event())
    first = PhysicalQuery(provider.provider, "shared", payload="first")
    second = PhysicalQuery(provider.provider, "shared", payload="second")
    handle = QueryCoordinator(max_parallel=2).submit(
        PhysicalPlan("duplicates", (first, second)), provider
    )
    assert provider.started.wait(1)
    provider.release.set()

    result = handle.result(1)
    assert provider.calls == ["shared"]
    assert len(result.records) == 2


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


def test_shared_physical_work_is_assembled_into_independent_owner_results() -> None:
    @dataclass(frozen=True, slots=True)
    class OwnerProvider(RecordingProvider):
        def assemble(
            self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
        ) -> ProviderResult:
            assembled = RecordingProvider.assemble(self, plan, fragments)
            return ProviderResult(
                assembled.records,
                assembled.provenance,
                assembled.resolution,
                assembled.coverage,
                provider_metadata=(("owner", plan.plan_id),),
            )

    calls: list[str] = []
    provider = OwnerProvider(calls, Lock(), Event(), Event())
    query = PhysicalQuery(provider.provider, "shared")
    coordinator = QueryCoordinator(max_parallel=1)

    first = coordinator.submit(PhysicalPlan("first-owner", (query,)), provider)
    assert provider.started.wait(1)
    second = coordinator.submit(PhysicalPlan("second-owner", (query,)), provider)
    time.sleep(0.05)
    provider.release.set()

    first_result = first.result(1)
    second_result = second.result(1)
    assert calls == ["shared"]
    assert first_result is not second_result
    assert first_result.provider_metadata == (("owner", "first-owner"),)
    assert second_result.provider_metadata == (("owner", "second-owner"),)
    with pytest.raises(FrozenInstanceError):
        first_result.provider_metadata = ()  # type: ignore[misc]


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


def test_optional_query_failure_preserves_required_fragments() -> None:
    @dataclass(frozen=True, slots=True)
    class OptionalFailureProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            if query.operation == "optional":
                raise QueryError("error.ccusage_failed", query=query.operation)
            return PhysicalResult(query, query.operation.encode())

    calls: list[str] = []
    provider = OptionalFailureProvider(calls, Lock(), Event(), Event())
    plan = PhysicalPlan(
        "plan",
        (
            PhysicalQuery(provider.provider, "required"),
            PhysicalQuery(provider.provider, "optional", required=False),
        ),
    )

    result = QueryCoordinator(max_parallel=2).run(plan, provider)

    assert len(result.records) == 1
    assert result.provenance[0].physical_fingerprint == plan.queries[0].fingerprint


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


def test_irrelevant_speculative_failure_is_ignored() -> None:
    assembled: list[tuple[str, ...]] = []

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            if query.operation == "unused-b":
                raise QueryError("error.ccusage_failed", query=query.operation)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return ()

        def assemble(self, plan, fragments):
            assembled.append(
                tuple(item.provider.source_id or "" for item in fragments[0].provenance)
            )
            return RecordingProvider.assemble(self, plan, fragments)

    provider = ResolverProvider([], Lock(), Event(), Event())
    plan = PhysicalPlan(
        "speculative-failure",
        (
            PhysicalQuery(ProviderRef("recording", "a"), "a"),
            PhysicalQuery(ProviderRef("recording", "unused-b"), "unused-b", speculative=True),
        ),
    )

    assert QueryCoordinator(max_parallel=2).run(plan, provider).records
    assert assembled == [("a",)]


def test_required_speculative_failure_is_fatal_and_skips_assemble() -> None:
    assembled = Event()
    required_b = PhysicalQuery(
        ProviderRef("recording", "required-b"), "required-b", speculative=True
    )

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            if query.operation == "required-b":
                raise QueryError("error.ccusage_failed", query=query.operation)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return (required_b,)

        def assemble(self, plan, fragments):
            assembled.set()
            return super().assemble(plan, fragments)

    provider = ResolverProvider([], Lock(), Event(), Event())
    plan = PhysicalPlan(
        "required-speculative-failure",
        (PhysicalQuery(provider.provider, "a"), required_b),
    )

    with pytest.raises(QueryError) as caught:
        QueryCoordinator(max_parallel=2).run(plan, provider)
    assert caught.value.key == "error.ccusage_failed"
    assert not assembled.is_set()


def test_resolver_rejects_optional_output() -> None:
    optional = PhysicalQuery(ProviderRef("recording"), "optional", required=False)

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query, cancelled):
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return (optional,)

    provider = ResolverProvider([], Lock(), Event(), Event())
    with pytest.raises(ValueError, match="non-required"):
        QueryCoordinator().run(
            PhysicalPlan("optional-resolver", (PhysicalQuery(provider.provider, "primary"),)),
            provider,
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


def test_dynamically_discovered_identical_query_shares_speculative_work() -> None:
    calls: list[str] = []
    speculative_b = PhysicalQuery(
        ProviderRef("recording", "b"),
        "b",
        scheduling_group="speculative-canonical-group",
        scheduling_limit=2,
        speculative=True,
    )
    dynamic_b = PhysicalQuery(ProviderRef("recording", "b"), "b")

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
            with self.lock:
                self.calls.append(query.operation)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return (dynamic_b,)

    provider = ResolverProvider(calls, Lock(), Event(), Event())
    result = QueryCoordinator(max_parallel=2).run(
        PhysicalPlan("dynamic-share", (PhysicalQuery(provider.provider, "a"), speculative_b)),
        provider,
    )

    assert calls.count("b") == 1
    assert len(result.records) == 2


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


def test_duplicate_dynamic_queries_share_one_physical_execution() -> None:
    dynamic = PhysicalQuery(ProviderRef("recording"), "dynamic")

    @dataclass(frozen=True, slots=True)
    class ResolverProvider(RecordingProvider):
        def execute(self, query, cancelled):
            with self.lock:
                self.calls.append(query.operation)
            return PhysicalResult(query, query.operation.encode())

        def resolve_queries(self, plan, primary_fragments):
            return (dynamic, dynamic)

    provider = ResolverProvider([], Lock(), Event(), Event())
    result = QueryCoordinator(max_parallel=2).run(
        PhysicalPlan("dynamic-duplicates", (PhysicalQuery(provider.provider, "primary"),)),
        provider,
    )

    assert provider.calls.count("dynamic") == 1
    assert len(result.records) == 3


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


def test_scheduling_group_registry_is_process_wide() -> None:
    provider = RecordingProvider([], Lock(), Event(), Event())
    first = PhysicalQuery(
        provider.provider, "one", scheduling_group="global-limit-conflict", scheduling_limit=1
    )
    second = PhysicalQuery(
        provider.provider, "two", scheduling_group="global-limit-conflict", scheduling_limit=2
    )
    first_handle = QueryCoordinator().submit(PhysicalPlan("first", (first,)), provider)
    assert provider.started.wait(1)
    second_handle = QueryCoordinator().submit(PhysicalPlan("second", (second,)), provider)
    with pytest.raises(ValueError, match="conflicting scheduling limits"):
        second_handle.result(1)
    provider.release.set()
    assert first_handle.result(1).records


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


def test_cancelled_coordinator_rejects_new_work() -> None:
    calls: list[str] = []
    provider = RecordingProvider(calls, Lock(), Event(), Event())
    coordinator = QueryCoordinator()
    coordinator.cancel()

    with pytest.raises(RuntimeError, match="coordinator is cancelled"):
        coordinator.submit(
            PhysicalPlan("plan", (PhysicalQuery(provider.provider, "query"),)), provider
        )


def test_ccusage_execution_bounds_stderr_and_times_out_pipe_holding_descendants() -> None:
    provider = CCUSAGE_DEFINITION.provider
    context = ExecutionContext(sys.executable, 0.2, 1024)
    noisy = PhysicalQuery(
        ProviderRef("ccusage"),
        "unified_daily",
        ("-c", "import os,sys; os.write(2, b'x' * 100000); sys.exit(7)"),
        context,
    )
    with pytest.raises(QueryError) as caught:
        provider.execute(noisy, Event())
    assert caught.value.key == "error.ccusage_failed"
    assert len(caught.value.values["stderr"]) == 16 * 1024

    if sys.platform != "win32":
        descendant = PhysicalQuery(
            ProviderRef("ccusage"),
            "unified_daily",
            ("-c", "import os,time; os.fork() and exit(); time.sleep(5)"),
            context,
        )
        started = time.monotonic()
        with pytest.raises(QueryError) as caught:
            provider.execute(descendant, Event())
        assert caught.value.key == "error.ccusage_timeout"
        assert time.monotonic() - started < 2


def test_registry_definitions_are_fully_executable() -> None:
    for definition in (CCUSAGE_DEFINITION, DEMO_DEFINITION):
        assert isinstance(definition, ProviderDefinition)
        assert callable(definition.provider.execute)
        assert callable(definition.provider.normalize)
        assert callable(definition.provider.assemble)
