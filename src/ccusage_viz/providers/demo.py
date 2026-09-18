from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import date
from threading import Event

from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.demo import generate_demo
from ccusage_viz.domain import UsageRecord
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
    QueryIntent,
)
from ccusage_viz.query.provider import ProviderCapabilities, ProviderDefinition

DEMO_PROVIDER = ProviderRef("demo")


@dataclass(frozen=True, slots=True)
class DemoProvider:
    provider = DEMO_PROVIDER
    capabilities = ProviderCapabilities(
        resolutions=(DataResolution.DATE.value,),
        dimensions=("agent", "model", "project"),
        execution_options=("demo_size",),
        in_process=True,
    )

    def compile(self, intent: QueryIntent) -> PhysicalPlan:
        if intent.provider.provider_id != self.provider.provider_id:
            raise ValueError("demo provider cannot compile an intent for another provider")
        self.capabilities.validate(intent)
        size = str(dict(intent.execution_options).get("demo_size", "small"))
        queries = tuple(
            PhysicalQuery(
                intent.provider,
                "generate",
                (size, interval.since.isoformat(), interval.until.isoformat()),
                intent.execution_context,
                DateCoverage.from_interval(interval.since, interval.until),
            )
            for interval in intent.missing_intervals
        )
        return PhysicalPlan(intent.fingerprint, queries)

    def fingerprint(self, query: PhysicalQuery) -> str:
        if query.provider.provider_id != self.provider.provider_id:
            raise ValueError("demo provider cannot fingerprint another provider's query")
        return query.fingerprint

    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult:
        if query.operation != "generate" or len(query.arguments) != 3:
            raise ValueError(f"unsupported demo operation: {query.operation}")
        if cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=query.operation)
        size, raw_since, raw_until = query.arguments
        records = generate_demo(
            size,
            DateRange(date.fromisoformat(raw_since), date.fromisoformat(raw_until), None),
            cancelled=cancelled.is_set,
        )
        if cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=query.operation)
        return PhysicalResult(query, pickle.dumps(records, protocol=5))

    def normalize(self, result: PhysicalResult) -> ProviderResultFragment:
        records = pickle.loads(result.payload)
        if not isinstance(records, tuple) or not all(
            isinstance(record, UsageRecord) for record in records
        ):
            raise TypeError("invalid demo provider payload")
        return ProviderResultFragment(
            records,
            (ProviderProvenance(result.query.provider, result.query.fingerprint),),
            DataResolution.DATE,
            result.query.coverage,
        )

    def assemble(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> ProviderResult:
        coverage = DateCoverage()
        records = ()
        provenance = ()
        notices = plan.notices
        for fragment in fragments:
            coverage = coverage.merge(fragment.coverage)
            records += fragment.records
            provenance += fragment.provenance
            notices += fragment.notices
        return ProviderResult(
            records,
            provenance,
            DataResolution.DATE,
            coverage,
            notices,
            plan.summary_notices,
            includes_project_attribution=True,
        )


DEMO_DEFINITION = ProviderDefinition(DemoProvider())
