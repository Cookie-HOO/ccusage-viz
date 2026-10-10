from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from re import fullmatch

_BARE_ROLLOUT_SESSION_ID = r"rollout-(\d{4})-(\d{2})-(\d{2})T[^/]+"


def resolve_codex_session_cwds(
    session_ids: Iterable[str], *, sessions_root: Path | None = None
) -> dict[str, str]:
    """Return usable cwd metadata for the requested Codex session IDs only.

    Session IDs originate in ccusage output and are therefore treated as
    untrusted relative paths. Missing or malformed local state is normal and
    simply leaves a session unresolved.
    """
    root = (sessions_root or Path.home() / ".codex" / "sessions").resolve()
    archive_root = root.parent / "archived_sessions"
    resolved: dict[str, str] = {}
    for session_id in dict.fromkeys(session_ids):
        if not _is_safe_session_id(session_id):
            continue
        for candidate, allowed_root in _session_candidates(root, archive_root, session_id):
            try:
                path = candidate.resolve(strict=True)
                path.relative_to(allowed_root.resolve())
            except (OSError, ValueError):
                continue
            if path.is_file() and (cwd := _read_session_cwd(path, session_id)) is not None:
                resolved[session_id] = cwd
                break
    return resolved


def _is_safe_session_id(value: str) -> bool:
    path = Path(value)
    return (
        bool(value)
        and not path.is_absolute()
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _session_candidates(
    root: Path, archive_root: Path, session_id: str
) -> tuple[tuple[Path, Path], ...]:
    """Return exact active and archived paths permitted for one ccusage session ID."""

    filename = f"{session_id.rsplit('/', 1)[-1]}.jsonl"
    direct = root.joinpath(*session_id.split("/")).with_name(filename)
    match = fullmatch(_BARE_ROLLOUT_SESSION_ID, session_id)
    if match is None:
        return ((direct, root), (archive_root / filename, archive_root))
    year, month, day = match.groups()
    return (
        (root / year / month / day / filename, root),
        (archive_root / filename, archive_root),
    )


def _read_session_cwd(path: Path, session_id: str) -> str | None:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = _session_meta_cwd(entry, session_id)
                if cwd is not None:
                    return cwd
    except (OSError, UnicodeError):
        return None
    return None


def _session_meta_cwd(value: object, session_id: str) -> str | None:
    if not isinstance(value, dict) or value.get("type") != "session_meta":
        return None
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return None
    metadata_id = payload.get("id")
    if not isinstance(metadata_id, str) or not session_id.endswith(metadata_id):
        return None
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else None
