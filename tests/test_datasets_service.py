from __future__ import annotations

from pathlib import Path

import pytest

from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.errors import UsageError


def test_status_exposes_corrupt_dataset_without_executing_it(tmp_path: Path) -> None:
    (tmp_path / "weread").mkdir()
    service = DatasetService(root=tmp_path, environ={})

    status = service.status()

    assert len(status) == 1
    assert status[0].dataset_id == "weread"
    assert status[0].corrupt
    assert status[0].installed is None

    with pytest.raises(UsageError) as caught:
        service.installed_command_source("weread")

    assert caught.value.key == "error.dataset_corrupt"


def test_status_rejects_invalid_dataset_id(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={})

    with pytest.raises(UsageError) as caught:
        service.status("../weread")

    assert caught.value.key == "error.dataset_invalid_id"
