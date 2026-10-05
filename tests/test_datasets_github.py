from __future__ import annotations

import pytest

from ccusage_viz.datasets.github import (
    download_release_artifact,
    parse_github_repository,
    parse_repository,
    resolve_github_repository,
)
from ccusage_viz.datasets.models import ReleaseArtifact
from ccusage_viz.errors import UsageError


def artifact() -> ReleaseArtifact:
    return ReleaseArtifact(
        dataset_id=None,
        repository="example/weread",
        release_tag="v1.0.0",
        asset_name="weread-darwin-arm64.tar.gz",
        download_url="https://github.com/example/weread/releases/download/v1.0.0/weread.tar.gz",
        sha256="a" * 64,
        manifest_sha256=None,
        size=42,
        source_kind="github",
    )


def test_download_release_artifact_requires_github_declared_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def read(url: str, *, accept: str, expected_size: int | None = None) -> bytes:
        observed.update(url=url, accept=accept, expected_size=expected_size)
        return b"archive"

    monkeypatch.setattr("ccusage_viz.datasets.github._read", read)

    assert download_release_artifact(artifact()) == b"archive"
    assert observed == {
        "url": "https://github.com/example/weread/releases/download/v1.0.0/weread.tar.gz",
        "accept": "application/octet-stream",
        "expected_size": 42,
    }


@pytest.mark.parametrize(
    "value", ("", "owner", "owner/repo/extra", "https://github.com/owner/repo")
)
def test_parse_repository_rejects_non_canonical_repositories(value: str) -> None:
    with pytest.raises(UsageError) as caught:
        parse_repository(value)

    assert caught.value.key == "error.dataset_invalid_repository"


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("Cookie-HOO/ccuv-dataset-weread", "Cookie-HOO/ccuv-dataset-weread"),
        (
            "https://github.com/Cookie-HOO/ccuv-dataset-weread",
            "Cookie-HOO/ccuv-dataset-weread",
        ),
    ),
)
def test_parse_github_repository_accepts_one_simple_input(value: str, expected: str) -> None:
    assert parse_github_repository(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "http://github.com/owner/repo",
        "https://github.com/owner/repo/",
        "https://github.com/owner/repo/releases",
        "https://github.com/owner/repo?ref=main",
        "https://example.com/owner/repo",
    ),
)
def test_parse_github_repository_rejects_noncanonical_links(value: str) -> None:
    with pytest.raises(UsageError) as caught:
        parse_github_repository(value)

    assert caught.value.key == "error.dataset_invalid_repository"


def test_resolve_github_repository_uses_github_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "tag_name": "v1.2.3",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "ccuv-dataset-weread-darwin-arm64.tar.gz",
                "browser_download_url": "https://github.com/Cookie-HOO/ccuv-dataset-weread/releases/download/v1.2.3/ccuv-dataset-weread-darwin-arm64.tar.gz",
                "size": 42,
                "digest": "sha256:" + "b" * 64,
            }
        ],
    }
    monkeypatch.setattr(
        "ccusage_viz.datasets.github._read",
        lambda *_args, **_kwargs: __import__("json").dumps(payload).encode(),
    )

    artifact = resolve_github_repository(
        repository="https://github.com/Cookie-HOO/ccuv-dataset-weread", os="darwin", arch="arm64"
    )

    assert artifact.repository == "Cookie-HOO/ccuv-dataset-weread"
    assert artifact.release_tag == "v1.2.3"
    assert artifact.sha256 == "b" * 64


def test_resolve_github_repository_requires_a_verifiable_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "tag_name": "v1.2.3",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "ccuv-dataset-weread-darwin-arm64.tar.gz",
                "browser_download_url": "https://github.com/Cookie-HOO/ccuv-dataset-weread/releases/download/v1.2.3/ccuv-dataset-weread-darwin-arm64.tar.gz",
                "size": 42,
            }
        ],
    }
    monkeypatch.setattr(
        "ccusage_viz.datasets.github._read",
        lambda *_args, **_kwargs: __import__("json").dumps(payload).encode(),
    )

    with pytest.raises(UsageError) as caught:
        resolve_github_repository(
            repository="Cookie-HOO/ccuv-dataset-weread", os="darwin", arch="arm64"
        )

    assert caught.value.key == "error.dataset_invalid_release"
