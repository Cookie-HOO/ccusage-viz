import json
from pathlib import Path

from ccusage_viz.codex_sessions import resolve_codex_session_cwds


def write_session(root: Path, session_id: str, entries: list[object]) -> None:
    path = root.joinpath(*session_id.split("/")).with_name(f"{session_id.rsplit('/', 1)[-1]}.jsonl")
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")


def test_resolve_codex_session_cwd_reads_session_meta_only(tmp_path: Path) -> None:
    session_id = "2026/06/04/rollout-abc"
    write_session(
        tmp_path,
        session_id,
        [
            {"type": "response_item", "payload": {"text": "private content"}},
            {"type": "session_meta", "payload": {"id": "abc", "cwd": "/private/work/repo"}},
        ],
    )

    assert resolve_codex_session_cwds([session_id], sessions_root=tmp_path) == {
        session_id: "/private/work/repo"
    }


def test_resolve_codex_session_cwd_ignores_missing_and_unsafe_ids(tmp_path: Path) -> None:
    assert (
        resolve_codex_session_cwds(
            ["missing", "../outside", "/outside", "2026\\bad"], sessions_root=tmp_path
        )
        == {}
    )


def test_resolve_codex_session_cwd_rejects_mismatched_metadata_id(tmp_path: Path) -> None:
    session_id = "2026/06/04/rollout-abc"
    write_session(
        tmp_path,
        session_id,
        [{"type": "session_meta", "payload": {"id": "other", "cwd": "/private/work/repo"}}],
    )

    assert resolve_codex_session_cwds([session_id], sessions_root=tmp_path) == {}


def test_resolve_codex_session_cwd_requires_nonempty_metadata_cwd(tmp_path: Path) -> None:
    session_id = "2026/06/04/rollout-empty"
    write_session(
        tmp_path,
        session_id,
        [{"type": "session_meta", "payload": {"id": "empty", "cwd": ""}}],
    )

    assert resolve_codex_session_cwds([session_id], sessions_root=tmp_path) == {}
