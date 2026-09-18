from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Protocol

from ccusage_viz.query.models import (
    PhysicalPlan,
    PhysicalQuery,
    PhysicalResult,
    ProviderRef,
    ProviderResult,
    ProviderResultFragment,
    QueryIntent,
)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    resolutions: tuple[str, ...]
    dimensions: tuple[str, ...]
    execution_options: tuple[str, ...] = ()
    in_process: bool = False

    def validate(self, intent: QueryIntent) -> None:
        if intent.resolution.value not in self.resolutions:
            raise ValueError(f"unsupported resolution: {intent.resolution.value}")
        unsupported_dimensions = set(intent.dimensions).difference(self.dimensions)
        if unsupported_dimensions:
            value = ", ".join(sorted(unsupported_dimensions))
            raise ValueError(f"unsupported dimensions: {value}")
        unsupported_options = {key for key, _ in intent.execution_options}.difference(
            self.execution_options
        )
        if unsupported_options:
            value = ", ".join(sorted(unsupported_options))
            raise ValueError(f"unsupported execution options: {value}")


class ProviderCompiler(Protocol):
    @property
    def provider(self) -> ProviderRef: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def compile(self, intent: QueryIntent) -> PhysicalPlan: ...

    def fingerprint(self, query: PhysicalQuery) -> str: ...


class ProviderExecutor(Protocol):
    def execute(self, query: PhysicalQuery, cancelled: Event) -> PhysicalResult: ...

    def normalize(self, result: PhysicalResult) -> ProviderResultFragment: ...

    def assemble(
        self, plan: PhysicalPlan, fragments: tuple[ProviderResultFragment, ...]
    ) -> ProviderResult: ...


class Provider(ProviderCompiler, ProviderExecutor, Protocol):
    pass


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider: Provider

    @property
    def provider_id(self) -> str:
        return self.provider.provider.provider_id
