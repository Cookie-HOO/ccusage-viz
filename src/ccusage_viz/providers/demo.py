from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import date
from threading import Event

from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.demo import generate_demo
from ccusage_viz.domain import ModelBreakdown, TokenUsage, UsageRecord
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
        execution_options=("demo_size", "sample_ordinal"),
        in_process=True,
    )

    def compile(self, intent: QueryIntent) -> PhysicalPlan:
        if intent.provider.provider_id != self.provider.provider_id:
            raise ValueError("demo provider cannot compile an intent for another provider")
        self.capabilities.validate(intent)
        options = dict(intent.execution_options)
        size = str(options.get("demo_size", "small"))
        raw_sample_ordinal = options.get("sample_ordinal")
        if raw_sample_ordinal is not None and not isinstance(raw_sample_ordinal, (str, int)):
            raise ValueError("demo sample ordinal must be an integer")
        sample_arguments = () if raw_sample_ordinal is None else (str(int(raw_sample_ordinal)),)
        queries = tuple(
            PhysicalQuery(
                intent.provider,
                "generate",
                (
                    size,
                    interval.since.isoformat(),
                    interval.until.isoformat(),
                    *sample_arguments,
                ),
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
        if query.operation != "generate" or len(query.arguments) not in {3, 4}:
            raise ValueError(f"unsupported demo operation: {query.operation}")
        if cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=query.operation)
        size, raw_since, raw_until, *ordinal = query.arguments
        raw_ordinal = ordinal[0] if ordinal else "0"
        records = generate_demo(
            size,
            DateRange(date.fromisoformat(raw_since), date.fromisoformat(raw_until), None),
            cancelled=cancelled.is_set,
        )
        sample_ordinal = int(raw_ordinal)
        if sample_ordinal:
            records = tuple(_scale_record(record, _sample_factor(sample_ordinal)) for record in records)
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


def _sample_factor(ordinal: int) -> int:
    if ordinal < 0:
        raise ValueError("demo sample ordinal must be non-negative")
    waveform = (1, 1, 2, 1, 6, 14, 5, 2, 1, 3, 8, 2)
    return sum(waveform[index % len(waveform)] for index in range(ordinal + 1))


def _scale_usage(usage: TokenUsage, factor: int) -> TokenUsage:
    return TokenUsage(
        usage.total * factor,
        usage.input * factor,
        usage.output * factor,
        usage.cache_read * factor,
        usage.cache_creation * factor,
        usage.other * factor,
    )


def _scale_record(record: UsageRecord, factor: int) -> UsageRecord:
    return UsageRecord(
        record.day,
        record.agent,
        _scale_usage(record.usage, factor),
        record.source,
        record.project,
        tuple(ModelBreakdown(model.model, _scale_usage(model.usage, factor)) for model in record.models),
    )


DEMO_DEFINITION = ProviderDefinition(DemoProvider())
