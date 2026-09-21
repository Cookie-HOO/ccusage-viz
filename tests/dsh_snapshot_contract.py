from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, NoReturn, cast

from ccusage_viz.domain import TokenUsage
from ccusage_viz.errors import SchemaError
from ccusage_viz.project_identity import make_project_ref

_SCHEMA_VERSION = 1
_SOURCE_ID = "dsh"
_COVERAGE_STATES = frozenset({"complete", "partial", "empty"})


@dataclass(frozen=True, slots=True)
class DshSnapshotFact:
    day: date
    model: str
    project: str
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class DshSnapshot:
    facts: tuple[DshSnapshotFact, ...]
    coverage_state: str
    notices: tuple[dict[str, object], ...]


def parse_dsh_snapshot(
    payload: object,
    *,
    timezone: str,
    from_day: date,
    to_day: date,
) -> DshSnapshot:
    root = _mapping(payload, "$")
    _equal(root.get("schemaVersion"), _SCHEMA_VERSION, "$.schemaVersion")
    _equal(root.get("sourceId"), _SOURCE_ID, "$.sourceId")
    _equal(root.get("timezone"), timezone, "$.timezone")
    requested_range = _mapping(root.get("requestedRange"), "$.requestedRange")
    _equal(requested_range.get("from"), from_day.isoformat(), "$.requestedRange.from")
    _equal(requested_range.get("to"), to_day.isoformat(), "$.requestedRange.to")

    coverage = _mapping(root.get("coverage"), "$.coverage")
    coverage_state = coverage.get("state")
    if not isinstance(coverage_state, str) or coverage_state not in _COVERAGE_STATES:
        _raise("$.coverage.state", "expected complete, partial, or empty")
    if not isinstance(coverage.get("semantics"), str) or not coverage["semantics"]:
        _raise("$.coverage.semantics", "expected non-empty string")

    notices = _notices(root.get("notices"))
    facts = tuple(
        _fact(row, f"$.records[{index}]", from_day=from_day, to_day=to_day)
        for index, row in enumerate(_array(root.get("records"), "$.records"))
    )
    return DshSnapshot(facts, coverage_state, notices)


def _fact(value: object, path: str, *, from_day: date, to_day: date) -> DshSnapshotFact:
    row = _mapping(value, path)
    day = _date(row.get("date"), f"{path}.date")
    if not from_day <= day <= to_day:
        _raise(f"{path}.date", "outside requested range")
    model = _string(row.get("model"), f"{path}.model")
    project = _string(row.get("project"), f"{path}.project")
    # Validate the exact project form that a later provider will normalize to.
    make_project_ref("dsh", project)
    values = {
        "total": _tokens(row.get("totalTokens"), f"{path}.totalTokens"),
        "input": _tokens(row.get("inputTokens"), f"{path}.inputTokens"),
        "output": _tokens(row.get("outputTokens"), f"{path}.outputTokens"),
        "cache_read": _tokens(row.get("cacheReadTokens"), f"{path}.cacheReadTokens"),
        "cache_creation": _tokens(row.get("cacheCreationTokens"), f"{path}.cacheCreationTokens"),
    }
    if values["total"] != sum(values[key] for key in values if key != "total"):
        _raise(path, "totalTokens must equal the canonical token buckets")
    return DshSnapshotFact(day, model, project, TokenUsage.from_parts(**values))


def _notices(value: object) -> tuple[dict[str, object], ...]:
    notices = []
    for index, item in enumerate(_array(value, "$.notices")):
        row = _mapping(item, f"$.notices[{index}]")
        _string(row.get("code"), f"$.notices[{index}].code")
        notices.append(row)
    return tuple(notices)


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _raise(path, "expected object")
    return cast(dict[str, Any], value)


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        _raise(path, "expected array")
    return cast(list[object], value)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        _raise(path, "expected non-empty string")
    return cast(str, value)


def _tokens(value: object, path: str) -> int:
    if type(value) is not int or value < 0:
        _raise(path, "expected non-negative integer")
    return value


def _date(value: object, path: str) -> date:
    text = _string(value, path)
    try:
        return date.fromisoformat(text)
    except ValueError:
        _raise(path, "expected ISO date")


def _equal(actual: object, expected: object, path: str) -> None:
    if actual != expected:
        _raise(path, f"expected {expected!r}")


def _raise(path: str, reason: str) -> NoReturn:
    raise SchemaError("error.schema", path=path, reason=reason)
