from __future__ import annotations

import sys
import threading
import time

import pytest

from ccusage_viz.errors import QueryError
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.query.models import QueryKind, QueryPlan, QuerySpec


def spec(code: str, kind: QueryKind = QueryKind.UNIFIED_DAILY) -> QuerySpec:
    return QuerySpec(kind, ("-c", code))


def test_runner_decodes_json_and_preserves_plan_order() -> None:
    plan = QueryPlan(
        (
            spec("import json,time; time.sleep(.08); print(json.dumps({'n': 1}))"),
            spec("import json; print(json.dumps({'n': 2}))", QueryKind.CODEX_SESSIONS),
        )
    )
    results = QueryRunner(sys.executable, max_parallel=2).run(plan)
    assert [result.data for result in results] == [{"n": 1}, {"n": 2}]
    assert [result.kind for result in results] == [
        QueryKind.UNIFIED_DAILY,
        QueryKind.CODEX_SESSIONS,
    ]


def test_runner_invokes_popen_without_shell(monkeypatch) -> None:
    import ccusage_viz.query.client as client

    real_popen = client.subprocess.Popen
    seen: dict[str, object] = {}

    def recording_popen(*args, **kwargs):
        seen.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(client.subprocess, "Popen", recording_popen)
    QueryRunner(sys.executable).run(QueryPlan((spec("print('{}')"),)))
    assert seen["shell"] is False
    if sys.platform != "win32":
        assert seen["start_new_session"] is True


def test_runner_reports_missing_executable() -> None:
    binary = "/definitely/missing/ccusage"
    with pytest.raises(QueryError) as caught:
        QueryRunner(binary).run(QueryPlan((spec(""),)))
    assert caught.value.key == "error.ccusage_missing"
    assert caught.value.values == {"binary": binary}


def test_runner_rejects_invalid_utf8_and_json() -> None:
    invalid_utf8 = "import os; os.write(1, bytes([255]))"
    with pytest.raises(QueryError) as caught:
        QueryRunner(sys.executable).run(QueryPlan((spec(invalid_utf8),)))
    assert caught.value.key == "error.ccusage_utf8"

    with pytest.raises(QueryError) as caught:
        QueryRunner(sys.executable).run(QueryPlan((spec("print('not json')"),)))
    assert caught.value.key == "error.ccusage_json"


def test_nonzero_exit_has_bounded_stderr() -> None:
    code = "import os,sys; os.write(2, b'x' * 40000); sys.exit(7)"
    with pytest.raises(QueryError) as caught:
        QueryRunner(sys.executable).run(QueryPlan((spec(code),)))
    assert caught.value.key == "error.ccusage_failed"
    assert caught.value.values["code"] == 7
    stderr = caught.value.values["stderr"]
    assert isinstance(stderr, str)
    assert len(stderr) == 16 * 1024


def test_timeout_terminates_then_reaps(monkeypatch) -> None:
    import ccusage_viz.query.client as client

    calls: list[str] = []

    class Process:
        returncode = None

        def communicate(self, timeout):
            raise client.subprocess.TimeoutExpired("fake", timeout)

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append("wait" if timeout is not None else "reap")
            if timeout is not None:
                raise client.subprocess.TimeoutExpired("fake", timeout)
            self.returncode = -9

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(client.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(QueryError) as caught:
        QueryRunner("fake", timeout=0.01).run(QueryPlan((spec(""),)))
    assert caught.value.key == "error.ccusage_timeout"
    assert calls == ["terminate", "wait", "kill", "reap"]


def test_cancel_stops_running_query() -> None:
    runner = QueryRunner(sys.executable, timeout=10)
    plan = QueryPlan((spec("import time; time.sleep(5); print('{}')"),))
    errors: list[BaseException] = []

    def run() -> None:
        try:
            runner.run(plan)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with runner._lock:
            if runner._processes:
                break
        time.sleep(0.01)
    runner.cancel()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors and isinstance(errors[0], QueryError)
    assert errors[0].key == "error.ccusage_cancelled"
