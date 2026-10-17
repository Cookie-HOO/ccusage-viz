from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
from pathlib import Path

from ccusage_viz.datasets.models import DatasetManifest
from ccusage_viz.errors import UsageError

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 48 * 1024 * 1024
MAX_TOTAL_MEMBER_BYTES = 64 * 1024 * 1024


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _normalized_member_name(name: str) -> str | None:
    path = Path(name)
    if not name or "\x00" in name or path.is_absolute() or ".." in path.parts:
        return None
    normalized = path.as_posix()
    return normalized if normalized not in {".", ""} else None


def extract_dataset_archive(
    archive: bytes,
    *,
    expected_sha256: str,
    destination: Path,
    expected_dataset_id: str | None,
    host_os: str,
    host_arch: str,
) -> DatasetManifest:
    """Validate and extract the strict two-file dataset archive into ``destination``."""

    if len(archive) > MAX_ARCHIVE_BYTES or sha256_bytes(archive) != expected_sha256:
        raise UsageError("error.dataset_archive_digest")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as file:
            members = file.getmembers()
            expected_names = {"manifest.json"}
            names: set[str] = set()
            total_size = 0
            for member in members:
                name = _normalized_member_name(member.name)
                if name is None or name != member.name or name in names or not member.isfile():
                    raise UsageError("error.dataset_archive_invalid")
                names.add(name)
                if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                    raise UsageError("error.dataset_archive_invalid")
                total_size += member.size
                if total_size > MAX_TOTAL_MEMBER_BYTES:
                    raise UsageError("error.dataset_archive_invalid")
            if "manifest.json" not in names or len(names) != 2:
                raise UsageError("error.dataset_archive_invalid")
            manifest_member = file.extractfile("manifest.json")
            if manifest_member is None:
                raise UsageError("error.dataset_archive_invalid")
            try:
                manifest = DatasetManifest.parse(json.loads(manifest_member.read()))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise UsageError("error.dataset_manifest_invalid") from exc
            expected_names.add(manifest.entrypoint)
            if names != expected_names:
                raise UsageError("error.dataset_archive_invalid")
            if (
                (expected_dataset_id is not None and manifest.id != expected_dataset_id)
                or manifest.os != host_os
                or manifest.arch != host_arch
            ):
                raise UsageError("error.dataset_platform_incompatible")
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            for name in sorted(names):
                source = file.extractfile(name)
                if source is None:
                    raise UsageError("error.dataset_archive_invalid")
                target = destination / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(source.read())
                os.chmod(target, 0o755 if name == manifest.entrypoint else 0o600)
            executable = destination / manifest.entrypoint
            if not executable.is_file() or not executable.stat().st_mode & stat.S_IXUSR:
                raise UsageError("error.dataset_archive_invalid")
            return manifest
    except (tarfile.TarError, OSError) as exc:
        raise UsageError("error.dataset_archive_invalid") from exc
