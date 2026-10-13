from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field, replace
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
    scheduling: tuple[str, int] | None
    group: BoundedSemaphore | None
    cancelled: Event = field(default_factory=Event)
    started: Event = field(default_factory=Event)
    launched: bool = False
    subscribers: int = 0


@dataclass(slots=True, eq=False)
class _QuerySubscription:
    entry: _InFlightQuery
    query: PhysicalQuery
    group: BoundedSemaphore | None
    detached: bool = False


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
    """Execute immutable plans with process-wide in-flight and group sharing.

    Any subscriber may launch shared physical work. The coordinator that atomically
    launches an entry contributes its ``max_parallel`` execution limit.
    """

    _inflight_lock = Lock()
    _inflight: dict[_WorkKey, _InFlightQuery] = {}
    _group_lock = Lock()
    _group_limits: dict[str, tuple[int, BoundedSemaphore]] = {}

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
        self._validate_queries(plan.queries, provider)

        subscriptions: list[_QuerySubscription] = []
        try:
            # Subscribe the whole batch before any entry can complete and leave the registry.
            initial = self._register_batch(run, provider, plan.queries)
            subscriptions.extend(initial)
            self._launch_initial_batch(initial, provider)
            resolver = getattr(provider, "resolve_queries", None)
            if resolver is None:
                return self._execute_legacy_plan(run, plan, provider, initial)

            primary = [item for item in initial if not item.query.speculative]
            primary_results = self._await_many(run, primary)
            primary_fragments = tuple(
                provider.normalize(result) for result in primary_results if result is not None
            )
            required_queries = tuple(resolver(plan, primary_fragments))
            self._validate_queries(required_queries, provider)
            if any(not query.required for query in required_queries):
                raise ValueError("query resolver returned a non-required query")

            speculative: dict[str, _QuerySubscription] = {
                provider.fingerprint(item.query): item for item in initial if item.query.speculative
            }
            required: list[_QuerySubscription | None] = []
            dynamic_queries: list[PhysicalQuery] = []
            for query in required_queries:
                match = speculative.get(provider.fingerprint(query))
                if match is None:
                    required.append(None)
                    dynamic_queries.append(query)
                else:
                    required.append(self._duplicate_subscription(run, match, query))

            dynamic = self._register_batch(run, provider, tuple(dynamic_queries))
            subscriptions.extend(dynamic)
            self._launch_batch(dynamic, provider)
            dynamic_iter = iter(dynamic)
            resolved = [next(dynamic_iter) if item is None else item for item in required]
            subscriptions.extend(item for item in resolved if item not in subscriptions)

            retained_entries = {item.entry for item in resolved}
            for item in initial:
                if item.query.speculative and item.entry not in retained_entries:
                    self._detach_subscription(run, item)

            required_results = self._await_many(run, resolved)
            required_fragments = tuple(
                provider.normalize(result) for result in required_results if result is not None
            )
            return provider.assemble(plan, primary_fragments + required_fragments)
        finally:
            for subscription in subscriptions:
                self._detach_subscription(run, subscription)

    def _execute_legacy_plan(
        self,
        run: _PlanRun,
        plan: PhysicalPlan,
        provider: Provider,
        initial: list[_QuerySubscription],
    ) -> ProviderResult:
        results = self._await_many(run, initial)
        fragments = tuple(provider.normalize(result) for result in results if result is not None)
        supplemental = getattr(provider, "supplemental_queries", lambda _plan, _fragments: ())(
            plan, fragments
        )
        supplemental_queries = tuple(supplemental)
        self._validate_queries(supplemental_queries, provider)
        supplemental_subscriptions = self._register_batch(run, provider, supplemental_queries)
        self._launch_batch(supplemental_subscriptions, provider)
        try:
            supplemental_results = self._await_many(run, supplemental_subscriptions)
            fragments += tuple(
                provider.normalize(result) for result in supplemental_results if result is not None
            )
        finally:
            for subscription in supplemental_subscriptions:
                self._detach_subscription(run, subscription)
        return provider.assemble(plan, fragments)

    @staticmethod
    def _validate_queries(queries: tuple[PhysicalQuery, ...], provider: Provider) -> None:
        if any(query.provider.provider_id != provider.provider.provider_id for query in queries):
            raise ValueError("physical plan contains a query for another provider")

    def _register_batch(
        self,
        run: _PlanRun,
        provider: Provider,
        queries: tuple[PhysicalQuery, ...],
    ) -> list[_QuerySubscription]:
        subscriptions: list[_QuerySubscription] = []
        try:
            for query in queries:
                if run.cancelled.is_set() or self._shutdown.is_set():
                    raise _cancelled(query)
                key = (provider.provider.provider_id, provider.fingerprint(query))
                entry, _created = self._subscribe(run, key, query)
                subscriptions.append(_QuerySubscription(entry, query, entry.group))
        except BaseException:
            for subscription in subscriptions:
                self._detach_subscription(run, subscription)
            raise
        return subscriptions

    def _duplicate_subscription(
        self,
        run: _PlanRun,
        subscription: _QuerySubscription,
        query: PhysicalQuery,
    ) -> _QuerySubscription:
        entry = subscription.entry
        with self._inflight_lock:
            entry.subscribers += 1
        with run.lock:
            if run.cancelled.is_set() or self._shutdown.is_set():
                self._release(entry.key, entry)
                raise _cancelled(query)
            run.subscriptions[entry] = run.subscriptions.get(entry, 0) + 1
        return _QuerySubscription(entry, query, subscription.group)

    def _launch_initial_batch(
        self, subscriptions: list[_QuerySubscription], provider: Provider
    ) -> None:
        primaries = [item for item in subscriptions if not item.query.speculative]
        self._launch_batch(primaries, provider)
        primary_entries = tuple(dict.fromkeys(item.entry for item in primaries))
        target = min(len(primary_entries), self.max_parallel)
        while (
            sum(
                entry.started.is_set() or entry.future.done() or entry.cancelled.is_set()
                for entry in primary_entries
            )
            < target
        ):
            pending = next(
                (
                    entry
                    for entry in primary_entries
                    if not entry.started.is_set()
                    and not entry.future.done()
                    and not entry.cancelled.is_set()
                ),
                None,
            )
            if pending is None:
                break
            pending.started.wait(_WAIT_INTERVAL)
        self._launch_batch([item for item in subscriptions if item.query.speculative], provider)

    def _launch_batch(self, subscriptions: list[_QuerySubscription], provider: Provider) -> None:
        for subscription in subscriptions:
            self._ensure_launched(subscription, provider)

    def _ensure_launched(self, subscription: _QuerySubscription, provider: Provider) -> None:
        entry = subscription.entry
        with self._inflight_lock:
            if entry.launched or entry.subscribers == 0 or entry.future.done():
                return
            entry.launched = True
        Thread(
            target=self._execute_bounded,
            args=(
                entry.key,
                entry,
                provider,
                subscription.query,
                subscription.group,
            ),
            name="provider-query-execution",
            daemon=True,
        ).start()

    def _await_many(
        self,
        run: _PlanRun,
        subscriptions: list[_QuerySubscription],
    ) -> list[PhysicalResult | None]:
        results: list[PhysicalResult | None] = [None] * len(subscriptions)
        pending = set(range(len(subscriptions)))
        while pending:
            if run.cancelled.is_set() or self._shutdown.is_set():
                raise _cancelled(subscriptions[next(iter(pending))].query)
            futures = {subscriptions[index].entry.future for index in pending}
            done, _ = wait(futures, timeout=_WAIT_INTERVAL, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for index in tuple(pending):
                subscription = subscriptions[index]
                if subscription.entry.future not in done:
                    continue
                pending.remove(index)
                try:
                    shared = subscription.entry.future.result()
                    results[index] = replace(shared, query=subscription.query)
                except BaseException:
                    if (
                        subscription.query.required
                        or run.cancelled.is_set()
                        or self._shutdown.is_set()
                    ):
                        raise
        return results

    def _detach_subscription(self, run: _PlanRun, subscription: _QuerySubscription) -> None:
        if subscription.detached:
            return
        subscription.detached = True
        self._unsubscribe(run, subscription.entry)

    def _register_group(self, query: PhysicalQuery) -> BoundedSemaphore | None:
        if query.scheduling_group is None:
            return None
        assert query.scheduling_limit is not None
        with type(self)._group_lock:
            registered = type(self)._group_limits.get(query.scheduling_group)
            if registered is None:
                semaphore = BoundedSemaphore(query.scheduling_limit)
                type(self)._group_limits[query.scheduling_group] = (
                    query.scheduling_limit,
                    semaphore,
                )
                return semaphore
            limit, semaphore = registered
            if limit != query.scheduling_limit:
                raise ValueError(
                    f"conflicting scheduling limits for group {query.scheduling_group!r}"
                )
            return semaphore

    def _subscribe(
        self, run: _PlanRun, key: _WorkKey, query: PhysicalQuery
    ) -> tuple[_InFlightQuery, bool]:
        with self._inflight_lock:
            entry = self._inflight.get(key)
            created = entry is None
            if entry is None:
                if query.scheduling_group is None:
                    scheduling = None
                else:
                    assert query.scheduling_limit is not None
                    scheduling = (query.scheduling_group, query.scheduling_limit)
                group = self._register_group(query)
                entry = _InFlightQuery(key, Future(), scheduling, group)
                self._inflight[key] = entry
            entry.subscribers += 1
        with run.lock:
            if run.cancelled.is_set() or self._shutdown.is_set():
                self._release(key, entry)
                raise _cancelled(query)
            run.subscriptions[entry] = run.subscriptions.get(entry, 0) + 1
        return entry, created

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
        group: BoundedSemaphore | None,
    ) -> None:
        acquired_group = False
        acquired_global = False
        try:
            # Group capacity is acquired first. Timed acquisition keeps detached
            # launch threads from becoming permanent semaphore waiters.
            if group is not None:
                while not group.acquire(timeout=_WAIT_INTERVAL):
                    if self._entry_detached(entry):
                        return
                acquired_group = True
                if self._entry_detached(entry):
                    return
            while not self._execution_slots.acquire(timeout=_WAIT_INTERVAL):
                if self._entry_detached(entry):
                    return
            acquired_global = True
            if self._entry_detached(entry):
                return
            entry.started.set()
            self._execute(key, entry, provider, query)
        finally:
            if acquired_global:
                self._execution_slots.release()
            if acquired_group:
                assert group is not None
                group.release()

    @classmethod
    def _entry_detached(cls, entry: _InFlightQuery) -> bool:
        with cls._inflight_lock:
            return entry.subscribers == 0

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


def _cancelled(query: PhysicalQuery) -> QueryError:
    return QueryError("error.ccusage_cancelled", query=query.operation)


def _cancelled_plan(plan: PhysicalPlan) -> QueryError:
    operation = plan.queries[0].operation if plan.queries else plan.plan_id
    return QueryError("error.ccusage_cancelled", query=operation)
