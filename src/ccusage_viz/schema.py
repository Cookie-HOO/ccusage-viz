from __future__ import annotations

from datetime import date
from typing import Any

from ccusage_viz.domain import ModelBreakdown, ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import SchemaError
from ccusage_viz.project_identity import make_project_ref
from ccusage_viz.query.models import QueryKind

_TOKEN_FIELDS = (
    "totalTokens",
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheCreationTokens",
)


def _error(path: str, reason: str) -> SchemaError:
    return SchemaError("error.schema", path=path, reason=reason)


def _object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _error(path, "expected object")
    return value


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise _error(path, "expected array")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(path, "expected non-empty string")
    return value


def _token(value: object, path: str) -> int:
    if type(value) is not int:  # bool is intentionally rejected
        raise _error(path, "expected integer")
    if value < 0:
        raise _error(path, "expected non-negative integer")
    return value


def _usage(row: dict[str, Any], path: str, *, total_optional: bool = False) -> TokenUsage:
    values: dict[str, int] = {}
    for field in _TOKEN_FIELDS[1:]:
        if field not in row:
            raise _error(f"{path}.{field}", "missing field")
        values[field] = _token(row[field], f"{path}.{field}")

    if "totalTokens" in row:
        total = _token(row["totalTokens"], f"{path}.totalTokens")
    elif total_optional:
        total = sum(values.values())
    else:
        raise _error(f"{path}.totalTokens", "missing field")
    try:
        return TokenUsage.from_parts(
            total=total,
            input=values["inputTokens"],
            output=values["outputTokens"],
            cache_read=values["cacheReadTokens"],
            cache_creation=values["cacheCreationTokens"],
        )
    except ValueError as exc:
        raise _error(path, str(exc)) from exc


def _models(row: dict[str, Any], path: str) -> tuple[ModelBreakdown, ...]:
    raw = row.get("modelBreakdowns", row.get("models", []))
    result: list[ModelBreakdown] = []
    if isinstance(raw, dict):
        items = [(name, value) for name, value in raw.items()]
    else:
        items = [(None, value) for value in _array(raw, f"{path}.modelBreakdowns")]
    for index, (mapping_name, item) in enumerate(items):
        model_path = f"{path}.modelBreakdowns[{index}]"
        model = _object(item, model_path)
        name_value = mapping_name or model.get("modelName", model.get("model"))
        name = _string(name_value, f"{model_path}.modelName")
        # Some report shapes omit model totalTokens. Deriving it keeps their
        # components exactly stackable while still validating every component.
        result.append(ModelBreakdown(name, _usage(model, model_path, total_optional=True)))
    return tuple(result)


def _day(row: dict[str, Any], path: str) -> date:
    raw = row.get("date", row.get("period"))
    value = _string(raw, f"{path}.date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _error(f"{path}.date", "expected ISO date") from exc


def _record(
    row: dict[str, Any],
    path: str,
    *,
    agent: str,
    source: SourceKind,
    project: ProjectRef | None = None,
    day: date | None = None,
) -> UsageRecord:
    return UsageRecord(
        day=_day(row, path) if day is None and source is not SourceKind.CODEX_SESSIONS else day,
        agent=agent,
        usage=_usage(row, path),
        source=source,
        project=project,
        models=_models(row, path),
    )


def parse_unified_daily(data: object) -> tuple[UsageRecord, ...]:
    root = _object(data, "$.")
    records: list[UsageRecord] = []
    for day_index, item in enumerate(_array(root.get("daily"), "$.daily")):
        day_path = f"$.daily[{day_index}]"
        daily = _object(item, day_path)
        parsed_day = _day(daily, day_path)
        for agent_index, agent_item in enumerate(_array(daily.get("agents"), f"{day_path}.agents")):
            path = f"{day_path}.agents[{agent_index}]"
            agent_row = _object(agent_item, path)
            agent = _string(agent_row.get("agent"), f"{path}.agent")
            records.append(
                _record(
                    agent_row,
                    path,
                    agent=agent,
                    source=SourceKind.UNIFIED_DAILY,
                    day=parsed_day,
                )
            )
    return tuple(records)


def parse_claude_daily_projects(data: object) -> tuple[UsageRecord, ...]:
    root = _object(data, "$.")
    projects = _object(root.get("projects"), "$.projects")
    records: list[UsageRecord] = []
    for raw_id, rows_value in projects.items():
        project = make_project_ref("claude", raw_id)
        for index, item in enumerate(_array(rows_value, f"$.projects.{raw_id}")):
            path = f"$.projects.{raw_id}[{index}]"
            records.append(
                _record(
                    _object(item, path),
                    path,
                    agent="claude",
                    source=SourceKind.CLAUDE_DAILY_PROJECTS,
                    project=project,
                )
            )
    return tuple(records)


def _codex_rows(root: dict[str, Any]) -> list[object]:
    for field in ("sessions", "session", "data"):
        if field in root:
            return _array(root[field], f"$.{field}")
    raise _error("$.sessions", "missing session array")


def _project_identity(row: dict[str, Any], path: str) -> tuple[str, str]:
    metadata_value = row.get("metadata", {})
    metadata = _object(metadata_value, f"{path}.metadata")
    identity = row.get(
        "project",
        row.get(
            "projectPath",
            row.get("directory", metadata.get("project", metadata.get("cwd"))),
        ),
    )
    raw_id = _string(identity, f"{path}.project")
    display = row.get("projectName", metadata.get("projectName"))
    display_name = (
        make_project_ref("codex", raw_id).display_name
        if display is None
        else _string(display, f"{path}.projectName")
    )
    return raw_id, display_name


def parse_codex_sessions(data: object) -> tuple[UsageRecord, ...]:
    root = _object(data, "$.")
    records: list[UsageRecord] = []
    for index, item in enumerate(_codex_rows(root)):
        path = f"$.sessions[{index}]"
        row = _object(item, path)
        raw_id, display = _project_identity(row, path)
        records.append(
            _record(
                row,
                path,
                agent="codex",
                source=SourceKind.CODEX_SESSIONS,
                project=make_project_ref("codex", raw_id, display),
                day=None,
            )
        )
    return tuple(records)


def parse_usage_records(kind: QueryKind, data: object) -> tuple[UsageRecord, ...]:
    if kind is QueryKind.UNIFIED_DAILY:
        return parse_unified_daily(data)
    if kind is QueryKind.CLAUDE_DAILY_PROJECTS:
        return parse_claude_daily_projects(data)
    if kind is QueryKind.CODEX_SESSIONS:
        return parse_codex_sessions(data)
    raise _error("$", f"unsupported query kind: {kind}")
