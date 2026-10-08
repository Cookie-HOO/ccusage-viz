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


def test_resolve_codex_session_cwd_reads_bare_rollout_id_from_its_date_directory(
    tmp_path: Path,
) -> None:
    session_id = "rollout-2026-10-06T21-51-17-01a11170-a2f8-7572-b584-924cf8ed7a66"
    path = tmp_path / "2026" / "10" / "06" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "01a11170-a2f8-7572-b584-924cf8ed7a66",
                    "cwd": "/private/work/repo",
                },
            }
        ),
        encoding="utf-8",
    )

    assert resolve_codex_session_cwds([session_id], sessions_root=tmp_path) == {
        session_id: "/private/work/repo"
    }


def test_resolve_codex_session_cwd_does_not_scan_a_rollout_date_directory(tmp_path: Path) -> None:
    session_id = "rollout-2026-10-06T21-51-17-01a11170-a2f8-7572-b584-924cf8ed7a66"
    other = "rollout-2026-10-06T22-02-56-01a11186-4aa4-7e32-bf61-c6cafdfa27a9"
    path = tmp_path / "2026" / "10" / "06" / f"{other}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "01a11186-4aa4-7e32-bf61-c6cafdfa27a9",
                    "cwd": "/private/work/other-repo",
                },
            }
        ),
        encoding="utf-8",
    )

    assert resolve_codex_session_cwds([session_id], sessions_root=tmp_path) == {}


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
