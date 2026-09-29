import pytest

from ccusage_viz.dashboard_history import DashboardHistory


def test_history_keeps_baseline_and_traverses_edits() -> None:
    history = DashboardHistory("baseline").record("first").record("second")

    assert history.current == "second"
    assert history.can_undo
    assert not history.can_redo
    assert history.undo().current == "first"
    assert history.undo().undo().current == "baseline"
    assert history.undo().undo().redo().current == "first"


def test_history_is_frozen_and_returns_new_snapshots() -> None:
    history = DashboardHistory("A")

    with pytest.raises((AttributeError, TypeError)):
        history.cursor = 1  # type: ignore[misc]
    assert history.record("B") is not history


def test_new_edit_after_undo_truncates_redo_branch() -> None:
    history = DashboardHistory("A").record("B").record("C")
    changed = history.undo().record("D")

    assert changed.snapshots == ("A", "B", "D")
    assert changed.current == "D"
    assert not changed.can_redo


def test_equal_snapshot_is_a_no_op_and_preserves_redo_branch() -> None:
    history = DashboardHistory("A").record("B").record("C").undo()

    assert history.record("B") is history
    assert history.can_redo


def test_same_family_and_target_coalesce_within_one_second() -> None:
    history = DashboardHistory("A").record(
        "B", family="theme", target="pane-1", timestamp=10.0
    )
    coalesced = history.record("C", family="theme", target="pane-1", timestamp=11.0)

    assert coalesced.snapshots == ("A", "C")
    assert coalesced.current == "C"
    assert coalesced.undo().current == "A"


def test_coalescing_requires_matching_family_target_and_time_window() -> None:
    initial = DashboardHistory("A").record(
        "B", family="theme", target="pane-1", timestamp=10.0
    )

    assert initial.record("C", family="style", target="pane-1", timestamp=10.5).edit_count == 2
    assert initial.record("C", family="theme", target="pane-2", timestamp=10.5).edit_count == 2
    assert initial.record("C", family="theme", target="pane-1", timestamp=11.01).edit_count == 2
    assert initial.record("C", family="theme", target="pane-1").edit_count == 2


def test_undo_then_record_does_not_coalesce_with_old_branch() -> None:
    history = DashboardHistory("A").record(
        "B", family="theme", target="pane-1", timestamp=1.0
    )

    changed = history.undo().record("C", family="theme", target="pane-1", timestamp=1.5)
    assert changed.snapshots == ("A", "C")


def test_capacity_retains_baseline_and_most_recent_hundred_edits() -> None:
    history = DashboardHistory(0)
    for value in range(1, 102):
        history = history.record(value)

    assert history.edit_count == 100
    assert history.baseline == 1
    assert history.current == 101

    for _ in range(100):
        history = history.undo()
    assert history.current == 1
    assert not history.can_undo


def test_invalid_max_edits_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_edits"):
        DashboardHistory("A", max_edits=0)
    with pytest.raises(ValueError, match="max_edits"):
        DashboardHistory("A", max_edits=101)
