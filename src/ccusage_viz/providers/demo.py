from __future__ import annotations

from dataclasses import dataclass

from ccusage_viz.coverage import DateCoverage
from ccusage_viz.query.models import (
    DataResolution,
    PhysicalPlan,
    PhysicalQuery,
    ProviderRef,
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


DEMO_DEFINITION = ProviderDefinition(DemoProvider())
