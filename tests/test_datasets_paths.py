from __future__ import annotations

from pathlib import Path

import pytest

from ccusage_viz.datasets.paths import dataset_directory, dataset_state_root
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


def test_dataset_directory_rejects_unsafe_ids(tmp_path: Path) -> None:
    assert dataset_directory(tmp_path, "reading-time") == tmp_path / "reading-time"

    with pytest.raises(UsageError) as caught:
        dataset_directory(tmp_path, "../escape")

    assert caught.value.key == "error.dataset_invalid_id"
