from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ccusage_viz.datasets.models import ReleaseArtifact, parse_sha256
from ccusage_viz.errors import UsageError

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PLATFORM_ARCHIVE = re.compile(r".+-(?P<os>[a-z0-9]+)-(?P<arch>[a-z0-9]+)\.tar\.gz$")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})$")
_CHECKSUM_ASSETS = frozenset({"checksums.txt", "sha256sums", "sha256sums.txt"})
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


def parse_repository(value: str) -> str:
    if not _REPOSITORY.fullmatch(value):
        raise UsageError("error.dataset_invalid_repository")
    return value


def parse_github_repository(value: str) -> str:
    """Normalize an owner/repository pair or a GitHub repository URL."""

    value = value.strip()
    if _REPOSITORY.fullmatch(value):
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.path.count("/") not in {2, 3}
    ):
        raise UsageError("error.dataset_invalid_repository")
    repository = parsed.path.strip("/")
    return parse_repository(repository)


def _read(
    url: str,
    *,
    accept: str = "application/vnd.github+json",
    expected_size: int | None = None,
) -> bytes:
    if not url.startswith("https://"):
        raise UsageError("error.dataset_download_failed")
    request = Request(url, headers={"Accept": accept, "User-Agent": "ccuv-datasets"})
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - URL validated by resolver.
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UsageError("error.dataset_download_failed") from exc
    if len(payload) > MAX_DOWNLOAD_BYTES or (
        expected_size is not None and len(payload) != expected_size
    ):
        raise UsageError("error.dataset_download_failed")
    return payload


def _parse_release(body: bytes) -> dict[str, object]:
    try:
        release = json.loads(body)
    except json.JSONDecodeError as exc:
        raise UsageError("error.dataset_download_failed") from exc
    if not isinstance(release, dict):
        raise UsageError("error.dataset_invalid_release")
    return release


def _release_assets(release: dict[str, object]) -> list[dict[str, object]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UsageError("error.dataset_invalid_release")
    return [asset for asset in assets if isinstance(asset, dict)]


def _artifact_from_asset(
    *, repository: str, release_tag: str, asset: dict[str, object], sha256: str
) -> ReleaseArtifact:
    name = asset.get("name")
    url = asset.get("browser_download_url")
    size = asset.get("size")
    if (
        not isinstance(name, str)
        or not isinstance(url, str)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise UsageError("error.dataset_invalid_release")
    return ReleaseArtifact(
        dataset_id=None,
        repository=repository,
        release_tag=release_tag,
        asset_name=name,
        download_url=url,
        sha256=parse_sha256(sha256),
        manifest_sha256=None,
        size=size,
        source_kind="github",
    )


def resolve_github_release(
    *, repository: str, release_tag: str, asset_name: str, expected_sha256: str
) -> ReleaseArtifact:
    repository = parse_repository(repository)
    if not release_tag or not asset_name:
        raise UsageError("error.dataset_invalid_release")
    release = _parse_release(
        _read(f"https://api.github.com/repos/{repository}/releases/tags/{release_tag}")
    )
    if release.get("draft") or release.get("tag_name") != release_tag:
        raise UsageError("error.dataset_invalid_release")
    matches = [asset for asset in _release_assets(release) if asset.get("name") == asset_name]
    if len(matches) != 1:
        raise UsageError("error.dataset_invalid_release")
    return _artifact_from_asset(
        repository=repository,
        release_tag=release_tag,
        asset=matches[0],
        sha256=expected_sha256,
    )


def _checksum_for_asset(asset: dict[str, object], checksum_asset: dict[str, object]) -> str:
    name = asset.get("name")
    url = checksum_asset.get("browser_download_url")
    size = checksum_asset.get("size")
    if (
        not isinstance(name, str)
        or not isinstance(url, str)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise UsageError("error.dataset_invalid_release")
    lines = (
        _read(url, accept="text/plain", expected_size=size)
        .decode("utf-8", errors="strict")
        .splitlines()
    )
    matches = [
        match.group(1)
        for line in lines
        if (match := re.fullmatch(r"([0-9a-f]{64})  \*?" + re.escape(name), line))
    ]
    if len(matches) != 1:
        raise UsageError("error.dataset_invalid_release")
    return matches[0]


def resolve_github_repository(*, repository: str, os: str, arch: str) -> ReleaseArtifact:
    """Resolve one verifiable stable platform archive from a GitHub repository."""

    repository = parse_github_repository(repository)
    release = _parse_release(_read(f"https://api.github.com/repos/{repository}/releases/latest"))
    tag = release.get("tag_name")
    if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not tag:
        raise UsageError("error.dataset_invalid_release")
    assets = _release_assets(release)
    matching_archives: list[dict[str, object]] = []
    for asset in assets:
        name = asset.get("name")
        if not isinstance(name, str):
            continue
        match = _PLATFORM_ARCHIVE.fullmatch(name)
        if match is not None and match["os"] == os and match["arch"] == arch:
            matching_archives.append(asset)
    if len(matching_archives) != 1:
        raise UsageError("error.dataset_platform_incompatible")
    archive = matching_archives[0]
    digest = archive.get("digest")
    if isinstance(digest, str) and (match := _DIGEST.fullmatch(digest)) is not None:
        sha256 = match.group(1)
    else:
        checksum_assets = [
            asset
            for asset in assets
            if isinstance(name := asset.get("name"), str) and name.lower() in _CHECKSUM_ASSETS
        ]
        if len(checksum_assets) != 1:
            raise UsageError("error.dataset_invalid_release")
        sha256 = _checksum_for_asset(archive, checksum_assets[0])
    return _artifact_from_asset(
        repository=repository,
        release_tag=tag,
        asset=archive,
        sha256=sha256,
    )


def resolve_official_artifact(
    artifact: ReleaseArtifact,
    *,
    expected_os: str,
    expected_arch: str,
) -> ReleaseArtifact:
    if (
        artifact.source_kind != "official"
        or artifact.dataset_id is None
        or artifact.os != expected_os
        or artifact.arch != expected_arch
    ):
        raise UsageError("error.dataset_platform_incompatible")
    expected_url = (
        f"https://github.com/{artifact.repository}/releases/download/"
        f"{artifact.release_tag}/{artifact.asset_name}"
    )
    if artifact.download_url != expected_url:
        raise UsageError("error.dataset_catalog_invalid")
    body = _read(
        f"https://api.github.com/repos/{artifact.repository}/releases/tags/{artifact.release_tag}"
    )
    try:
        release = json.loads(body)
    except json.JSONDecodeError as exc:
        raise UsageError("error.dataset_download_failed") from exc
    if (
        not isinstance(release, dict)
        or release.get("draft")
        or release.get("tag_name") != artifact.release_tag
    ):
        raise UsageError("error.dataset_download_failed")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UsageError("error.dataset_download_failed")
    matches = [
        item
        for item in assets
        if isinstance(item, dict) and item.get("name") == artifact.asset_name
    ]
    if len(matches) != 1:
        raise UsageError("error.dataset_download_failed")
    matched = matches[0]
    if (
        matched.get("browser_download_url") != artifact.download_url
        or matched.get("size") != artifact.size
    ):
        raise UsageError("error.dataset_download_failed")
    return artifact


def download_release_artifact(artifact: ReleaseArtifact) -> bytes:
    return _read(
        artifact.download_url,
        accept="application/octet-stream",
        expected_size=artifact.size,
    )
