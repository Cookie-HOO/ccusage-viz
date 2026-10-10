from __future__ import annotations

import json
from pathlib import Path

from ccusage_viz.pi_sessions import resolve_pi_session_cwds


def write_session(root: Path, directory: str, session_id: str, cwd: str) -> None:
    path = root / directory / f"2026-10-09_{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"type": "session", "id": session_id, "cwd": cwd}), encoding="utf-8"
    )


def test_resolve_pi_session_cwds_uses_the_session_header_cwd(tmp_path: Path) -> None:
    write_session(
        tmp_path,
        "--Users-me-Projects-github-projects--",
        "session-github",
        "/Users/me/Projects/github-projects",
    )

    assert resolve_pi_session_cwds(["session-github"], sessions_root=tmp_path) == {
        "session-github": "/Users/me/Projects/github-projects"
    }


def test_resolve_pi_session_cwds_rejects_relative_cwd_and_unsafe_ids(tmp_path: Path) -> None:
    write_session(tmp_path, "project", "session-relative", "relative/project")

    assert resolve_pi_session_cwds(["session-relative", "../outside"], sessions_root=tmp_path) == {}
