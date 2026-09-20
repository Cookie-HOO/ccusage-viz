from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass, field
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Generic, TypeVar

from ccusage_viz.errors import QueryError
from ccusage_viz.query.models import PhysicalPlan, PhysicalQuery, PhysicalResult, ProviderResult
from ccusage_viz.query.provider import Provider

_WAIT_INTERVAL = 0.05
_WorkKey = tuple[str, str]
_Result = TypeVar("_Result")


@dataclass(slots=True, eq=False)
class _InFlightQuery:
    key: _WorkKey
    future: Future[PhysicalResult]
    cancelled: Event = field(default_factory=Event)
    subscribers: int = 0


@dataclass(slots=True, eq=False)
class _PlanRun:
    plan: PhysicalPlan
    future: Future[ProviderResult]
    cancelled: Event = field(default_factory=Event)
    lock: Lock = field(default_factory=Lock)
    subscriptions: dict[_InFlightQuery, int] = field(default_factory=dict)
    delivered: bool = False


class QueryHandle(Generic[_Result]):
    """Detachable subscription to one atomic query-plan result."""

    __slots__ = ("_cancel", "_future")

    def __init__(self, future: Future[_Result], cancel: Callable[[], None]) -> None:
        self._future = future
        self._cancel = cancel

    def result(self, timeout: float | None = None) -> _Result:
        return self._future.result(timeout)

    def cancel(self) -> None:
        self._cancel()

    def done(self) -> bool:
        return self._future.done()


class QueryCoordinator:
    """Execute immutable physical plans with bounded, in-flight-only sharing."""

    _inflight_lock = Lock()
    _inflight: dict[_WorkKey, _InFlightQuery] = {}

    def __init__(self, *, max_parallel: int = 2) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be at least one")
        self.max_parallel = max_parallel
        self._execution_slots = BoundedSemaphore(max_parallel)
        self._shutdown = Event()
        self._lock = Lock()
        self._runs: set[_PlanRun] = set()

    def submit(self, plan: PhysicalPlan, provider: Provider) -> QueryHandle[ProviderResult]:
        """Submit a plan and return an independently detachable result handle."""
        if self._shutdown.is_set():
            raise RuntimeError("query coordinator is cancelled")
        future: Future[ProviderResult] = Future()
        run = _PlanRun(plan, future)
        with self._lock:
            if self._shutdown.is_set():
                raise RuntimeError("query coordinator is cancelled")
            self._runs.add(run)
        Thread(
            target=self._complete_plan,
            args=(future, run, plan, provider),
            name="provider-query-plan",
            daemon=True,
        ).start()
        return QueryHandle(future, lambda: self._cancel_run(run))

    def cancel(self) -> None:
        """Cancel every plan owned by this coordinator and reject new work."""
        self._shutdown.set()
        with self._lock:
            runs = tuple(self._runs)
        for run in runs:
            self._cancel_run(run)

    def run(self, plan: PhysicalPlan, provider: Provider) -> ProviderResult:
        """Execute one plan synchronously through a detachable subscription."""
        return self.submit(plan, provider).result()

    def _complete_plan(
        self,
        future: Future[ProviderResult],
        run: _PlanRun,
        plan: PhysicalPlan,
        provider: Provider,
    ) -> None:
        try:
            result = self._execute_plan(run, plan, provider)
        except BaseException as exc:
            with run.lock:
                if not future.done():
                    run.delivered = True
                    future.set_exception(exc)
        else:
            with run.lock:
                if not future.done():
                    run.delivered = True
                    future.set_result(result)
        finally:
            self._finish_run(run)

    def _execute_plan(
        self, run: _PlanRun, plan: PhysicalPlan, provider: Provider
    ) -> ProviderResult:
        if not plan.queries:
            return provider.assemble(plan, ())
        if any(
            query.provider.provider_id != provider.provider.provider_id for query in plan.queries
        ):
            raise ValueError("physical plan contains a query for another provider")

        workers = min(self.max_parallel, len(plan.queries))
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="provider-query")
        futures = {
            executor.submit(self._run_one, run, provider, query): index
            for index, query in enumerate(plan.queries)
        }
        results: list[PhysicalResult | None] = [None] * len(plan.queries)
        try:
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except BaseException:
                    if (
                        run.cancelled.is_set()
                        or self._shutdown.is_set()
                        or plan.queries[index].required
                    ):
                        raise
        except BaseException:
            self._detach_run(run)
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
        ordered = tuple(result for result in results if result is not None)
        fragments = tuple(provider.normalize(result) for result in ordered)
        return provider.assemble(plan, fragments)

    def _run_one(self, run: _PlanRun, provider: Provider, query: PhysicalQuery) -> PhysicalResult:
        if run.cancelled.is_set() or self._shutdown.is_set():
            raise _cancelled(query)
        key = (provider.provider.provider_id, provider.fingerprint(query))
        entry, owner = self._subscribe(run, key, query)
        if owner:
            Thread(
                target=self._execute_bounded,
                args=(key, entry, provider, query),
                name="provider-query-execution",
                daemon=True,
            ).start()
        try:
            return self._await(run, entry, query)
        finally:
            self._unsubscribe(run, entry)

    def _subscribe(
        self, run: _PlanRun, key: _WorkKey, query: PhysicalQuery
    ) -> tuple[_InFlightQuery, bool]:
        with self._inflight_lock:
            entry = self._inflight.get(key)
            owner = entry is None
            if entry is None:
                entry = _InFlightQuery(key, Future())
                self._inflight[key] = entry
            entry.subscribers += 1
        with run.lock:
            if run.cancelled.is_set() or self._shutdown.is_set():
                self._release(key, entry)
                raise _cancelled(query)
            run.subscriptions[entry] = run.subscriptions.get(entry, 0) + 1
        return entry, owner

    def _unsubscribe(self, run: _PlanRun, entry: _InFlightQuery) -> None:
        with run.lock:
            count = run.subscriptions.get(entry, 0)
            if count == 0:
                return
            if count == 1:
                del run.subscriptions[entry]
            else:
                run.subscriptions[entry] = count - 1
        self._release(entry.key, entry)

    def _cancel_run(self, run: _PlanRun) -> None:
        with run.lock:
            if run.delivered:
                return
            run.cancelled.set()
            if not run.future.done():
                run.future.set_exception(_cancelled_plan(run.plan))
        self._detach_run(run)

    def _detach_run(self, run: _PlanRun) -> None:
        with run.lock:
            subscriptions = tuple(run.subscriptions.items())
            run.subscriptions.clear()
        for entry, count in subscriptions:
            self._release(entry.key, entry, count)

    def _finish_run(self, run: _PlanRun) -> None:
        self._detach_run(run)
        with self._lock:
            self._runs.discard(run)

    @classmethod
    def _release(cls, key: _WorkKey, entry: _InFlightQuery, count: int = 1) -> None:
        with cls._inflight_lock:
            entry.subscribers -= count
            if entry.subscribers == 0 and not entry.future.done():
                entry.cancelled.set()
                cls._inflight.pop(key, None)

    def _execute_bounded(
        self,
        key: _WorkKey,
        entry: _InFlightQuery,
        provider: Provider,
        query: PhysicalQuery,
    ) -> None:
        with self._execution_slots:
            self._execute(key, entry, provider, query)

    @classmethod
    def _execute(
        cls,
        key: _WorkKey,
        entry: _InFlightQuery,
        provider: Provider,
        query: PhysicalQuery,
    ) -> None:
        try:
            with cls._inflight_lock:
                if entry.subscribers == 0:
                    raise _cancelled(query)
            result = provider.execute(query, entry.cancelled)
        except BaseException as exc:
            cls._complete(key, entry, exception=exc)
        else:
            cls._complete(key, entry, result=result)

    @classmethod
    def _complete(
        cls,
        key: _WorkKey,
        entry: _InFlightQuery,
        *,
        result: PhysicalResult | None = None,
        exception: BaseException | None = None,
    ) -> None:
        with cls._inflight_lock:
            if cls._inflight.get(key) is entry:
                cls._inflight.pop(key)
            if entry.future.done():
                return
            if exception is not None:
                entry.future.set_exception(exception)
            else:
                assert result is not None
                entry.future.set_result(result)

    def _await(self, run: _PlanRun, entry: _InFlightQuery, query: PhysicalQuery) -> PhysicalResult:
        while True:
            if run.cancelled.is_set() or self._shutdown.is_set():
                raise _cancelled(query)
            try:
                result = entry.future.result(timeout=_WAIT_INTERVAL)
            except TimeoutError:
                continue
            except BaseException:
                if run.cancelled.is_set() or self._shutdown.is_set():
                    raise _cancelled(query) from None
                raise
            if run.cancelled.is_set() or self._shutdown.is_set():
                raise _cancelled(query)
            return result


def _cancelled(query: PhysicalQuery) -> QueryError:
    return QueryError("error.ccusage_cancelled", query=query.operation)


def _cancelled_plan(plan: PhysicalPlan) -> QueryError:
    operation = plan.queries[0].operation if plan.queries else plan.plan_id
    return QueryError("error.ccusage_cancelled", query=operation)
