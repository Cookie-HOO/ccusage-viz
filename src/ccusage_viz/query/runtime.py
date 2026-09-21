from __future__ import annotations

from concurrent.futures import Future
from threading import Event, Lock, Thread

from ccusage_viz.query.coordinator import QueryCoordinator, QueryHandle
from ccusage_viz.query.models import ProviderResult, QueryIntent
from ccusage_viz.query.provider import ProviderDefinition
from ccusage_viz.query.registry import ProviderRegistry


class QueryRuntime:
    """Shared Standalone/Pane runtime for provider-backed acquisition."""

    __slots__ = ("_coordinator", "_registry")

    def __init__(self, registry: ProviderRegistry, coordinator: QueryCoordinator) -> None:
        if not registry.frozen:
            raise ValueError("provider registry must be frozen before runtime use")
        self._registry = registry
        self._coordinator = coordinator

    def definition(self, provider_id: str) -> ProviderDefinition:
        return self._registry.get(provider_id)

    def submit(self, intent: QueryIntent) -> QueryHandle[ProviderResult]:
        provider = self._registry.get(intent.provider.provider_id).provider
        future: Future[ProviderResult] = Future()
        cancelled = Event()
        lock = Lock()
        handle: QueryHandle[ProviderResult] | None = None

        def cancel() -> None:
            cancelled.set()
            with lock:
                active = handle
            if active is not None:
                active.cancel()
            if not future.done():
                future.cancel()

        def compile_and_submit() -> None:
            nonlocal handle
            try:
                plan = provider.compile(intent)
                if cancelled.is_set():
                    return
                submitted = self._coordinator.submit(plan, provider)
                with lock:
                    handle = submitted
                if cancelled.is_set():
                    submitted.cancel()
                    return
                result = submitted.result()
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)

        Thread(target=compile_and_submit, name="provider-query-compile", daemon=True).start()
        return QueryHandle(future, cancel)

    def acquire(self, intent: QueryIntent) -> ProviderResult:
        return self.submit(intent).result()

    def cancel(self) -> None:
        self._coordinator.cancel()
