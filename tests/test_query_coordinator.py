from __future__ import annotations

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
from ccusage_viz.providers.ccusage import CCUSAGE_DEFINITION
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
