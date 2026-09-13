from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import suppress
from threading import Event, Lock
from typing import Final

from ccusage_viz.errors import QueryError
from ccusage_viz.query.models import QueryPlan, QueryResult, QuerySpec

_STDERR_LIMIT: Final = 16 * 1024
_TERMINATE_GRACE: Final = 0.25


class QueryRunner:
    """Run a bounded set of ccusage JSON queries without a shell."""

    def __init__(
        self,
        executable: str = "ccusage",
        *,
        timeout: float = 30.0,
        max_parallel: int = 2,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_parallel < 1:
            raise ValueError("max_parallel must be at least one")
        self.executable = executable
        self.timeout = timeout
        self.max_parallel = max_parallel
        self._cancelled = Event()
        self._lock = Lock()
        self._processes: set[subprocess.Popen[bytes]] = set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            processes = tuple(self._processes)
        for process in processes:
            self._stop(process)

    def run(self, plan: QueryPlan) -> tuple[QueryResult, ...]:
        self._cancelled.clear()
        if not plan.queries:
            return ()
        if len(plan.queries) == 1 or self.max_parallel == 1:
            return tuple(self._run_one(query) for query in plan.queries)

        workers = min(self.max_parallel, len(plan.queries))
        results: list[QueryResult | None] = [None] * len(plan.queries)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ccusage-query")
        futures: dict[Future[QueryResult], int] = {
            executor.submit(self._run_one, query): index for index, query in enumerate(plan.queries)
        }
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except BaseException:
            self.cancel()
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
        return tuple(result for result in results if result is not None)

    def _run_one(self, query: QuerySpec) -> QueryResult:
        if self._cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=query.kind.value)
        command = [self.executable, *query.args]
        with self._lock:
            if self._cancelled.is_set():
                raise QueryError("error.ccusage_cancelled", query=query.kind.value)
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=os.name == "posix",
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                )
            except FileNotFoundError as exc:
                raise QueryError("error.ccusage_missing", binary=self.executable) from exc
            except OSError as exc:
                raise QueryError(
                    "error.ccusage_start", query=query.kind.value, detail=str(exc)
                ) from exc
            self._processes.add(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                self._stop(process)
                raise QueryError(
                    "error.ccusage_timeout",
                    query=query.kind.value,
                    seconds=self.timeout,
                ) from exc
            if self._cancelled.is_set():
                self._stop(process)
                raise QueryError("error.ccusage_cancelled", query=query.kind.value)
        finally:
            with self._lock:
                self._processes.discard(process)

        stderr_text = _decode_stderr(stderr)
        if process.returncode != 0:
            raise QueryError(
                "error.ccusage_failed",
                query=query.kind.value,
                code=process.returncode,
                stderr=stderr_text,
            )
        try:
            text = stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise QueryError("error.ccusage_utf8", query=query.kind.value) from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QueryError(
                "error.ccusage_json",
                query=query.kind.value,
                line=exc.lineno,
                column=exc.colno,
                stderr=stderr_text,
            ) from exc
        return QueryResult(query.kind, data)

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        leader_exited = process.poll() is not None
        _terminate_process_tree(process)
        if leader_exited:
            # A descendant may still hold the captured pipes after its leader exits.
            time.sleep(_TERMINATE_GRACE)
            _kill_process_tree(process)
            with suppress(ChildProcessError):
                process.wait()
            return
        try:
            process.wait(timeout=_TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            with suppress(ChildProcessError):
                process.wait()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix" and hasattr(process, "pid"):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    with suppress(ProcessLookupError):
        process.terminate()


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix" and hasattr(process, "pid"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    with suppress(ProcessLookupError):
        process.kill()


def _decode_stderr(value: bytes) -> str:
    bounded = value[-_STDERR_LIMIT:]
    return bounded.decode("utf-8", errors="replace")
