from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.dashboard_preset_store import (
    DashboardPresetStore,
    DashboardPresetStoreCorruptError,
    DashboardPresetStoreError,
    DashboardPresetStoreNotFoundError,
)
from ccusage_viz.dashboard_presets import DashboardPresetDocument, preset_from_launch
from ccusage_viz.options import (
    ChartPaneConfig,
    DashboardHostConfig,
    DashboardLaunch,
    ProcessConfig,
    TimelineConfig,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
RANGE = DateRange(datetime(2026, 10, 1, tzinfo=UTC).date(), NOW.date())


def _record(name: str, *, now: datetime = NOW):
    launch = DashboardLaunch(
        ProcessConfig(),
        DashboardHostConfig(),
        (ChartPaneConfig(TimelineConfig("timeline", RANGE)),),
    )
    return preset_from_launch(name, launch, now=now)


def test_missing_store_loads_empty_document_without_creating_files(tmp_path: Path) -> None:
    store = DashboardPresetStore(tmp_path / "dashboard-presets")

    assert store.load() == DashboardPresetDocument.empty()
    assert store.list() == ()
    assert not store.root.exists()


def test_store_saves_loads_and_deletes_records_with_private_permissions(tmp_path: Path) -> None:
    store = DashboardPresetStore(tmp_path / "dashboard-presets", clock=lambda: NOW)

    saved = store.save(_record("review"))

    assert saved.name == "review"
    assert saved.created_at == NOW
    assert saved.updated_at == NOW
    assert store.get("review") == saved
    assert store.list() == (saved,)
    assert store.path.read_bytes().endswith(b"\n")
    if os.name == "posix":
        assert store.root.stat().st_mode & 0o777 == 0o700
        assert store.path.stat().st_mode & 0o777 == 0o600

    store.delete("review")

    assert store.list() == ()
    with pytest.raises(DashboardPresetStoreNotFoundError, match="review"):
        store.get("review")
    with pytest.raises(DashboardPresetStoreNotFoundError, match="review"):
        store.delete("review")


def test_store_overwrite_preserves_created_at_and_refreshes_updated_at(tmp_path: Path) -> None:
    ticks = iter((NOW, NOW + timedelta(hours=1)))
    store = DashboardPresetStore(tmp_path / "dashboard-presets", clock=lambda: next(ticks))

    first = store.save(_record("review", now=NOW - timedelta(days=1)))
    replacement = store.save(_record("review", now=NOW - timedelta(days=2)))

    assert first.created_at == NOW
    assert first.updated_at == NOW
    assert replacement.created_at == NOW
    assert replacement.updated_at == NOW + timedelta(hours=1)
    assert len(store.list()) == 1


@pytest.mark.parametrize(
    "payload",
    (
        b"\xff\xfe",
        b"{",
        b'{"schema":"ccuv.dashboard-presets/v1","schema":"ccuv.dashboard-presets/v1","presets":[]}',
        b'{"schema":"ccuv.dashboard-presets/v1","presets":[{"name":"bad"}]}',
    ),
)
def test_corrupt_store_is_reported_and_never_mutated(tmp_path: Path, payload: bytes) -> None:
    store = DashboardPresetStore(tmp_path / "dashboard-presets")
    store.root.mkdir()
    store.path.write_bytes(payload)

    with pytest.raises(DashboardPresetStoreCorruptError):
        store.load()
    with pytest.raises(DashboardPresetStoreCorruptError):
        store.save(_record("review"))
    with pytest.raises(DashboardPresetStoreCorruptError):
        store.delete("review")

    assert store.path.read_bytes() == payload


def test_write_failure_preserves_existing_collection_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = DashboardPresetStore(tmp_path / "dashboard-presets", clock=lambda: NOW)
    initial = store.save(_record("first"))
    original_bytes = store.path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("ccusage_viz.dashboard_preset_store.os.replace", fail_replace)

    with pytest.raises(DashboardPresetStoreError, match="unable to write"):
        store.save(_record("second"))

    assert store.path.read_bytes() == original_bytes
    assert store.list() == (initial,)
    assert tuple(store.root.glob("*.tmp")) == ()
