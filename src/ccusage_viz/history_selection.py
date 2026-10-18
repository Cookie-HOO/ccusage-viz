from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

_Record = TypeVar("_Record")


@dataclass(slots=True)
class HistorySelectionState(Generic[_Record]):
    """Shared newest-first selection and viewport state for bounded histories."""

    selected: _Record | None = None
    selected_index: int = 0
    offset: int = 0


def reconcile_history_selection(
    state: HistorySelectionState[_Record], records: tuple[_Record, ...], visible: int
) -> int | None:
    """Reconcile selection and viewport, returning the selected index when present."""

    if not records:
        state.selected = None
        state.selected_index = 0
        state.offset = 0
        return None
    visible = max(1, visible)
    selected_index = (
        records.index(state.selected)
        if state.selected in records
        else min(max(0, state.selected_index), len(records) - 1)
    )
    state.selected_index = selected_index
    state.selected = records[selected_index]
    state.offset = min(max(0, state.offset), max(0, len(records) - visible))
    if selected_index < state.offset:
        state.offset = selected_index
    elif selected_index >= state.offset + visible:
        state.offset = selected_index - visible + 1
    return selected_index


def move_history_selection(
    state: HistorySelectionState[_Record], records: tuple[_Record, ...], step: int
) -> None:
    """Move selection without crossing the bounded history's ends."""

    if not records:
        return
    current = records.index(state.selected) if state.selected in records else state.selected_index
    state.selected_index = min(max(0, current + step), len(records) - 1)
    state.selected = records[state.selected_index]
