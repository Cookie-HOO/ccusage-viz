from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from ccusage_viz.errors import UsageError

T = TypeVar("T")


def _candidate_labels(candidates: Iterable[SelectorCandidate[T]]) -> tuple[str, int]:
    pool = tuple(candidates)
    primary_counts: dict[str, int] = {}
    for candidate in pool:
        primary = candidate.names[0]
        folded = primary.casefold()
        primary_counts[folded] = primary_counts.get(folded, 0) + 1
    labels = (
        candidate.label
        or (
            candidate.names[-1]
            if primary_counts[candidate.names[0].casefold()] > 1
            else candidate.names[0]
        )
        for candidate in pool
    )
    unique = sorted(set(labels), key=lambda value: (value.casefold(), value))
    preview = unique[:5]
    return "\n".join(f"  - {label}" for label in preview), len(unique) - len(preview)


def _ambiguous_error(
    selector: str, dimension: str, matches: tuple[SelectorCandidate[T], ...]
) -> UsageError:
    candidates, remaining = _candidate_labels(matches)
    key = "error.selector_ambiguous_more" if remaining else "error.selector_ambiguous"
    values: dict[str, object] = {
        "selector": selector,
        "dimension": dimension,
        "candidates": candidates,
    }
    if remaining:
        values["remaining"] = remaining
    return UsageError(key, **values)


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
    expand_exact: Callable[
        [str, tuple[SelectorCandidate[T], ...]], tuple[SelectorCandidate[T], ...]
    ]
    | None = None,
) -> tuple[T, ...]:
    """Resolve selectors by exact match first, then by a unique substring.

    Multiple exact matches may be expanded by a dimension-specific callback. This is
    used for projects, where one display name intentionally selects every agent-scoped
    project carrying that exact name.
    """
    pool = tuple(candidates)
    selected: list[T] = []
    selected_keys: set[Hashable] = set()
    for selector in selectors:
        needle = selector.casefold()
        exact = tuple(
            candidate
            for candidate in pool
            if any(name.casefold() == needle for name in candidate.names)
        )
        if exact:
            matches = expand_exact(selector, exact) if expand_exact else exact
        else:
            matches = tuple(
                candidate
                for candidate in pool
                if any(needle in name.casefold() for name in candidate.names)
            )
            if len(matches) != 1:
                if not matches:
                    raise UsageError(
                        "error.selector_no_match", selector=selector, dimension=dimension
                    )
                raise _ambiguous_error(selector, dimension, matches)
        if len(matches) != 1 and not (exact and expand_exact):
            raise _ambiguous_error(selector, dimension, matches)
        for candidate in matches:
            if candidate.key not in selected_keys:
                selected_keys.add(candidate.key)
                selected.append(candidate.value)
    return tuple(selected)
