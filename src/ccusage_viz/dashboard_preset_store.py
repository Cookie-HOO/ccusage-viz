"""Private, atomic persistence for the Dashboard user-preset collection.

The wire schema and its validation live in :mod:`ccusage_viz.presets.document`.
This module intentionally has no knowledge of panes, launch options, or built-in
presets: it only protects the user-owned collection document on disk.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccusage_viz.presets.document import DashboardPresetDocument, DashboardPresetRecord


class DashboardPresetStoreError(RuntimeError):
    """Base failure for Dashboard preset collection persistence."""


class DashboardPresetStoreCorruptError(DashboardPresetStoreError):
    """The existing user collection cannot safely be read or changed."""


class DashboardPresetStoreLegacyError(DashboardPresetStoreError):
    """The existing collection is a recognized, unsupported v1 document."""


class DashboardPresetStoreNotFoundError(DashboardPresetStoreError):
    """A requested user preset does not exist in a valid collection."""


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DashboardPresetStore:
    """Read and atomically replace one validated Dashboard preset collection.

    The store never attempts recovery from malformed storage.  Consequently a
    failed load also prevents mutation: replacing an unreadable collection could
    silently destroy user presets or expose secrets accidentally retained by an
    older version.
    """

    filename = "presets.json"

    def __init__(self, root: Path, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self.root = root
        self.clock = clock

    @property
    def path(self) -> Path:
        return self.root / self.filename

    def load(self) -> DashboardPresetDocument:
        """Return the valid collection, or an empty collection when absent."""

        # Import lazily so model consumers can import their DTOs without a store
        # dependency and so this module stays narrowly persistence-focused.
        from ccusage_viz.presets.document import DashboardPresetDocument

        try:
            payload = self.path.read_bytes()
        except FileNotFoundError:
            return DashboardPresetDocument.empty()
        except OSError as exc:
            raise DashboardPresetStoreCorruptError("unable to read preset collection") from exc
        try:
            text = payload.decode("utf-8")
            wire = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(wire, Mapping):
                raise ValueError("preset collection must be a JSON object")
            if wire.get("schema") == "ccuv.dashboard-presets/v1":
                raise DashboardPresetStoreLegacyError("unsupported v1 preset collection")
            return DashboardPresetDocument.parse(wire)
        except DashboardPresetStoreLegacyError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError, ValueError) as exc:
            raise DashboardPresetStoreCorruptError("invalid preset collection") from exc

    def list(self) -> tuple[DashboardPresetRecord, ...]:
        """List user records in the document's validated stable order."""

        return self.load().presets

    def get(self, name: str) -> DashboardPresetRecord:
        """Return one user preset without treating a missing record as corruption."""

        for record in self.load().presets:
            if record.name == name:
                return record
        raise DashboardPresetStoreNotFoundError(name)

    def save(self, record: DashboardPresetRecord) -> DashboardPresetRecord:
        """Create or update ``record`` and atomically persist the collection.

        ``DashboardPresetDocument.with_saved`` owns timestamp semantics.  It
        receives this store's injectable clock so tests and callers can make the
        updated/created timestamps deterministic.
        """

        document = self.load()
        updated = document.with_saved(record, self.clock)
        self._write(updated)
        return next(item for item in updated.presets if item.name == record.name)

    def save_replacing_legacy(
        self, record: DashboardPresetRecord
    ) -> tuple[DashboardPresetRecord, Path | None]:
        """Save a v2 record, archiving only a recognized v1 collection first."""
        try:
            return self.save(record), None
        except DashboardPresetStoreLegacyError:
            backup = self.root / f"presets.v1.{uuid.uuid4().hex}.backup.json"
            try:
                os.replace(self.path, backup)
                os.chmod(backup, 0o600)
                self._fsync_directory()
            except OSError as exc:
                raise DashboardPresetStoreError("unable to archive v1 preset collection") from exc
            return self.save(record), backup

    def delete(self, name: str) -> None:
        """Remove one user record, refusing writes when the collection is corrupt."""

        document = self.load()
        if not any(record.name == name for record in document.presets):
            raise DashboardPresetStoreNotFoundError(name)
        self._write(document.with_deleted(name))

    def _write(self, document: DashboardPresetDocument) -> None:
        """Commit a complete collection through a same-directory private file."""

        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
        except OSError as exc:
            raise DashboardPresetStoreError("unable to create private preset directory") from exc

        temporary = self.root / f".{self.filename}.{uuid.uuid4().hex}.tmp"
        encoded = (
            json.dumps(
                document.to_wire(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                # fdopen owns descriptor after success, but keep the cleanup
                # robust if construction itself ever changes.
                raise
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            self._fsync_directory()
        except OSError as exc:
            raise DashboardPresetStoreError("unable to write preset collection") from exc
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _fsync_directory(self) -> None:
        """Persist the rename where the platform permits directory fsync."""

        try:
            descriptor = os.open(self.root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # Windows and some filesystems do not support directory fsync.  The
            # file itself was already flushed; atomic replacement still holds.
            pass
        finally:
            os.close(descriptor)
