from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ccusage_viz.query.models import PhysicalPlan, PhysicalQuery, ProviderRef, QueryIntent


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


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider: ProviderCompiler

    @property
    def provider_id(self) -> str:
        return self.provider.provider.provider_id
