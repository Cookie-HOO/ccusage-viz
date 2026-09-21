from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import NoReturn

import pytest
from dsh_snapshot_contract import parse_dsh_snapshot

from ccusage_viz.errors import SchemaError

_FROM_DAY = date(2026, 9, 22)
_TO_DAY = date(2026, 9, 22)
_TIMEZONE = "Asia/Shanghai"


def _payload() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "sourceId": "dsh",
        "timezone": _TIMEZONE,
        "requestedRange": {"from": _FROM_DAY.isoformat(), "to": _TO_DAY.isoformat()},
        "coverage": {"state": "complete", "semantics": "observed-dsh-storage"},
        "notices": [],
        "records": [
            {
                "date": "2026-09-22",
                "project": "/Users/test/Projects/demo",
                "model": "deepseek/chat",
                "inputTokens": 10,
                "outputTokens": 5,
                "cacheReadTokens": 0,
                "cacheCreationTokens": 3,
                "totalTokens": 18,
            }
        ],
    }


def test_parses_collector_snapshot_into_future_dsh_facts() -> None:
    (fact,) = parse_dsh_snapshot(
        _payload(), timezone=_TIMEZONE, from_day=_FROM_DAY, to_day=_TO_DAY
    ).facts

    assert fact.day == _FROM_DAY
    assert fact.project == "/Users/test/Projects/demo"
    assert fact.model == "deepseek/chat"
    assert fact.usage.total == 18
    assert fact.usage.cache_creation == 3


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda payload: payload.update(schemaVersion=2), "$.schemaVersion"),
        (lambda payload: payload.update(sourceId="other"), "$.sourceId"),
        (lambda payload: payload.update(timezone="UTC"), "$.timezone"),
        (lambda payload: payload["records"][0].update(totalTokens=17), "$.records[0]"),
        (lambda payload: payload["records"][0].update(project=""), "$.records[0].project"),
        (lambda payload: payload["records"][0].update(date="2026-09-23"), "$.records[0].date"),
        (lambda payload: payload["coverage"].update(state="unknown"), "$.coverage.state"),
    ],
)
def test_rejects_invalid_collector_contract(mutation, path: str) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(SchemaError) as caught:
        parse_dsh_snapshot(payload, timezone=_TIMEZONE, from_day=_FROM_DAY, to_day=_TO_DAY)

    assert caught.value.values["path"] == path


@pytest.mark.integration
def test_real_collector_snapshot_matches_ccuv_contract(tmp_path: Path) -> None:
    collector = _collector_binary()
    dsh_home = tmp_path / "dsh-home"
    sessions = dsh_home / "sessions" / "session-a"
    sessions.mkdir(parents=True)
    (sessions / "session.jsonl").write_text(
        "\n".join(
            (
                '{"type":"session","data":{"id":"session-a","createdAt":"2026-09-21T16:30:00Z","cwd":"/Users/test/Projects/demo"}}',
                '{"type":"request/context","time":"2026-09-21T16:30:00Z","data":{"provider":"deepseek","model":"chat"}}',
                '{"type":"assistant/chunk","time":"2026-09-21T16:30:00Z","data":{"turn":1,"step":2,"chunk":{"type":"usage","usage":{"inputTokens":10,"outputTokens":2}}}}',
                '{"type":"assistant/message","time":"2026-09-21T16:31:00Z","data":{"turn":1,"step":2,"message":{"source":{"provider":"deepseek","model":"chat"}},"usage":{"inputTokens":10,"outputTokens":5,"cacheWriteTokens":3}}}',
            )
        )
        + "\n"
    )
    state_dir = tmp_path / "explicit-state"
    environment_state = tmp_path / "environment-state"
    environment = os.environ | {
        "DSH_HOME": str(dsh_home),
        "DSH_TOKEN_COLLECTOR_STATE_DIR": str(environment_state),
    }
    command = [
        str(collector),
        "snapshot",
        "--sync",
        "incremental",
        "--json",
        "--timezone",
        _TIMEZONE,
        "--from",
        _FROM_DAY.isoformat(),
        "--to",
        _TO_DAY.isoformat(),
        "--state-dir",
        str(state_dir),
    ]

    first = _run(command, environment)
    second = _run(command, environment)

    assert first == second
    snapshot = parse_dsh_snapshot(first, timezone=_TIMEZONE, from_day=_FROM_DAY, to_day=_TO_DAY)
    assert snapshot.coverage_state == "complete"
    assert snapshot.notices == ()
    (fact,) = snapshot.facts
    assert (fact.day, fact.project, fact.model, fact.usage.total) == (
        _FROM_DAY,
        "/Users/test/Projects/demo",
        "deepseek/chat",
        18,
    )
    assert state_dir.joinpath("ledger.sqlite3").is_file()
    assert not environment_state.exists()


@pytest.mark.integration
def test_real_collector_preserves_partial_coverage_notice(tmp_path: Path) -> None:
    collector = _collector_binary()
    dsh_home = tmp_path / "dsh-home"
    missing_home = tmp_path / "missing-home"
    sessions = dsh_home / "sessions" / "session-a"
    sessions.mkdir(parents=True)
    (sessions / "session.jsonl").write_text(
        '{"type":"session","data":{"id":"session-a","createdAt":"2026-09-21T16:30:00Z","cwd":"/project"}}\n'
        '{"type":"assistant/message","time":"2026-09-21T16:31:00Z","data":{"turn":1,"step":1,"usage":{"inputTokens":4}}}\n'
    )
    result = _run(
        [
            str(collector),
            "snapshot",
            "--sync",
            "incremental",
            "--json",
            "--timezone",
            _TIMEZONE,
            "--from",
            _FROM_DAY.isoformat(),
            "--to",
            _TO_DAY.isoformat(),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        os.environ | {"DSH_HOME": f"{dsh_home},{missing_home}"},
    )

    snapshot = parse_dsh_snapshot(result, timezone=_TIMEZONE, from_day=_FROM_DAY, to_day=_TO_DAY)
    assert snapshot.coverage_state == "partial"
    assert snapshot.facts
    assert any(notice["code"] == "root-unavailable" for notice in snapshot.notices)


def _collector_binary() -> Path:
    configured = os.environ.get("DSH_COLLECTOR_BIN")
    if configured is None:
        _skip("set DSH_COLLECTOR_BIN to run the real DSH collector integration test")
    collector = Path(configured)
    if not collector.is_file() or not os.access(collector, os.X_OK):
        _skip(f"DSH_COLLECTOR_BIN is not an executable file: {collector}")
    return collector


def _skip(message: str) -> NoReturn:
    raise pytest.skip.Exception(message)


def _run(command: list[str], environment: dict[str, str]) -> object:
    completed = subprocess.run(
        command,
        check=False,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
