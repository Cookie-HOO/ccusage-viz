from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.datasets.models import (
    DatasetManifest,
    DatasetProbeSnapshot,
    DatasetRegistration,
    LocalDatasetSource,
)
from ccusage_viz.datasets.store import DatasetStore
from ccusage_viz.errors import UsageError


def manifest_wire() -> dict[str, object]:
    return {
        "schema": "ccuv.dataset/v1",
        "id": "reading-time",
        "version": "1.2.3",
        "protocol": "ccuv.custom/v1",
        "entrypoint": "bin/reading-time",
        "platform": {"os": "darwin", "arch": "arm64"},
        "metric": {
            "id": "reading-minutes",
            "title": {"en": "Reading time", "zh-CN": "阅读时长"},
            "unit": {
                "id": "minutes",
                "label": {"en": "minutes", "zh-CN": "分钟"},
                "placement": "suffix",
                "decimal_places": 0,
            },
        },
        "charts": ["timeline", "calendar", "stack", "ranking"],
        "environment": [],
    }


def write_staged_dataset(path: Path) -> DatasetManifest:
    manifest = DatasetManifest.parse(manifest_wire())
    (path / "bin").mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps(manifest_wire()))
    executable = path / manifest.entrypoint
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return manifest


def registration() -> DatasetRegistration:
    text = LocalizedText("WeRead", "微信读书")
    descriptor = CustomProbeDescriptor(
        "weread-1",
        "0.1.0",
        CustomDataset(text, text, CustomUnit("minute", text, "suffix", 2)),
        CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
        {"timeline": CustomChartDefaults("14d", None, None)},
        (),
    )
    return DatasetRegistration(
        "weread",
        LocalDatasetSource(("weread", "ccuv")),
        True,
        "2026-10-07T00:00:00+00:00",
        "2026-10-07T00:00:00+00:00",
        DatasetProbeSnapshot("weread", descriptor, "2026-10-07T00:00:00+00:00"),
    )


def test_store_installs_loads_and_removes_active_version(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    staged = store.stage_directory()
    manifest = write_staged_dataset(staged)

    installed = store.install(
        staged_version=staged,
        manifest=manifest,
        source_kind="official",
        repository="Cookie-HOO/ccuv-dataset-reading-time",
        release_tag="v1.2.3",
        asset_name="reading-time-darwin-arm64.tar.gz",
        archive_sha256="a" * 64,
    )
    loaded, loaded_manifest, executable = store.load("reading-time")

    assert loaded == installed
    assert loaded_manifest == manifest
    assert executable.is_file()
    assert store.list() == ((installed, manifest, executable),)

    store.remove("reading-time")
    with pytest.raises(UsageError) as caught:
        store.load("reading-time")
    assert caught.value.key == "error.dataset_not_installed"


def test_store_replaces_same_version_content_before_updating_metadata(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    first = store.stage_directory()
    manifest = write_staged_dataset(first)
    store.install(
        staged_version=first,
        manifest=manifest,
        source_kind="official",
        repository="Cookie-HOO/ccuv-dataset-reading-time",
        release_tag="v1.2.3",
        asset_name="reading-time-darwin-arm64.tar.gz",
        archive_sha256="a" * 64,
    )
    replacement = store.stage_directory()
    write_staged_dataset(replacement)
    executable = replacement / manifest.entrypoint
    executable.write_text("#!/bin/sh\necho replacement\n")
    executable.chmod(0o755)

    installed = store.install(
        staged_version=replacement,
        manifest=manifest,
        source_kind="official",
        repository="Cookie-HOO/ccuv-dataset-reading-time",
        release_tag="v1.2.3",
        asset_name="reading-time-darwin-arm64.tar.gz",
        archive_sha256="b" * 64,
    )
    loaded, _, installed_executable = store.load("reading-time")

    assert loaded == installed
    assert loaded.sha256 == "b" * 64
    assert installed_executable.read_text() == "#!/bin/sh\necho replacement\n"


def test_store_lists_corrupt_installations_for_service_status(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    staged = store.stage_directory()
    manifest = write_staged_dataset(staged)
    store.install(
        staged_version=staged,
        manifest=manifest,
        source_kind="github",
        repository="example/reading-time",
        release_tag="v1.2.3",
        asset_name="reading-time-darwin-arm64.tar.gz",
        archive_sha256="a" * 64,
    )
    (tmp_path / "datasets" / "reading-time" / "versions" / "1.2.3" / "manifest.json").write_text(
        "{}"
    )

    with pytest.raises(UsageError) as caught:
        store.list()

    assert caught.value.key == "error.dataset_corrupt"
    assert store.dataset_ids() == ("reading-time",)


def test_store_detects_tampered_manifest_as_corrupt(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    staged = store.stage_directory()
    manifest = write_staged_dataset(staged)
    store.install(
        staged_version=staged,
        manifest=manifest,
        source_kind="github",
        repository="example/reading-time",
        release_tag="v1.2.3",
        asset_name="reading-time-darwin-arm64.tar.gz",
        archive_sha256="a" * 64,
    )
    (tmp_path / "datasets" / "reading-time" / "versions" / "1.2.3" / "manifest.json").write_text(
        "{}"
    )

    with pytest.raises(UsageError) as caught:
        store.load("reading-time")

    assert caught.value.key == "error.dataset_corrupt"


def test_store_round_trips_local_registration_without_a_managed_artifact(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    record = registration()

    store.save_registration(record)

    assert store.registration_ids() == ("weread",)
    assert store.load_registration("weread") == record
    assert store.registrations() == (record,)
    assert not (tmp_path / "datasets" / "weread").exists()

    store.remove_registration("weread")
    assert store.registration_ids() == ()
