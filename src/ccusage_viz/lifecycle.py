from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


class QueryTrigger(StrEnum):
    STARTUP = "startup"
    REFRESH = "refresh"
    TICK = "tick"


class LifecycleTrigger(StrEnum):
    STARTUP = "startup"
    PERIODIC = "periodic"
    MANUAL = "manual"
    CONFIGURATION = "configuration"
    RESUME = "resume"


_AUTOMATIC_TRIGGERS = frozenset(
    {LifecycleTrigger.STARTUP, LifecycleTrigger.PERIODIC, LifecycleTrigger.RESUME}
)
_TRIGGER_PRIORITY = {
    LifecycleTrigger.STARTUP: 1,
    LifecycleTrigger.PERIODIC: 1,
    LifecycleTrigger.RESUME: 2,
    LifecycleTrigger.MANUAL: 2,
    LifecycleTrigger.CONFIGURATION: 3,
}


@dataclass(frozen=True, slots=True)
class LifecycleIntent:
    trigger: LifecycleTrigger
    generation: int
    ready_at: float


@dataclass(frozen=True, slots=True)
class OperationToken:
    owner_id: str
    generation: int
    operation_id: int
    trigger: LifecycleTrigger


class FixedIntervalScheduler:
    """A fixed-baseline periodic opportunity source with no pause backlog."""

    __slots__ = ("baseline", "enabled", "interval", "next_opportunity", "stopping")

    def __init__(self, interval: float, *, now: float) -> None:
        self._validate_interval(interval)
        self.interval = interval
        self.baseline = now
        self.next_opportunity = now + interval
        self.enabled = True
        self.stopping = False

    def due(self, *, now: float) -> bool:
        if self.stopping or not self.enabled or now < self.next_opportunity:
            return False
        self._advance_past(now)
        return True

    def pause(self) -> None:
        self.enabled = False

    def resume(self, *, now: float) -> None:
        if self.stopping:
            return
        self.enabled = True
        self._advance_past(now)

    def rebuild(self, interval: float, *, now: float) -> None:
        self._validate_interval(interval)
        self.interval = interval
        self.baseline = now
        self.next_opportunity = now + interval

    def shutdown(self) -> None:
        self.stopping = True
        self.enabled = False

    def _advance_past(self, now: float) -> None:
        if self.next_opportunity > now:
            return
        steps = math.floor((now - self.next_opportunity) / self.interval) + 1
        self.next_opportunity += steps * self.interval

    @staticmethod
    def _validate_interval(interval: float) -> None:
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("scheduler interval must be positive and finite")


_Submission = TypeVar("_Submission")


class LifecycleOperation(Generic[_Submission]):
    """Bind lifecycle admission to one host-owned asynchronous submission."""

    __slots__ = ("coordinator", "operation", "submission")

    def __init__(self, owner_id: str) -> None:
        self.coordinator = LifecycleCoordinator(owner_id)
        self.operation: OperationToken | None = None
        self.submission: _Submission | None = None

    @property
    def active(self) -> OperationToken | None:
        return self.coordinator.active

    @property
    def paused(self) -> bool:
        return self.coordinator.paused

    def request(
        self,
        trigger: LifecycleTrigger,
        *,
        generation: int,
        now: float,
        start: Callable[[OperationToken], tuple[_Submission, Callable[[], None]]],
        debounce: float = 0.0,
        replace_active: bool = False,
    ) -> bool:
        previous = self.coordinator.active
        try:
            requested = self.coordinator.request(
                trigger,
                generation=generation,
                now=now,
                debounce=debounce,
                replace_active=replace_active,
            )
        finally:
            if previous is not None and self.coordinator.active is None:
                self.operation = None
                self.submission = None
        return requested and self.start_ready(now=now, start=start)

    def start_ready(
        self,
        *,
        now: float,
        start: Callable[[OperationToken], tuple[_Submission, Callable[[], None]]],
    ) -> bool:
        operation = self.coordinator.take_ready(now=now)
        if operation is None:
            return False
        try:
            submission, cancel = start(operation)
        except BaseException:
            self.coordinator.abandon(operation)
            raise
        self.operation = operation
        self.submission = submission
        self.coordinator.attach(operation, cancel)
        return True

    def take_completed(
        self,
        done: Callable[[_Submission], bool],
    ) -> tuple[OperationToken, _Submission] | None:
        operation = self.operation
        submission = self.submission
        if operation is None or submission is None or not done(submission):
            return None
        return operation, submission

    def accepts(self, operation: OperationToken, *, generation: int) -> bool:
        return self.coordinator.accepts(operation, generation=generation)

    def complete(self, operation: OperationToken, *, generation: int) -> bool:
        completed = self.coordinator.complete(operation, generation=generation)
        if completed and operation == self.operation:
            self.operation = None
            self.submission = None
        return completed

    def abandon(self, operation: OperationToken) -> None:
        self.coordinator.abandon(operation)
        if operation == self.operation and operation != self.coordinator.active:
            self.operation = None
            self.submission = None

    def pause(self) -> None:
        previous = self.coordinator.active
        try:
            self.coordinator.pause()
        finally:
            if previous is not None and self.coordinator.active is None:
                self.operation = None
                self.submission = None

    def resume(self) -> None:
        self.coordinator.resume()

    def detach_active(self) -> OperationToken | None:
        operation = self.coordinator.active
        try:
            return self.coordinator.detach_active()
        finally:
            if operation is not None and self.coordinator.active is None:
                self.operation = None
                self.submission = None

    def shutdown(self) -> None:
        try:
            self.coordinator.shutdown()
        finally:
            self.operation = None
            self.submission = None


class LifecycleCoordinator:
    """Coordinate one data owner's active operation and coalesced pending intent."""

    __slots__ = (
        "_active",
        "_cancel_active",
        "_generation",
        "_next_operation_id",
        "owner_id",
        "paused",
        "pending",
        "stopping",
    )

    def __init__(self, owner_id: str) -> None:
        if not owner_id:
            raise ValueError("owner ID must not be empty")
        self.owner_id = owner_id
        self.pending: LifecycleIntent | None = None
        self.paused = False
        self.stopping = False
        self._active: OperationToken | None = None
        self._cancel_active: Callable[[], None] | None = None
        self._generation = 0
        self._next_operation_id = 1

    @property
    def active(self) -> OperationToken | None:
        return self._active

    def request(
        self,
        trigger: LifecycleTrigger,
        *,
        generation: int,
        now: float,
        debounce: float = 0.0,
        replace_active: bool = False,
    ) -> bool:
        if generation < 0:
            raise ValueError("generation must be non-negative")
        if not math.isfinite(debounce) or debounce < 0:
            raise ValueError("debounce must be non-negative and finite")
        if self.stopping or generation < self._generation:
            return False
        if self.paused and trigger in _AUTOMATIC_TRIGGERS:
            return False

        self._generation = generation
        ready_at = now + debounce if trigger is LifecycleTrigger.CONFIGURATION else now
        incoming = LifecycleIntent(trigger, generation, ready_at)
        pending = self.pending
        if (
            pending is None
            or generation > pending.generation
            or generation == pending.generation
            and _TRIGGER_PRIORITY[trigger] >= _TRIGGER_PRIORITY[pending.trigger]
        ):
            self.pending = incoming

        if replace_active or trigger is LifecycleTrigger.CONFIGURATION:
            self.detach_active()
        return True

    def take_ready(self, *, now: float) -> OperationToken | None:
        if self.stopping or self._active is not None or self.pending is None:
            return None
        if self.paused and self.pending.trigger in _AUTOMATIC_TRIGGERS:
            return None
        if now < self.pending.ready_at:
            return None
        intent = self.pending
        self.pending = None
        token = OperationToken(
            self.owner_id,
            intent.generation,
            self._next_operation_id,
            intent.trigger,
        )
        self._next_operation_id += 1
        self._active = token
        return token

    def attach(self, token: OperationToken, cancel: Callable[[], None]) -> None:
        if token != self._active:
            raise ValueError("operation is not active")
        self._cancel_active = cancel

    def accepts(self, token: OperationToken, *, generation: int) -> bool:
        return (
            not self.stopping
            and token == self._active
            and token.owner_id == self.owner_id
            and token.generation == generation
        )

    def complete(self, token: OperationToken, *, generation: int) -> bool:
        if not self.accepts(token, generation=generation):
            return False
        self._active = None
        self._cancel_active = None
        return True

    def abandon(self, token: OperationToken) -> None:
        if token == self._active:
            self._active = None
            self._cancel_active = None

    def detach_active(self) -> OperationToken | None:
        active = self._active
        cancel = self._cancel_active
        self._active = None
        self._cancel_active = None
        if cancel is not None:
            cancel()
        return active

    def pause(self) -> None:
        self.paused = True
        if self.pending is not None and self.pending.trigger in _AUTOMATIC_TRIGGERS:
            self.pending = None
        if self._active is not None and self._active.trigger in _AUTOMATIC_TRIGGERS:
            self.detach_active()

    def resume(self) -> None:
        if not self.stopping:
            self.paused = False

    def shutdown(self) -> None:
        self.stopping = True
        self.pending = None
        self.detach_active()


def query_trigger(trigger: LifecycleTrigger) -> QueryTrigger:
    match trigger:
        case LifecycleTrigger.STARTUP:
            return QueryTrigger.STARTUP
        case LifecycleTrigger.PERIODIC:
            return QueryTrigger.TICK
        case LifecycleTrigger.MANUAL | LifecycleTrigger.CONFIGURATION | LifecycleTrigger.RESUME:
            return QueryTrigger.REFRESH
        case _:
            raise ValueError(f"unknown lifecycle trigger: {trigger!r}")
