from __future__ import annotations

import platform as system_platform
import shutil
from collections.abc import Mapping
from pathlib import Path

from ccusage_viz.datasets.archive import extract_dataset_archive, sha256_bytes
from ccusage_viz.datasets.github import (
    download_release_artifact,
    resolve_github_release,
    resolve_github_repository,
    resolve_official_artifact,
)
from ccusage_viz.datasets.models import (
    DatasetStatus,
    ReleaseArtifact,
    environment_status,
    parse_dataset_id,
)
from ccusage_viz.datasets.paths import dataset_state_root
from ccusage_viz.datasets.store import DatasetStore
from ccusage_viz.errors import UsageError
from ccusage_viz.options import CustomCommandSource


def host_platform() -> tuple[str, str]:
    systems = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}
    architectures = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}
    return systems.get(
        system_platform.system(), system_platform.system().lower()
    ), architectures.get(system_platform.machine(), system_platform.machine().lower())


class DatasetService:
    """Install and resolve datasets while leaving query execution provider-owned."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        platform: tuple[str, str] | None = None,
    ) -> None:
        self.environ = environ
        self.store = DatasetStore(dataset_state_root(environ=environ) if root is None else root)
        self.platform = host_platform() if platform is None else platform

    def status(self, dataset_id: str | None = None) -> tuple[DatasetStatus, ...]:
        if dataset_id is not None:
            identifier = parse_dataset_id(dataset_id)
            try:
                installed, manifest, _ = self.store.load(identifier)
            except UsageError as error:
                if (
                    error.key == "error.dataset_not_installed"
                    and identifier not in self.store.dataset_ids()
                ):
                    return (DatasetStatus(None, None, (), False, dataset_id=identifier),)
                return (DatasetStatus(None, None, (), True, dataset_id=identifier),)
            return (DatasetStatus(installed, manifest, environment_status(manifest, self.environ)),)
        statuses: list[DatasetStatus] = []
        for identifier in self.store.dataset_ids():
            try:
                installed, manifest, _ = self.store.load(identifier)
            except UsageError:
                statuses.append(DatasetStatus(None, None, (), True, dataset_id=identifier))
                continue
            statuses.append(
                DatasetStatus(installed, manifest, environment_status(manifest, self.environ))
            )
        return tuple(statuses)

    def official_catalog(self):
        from ccusage_viz.datasets.catalog import fetch_official_catalog

        return fetch_official_catalog()

    def official_entries(self):
        return self.official_catalog().entries

    def install_official(self, dataset_id: str, *, replace: bool = False) -> DatasetStatus:
        identifier = parse_dataset_id(dataset_id)
        catalog = self.official_catalog()
        host_os, host_arch = self.platform
        artifact = resolve_official_artifact(
            catalog.artifact_for(identifier, host_os, host_arch),
            expected_os=host_os,
            expected_arch=host_arch,
        )
        archive = download_release_artifact(artifact)
        return self.install_artifact(artifact, archive, replace=replace)

    def update_official(
        self, dataset_id: str | None = None, *, replace: bool = False
    ) -> tuple[DatasetStatus, ...]:
        if dataset_id is not None:
            identifiers = (parse_dataset_id(dataset_id),)
        else:
            identifiers = tuple(
                status.installed.dataset_id
                for status in self.status()
                if status.installed is not None and status.installed.source_kind == "official"
            )
        catalog = self.official_catalog()
        host_os, host_arch = self.platform
        updated: list[DatasetStatus] = []
        for identifier in identifiers:
            current = self.status(identifier)[0]
            if current.corrupt:
                raise UsageError("error.dataset_corrupt", dataset_id=identifier)
            if current.installed is None or current.installed.source_kind != "official":
                raise UsageError("error.dataset_not_official", dataset_id=identifier)
            artifact = catalog.artifact_for(identifier, host_os, host_arch)
            if (
                not replace
                and current.installed.repository == artifact.repository
                and current.installed.release_tag == artifact.release_tag
                and current.installed.asset_name == artifact.asset_name
                and current.installed.sha256 == artifact.sha256
                and current.installed.manifest_sha256 == artifact.manifest_sha256
            ):
                updated.append(current)
                continue
            artifact = resolve_official_artifact(
                artifact, expected_os=host_os, expected_arch=host_arch
            )
            archive = download_release_artifact(artifact)
            updated.append(self.install_artifact(artifact, archive, replace=True))
        return tuple(updated)

    def installed_command_source(self, dataset_id: str) -> CustomCommandSource:
        status = self.status(dataset_id)[0]
        if status.corrupt:
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id)
        if status.installed is None:
            raise UsageError("error.dataset_not_installed", dataset_id=dataset_id)
        if status.manifest is None:
            raise UsageError("error.dataset_corrupt", dataset_id=dataset_id)
        if not status.ready:
            raise UsageError("error.dataset_environment_missing", dataset_id=dataset_id)
        _, _, executable = self.store.load(dataset_id)
        return CustomCommandSource(dataset_id, (str(executable), "ccuv"), source_kind="installed")

    def install_artifact(
        self,
        artifact: ReleaseArtifact,
        archive: bytes,
        *,
        replace: bool = False,
    ) -> DatasetStatus:
        host_os, host_arch = self.platform
        staging = self.store.stage_directory()
        try:
            # Reserve a unique staging name, then let the strict extractor create
            # it so extraction cannot merge archive members into prior contents.
            staging.rmdir()
            manifest = extract_dataset_archive(
                archive,
                expected_sha256=artifact.sha256,
                destination=staging,
                expected_dataset_id=artifact.dataset_id,
                host_os=host_os,
                host_arch=host_arch,
            )
            manifest_sha256 = sha256_bytes((staging / "manifest.json").read_bytes())
            if artifact.manifest_sha256 is not None and manifest_sha256 != artifact.manifest_sha256:
                raise UsageError("error.dataset_manifest_invalid")
            try:
                current, _, _ = self.store.load(manifest.id)
            except UsageError as error:
                if error.key not in {"error.dataset_not_installed", "error.dataset_corrupt"}:
                    raise
            else:
                if current.repository != artifact.repository and not replace:
                    raise UsageError("error.dataset_source_conflict", dataset_id=manifest.id)
            installed = self.store.install(
                staged_version=staging,
                manifest=manifest,
                source_kind=artifact.source_kind,
                repository=artifact.repository,
                release_tag=artifact.release_tag,
                asset_name=artifact.asset_name,
                archive_sha256=artifact.sha256,
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return DatasetStatus(installed, manifest, environment_status(manifest, self.environ))

    def resolve_github_repository(self, repository: str) -> ReleaseArtifact:
        host_os, host_arch = self.platform
        return resolve_github_repository(repository=repository, os=host_os, arch=host_arch)

    def install_resolved_github_artifact(
        self, artifact: ReleaseArtifact, *, replace: bool = False
    ) -> DatasetStatus:
        if artifact.source_kind != "github":
            raise UsageError("error.dataset_invalid_release")
        archive = download_release_artifact(artifact)
        return self.install_artifact(artifact, archive, replace=replace)

    def install_github_repository(self, repository: str, *, replace: bool = False) -> DatasetStatus:
        return self.install_resolved_github_artifact(
            self.resolve_github_repository(repository), replace=replace
        )

    def install_github(
        self,
        *,
        repository: str,
        release_tag: str,
        asset_name: str,
        sha256: str,
        replace: bool = False,
    ) -> DatasetStatus:
        artifact = resolve_github_release(
            repository=repository,
            release_tag=release_tag,
            asset_name=asset_name,
            expected_sha256=sha256,
        )
        archive = download_release_artifact(artifact)
        return self.install_artifact(artifact, archive, replace=replace)

    def remove(self, dataset_id: str) -> None:
        self.store.remove(dataset_id)
