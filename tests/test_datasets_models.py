from __future__ import annotations

import pytest

from ccusage_viz.datasets.models import (
    DatasetManifest,
    InstalledDataset,
    environment_status,
)


def manifest_wire(*, environment: list[object] | None = None) -> dict[str, object]:
    return {
        "schema": "ccuv.dataset/v1",
        "id": "reading-time",
        "version": "1.2.3",
        "protocol": "ccuv.custom/v1",
        "entrypoint": "bin/reading-time",
        "platform": {"os": "darwin", "arch": "arm64"},
        "metric": {
            "id": "reading-minutes",
            "title": {"en": "Reading time", "zh-CN": "阅读时长"},
            "unit": {
                "id": "minutes",
                "label": {"en": "minutes", "zh-CN": "分钟"},
                "placement": "suffix",
                "decimal_places": 0,
            },
        },
        "charts": ["timeline", "calendar", "stack", "ranking"],
        "environment": [] if environment is None else environment,
    }


def test_manifest_requires_exact_supported_contract() -> None:
    manifest = DatasetManifest.parse(manifest_wire())

    assert manifest.id == "reading-time"
    assert manifest.entrypoint == "bin/reading-time"
    assert manifest.charts == ("timeline", "calendar", "stack", "ranking")

    invalid = manifest_wire()
    invalid["charts"] = ["timeline", "ranking"]
    with pytest.raises(ValueError, match="four chart kinds"):
        DatasetManifest.parse(invalid)


def test_manifest_accepts_static_probe_descriptor_without_duplicate_metadata() -> None:
    manifest = DatasetManifest.parse(
        {
            "schema": "ccuv.dataset/v1",
            "protocol": "ccuv.custom/v1",
            "entrypoint": "bin/reading-time",
            "platform": {"os": "darwin", "arch": "arm64"},
            "probe": {
                "dataset_id": "reading-time",
                "descriptor": {
                    "revision": "reading-1",
                    "version": "1.2.3",
                    "dataset": {
                        "title": {"en": "Reading time", "zh-CN": "阅读时长"},
                        "description": {"en": "Daily reading", "zh-CN": "每日阅读"},
                        "unit": {
                            "id": "minutes",
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
    )

    assert manifest.id == "reading-time"
    assert manifest.version == "1.2.3"
    assert manifest.charts == ("timeline",)


def test_environment_status_never_retains_values() -> None:
    manifest = DatasetManifest.parse(
        manifest_wire(
            environment=[
                {
                    "name": "READING_TOKEN",
                    "required": True,
                    "sensitive": True,
                    "label": {"en": "Reading token", "zh-CN": "阅读令牌"},
                    "how_to_get": {"en": "Create one", "zh-CN": "创建令牌"},
                }
            ]
        )
    )

    statuses = environment_status(manifest, {"READING_TOKEN": "secret-value"})

    assert statuses[0].present is True
    assert "secret-value" not in repr(statuses)


def test_installed_dataset_round_trip_rejects_unknown_fields() -> None:
    installed = InstalledDataset(
        "reading-time",
        "1.2.3",
        "official",
        "Cookie-HOO/ccuv-dataset-reading-time",
        "v1.2.3",
        "reading-time-darwin-arm64.tar.gz",
        "a" * 64,
        "b" * 64,
        "2026-10-04T00:00:00+00:00",
    )

    assert InstalledDataset.parse(installed.to_wire()) == installed

    invalid = installed.to_wire() | {"extra": "value"}
    with pytest.raises(ValueError, match="unsupported fields"):
        InstalledDataset.parse(invalid)
