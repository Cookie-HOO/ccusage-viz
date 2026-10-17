from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress
from threading import Event, Thread

from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage_fallback import _STDERR_LIMIT, _TERMINATE_GRACE


def _communicate_bounded(
    process: subprocess.Popen[bytes],
    output_limit: int,
    timeout: float,
    cancelled: Event,
    operation: str,
) -> tuple[bytes, bytes]:
    stdout = bytearray()
    stderr = bytearray()
    exceeded = Event()

    def drain(pipe, target: bytearray, *, bounded: bool) -> None:
        try:
            while chunk := pipe.read1(64 * 1024):
                target.extend(chunk)
                if bounded and len(target) > output_limit:
                    exceeded.set()
                    return
                if not bounded and len(target) > _STDERR_LIMIT:
                    del target[:-_STDERR_LIMIT]
        except (OSError, ValueError):
            # Abnormal cleanup closes the parent pipe to release readers even
            # when an escaped descendant still owns the write end.
            return

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = Thread(
        target=drain,
        args=(process.stdout, stdout),
        kwargs={"bounded": True},
        daemon=True,
    )
    stderr_thread = Thread(
        target=drain,
        args=(process.stderr, stderr),
        kwargs={"bounded": False},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None or stdout_thread.is_alive() or stderr_thread.is_alive():
        if cancelled.is_set():
            _stop(process)
            break
        if exceeded.is_set():
            _stop(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _stop(process)
            break
        time.sleep(0.01)
    if cancelled.is_set() or exceeded.is_set() or timed_out:
        # Do not close or join a stream here. Buffered pipe close can itself
        # wait for a concurrent read1(), and an escaped descendant can retain
        # the write end forever. The daemon readers may finish later, but must
        # never retain this query worker or a coordinator execution slot.
        if cancelled.is_set():
            raise QueryError("error.ccusage_cancelled", query=operation)
        if exceeded.is_set():
            raise QueryError("error.ccusage_output_limit", query=operation, limit=output_limit)
        raise QueryError("error.ccusage_timeout", query=operation, seconds=timeout)
    stdout_thread.join()
    stderr_thread.join()
    return bytes(stdout), bytes(stderr)


def _stop(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with suppress(ChildProcessError):
            process.wait()
        return
    leader_exited = process.poll() is not None
    _signal_process_group(process, signal.SIGTERM)
    if leader_exited:
        time.sleep(_TERMINATE_GRACE)
        _signal_process_group(process, signal.SIGKILL)
        with suppress(ChildProcessError):
            process.wait()
        return
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=_TERMINATE_GRACE)
    _signal_process_group(process, signal.SIGKILL)
    with suppress(ChildProcessError):
        process.wait()


def _signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        with suppress(ProcessLookupError):
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()


def _decode_stderr(value: bytes) -> str:
    return value[-_STDERR_LIMIT:].decode("utf-8", errors="replace")
