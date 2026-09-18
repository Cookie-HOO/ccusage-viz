from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
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
