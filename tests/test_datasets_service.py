from __future__ import annotations

from pathlib import Path

import pytest

from ccusage_viz.custom_models import (
    CustomCapabilities,
    CustomChartCapability,
    CustomChartDefaults,
    CustomDataset,
    CustomProbeDescriptor,
    CustomUnit,
    LocalizedText,
)
from ccusage_viz.custom_protocol import CustomProbeResponse
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


def probe(dataset_id: str = "weread") -> CustomProbeResponse:
    text = LocalizedText("WeRead", "微信读书")
    descriptor = CustomProbeDescriptor(
        "weread-1",
        "0.1.0",
        CustomDataset(text, text, CustomUnit("minute", text, "suffix", 2)),
        CustomCapabilities((), (), {"timeline": CustomChartCapability(("day",), (), ())}),
        {"timeline": CustomChartDefaults("14d", None, None)},
        (),
    )
    return CustomProbeResponse(dataset_id, descriptor)


def test_register_local_command_uses_probe_identity_and_preserves_argv(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: probe())

    result = service.register_local_command(("reader", "ccuv"))

    assert result.kind == "created"
    assert result.registration.dataset_id == "weread"
    assert result.registration.source.command_argv == ("reader", "ccuv")
    assert service.registrations()[0].availability == "ready"


def test_register_local_command_requires_explicit_replace_for_conflict(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: probe())
    service.register_local_command(("reader-a", "ccuv"))

    conflict = service.register_local_command(("reader-b", "ccuv"))
    replacement = service.register_local_command(("reader-b", "ccuv"), replace=True)

    assert conflict.kind == "conflict"
    assert replacement.kind == "replaced"
    assert service.registrations()[0].registration.source.command_argv == ("reader-b", "ccuv")


def test_local_registration_can_be_disabled_reenabled_and_removed_without_target_deletion(
    tmp_path: Path,
) -> None:
    target = tmp_path / "reader"
    target.write_text("#!/bin/sh\n")
    service = DatasetService(root=tmp_path / "state", environ={}, probe_runner=lambda _argv: probe())
    service.register_local_command((str(target), "ccuv"))

    service.set_enabled("weread", False)
    assert service.registrations()[0].availability == "disabled"
    service.set_enabled("weread", True)
    assert service.registrations()[0].availability == "ready"
    service.remove_registration("weread")

    assert target.exists()
    assert service.registrations() == ()


def test_refresh_preserves_last_successful_snapshot_when_probe_fails(tmp_path: Path) -> None:
    responses = [probe(), RuntimeError("command failed")]

    def run_probe(_argv: tuple[str, ...]) -> CustomProbeResponse:
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    service = DatasetService(root=tmp_path, environ={}, probe_runner=run_probe)
    created = service.register_local_command(("reader", "ccuv")).registration

    refreshed = service.refresh_all()[0]

    assert refreshed.availability == "unavailable"
    assert refreshed.registration.probe == created.probe
    assert refreshed.registration.last_probe_error == "command failed"
