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
        execution_options=("demo_report_time", "demo_seed", "demo_size"),
        in_process=True,
    )

    def compile(self, intent: QueryIntent) -> PhysicalPlan:
        if intent.provider.provider_id != self.provider.provider_id:
            raise ValueError("demo provider cannot compile an intent for another provider")
        self.capabilities.validate(intent)
        options = dict(intent.execution_options)
        size = str(options.get("demo_size", "small"))
        seed = _option_int(options.get("demo_seed", 0), "demo seed")
        report_time = options.get("demo_report_time")
        if report_time is not None and (
            isinstance(report_time, bool) or not isinstance(report_time, (int, float))
        ):
            raise ValueError("demo report time must be numeric")
        arguments = (
            (size, str(seed))
            if report_time is None
            else (size, str(seed), str(float(report_time)))
        )
        queries = tuple(
            PhysicalQuery(
                intent.provider,
                "generate",
                (
                    arguments[0],
                    interval.since.isoformat(),
                    interval.until.isoformat(),
                    *arguments[1:],
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
        if query.operation != "generate" or len(query.arguments) not in {3, 4, 5}:
            raise ValueError(f"unsupported demo operation: {query.operation}")
        if cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=query.operation)
        size, raw_since, raw_until, *live_arguments = query.arguments
        raw_seed, *report_time = live_arguments or ("0",)
        records = generate_demo(
            size,
            DateRange(date.fromisoformat(raw_since), date.fromisoformat(raw_until)),
            seed=_option_int(raw_seed, "demo seed"),
            report_time=float(report_time[0]) if len(query.arguments) == 5 else None,
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


def _option_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


DEMO_DEFINITION = ProviderDefinition(DemoProvider())
