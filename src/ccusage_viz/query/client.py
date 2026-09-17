from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, as_completed
from contextlib import suppress
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Final

from ccusage_viz.errors import QueryError
from ccusage_viz.query.models import QueryPlan, QueryResult, QuerySpec

_STDERR_LIMIT: Final = 16 * 1024
_TERMINATE_GRACE: Final = 0.25
_WAIT_INTERVAL: Final = 0.05
_CommandKey = tuple[str, tuple[str, ...], float]


@dataclass(slots=True, eq=False)
class _InFlightCommand:
    future: Future[object]
    subscribers: int = 0
    process: subprocess.Popen[bytes] | None = None


class QueryRunner:
    """Run a bounded set of ccusage JSON queries without a shell."""

    _inflight_lock = Lock()
    _inflight: dict[_CommandKey, _InFlightCommand] = {}

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
        self._subscriptions: dict[_InFlightCommand, int] = {}

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            subscriptions = tuple(self._subscriptions.items())
            self._subscriptions.clear()
        for entry, count in subscriptions:
            self._release(entry, count)

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
        key: _CommandKey = (self.executable, query.args, self.timeout)
        entry, owner = self._subscribe(key)
        if owner:
            Thread(
                target=self._run_command,
                args=(key, entry, query),
                name="ccusage-query-command",
                daemon=True,
            ).start()
        try:
            data = self._await(entry, query)
            return QueryResult(query.kind, copy.deepcopy(data))
        finally:
            self._unsubscribe(entry)

    def _subscribe(self, key: _CommandKey) -> tuple[_InFlightCommand, bool]:
        with self._inflight_lock:
            entry = self._inflight.get(key)
            owner = entry is None
            if entry is None:
                entry = _InFlightCommand(Future())
                self._inflight[key] = entry
            entry.subscribers += 1
        with self._lock:
            if self._cancelled.is_set():
                self._release(entry)
                raise QueryError("error.ccusage_cancelled", query="query")
            self._subscriptions[entry] = self._subscriptions.get(entry, 0) + 1
        return entry, owner

    def _unsubscribe(self, entry: _InFlightCommand) -> None:
        with self._lock:
            count = self._subscriptions.get(entry, 0)
            if count == 0:
                return
            if count == 1:
                del self._subscriptions[entry]
            else:
                self._subscriptions[entry] = count - 1
        self._release(entry)

    @classmethod
    def _release(cls, entry: _InFlightCommand, count: int = 1) -> None:
        process: subprocess.Popen[bytes] | None = None
        with cls._inflight_lock:
            entry.subscribers -= count
            if entry.subscribers == 0:
                process = entry.process
        if process is not None:
            cls._stop(process)

    def _run_command(self, key: _CommandKey, entry: _InFlightCommand, query: QuerySpec) -> None:
        try:
            with self._inflight_lock:
                if entry.subscribers == 0:
                    raise QueryError("error.ccusage_cancelled", query=query.kind.value)
                process = subprocess.Popen(
                    [self.executable, *query.args],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=os.name == "posix",
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                )
                entry.process = process
            with self._lock:
                self._processes.add(process)
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                self._stop(process)
                raise QueryError(
                    "error.ccusage_timeout", query=query.kind.value, seconds=self.timeout
                ) from exc
            data = self._decode_result(process, stdout, stderr, query)
        except FileNotFoundError:
            self._complete(
                key,
                entry,
                exception=QueryError("error.ccusage_missing", binary=self.executable),
            )
        except BaseException as exc:
            self._complete(key, entry, exception=exc)
        else:
            self._complete(key, entry, result=data)
        finally:
            with self._lock:
                if entry.process is not None:
                    self._processes.discard(entry.process)
            with self._inflight_lock:
                entry.process = None

    @classmethod
    def _complete(
        cls,
        key: _CommandKey,
        entry: _InFlightCommand,
        *,
        result: object | None = None,
        exception: BaseException | None = None,
    ) -> None:
        with cls._inflight_lock:
            cls._inflight.pop(key, None)
            if exception is not None:
                entry.future.set_exception(exception)
            else:
                entry.future.set_result(result)

    def _await(self, entry: _InFlightCommand, query: QuerySpec) -> object:
        while True:
            if self._cancelled.is_set():
                raise QueryError("error.ccusage_cancelled", query=query.kind.value)
            try:
                result = entry.future.result(timeout=_WAIT_INTERVAL)
            except TimeoutError:
                continue
            except BaseException:
                if self._cancelled.is_set():
                    raise QueryError("error.ccusage_cancelled", query=query.kind.value) from None
                raise
            if self._cancelled.is_set():
                raise QueryError("error.ccusage_cancelled", query=query.kind.value)
            return result

    @staticmethod
    def _decode_result(
        process: subprocess.Popen[bytes], stdout: bytes, stderr: bytes, query: QuerySpec
    ) -> object:
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
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise QueryError(
                "error.ccusage_json",
                query=query.kind.value,
                line=exc.lineno,
                column=exc.colno,
                stderr=stderr_text,
            ) from exc

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
