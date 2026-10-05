from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from ccusage_viz.errors import UsageError

_DATASET_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_SHA256 = re.compile(r"[0-9a-f]{64}$")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

DATASET_MANIFEST_SCHEMA = "ccuv.dataset/v1"
OFFICIAL_CATALOG_SCHEMA = "ccuv.dataset-catalog/v1"
CUSTOM_PROTOCOL = "ccuv.custom/v1"
CHART_KINDS = ("timeline", "calendar", "stack", "ranking")


@dataclass(frozen=True, slots=True)
class LocalizedText:
    en: str
    zh_cn: str

    @classmethod
    def parse(cls, value: object, *, field: str) -> LocalizedText:
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")
        en = value.get("en")
        zh_cn = value.get("zh-CN")
        if (
            not isinstance(en, str)
            or not en.strip()
            or not isinstance(zh_cn, str)
            or not zh_cn.strip()
        ):
            raise ValueError(f"{field} must contain non-empty en and zh-CN text")
        if set(value) != {"en", "zh-CN"}:
            raise ValueError(f"{field} contains unsupported fields")
        return cls(en.strip(), zh_cn.strip())


@dataclass(frozen=True, slots=True)
class DatasetUnit:
    id: str
    label: LocalizedText
    placement: Literal["prefix", "suffix"]
    decimal_places: int

    @classmethod
    def parse(cls, value: object, *, field: str) -> DatasetUnit:
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")
        identifier = value.get("id")
        placement = value.get("placement")
        decimal_places = value.get("decimal_places")
        if not isinstance(identifier, str) or not _DATASET_ID.fullmatch(identifier):
            raise ValueError(f"{field}.id is invalid")
        if placement not in {"prefix", "suffix"}:
            raise ValueError(f"{field}.placement is invalid")
        if (
            not isinstance(decimal_places, int)
            or isinstance(decimal_places, bool)
            or decimal_places < 0
        ):
            raise ValueError(f"{field}.decimal_places is invalid")
        if set(value) != {"id", "label", "placement", "decimal_places"}:
            raise ValueError(f"{field} contains unsupported fields")
        return cls(
            identifier,
            LocalizedText.parse(value.get("label"), field=f"{field}.label"),
            placement,
            decimal_places,
        )


@dataclass(frozen=True, slots=True)
class DatasetMetric:
    id: str
    title: LocalizedText
    unit: DatasetUnit

    @classmethod
    def parse(cls, value: object) -> DatasetMetric:
        if not isinstance(value, Mapping):
            raise ValueError("metric must be an object")
        identifier = value.get("id")
        if not isinstance(identifier, str) or not _DATASET_ID.fullmatch(identifier):
            raise ValueError("metric.id is invalid")
        if set(value) != {"id", "title", "unit"}:
            raise ValueError("metric contains unsupported fields")
        return cls(
            identifier,
            LocalizedText.parse(value.get("title"), field="metric.title"),
            DatasetUnit.parse(value.get("unit"), field="metric.unit"),
        )


@dataclass(frozen=True, slots=True)
class EnvironmentRequirement:
    name: str
    required: bool
    sensitive: bool
    label: LocalizedText
    how_to_get: LocalizedText
    help_url: str | None = None

    @classmethod
    def parse(cls, value: object) -> EnvironmentRequirement:
        if not isinstance(value, Mapping):
            raise ValueError("environment requirement must be an object")
        allowed = {"name", "required", "sensitive", "label", "how_to_get", "help_url"}
        if not set(value).issubset(allowed) or {
            "name",
            "required",
            "sensitive",
            "label",
            "how_to_get",
        } - set(value):
            raise ValueError("environment requirement contains unsupported or missing fields")
        name = value.get("name")
        required = value.get("required")
        sensitive = value.get("sensitive")
        help_url = value.get("help_url")
        if not isinstance(name, str) or not _ENVIRONMENT_NAME.fullmatch(name):
            raise ValueError("environment requirement name is invalid")
        if not isinstance(required, bool) or not isinstance(sensitive, bool):
            raise ValueError("environment requirement flags are invalid")
        if help_url is not None and (
            not isinstance(help_url, str) or not help_url.startswith("https://")
        ):
            raise ValueError("environment requirement help_url is invalid")
        return cls(
            name,
            required,
            sensitive,
            LocalizedText.parse(value.get("label"), field=f"environment.{name}.label"),
            LocalizedText.parse(value.get("how_to_get"), field=f"environment.{name}.how_to_get"),
            help_url,
        )


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    id: str
    version: str
    protocol: str
    entrypoint: str
    os: str
    arch: str
    metric: DatasetMetric
    charts: tuple[str, ...]
    environment: tuple[EnvironmentRequirement, ...]

    @classmethod
    def parse(cls, value: object) -> DatasetManifest:
        if not isinstance(value, Mapping):
            raise ValueError("manifest must be an object")
        allowed = {
            "schema",
            "id",
            "version",
            "protocol",
            "entrypoint",
            "platform",
            "metric",
            "charts",
            "environment",
        }
        if set(value) != allowed:
            raise ValueError("manifest contains unsupported or missing fields")
        if value.get("schema") != DATASET_MANIFEST_SCHEMA:
            raise ValueError("manifest schema is unsupported")
        identifier = value.get("id")
        version = value.get("version")
        protocol = value.get("protocol")
        entrypoint = value.get("entrypoint")
        platform = value.get("platform")
        charts = value.get("charts")
        environment = value.get("environment")
        if not isinstance(identifier, str) or not _DATASET_ID.fullmatch(identifier):
            raise ValueError("manifest id is invalid")
        if not isinstance(version, str) or not _SEMVER.fullmatch(version):
            raise ValueError("manifest version is invalid")
        if protocol != CUSTOM_PROTOCOL:
            raise ValueError("manifest protocol is unsupported")
        if (
            not isinstance(entrypoint, str)
            or not entrypoint.startswith("bin/")
            or "/" in entrypoint[4:]
            or "\\" in entrypoint
        ):
            raise ValueError("manifest entrypoint is invalid")
        if not isinstance(platform, Mapping) or set(platform) != {"os", "arch"}:
            raise ValueError("manifest platform is invalid")
        platform_os = platform.get("os")
        platform_arch = platform.get("arch")
        if (
            not isinstance(platform_os, str)
            or not platform_os
            or not isinstance(platform_arch, str)
            or not platform_arch
        ):
            raise ValueError("manifest platform is invalid")
        if not isinstance(charts, list) or tuple(charts) != CHART_KINDS:
            raise ValueError("manifest must support the four chart kinds in canonical order")
        if not isinstance(environment, list):
            raise ValueError("manifest environment is invalid")
        requirements = tuple(EnvironmentRequirement.parse(item) for item in environment)
        if len({item.name for item in requirements}) != len(requirements):
            raise ValueError("manifest environment names must be unique")
        return cls(
            identifier,
            version,
            protocol,
            entrypoint,
            platform_os,
            platform_arch,
            DatasetMetric.parse(value.get("metric")),
            tuple(charts),
            requirements,
        )


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    dataset_id: str | None
    repository: str
    release_tag: str
    asset_name: str
    download_url: str
    sha256: str
    manifest_sha256: str | None
    size: int
    source_kind: Literal["official", "github"]
    os: str | None = None
    arch: str | None = None

    def __post_init__(self) -> None:
        if self.dataset_id is not None and not _DATASET_ID.fullmatch(self.dataset_id):
            raise ValueError("dataset ID is invalid")
        if not _REPOSITORY.fullmatch(self.repository):
            raise ValueError("repository is invalid")
        if (
            not self.release_tag
            or not self.asset_name
            or not self.download_url.startswith("https://")
        ):
            raise ValueError("release artifact is invalid")
        if not _SHA256.fullmatch(self.sha256) or (
            self.manifest_sha256 is not None and not _SHA256.fullmatch(self.manifest_sha256)
        ):
            raise ValueError("release digest is invalid")
        if self.size <= 0:
            raise ValueError("release size is invalid")
        if (self.os is None) != (self.arch is None) or (
            self.os is not None and (not self.os or not self.arch)
        ):
            raise ValueError("release platform is invalid")
        if self.source_kind == "official":
            expected_url = (
                f"https://github.com/{self.repository}/releases/download/"
                f"{self.release_tag}/{self.asset_name}"
            )
            if (
                self.dataset_id is None
                or self.manifest_sha256 is None
                or self.os is None
                or self.arch is None
                or self.download_url != expected_url
            ):
                raise ValueError("official release artifact is invalid")

    @classmethod
    def parse_official(cls, value: object, *, dataset_id: str) -> ReleaseArtifact:
        if not isinstance(value, Mapping) or set(value) != {
            "repository",
            "release_tag",
            "asset_name",
            "download_url",
            "sha256",
            "manifest_sha256",
            "size",
            "platform",
        }:
            raise ValueError("catalog artifact is invalid")
        platform = value.get("platform")
        if not isinstance(platform, Mapping) or set(platform) != {"os", "arch"}:
            raise ValueError("catalog artifact platform is invalid")
        repository = value.get("repository")
        release_tag = value.get("release_tag")
        asset_name = value.get("asset_name")
        download_url = value.get("download_url")
        sha256 = value.get("sha256")
        manifest_sha256 = value.get("manifest_sha256")
        size = value.get("size")
        os = platform.get("os")
        arch = platform.get("arch")
        if (
            not all(
                isinstance(item, str)
                for item in (
                    repository,
                    release_tag,
                    asset_name,
                    download_url,
                    sha256,
                    manifest_sha256,
                    os,
                    arch,
                )
            )
            or not isinstance(size, int)
            or isinstance(size, bool)
        ):
            raise ValueError("catalog artifact fields are invalid")
        return cls(
            dataset_id,
            cast(str, repository),
            cast(str, release_tag),
            cast(str, asset_name),
            cast(str, download_url),
            cast(str, sha256),
            cast(str, manifest_sha256),
            size,
            "official",
            cast(str, os),
            cast(str, arch),
        )


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    title: LocalizedText
    description: LocalizedText
    artifacts: tuple[ReleaseArtifact, ...]

    @classmethod
    def parse(cls, value: object) -> CatalogEntry:
        if not isinstance(value, Mapping) or set(value) != {
            "id",
            "title",
            "description",
            "artifacts",
        }:
            raise ValueError("catalog entry is invalid")
        identifier = value.get("id")
        artifacts = value.get("artifacts")
        if not isinstance(identifier, str) or not _DATASET_ID.fullmatch(identifier):
            raise ValueError("catalog entry ID is invalid")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("catalog entry artifacts are invalid")
        return cls(
            identifier,
            LocalizedText.parse(value.get("title"), field="catalog.title"),
            LocalizedText.parse(value.get("description"), field="catalog.description"),
            tuple(
                ReleaseArtifact.parse_official(item, dataset_id=identifier) for item in artifacts
            ),
        )


@dataclass(frozen=True, slots=True)
class InstalledDataset:
    dataset_id: str
    version: str
    source_kind: Literal["official", "github"]
    repository: str
    release_tag: str
    asset_name: str
    sha256: str
    manifest_sha256: str
    installed_at: str

    def to_wire(self) -> dict[str, str | int]:
        return {
            "schema": 1,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "source_kind": self.source_kind,
            "repository": self.repository,
            "release_tag": self.release_tag,
            "asset_name": self.asset_name,
            "sha256": self.sha256,
            "manifest_sha256": self.manifest_sha256,
            "installed_at": self.installed_at,
        }

    @classmethod
    def parse(cls, value: object) -> InstalledDataset:
        if not isinstance(value, Mapping) or value.get("schema") != 1:
            raise ValueError("installed dataset state is invalid")
        allowed = {
            "schema",
            "dataset_id",
            "version",
            "source_kind",
            "repository",
            "release_tag",
            "asset_name",
            "sha256",
            "manifest_sha256",
            "installed_at",
        }
        if set(value) != allowed:
            raise ValueError("installed dataset state contains unsupported fields")
        source_kind = value.get("source_kind")
        dataset_id = value.get("dataset_id")
        version = value.get("version")
        repository = value.get("repository")
        release_tag = value.get("release_tag")
        asset_name = value.get("asset_name")
        sha256 = value.get("sha256")
        manifest_sha256 = value.get("manifest_sha256")
        installed_at = value.get("installed_at")
        fields = (
            dataset_id,
            version,
            repository,
            release_tag,
            asset_name,
            sha256,
            manifest_sha256,
            installed_at,
        )
        if source_kind not in {"official", "github"} or not all(
            isinstance(field, str) and field for field in fields
        ):
            raise ValueError("installed dataset state is invalid")
        return cls(
            dataset_id=cast(str, dataset_id),
            version=cast(str, version),
            source_kind=cast(Literal["official", "github"], source_kind),
            repository=cast(str, repository),
            release_tag=cast(str, release_tag),
            asset_name=cast(str, asset_name),
            sha256=cast(str, sha256),
            manifest_sha256=cast(str, manifest_sha256),
            installed_at=cast(str, installed_at),
        )


@dataclass(frozen=True, slots=True)
class DatasetEnvironmentStatus:
    requirement: EnvironmentRequirement
    present: bool


@dataclass(frozen=True, slots=True)
class DatasetStatus:
    installed: InstalledDataset | None
    manifest: DatasetManifest | None
    environment: tuple[DatasetEnvironmentStatus, ...]
    corrupt: bool = False
    dataset_id: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.installed is not None
            and not self.corrupt
            and all(
                status.present or not status.requirement.required for status in self.environment
            )
        )

    @property
    def missing_required(self) -> tuple[DatasetEnvironmentStatus, ...]:
        return tuple(
            status
            for status in self.environment
            if status.requirement.required and not status.present
        )


def environment_status(
    manifest: DatasetManifest, environ: Mapping[str, str] | None = None
) -> tuple[DatasetEnvironmentStatus, ...]:
    values = os.environ if environ is None else environ
    return tuple(
        DatasetEnvironmentStatus(requirement, bool(values.get(requirement.name)))
        for requirement in manifest.environment
    )


def parse_dataset_id(value: str) -> str:
    if not _DATASET_ID.fullmatch(value):
        raise UsageError("error.dataset_invalid_id", dataset_id=value)
    return value


def parse_sha256(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise UsageError("error.dataset_invalid_sha256")
    return value
