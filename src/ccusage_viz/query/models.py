from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeAlias

from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice, UsageRecord
from ccusage_viz.lifecycle import QueryTrigger


class DataResolution(StrEnum):
    DATE = "date"
    RANGE = "range"
    TIMESTAMP = "timestamp"


@dataclass(frozen=True, order=True, slots=True)
class ProviderRef:
    provider_id: str
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider ID must not be empty")
        if self.source_id == "":
            raise ValueError("source ID must not be empty")


@dataclass(frozen=True, slots=True)
class DataScope:
    intervals: tuple[DateInterval, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "intervals", DateCoverage(self.intervals).intervals)


Scalar: TypeAlias = str | int | float | bool | None
Option: TypeAlias = tuple[str, Scalar]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    executable: str
    timeout: float
    output_limit: int
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.executable:
            raise ValueError("executable must not be empty")
        if self.timeout <= 0:
            raise ValueError("execution timeout must be positive")
        if self.output_limit <= 0:
            raise ValueError("output limit must be positive")
        keys = tuple(key for key, _ in self.environment)
        if len(set(keys)) != len(keys):
            raise ValueError("environment keys must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("environment must be sorted by key")


@dataclass(frozen=True, slots=True)
class QueryIntent:
    owner_id: str
    generation: int
    trigger: QueryTrigger
    provider: ProviderRef
    scope: DataScope
    missing_intervals: tuple[DateInterval, ...]
    resolution: DataResolution
    dimensions: tuple[str, ...] = ()
    execution_options: tuple[Option, ...] = ()
    execution_context: ExecutionContext | None = None
    _fingerprint_value: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.owner_id:
            raise ValueError("owner ID must not be empty")
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("query dimensions must be unique")
        keys = tuple(key for key, _ in self.execution_options)
        if len(set(keys)) != len(keys):
            raise ValueError("execution option keys must be unique")
        if keys != tuple(sorted(keys)):
            raise ValueError("execution options must be sorted by key")
        missing = DateCoverage(self.missing_intervals).intervals
        if missing != self.missing_intervals:
            object.__setattr__(self, "missing_intervals", missing)
        if any(not DateCoverage(self.scope.intervals).covers(part) for part in missing):
            raise ValueError("missing intervals must be contained by the data scope")
        object.__setattr__(
            self,
            "_fingerprint_value",
            _fingerprint(
                (
                    self.owner_id,
                    self.generation,
                    self.trigger.value,
                    self.provider.provider_id,
                    self.provider.source_id,
                    tuple(
                        (item.since.isoformat(), item.until.isoformat())
                        for item in self.scope.intervals
                    ),
                    tuple(
                        (item.since.isoformat(), item.until.isoformat())
                        for item in self.missing_intervals
                    ),
                    self.resolution.value,
                    self.dimensions,
                    self.execution_options,
                    _execution_key(self.execution_context),
                )
            ),
        )

    @property
    def fingerprint(self) -> str:
        return self._fingerprint_value


@dataclass(frozen=True, slots=True)
class PhysicalQuery:
    provider: ProviderRef
    operation: str
    arguments: tuple[str, ...] = ()
    execution_context: ExecutionContext | None = None
    coverage: DateCoverage = DateCoverage()
    required: bool = True
    _fingerprint_value: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.operation:
            raise ValueError("physical query operation must not be empty")
        object.__setattr__(
            self,
            "_fingerprint_value",
            _fingerprint(
                (
                    self.provider.provider_id,
                    self.provider.source_id,
                    self.operation,
                    self.arguments,
                    _execution_key(self.execution_context),
                )
            ),
        )

    @property
    def fingerprint(self) -> str:
        return self._fingerprint_value


@dataclass(frozen=True, slots=True)
class PhysicalPlan:
    plan_id: str
    queries: tuple[PhysicalQuery, ...]
    notices: tuple[Notice, ...] = ()
    summary_notices: tuple[Notice, ...] = ()

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("physical plan ID must not be empty")


@dataclass(frozen=True, slots=True)
class ProviderProvenance:
    provider: ProviderRef
    physical_fingerprint: str

    def __post_init__(self) -> None:
        if not self.physical_fingerprint:
            raise ValueError("physical fingerprint must not be empty")


Metadata: TypeAlias = tuple[tuple[str, Scalar], ...]


@dataclass(frozen=True, slots=True)
class PhysicalResult:
    query: PhysicalQuery
    payload: bytes
    diagnostics: bytes = b""


@dataclass(frozen=True, slots=True)
class ProviderResultFragment:
    records: tuple[UsageRecord, ...]
    provenance: tuple[ProviderProvenance, ...]
    resolution: DataResolution
    coverage: DateCoverage
    notices: tuple[Notice, ...] = ()
    provider_metadata: Metadata = ()


@dataclass(frozen=True, slots=True)
class ProviderResult:
    records: tuple[UsageRecord, ...]
    provenance: tuple[ProviderProvenance, ...]
    resolution: DataResolution
    coverage: DateCoverage
    notices: tuple[Notice, ...] = ()
    summary_notices: tuple[Notice, ...] = ()
    provider_metadata: Metadata = ()
    includes_project_attribution: bool = False


class QueryKind(StrEnum):
    UNIFIED_DAILY = "unified daily"
    CLAUDE_DAILY_PROJECTS = "Claude daily projects"
    CODEX_SESSIONS = "Codex project sessions"


def _execution_key(context: ExecutionContext | None) -> object:
    if context is None:
        return None
    return (
        context.executable,
        context.timeout,
        context.output_limit,
        context.environment,
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
