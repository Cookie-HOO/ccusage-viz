"""Immutable, session-local undo/redo history for dashboard configuration snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

SnapshotT = TypeVar("SnapshotT")

MAX_EDIT_TRANSITIONS = 100
_COALESCE_WINDOW_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class HistoryTransition:
    """Metadata belonging to the edit that produced a timeline snapshot."""

    family: object | None = None
    target: object | None = None
    timestamp: float | None = None


@dataclass(frozen=True, slots=True, init=False)
class DashboardHistory(Generic[SnapshotT]):
    """A bounded, immutable timeline of dashboard configuration snapshots.

    The timeline retains at most 100 edit transitions. Once full, recording an
    edit evicts its oldest retained snapshot, which becomes the new baseline.
    """

    snapshots: tuple[SnapshotT, ...]
    cursor: int
    transitions: tuple[HistoryTransition, ...]
    max_edits: int

    def __init__(self, baseline: SnapshotT, *, max_edits: int = MAX_EDIT_TRANSITIONS) -> None:
        if not 1 <= max_edits <= MAX_EDIT_TRANSITIONS:
            raise ValueError(f"max_edits must be between 1 and {MAX_EDIT_TRANSITIONS}")
        object.__setattr__(self, "snapshots", (baseline,))
        object.__setattr__(self, "cursor", 0)
        object.__setattr__(self, "transitions", ())
        object.__setattr__(self, "max_edits", max_edits)

    @classmethod
    def _create(
        cls,
        snapshots: tuple[SnapshotT, ...],
        cursor: int,
        transitions: tuple[HistoryTransition, ...],
        max_edits: int,
    ) -> DashboardHistory[SnapshotT]:
        history = cls.__new__(cls)
        object.__setattr__(history, "snapshots", snapshots)
        object.__setattr__(history, "cursor", cursor)
        object.__setattr__(history, "transitions", transitions)
        object.__setattr__(history, "max_edits", max_edits)
        return history

    @property
    def current(self) -> SnapshotT:
        """Return the active snapshot."""
        return self.snapshots[self.cursor]

    @property
    def baseline(self) -> SnapshotT:
        """Return the oldest snapshot retained by the bounded timeline."""
        return self.snapshots[0]

    @property
    def edit_count(self) -> int:
        """Return the number of retained user-edit transitions."""
        return len(self.transitions)

    @property
    def can_undo(self) -> bool:
        return self.cursor > 0

    @property
    def can_redo(self) -> bool:
        return self.cursor < len(self.snapshots) - 1

    def record(
        self,
        snapshot: SnapshotT,
        *,
        family: object | None = None,
        target: object | None = None,
        timestamp: float | None = None,
    ) -> DashboardHistory[SnapshotT]:
        """Record a changed snapshot, coalescing a same-control edit when eligible.

        Equal snapshots are no-ops. A changed snapshot after undo truncates the
        redo branch. Coalescing only applies at the tip for matching non-null
        family and target metadata no more than one second apart.
        """
        if snapshot == self.current:
            return self

        at_tip = not self.can_redo
        snapshots = self.snapshots[: self.cursor + 1]
        transitions = self.transitions[: self.cursor]
        transition = HistoryTransition(family, target, timestamp)

        if at_tip and transitions and self._can_coalesce(transitions[-1], transition):
            return self._create(
                (*snapshots[:-1], snapshot),
                self.cursor,
                (*transitions[:-1], transition),
                self.max_edits,
            )

        snapshots = (*snapshots, snapshot)
        transitions = (*transitions, transition)
        if len(transitions) > self.max_edits:
            snapshots = snapshots[1:]
            transitions = transitions[1:]
        return self._create(snapshots, len(snapshots) - 1, transitions, self.max_edits)

    def undo(self) -> DashboardHistory[SnapshotT]:
        """Move to the preceding retained snapshot when possible."""
        if not self.can_undo:
            return self
        return self._create(self.snapshots, self.cursor - 1, self.transitions, self.max_edits)

    def redo(self) -> DashboardHistory[SnapshotT]:
        """Move to the following retained snapshot when possible."""
        if not self.can_redo:
            return self
        return self._create(self.snapshots, self.cursor + 1, self.transitions, self.max_edits)

    @staticmethod
    def _can_coalesce(previous: HistoryTransition, current: HistoryTransition) -> bool:
        if (
            previous.family is None
            or previous.target is None
            or current.family is None
            or current.target is None
            or previous.family != current.family
            or previous.target != current.target
            or previous.timestamp is None
            or current.timestamp is None
        ):
            return False
        elapsed = current.timestamp - previous.timestamp
        return 0 <= elapsed <= _COALESCE_WINDOW_SECONDS
