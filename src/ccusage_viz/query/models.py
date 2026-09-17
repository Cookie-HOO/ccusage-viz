from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ccusage_viz.coverage import DateInterval
from ccusage_viz.domain import Notice


class QueryKind(StrEnum):
    UNIFIED_DAILY = "unified daily"
    CLAUDE_DAILY_PROJECTS = "Claude daily projects"
    CODEX_SESSIONS = "Codex project sessions"


@dataclass(frozen=True, slots=True)
class QuerySpec:
    kind: QueryKind
    args: tuple[str, ...]
    daily_coverage: DateInterval | None = None


@dataclass(frozen=True, slots=True)
class QueryPlan:
    queries: tuple[QuerySpec, ...]
    notices: tuple[Notice, ...] = field(default_factory=tuple)
    summary_notices: tuple[Notice, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class QueryResult:
    kind: QueryKind
    data: object
