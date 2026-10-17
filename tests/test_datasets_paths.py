from __future__ import annotations

from pathlib import Path

import pytest

from ccusage_viz.datasets.paths import (
    ccuv_state_root,
    dashboard_preset_state_root,
    dataset_directory,
    dataset_state_root,
)
from ccusage_viz.errors import UsageError


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    (
        ("darwin", {}, "/home/test/Library/Application Support/ccuv/datasets"),
        ("linux", {}, "/home/test/.local/state/ccuv/datasets"),
        ("linux", {"XDG_STATE_HOME": "/state"}, "/state/ccuv/datasets"),
        ("win32", {"LOCALAPPDATA": "/local"}, "/local/ccuv/datasets"),
    ),
)
def test_dataset_state_root_uses_platform_conventions(
    platform: str, environ: dict[str, str], expected: str
) -> None:
    assert dataset_state_root(environ=environ, home=Path("/home/test"), platform=platform) == Path(
        expected
    )


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    (
        ("darwin", {}, "/home/test/Library/Application Support/ccuv"),
        ("linux", {}, "/home/test/.local/state/ccuv"),
        ("linux", {"XDG_STATE_HOME": "/state"}, "/state/ccuv"),
        ("win32", {"LOCALAPPDATA": "/local"}, "/local/ccuv"),
    ),
)
def test_ccuv_state_roots_keep_dataset_and_preset_domains_as_siblings(
    platform: str, environ: dict[str, str], expected: str
) -> None:
    root = ccuv_state_root(environ=environ, home=Path("/home/test"), platform=platform)

    assert root == Path(expected)
    assert (
        dataset_state_root(environ=environ, home=Path("/home/test"), platform=platform)
        == root / "datasets"
    )
    assert (
        dashboard_preset_state_root(environ=environ, home=Path("/home/test"), platform=platform)
        == root / "dashboard-presets"
    )


def test_dataset_directory_rejects_unsafe_ids(tmp_path: Path) -> None:
    assert dataset_directory(tmp_path, "reading-time") == tmp_path / "reading-time"

    with pytest.raises(UsageError) as caught:
        dataset_directory(tmp_path, "../escape")

    assert caught.value.key == "error.dataset_invalid_id"
