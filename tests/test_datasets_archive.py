from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from ccusage_viz.datasets.archive import extract_dataset_archive, sha256_bytes
from ccusage_viz.datasets.models import CUSTOM_V2_PROTOCOL, DatasetManifest
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


def dataset_archive(
    *, manifest: dict[str, object] | None = None, executable: bytes = b"#!/bin/sh\nexit 0\n"
) -> bytes:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        document = json.dumps(manifest or manifest_wire()).encode()
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(document)
        archive.addfile(manifest_info, io.BytesIO(document))
        executable_info = tarfile.TarInfo("bin/reading-time")
        executable_info.size = len(executable)
        archive.addfile(executable_info, io.BytesIO(executable))
    return payload.getvalue()


def extract(archive: bytes, destination: Path) -> None:
    extract_dataset_archive(
        archive,
        expected_sha256=sha256_bytes(archive),
        destination=destination,
        expected_dataset_id="reading-time",
        host_os="darwin",
        host_arch="arm64",
    )


def test_checked_in_weread_archive_is_a_v2_static_probe_fixture() -> None:
    fixture = Path("dist/datasets/ccuv-dataset-weread-darwin-arm64.tar.gz")
    with tarfile.open(fixture, "r:gz") as archive:
        manifest_member = archive.getmember("manifest.json")
        document = archive.extractfile(manifest_member)
        assert document is not None
        payload = json.loads(document.read())

    manifest = DatasetManifest.parse(payload)

    assert manifest.protocol == CUSTOM_V2_PROTOCOL
    assert manifest.id == "weread"
    assert manifest.descriptor is not None
    assert {metric.id for metric in manifest.descriptor.metrics} == {
        "reading_time",
        "total_notes",
    }


def test_extract_dataset_archive_accepts_exact_two_file_bundle(tmp_path: Path) -> None:
    archive = dataset_archive()

    manifest = extract_dataset_archive(
        archive,
        expected_sha256=sha256_bytes(archive),
        destination=tmp_path / "staged",
        expected_dataset_id="reading-time",
        host_os="darwin",
        host_arch="arm64",
    )

    assert manifest.id == "reading-time"
    assert (tmp_path / "staged" / "manifest.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "staged" / "bin" / "reading-time").stat().st_mode & 0o777 == 0o755


def test_extract_dataset_archive_rejects_digest_mismatch(tmp_path: Path) -> None:
    archive = dataset_archive()

    with pytest.raises(UsageError) as caught:
        extract_dataset_archive(
            archive,
            expected_sha256="0" * 64,
            destination=tmp_path / "staged",
            expected_dataset_id="reading-time",
            host_os="darwin",
            host_arch="arm64",
        )

    assert caught.value.key == "error.dataset_archive_digest"
    assert not (tmp_path / "staged").exists()


@pytest.mark.parametrize(
    "kind", (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE)
)
def test_extract_dataset_archive_rejects_non_regular_members(tmp_path: Path, kind: bytes) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        document = json.dumps(manifest_wire()).encode()
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(document)
        archive.addfile(manifest_info, io.BytesIO(document))
        special = tarfile.TarInfo("bin/reading-time")
        special.type = kind
        archive.addfile(special)
    archive = payload.getvalue()

    with pytest.raises(UsageError) as caught:
        extract(archive, tmp_path / "staged")

    assert caught.value.key == "error.dataset_archive_invalid"


def test_extract_dataset_archive_rejects_total_uncompressed_content_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ccusage_viz.datasets.archive.MAX_TOTAL_MEMBER_BYTES", 8)
    archive = dataset_archive()

    with pytest.raises(UsageError) as caught:
        extract(archive, tmp_path / "staged")

    assert caught.value.key == "error.dataset_archive_invalid"


def test_extract_dataset_archive_rejects_unexpected_members(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name, contents in (
            ("manifest.json", json.dumps(manifest_wire()).encode()),
            ("bin/reading-time", b"binary"),
            ("README.md", b"unexpected"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            archive.addfile(info, io.BytesIO(contents))
    archive = payload.getvalue()

    with pytest.raises(UsageError) as caught:
        extract(archive, tmp_path / "staged")

    assert caught.value.key == "error.dataset_archive_invalid"
