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

from .helpers import RecordingProvider


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
