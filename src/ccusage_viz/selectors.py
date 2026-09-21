from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from ccusage_viz.errors import UsageError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SelectorCandidate(Generic[T]):
    key: Hashable
    value: T
    names: tuple[str, ...]
    label: str | None = None


def resolve_selectors(
    selectors: Iterable[str],
    candidates: Iterable[SelectorCandidate[T]],
    *,
    dimension: str,
) -> tuple[T, ...]:
    """Resolve complete selectors with case-insensitive equality only."""
    pool = tuple(candidates)
    selected: list[T] = []
    selected_keys: set[Hashable] = set()
    for selector in selectors:
        matches = tuple(
            candidate
            for candidate in pool
            if any(name.casefold() == selector.casefold() for name in candidate.names)
        )
        if not matches:
            raise UsageError("error.selector_no_match", selector=selector, dimension=dimension)
        for candidate in matches:
            if candidate.key not in selected_keys:
                selected_keys.add(candidate.key)
                selected.append(candidate.value)
    return tuple(selected)
