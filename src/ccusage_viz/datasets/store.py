from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ccusage_viz.datasets.models import DatasetManifest, DatasetRegistration, InstalledDataset
from ccusage_viz.datasets.paths import dataset_directory
from ccusage_viz.errors import UsageError


class DatasetStore:
    """Persist validated dataset artifacts without persisting content or secrets."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _current_path(self, dataset_id: str) -> Path:
        return dataset_directory(self.root, dataset_id) / "current.json"

    def _version_path(self, dataset_id: str, version: str) -> Path:
        return dataset_directory(self.root, dataset_id) / "versions" / version

    def _registration_path(self, dataset_id: str) -> Path:
        return self.root / "registrations" / f"{dataset_id}.json"

    def load(self, dataset_id: str) -> tuple[InstalledDataset, DatasetManifest, Path]:
        current_path = self._current_path(dataset_id)
        try:
            current_text = current_path.read_text()
        except FileNotFoundError as exc:
            raise UsageError("error.dataset_not_installed", dataset_id=dataset_id) from exc
        except OSError as exc:
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id) from exc
        try:
            installed = InstalledDataset.parse(json.loads(current_text))
            version_path = self._version_path(installed.dataset_id, installed.version)
            manifest_text = (version_path / "manifest.json").read_bytes()
            manifest = DatasetManifest.parse(json.loads(manifest_text))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id) from exc
        manifest_digest = hashlib.sha256(manifest_text).hexdigest()
        executable = version_path / manifest.entrypoint
        if (
            installed.dataset_id != dataset_id
            or manifest.id != dataset_id
            or manifest.version != installed.version
            or manifest_digest != installed.manifest_sha256
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id)
        return installed, manifest, executable

    def dataset_ids(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(
            candidate.name
            for candidate in sorted(self.root.iterdir())
            if candidate.is_dir() and candidate.name not in {"locks", "staging", "registrations"}
        )

    def list(self) -> tuple[tuple[InstalledDataset, DatasetManifest, Path], ...]:
        return tuple(self.load(dataset_id) for dataset_id in self.dataset_ids())

    def registration_ids(self) -> tuple[str, ...]:
        directory = self.root / "registrations"
        if not directory.is_dir():
            return ()
        return tuple(candidate.stem for candidate in sorted(directory.glob("*.json")))

    def load_registration(self, dataset_id: str) -> DatasetRegistration:
        path = self._registration_path(dataset_id)
        try:
            registration = DatasetRegistration.parse(json.loads(path.read_text()))
        except FileNotFoundError as exc:
            raise UsageError("error.dataset_not_installed", dataset_id=dataset_id) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id) from exc
        if registration.dataset_id != dataset_id:
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id)
        return registration

    def registrations(self) -> tuple[DatasetRegistration, ...]:
        return tuple(self.load_registration(dataset_id) for dataset_id in self.registration_ids())

    def save_registration(self, registration: DatasetRegistration) -> None:
        directory = self.root / "registrations"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self._registration_path(registration.dataset_id)
        temporary = directory / f".{registration.dataset_id}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(registration.to_wire(), sort_keys=True) + "\n")
            os.chmod(temporary, 0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def remove_registration(self, dataset_id: str) -> None:
        path = self._registration_path(dataset_id)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise UsageError("error.dataset_not_installed", dataset_id=dataset_id) from exc

    def install(
        self,
        *,
        staged_version: Path,
        manifest: DatasetManifest,
        source_kind: Literal["official", "github"],
        repository: str,
        release_tag: str,
        asset_name: str,
        archive_sha256: str,
    ) -> InstalledDataset:
        dataset_root = dataset_directory(self.root, manifest.id)
        versions = dataset_root / "versions"
        versions.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = versions / manifest.version
        replacement = versions / f".{manifest.version}.replace-{uuid.uuid4().hex}"
        try:
            if target.exists():
                target.replace(replacement)
            staged_version.replace(target)
        except Exception:
            if replacement.exists() and not target.exists():
                replacement.replace(target)
            raise
        finally:
            shutil.rmtree(staged_version, ignore_errors=True)
        try:
            manifest_digest = hashlib.sha256((target / "manifest.json").read_bytes()).hexdigest()
            installed = InstalledDataset(
                manifest.id,
                manifest.version,
                source_kind,  # type: ignore[arg-type]
                repository,
                release_tag,
                asset_name,
                archive_sha256,
                manifest_digest,
                datetime.now(UTC).isoformat(),
            )
            temporary = dataset_root / ".current.json.tmp"
            temporary.write_text(json.dumps(installed.to_wire(), sort_keys=True) + "\n")
            os.chmod(temporary, 0o600)
            temporary.replace(dataset_root / "current.json")
        except Exception:
            if replacement.exists():
                shutil.rmtree(target, ignore_errors=True)
                replacement.replace(target)
            raise
        shutil.rmtree(replacement, ignore_errors=True)
        return installed

    def remove(self, dataset_id: str) -> None:
        target = dataset_directory(self.root, dataset_id)
        if not target.exists():
            raise UsageError("error.dataset_not_installed", dataset_id=dataset_id)
        shutil.rmtree(target)

    def stage_directory(self) -> Path:
        staging_root = self.root / "staging"
        staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="install-", dir=staging_root))
