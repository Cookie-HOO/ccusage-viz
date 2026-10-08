from __future__ import annotations

import io
import json
import tarfile
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
    V2Dataset,
    V2MetricCapabilities,
    V2MetricDescriptor,
    V2MonitorCapability,
    V2ProbeDescriptor,
)
from ccusage_viz.custom_protocol import CustomProbeResponse, V2ProbeResponse
from ccusage_viz.datasets.archive import sha256_bytes
from ccusage_viz.datasets.models import ReleaseArtifact
from ccusage_viz.datasets.service import DatasetService
from ccusage_viz.errors import UsageError
from ccusage_viz.options import CustomCommandSource


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


def v2_probe(dataset_id: str = "router") -> V2ProbeResponse:
    text = LocalizedText("Router", "Router")
    descriptor = V2ProbeDescriptor(
        "router-1",
        "0.1.0",
        V2Dataset(text, LocalizedText("Live", "实时")),
        (
            V2MetricDescriptor(
                "tokens",
                LocalizedText("Tokens", "Token"),
                LocalizedText("Live", "实时"),
                CustomUnit("token", text, "suffix", 0),
                "sum",
                V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
                {"monitor": CustomChartDefaults(None, None, None, style="ranking", window_seconds=21600, declared=frozenset({"style", "window"}))},
            ),
            V2MetricDescriptor(
                "completed_requests",
                LocalizedText("Requests", "请求"),
                LocalizedText("Live", "实时"),
                CustomUnit("request", text, "suffix", 0),
                "sum",
                V2MetricCapabilities((), (), {"monitor": V2MonitorCapability(60, 10, (), ())}),
                {"monitor": CustomChartDefaults(None, None, None, style="ranking", window_seconds=21600, declared=frozenset({"style", "window"}))},
            ),
        ),
        (),
    )
    return V2ProbeResponse(dataset_id, descriptor)


def test_registers_and_persists_a_v2_multi_metric_local_dataset(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: v2_probe())

    result = service.register_local_command(("router-dataset",))
    restored = service.store.load_registration("router")

    assert result.kind == "created"
    assert tuple(metric.id for metric in restored.probe.descriptor.metrics) == (
        "tokens",
        "completed_requests",
    )


def test_runtime_probe_refreshes_matching_registered_local_command(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: v2_probe())
    registration = service.register_local_command(("router-dataset",)).registration
    response = v2_probe()

    assert service.update_runtime_probe(
        CustomCommandSource("router", ("router-dataset",)), response
    )
    refreshed = service.store.load_registration("router")

    assert refreshed.probe.descriptor == response.descriptor
    assert refreshed.updated_at != registration.updated_at


def test_runtime_probe_does_not_replace_a_different_local_command(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: v2_probe())
    service.register_local_command(("router-dataset",))

    assert not service.update_runtime_probe(
        CustomCommandSource("router", ("other-router-dataset",)), v2_probe()
    )


def test_register_local_command_uses_probe_identity_and_preserves_argv(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: probe())

    result = service.register_local_command(("reader", "ccuv"))

    assert result.kind == "created"
    assert result.registration.dataset_id == "weread"
    assert result.registration.source.command_argv == ("reader", "ccuv")
    assert service.registrations()[0].availability == "ready"
    assert service.discover_local_command(("reader", "ccuv")).dataset_id == "weread"


def test_register_local_command_requires_explicit_replace_for_conflict(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: probe())
    service.register_local_command(("reader-a", "ccuv"))

    conflict = service.register_local_command(("reader-b", "ccuv"))
    replacement = service.register_local_command(("reader-b", "ccuv"), replace=True)

    assert conflict.kind == "conflict"
    assert replacement.kind == "replaced"
    assert service.registrations()[0].registration.source.command_argv == ("reader-b", "ccuv")


def test_registering_same_local_command_still_requires_explicit_replace(tmp_path: Path) -> None:
    service = DatasetService(root=tmp_path, environ={}, probe_runner=lambda _argv: probe())
    service.register_local_command(("reader", "ccuv"))

    result = service.register_local_command(("reader", "ccuv"))

    assert result.kind == "conflict"


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


def _archive() -> bytes:
    manifest = {
        "schema": "ccuv.dataset/v1",
        "protocol": "ccuv.custom/v1",
        "entrypoint": "bin/weread",
        "platform": {"os": "darwin", "arch": "arm64"},
        "probe": {
            "dataset_id": "weread",
            "descriptor": {
                "revision": "weread-1",
                "version": "0.1.0",
                "dataset": {
                    "title": {"en": "WeRead", "zh-CN": "微信读书"},
                    "description": {"en": "Reading activity", "zh-CN": "阅读活动"},
                    "unit": {
                        "id": "minute",
                        "label": {"en": "minutes", "zh-CN": "分钟"},
                        "placement": "suffix",
                        "decimal_places": 0,
                    },
                },
                "capabilities": {
                    "group_by": [],
                    "filters": [],
                    "charts": {"timeline": {"granularities": ["day"], "group_by": [], "filters": []}},
                },
                "defaults": {"timeline": {"period": "14d", "group_by": None, "top": None}},
                "environment": [],
            },
        },
    }
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        document = json.dumps(manifest).encode()
        item = tarfile.TarInfo("manifest.json")
        item.size = len(document)
        archive.addfile(item, io.BytesIO(document))
        executable = b"#!/bin/sh\n"
        item = tarfile.TarInfo("bin/weread")
        item.size = len(executable)
        archive.addfile(item, io.BytesIO(executable))
    return payload.getvalue()


def test_inspect_artifact_validates_full_descriptor_without_installing(tmp_path: Path) -> None:
    archive = _archive()
    manifest_sha256 = sha256_bytes(
        json.dumps(
            {
                "schema": "ccuv.dataset/v1",
                "protocol": "ccuv.custom/v1",
                "entrypoint": "bin/weread",
                "platform": {"os": "darwin", "arch": "arm64"},
                "probe": {
                    "dataset_id": "weread",
                    "descriptor": {
                        "revision": "weread-1",
                        "version": "0.1.0",
                        "dataset": {
                            "title": {"en": "WeRead", "zh-CN": "微信读书"},
                            "description": {"en": "Reading activity", "zh-CN": "阅读活动"},
                            "unit": {
                                "id": "minute",
                                "label": {"en": "minutes", "zh-CN": "分钟"},
                                "placement": "suffix",
                                "decimal_places": 0,
                            },
                        },
                        "capabilities": {
                            "group_by": [],
                            "filters": [],
                            "charts": {"timeline": {"granularities": ["day"], "group_by": [], "filters": []}},
                        },
                        "defaults": {"timeline": {"period": "14d", "group_by": None, "top": None}},
                        "environment": [],
                    },
                },
            }
        ).encode()
    )
    artifact = ReleaseArtifact(
        "weread",
        "example/weread",
        "v0.1.0",
        "weread-darwin-arm64.tar.gz",
        "https://github.com/example/weread/releases/download/v0.1.0/weread-darwin-arm64.tar.gz",
        sha256_bytes(archive),
        manifest_sha256,
        len(archive),
        "official",
        "darwin",
        "arm64",
    )
    service = DatasetService(root=tmp_path, environ={}, platform=("darwin", "arm64"))

    manifest = service.inspect_artifact(artifact, archive)

    assert manifest.descriptor is not None
    assert manifest.descriptor.dataset.description.en == "Reading activity"
    assert service.store.dataset_ids() == ()
    assert not (tmp_path / "staging").exists() or not tuple((tmp_path / "staging").iterdir())
