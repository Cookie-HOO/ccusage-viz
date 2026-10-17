from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from ccusage_viz.project_identity import normalized_absolute_project_path


def resolve_pi_session_cwds(
    session_ids: Iterable[str], *, sessions_root: Path | None = None
) -> dict[str, str]:
    """Return verified Pi session cwd metadata for the requested session IDs only."""

    root = (sessions_root or Path.home() / ".pi" / "agent" / "sessions").resolve()
    wanted = tuple(session_id for session_id in dict.fromkeys(session_ids) if _safe_id(session_id))
    if not wanted:
        return {}
    remaining = set(wanted)
    resolved: dict[str, str] = {}
    try:
        candidates = root.rglob("*.jsonl")
        for path in candidates:
            if not remaining:
                break
            try:
                resolved_path = path.resolve(strict=True)
                resolved_path.relative_to(root)
            except (OSError, ValueError):
                continue
            session_id, cwd = _read_session_header(resolved_path)
            if session_id not in remaining or cwd is None:
                continue
            resolved[session_id] = cwd
            remaining.remove(session_id)
    except OSError:
        return resolved
    return resolved


def _safe_id(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and value not in {".", ".."}


def _read_session_header(path: Path) -> tuple[str | None, str | None]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.loads(handle.readline())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, Mapping) or value.get("type") != "session":
        return None, None
    session_id = value.get("id")
    cwd = value.get("cwd")
    if not isinstance(session_id, str) or not _safe_id(session_id):
        return None, None
    if not isinstance(cwd, str) or normalized_absolute_project_path(cwd) is None:
        return session_id, None
    return session_id, cwd
