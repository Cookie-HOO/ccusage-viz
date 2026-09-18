from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass, field
from threading import BoundedSemaphore, Event, Lock, Thread

from ccusage_viz.errors import QueryError
from ccusage_viz.query.models import PhysicalPlan, PhysicalQuery, PhysicalResult, ProviderResult
from ccusage_viz.query.provider import Provider

_WAIT_INTERVAL = 0.05
_WorkKey = tuple[str, str]


@dataclass(slots=True, eq=False)
class _InFlightQuery:
    key: _WorkKey
    future: Future[PhysicalResult]
    cancelled: Event = field(default_factory=Event)
    subscribers: int = 0


class QueryCoordinator:
    """Execute immutable physical plans with bounded, in-flight-only sharing."""

    _inflight_lock = Lock()
    _inflight: dict[_WorkKey, _InFlightQuery] = {}

    def __init__(self, *, max_parallel: int = 2) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be at least one")
        self.max_parallel = max_parallel
        self._execution_slots = BoundedSemaphore(max_parallel)
        self._cancelled = Event()
        self._lock = Lock()
        self._subscriptions: dict[_InFlightQuery, int] = {}

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            subscriptions = tuple(self._subscriptions.items())
            self._subscriptions.clear()
        for entry, count in subscriptions:
            self._release(entry.key, entry, count)

    def run(self, plan: PhysicalPlan, provider: Provider) -> ProviderResult:
        self._cancelled.clear()
        if not plan.queries:
            return provider.assemble(plan, ())
        if any(
            query.provider.provider_id != provider.provider.provider_id for query in plan.queries
        ):
            raise ValueError("physical plan contains a query for another provider")

        workers = min(self.max_parallel, len(plan.queries))
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="provider-query")
        futures = {
            executor.submit(self._run_one, provider, query): index
            for index, query in enumerate(plan.queries)
        }
        results: list[PhysicalResult | None] = [None] * len(plan.queries)
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
        ordered = tuple(result for result in results if result is not None)
        fragments = tuple(provider.normalize(result) for result in ordered)
        return provider.assemble(plan, fragments)

    def _run_one(self, provider: Provider, query: PhysicalQuery) -> PhysicalResult:
        if self._cancelled.is_set():
            raise _cancelled(query)
        key = (provider.provider.provider_id, provider.fingerprint(query))
        entry, owner = self._subscribe(key, query)
        if owner:
            Thread(
                target=self._execute_bounded,
                args=(key, entry, provider, query),
                name="provider-query-execution",
                daemon=True,
            ).start()
        try:
            return self._await(entry, query)
        finally:
            self._unsubscribe(entry)

    def _subscribe(self, key: _WorkKey, query: PhysicalQuery) -> tuple[_InFlightQuery, bool]:
        with self._inflight_lock:
            entry = self._inflight.get(key)
            owner = entry is None
            if entry is None:
                entry = _InFlightQuery(key, Future())
                self._inflight[key] = entry
            entry.subscribers += 1
        with self._lock:
            if self._cancelled.is_set():
                self._release(key, entry)
                raise _cancelled(query)
            self._subscriptions[entry] = self._subscriptions.get(entry, 0) + 1
        return entry, owner

    def _unsubscribe(self, entry: _InFlightQuery) -> None:
        with self._lock:
            count = self._subscriptions.get(entry, 0)
            if count == 0:
                return
            if count == 1:
                del self._subscriptions[entry]
            else:
                self._subscriptions[entry] = count - 1
        self._release(entry.key, entry)

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
            if exception is not None:
                entry.future.set_exception(exception)
            else:
                assert result is not None
                entry.future.set_result(result)

    def _await(self, entry: _InFlightQuery, query: PhysicalQuery) -> PhysicalResult:
        while True:
            if self._cancelled.is_set():
                raise _cancelled(query)
            try:
                result = entry.future.result(timeout=_WAIT_INTERVAL)
            except TimeoutError:
                continue
            except BaseException:
                if self._cancelled.is_set():
                    raise _cancelled(query) from None
                raise
            if self._cancelled.is_set():
                raise _cancelled(query)
            return result


def _cancelled(query: PhysicalQuery) -> QueryError:
    return QueryError("error.ccusage_cancelled", query=query.operation)
