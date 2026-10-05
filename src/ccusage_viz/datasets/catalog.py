from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ccusage_viz.datasets.github import MAX_DOWNLOAD_BYTES
from ccusage_viz.datasets.models import CatalogEntry, parse_dataset_id
from ccusage_viz.errors import UsageError

CATALOG_REPOSITORY = "Cookie-HOO/ccuv-dataset-catalog"
CATALOG_URL = (
    "https://raw.githubusercontent.com/Cookie-HOO/ccuv-dataset-catalog/main/catalog/catalog.json"
)
CATALOG_KEY_ID = "ccuv-official-2026-01"
# Dedicated production signing key for the official catalog. The private seed is
# held outside this repository in the maintainer Keychain and release environment.
CATALOG_PUBLIC_KEY_B64 = "lfF6lTTEIRoh7Cw+2wHr/k2Jkh5dYcREQuKcjSYpPBo="
MAX_CATALOG_BYTES = 1024 * 1024
MAX_CATALOG_LIFETIME = timedelta(days=35)
MAX_FUTURE_ISSUED_AT = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class OfficialCatalog:
    issued_at: datetime
    expires_at: datetime
    entries: tuple[CatalogEntry, ...]

    def entry(self, dataset_id: str) -> CatalogEntry:
        identifier = parse_dataset_id(dataset_id)
        for entry in self.entries:
            if entry.id == identifier:
                return entry
        raise UsageError("error.dataset_catalog_not_found", dataset_id=identifier)

    def artifact_for(self, dataset_id: str, os: str, arch: str):
        entry = self.entry(dataset_id)
        matches = [
            artifact for artifact in entry.artifacts if artifact.os == os and artifact.arch == arch
        ]
        if len(matches) != 1:
            raise UsageError("error.dataset_platform_incompatible")
        return matches[0]


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise UsageError("error.dataset_catalog_invalid") from exc


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp is not UTC")
    return parsed.astimezone(UTC)


def _parse_signed(value: object, *, now: datetime) -> OfficialCatalog:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "catalog_version",
        "issued_at",
        "expires_at",
        "entries",
    }:
        raise ValueError("catalog signed body is invalid")
    if (
        value.get("schema") != "ccuv.official-dataset-catalog/v1"
        or value.get("catalog_version") != 1
    ):
        raise ValueError("catalog schema is invalid")
    issued_at = _parse_timestamp(value.get("issued_at"))
    expires_at = _parse_timestamp(value.get("expires_at"))
    if (
        issued_at > now + MAX_FUTURE_ISSUED_AT
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_CATALOG_LIFETIME
        or expires_at <= now
    ):
        raise UsageError("error.dataset_catalog_expired")
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("catalog entries are invalid")
    entries = tuple(CatalogEntry.parse(item) for item in raw_entries)
    if len({entry.id for entry in entries}) != len(entries):
        raise ValueError("catalog entry IDs are not unique")
    platforms = [
        (entry.id, artifact.os, artifact.arch) for entry in entries for artifact in entry.artifacts
    ]
    if len(set(platforms)) != len(platforms):
        raise ValueError("catalog artifacts overlap by platform")
    return OfficialCatalog(issued_at, expires_at, entries)


def parse_and_verify_official_catalog(
    payload: bytes,
    *,
    now: datetime | None = None,
    public_key_b64: str = CATALOG_PUBLIC_KEY_B64,
) -> OfficialCatalog:
    if len(payload) > MAX_CATALOG_BYTES:
        raise UsageError("error.dataset_catalog_invalid")
    envelope = _load_json(payload)
    if not isinstance(envelope, Mapping) or set(envelope) != {
        "schema",
        "key_id",
        "signed",
        "signature",
    }:
        raise UsageError("error.dataset_catalog_invalid")
    if (
        envelope.get("schema") != "ccuv.official-dataset-catalog-envelope/v1"
        or envelope.get("key_id") != CATALOG_KEY_ID
    ):
        raise UsageError("error.dataset_catalog_signature")
    signature = envelope.get("signature")
    if not isinstance(signature, Mapping) or set(signature) != {"algorithm", "encoding", "value"}:
        raise UsageError("error.dataset_catalog_invalid")
    if signature.get("algorithm") != "Ed25519" or signature.get("encoding") != "base64":
        raise UsageError("error.dataset_catalog_signature")
    signature_value = signature.get("value")
    signed = envelope.get("signed")
    if not isinstance(signature_value, str) or not isinstance(signed, Mapping):
        raise UsageError("error.dataset_catalog_invalid")
    try:
        signature_bytes = base64.b64decode(signature_value, validate=True)
        public_key = base64.b64decode(public_key_b64, validate=True)
        if len(signature_bytes) != 64 or len(public_key) != 32:
            raise ValueError("invalid key material")
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature_bytes, rfc8785.dumps(signed)
        )
    except (ValueError, InvalidSignature, rfc8785.CanonicalizationError) as exc:
        raise UsageError("error.dataset_catalog_signature") from exc
    try:
        return _parse_signed(signed, now=(datetime.now(UTC) if now is None else now))
    except UsageError:
        raise
    except (TypeError, ValueError) as exc:
        raise UsageError("error.dataset_catalog_invalid") from exc


def fetch_official_catalog(url: str = CATALOG_URL) -> OfficialCatalog:
    if url != CATALOG_URL or not url.startswith("https://"):
        raise UsageError("error.dataset_catalog_invalid")
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ccuv-datasets"},
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS catalog URL.
            payload = response.read(min(MAX_CATALOG_BYTES, MAX_DOWNLOAD_BYTES) + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UsageError("error.dataset_catalog_unavailable") from exc
    if len(payload) > MAX_CATALOG_BYTES:
        raise UsageError("error.dataset_catalog_invalid")
    return parse_and_verify_official_catalog(payload)
