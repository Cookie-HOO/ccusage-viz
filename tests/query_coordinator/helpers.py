from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from threading import Event, Lock

from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import QueryError
from ccusage_viz.query.models import (
    DataResolution,
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderProvenance,
    ProviderRef,
    ProviderResult,
    ProviderResultFragment,
)
from ccusage_viz.query.provider import ProviderCapabilities


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
