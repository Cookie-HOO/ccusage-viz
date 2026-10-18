from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import ccusage_viz.datasets.catalog as catalog_module
from ccusage_viz.datasets.catalog import (
    CATALOG_PUBLIC_KEY_B64,
    fetch_official_catalog,
    parse_and_verify_official_catalog,
)
from ccusage_viz.errors import UsageError


def signed_catalog(
    private_key: Ed25519PrivateKey,
    *,
    entries: list[object] | None = None,
    issued_at: datetime | None = None,
) -> tuple[bytes, str]:
    issued_at = issued_at or datetime(2026, 10, 4, tzinfo=UTC)
    signed = {
        "schema": "ccuv.official-dataset-catalog/v1",
        "catalog_version": 1,
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "entries": entries or [],
    }
    public_key = private_key.public_key().public_bytes_raw()
    envelope = {
        "schema": "ccuv.official-dataset-catalog-envelope/v1",
        "key_id": "ccuv-official-2026-01",
        "signed": signed,
        "signature": {
            "algorithm": "Ed25519",
            "encoding": "base64",
            "value": base64.b64encode(private_key.sign(rfc8785.dumps(signed))).decode(),
        },
    }
    return json.dumps(envelope).encode(), base64.b64encode(public_key).decode()


def catalog_entry() -> dict[str, object]:
    return {
        "id": "weread",
        "title": {"en": "WeRead", "zh-CN": "微信读书"},
        "summary": {"en": "Visualize reading activity", "zh-CN": "将阅读活动可视化"},
        "repository": "Cookie-HOO/ccuv-dataset-weread",
        "artifacts": [
            {
                "release_tag": "v1.2.3",
                "asset_name": "weread-darwin-arm64.tar.gz",
                "download_url": "https://github.com/Cookie-HOO/ccuv-dataset-weread/releases/download/v1.2.3/weread-darwin-arm64.tar.gz",
                "sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "size": 123,
                "platform": {"os": "darwin", "arch": "arm64"},
            }
        ],
    }


def test_catalog_distinguishes_github_connectivity_from_unavailable_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> object:
        raise URLError("offline")

    monkeypatch.setattr(catalog_module, "urlopen", fail_network)
    with pytest.raises(UsageError) as network:
        fetch_official_catalog()
    assert network.value.key == "error.dataset_catalog_network"

    def fail_http(*_args: object, **_kwargs: object) -> object:
        raise HTTPError("catalog", 503, "unavailable", {}, None)

    monkeypatch.setattr(catalog_module, "urlopen", fail_http)
    with pytest.raises(UsageError) as unavailable:
        fetch_official_catalog()
    assert unavailable.value.key == "error.dataset_catalog_unavailable"


def test_compiled_catalog_public_key_is_a_raw_ed25519_key() -> None:
    assert len(base64.b64decode(CATALOG_PUBLIC_KEY_B64, validate=True)) == 32


def test_catalog_verifies_signed_entries_and_selects_platform() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload, public_key = signed_catalog(private_key, entries=[catalog_entry()])

    catalog = parse_and_verify_official_catalog(
        payload, now=datetime(2026, 10, 5, tzinfo=UTC), public_key_b64=public_key
    )

    artifact = catalog.artifact_for("weread", "darwin", "arm64")
    assert catalog.entry("weread").title.en == "WeRead"
    assert catalog.entry("weread").summary.zh_cn == "将阅读活动可视化"
    assert catalog.entry("weread").repository == "Cookie-HOO/ccuv-dataset-weread"
    assert artifact.release_tag == "v1.2.3"
    assert artifact.source_kind == "official"
    assert catalog.entry_for_repository("Cookie-HOO/ccuv-dataset-weread") == catalog.entry("weread")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["signed"]["entries"][0].update({"id": "other"}),
        lambda value: value["signed"]["entries"][0]["artifacts"][0].update({"sha256": "c" * 64}),
    ],
)
def test_catalog_rejects_unsigned_tampering(mutation: object) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload, public_key = signed_catalog(private_key, entries=[catalog_entry()])
    envelope = json.loads(payload)
    mutation(envelope)  # type: ignore[operator]

    with pytest.raises(UsageError) as caught:
        parse_and_verify_official_catalog(
            json.dumps(envelope).encode(),
            now=datetime(2026, 10, 5, tzinfo=UTC),
            public_key_b64=public_key,
        )

    assert caught.value.key == "error.dataset_catalog_signature"


def test_catalog_accepts_an_old_signed_body_from_the_trusted_official_source() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload, public_key = signed_catalog(
        private_key,
        issued_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    catalog = parse_and_verify_official_catalog(
        payload, now=datetime(2026, 10, 5, tzinfo=UTC), public_key_b64=public_key
    )

    assert catalog.issued_at == datetime(2026, 8, 1, tzinfo=UTC)


def test_catalog_rejects_duplicate_json_keys() -> None:
    with pytest.raises(UsageError) as caught:
        parse_and_verify_official_catalog(b'{"schema":"x","schema":"x"}', public_key_b64="a" * 44)

    assert caught.value.key == "error.dataset_catalog_invalid"
