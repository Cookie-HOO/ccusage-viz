from __future__ import annotations

from collections.abc import Iterator

from ccusage_viz.query.provider import ProviderDefinition


class ProviderRegistry:
    """Private deterministic registry populated only by application bootstrap."""

    __slots__ = ("_definitions", "_frozen")

    def __init__(self) -> None:
        self._definitions: dict[str, ProviderDefinition] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, definition: ProviderDefinition) -> None:
        if self._frozen:
            raise RuntimeError("provider registry is frozen")
        if definition.provider_id in self._definitions:
            raise ValueError(f"duplicate provider ID: {definition.provider_id}")
        self._definitions[definition.provider_id] = definition

    def freeze(self) -> None:
        self._frozen = True

    def get(self, provider_id: str) -> ProviderDefinition:
        try:
            return self._definitions[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown provider ID: {provider_id}") from exc

    def __iter__(self) -> Iterator[ProviderDefinition]:
        return iter(self._definitions.values())

    def __len__(self) -> int:
        return len(self._definitions)
