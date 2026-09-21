from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias

NoticeValue: TypeAlias = str | int | float | bool | None


def model_identity(value: str) -> str:
    """Return the sole case-insensitive identity and display form for a model."""
    return value.casefold()


class Agent(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class SourceKind(StrEnum):
    UNIFIED_DAILY = "unified_daily"
    CLAUDE_DAILY_PROJECTS = "claude_daily_projects"
    CODEX_SESSIONS = "codex_sessions"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    total: int
    input: int
    output: int
    cache_read: int
    cache_creation: int
    other: int = 0

    @classmethod
    def from_parts(
        cls,
        *,
        total: int,
        input: int,
        output: int,
        cache_read: int,
        cache_creation: int,
    ) -> TokenUsage:
        values = (total, input, output, cache_read, cache_creation)
        if any(value < 0 for value in values):
            raise ValueError("token counts must be non-negative")
        known = input + output + cache_read + cache_creation
        if known > total:
            raise ValueError("token components exceed totalTokens")
        return cls(total, input, output, cache_read, cache_creation, total - known)

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.total + other.total,
            self.input + other.input,
            self.output + other.output,
            self.cache_read + other.cache_read,
            self.cache_creation + other.cache_creation,
            self.other + other.other,
        )

    def difference(self, previous: TokenUsage) -> TokenUsage | None:
        """Return a cumulative-counter delta, or None when a counter decreased."""
        values = tuple(
            current - before
            for current, before in zip(
                (
                    self.total,
                    self.input,
                    self.output,
                    self.cache_read,
                    self.cache_creation,
                    self.other,
                ),
                (
                    previous.total,
                    previous.input,
                    previous.output,
                    previous.cache_read,
                    previous.cache_creation,
                    previous.other,
                ),
                strict=True,
            )
        )
        if any(value < 0 for value in values):
            return None
        return TokenUsage(*values)

    @classmethod
    def zero(cls) -> TokenUsage:
        return cls(0, 0, 0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class ModelBreakdown:
    model: str
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class ProjectRef:
    agent: str
    raw_id: str
    display_name: str

    @property
    def key(self) -> tuple[str, str]:
        return self.agent, self.raw_id


@dataclass(frozen=True, slots=True)
class UsageRecord:
    day: date | None
    agent: str
    usage: TokenUsage
    source: SourceKind
    project: ProjectRef | None = None
    models: tuple[ModelBreakdown, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Notice:
    key: str
    values: Mapping[str, NoticeValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
