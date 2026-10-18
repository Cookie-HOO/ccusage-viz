from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from ccusage_viz.options import DashboardHostConfig, DashboardLaunch, PaneConfig, ProcessConfig
from ccusage_viz.presets.panes import _pane_wire, _parse_pane
from ccusage_viz.presets.values import (
    DashboardPresetValidationError,
    _exact,
    _expect_mapping,
    _host_parse,
    _host_wire,
    _process_parse,
    _process_wire,
    _string,
    _timestamp,
    _timestamp_wire,
    validate_preset_name,
)

PRESET_SCHEMA = "ccuv.dashboard-presets/v1"


@dataclass(frozen=True, slots=True)
class DashboardPresetRecord:
    """One validated, version-independent user preset declaration."""

    name: str
    created_at: datetime
    updated_at: datetime
    process: ProcessConfig
    host: DashboardHostConfig
    panes: tuple[PaneConfig, ...]
    language: str | None = None

    def __post_init__(self) -> None:
        validate_preset_name(self.name)
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise DashboardPresetValidationError("preset timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise DashboardPresetValidationError("preset updated_at cannot precede created_at")
        if not self.panes:
            raise DashboardPresetValidationError("a Dashboard preset requires at least one pane")
        if self.language not in {None, "en", "zh"}:
            raise DashboardPresetValidationError("preset language must be en or zh")
        _host_parse(_host_wire(self.host), len(self.panes))

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "created_at": _timestamp_wire(self.created_at),
            "updated_at": _timestamp_wire(self.updated_at),
            "language": self.language,
            "process": _process_wire(self.process),
            "host": _host_wire(self.host),
            "panes": [_pane_wire(pane) for pane in self.panes],
        }

    @classmethod
    def parse(cls, value: object) -> DashboardPresetRecord:
        wire = _expect_mapping(value, "preset")
        fields = frozenset(("name", "created_at", "updated_at", "process", "host", "panes"))
        if frozenset(wire) not in {fields, fields | {"language"}}:
            _exact(value, fields | {"language"}, "preset")
        name = validate_preset_name(_string(wire["name"], "preset.name"))
        created_at, updated_at = (
            _timestamp(wire["created_at"], "preset.created_at"),
            _timestamp(wire["updated_at"], "preset.updated_at"),
        )
        if updated_at < created_at:
            raise DashboardPresetValidationError("preset updated_at cannot precede created_at")
        if not isinstance(wire["panes"], list) or not wire["panes"]:
            raise DashboardPresetValidationError("preset.panes must be a non-empty array")
        panes = tuple(_parse_pane(pane) for pane in wire["panes"])
        return cls(
            name,
            created_at,
            updated_at,
            _process_parse(wire["process"]),
            _host_parse(wire["host"], len(panes)),
            panes,
            None if wire.get("language") is None else _string(wire["language"], "preset.language"),
        )

    def materialize(self) -> DashboardLaunch:
        return DashboardLaunch(self.process, self.host, self.panes, language=self.language)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DashboardPresetDocument:
    """The complete strict, versioned collection stored in one private file."""

    presets: tuple[DashboardPresetRecord, ...]
    schema: str = PRESET_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PRESET_SCHEMA:
            raise DashboardPresetValidationError("unsupported dashboard preset schema")
        names = [record.name for record in self.presets]
        if len(names) != len(set(names)):
            raise DashboardPresetValidationError("preset names must be unique")

    @classmethod
    def empty(cls) -> DashboardPresetDocument:
        return cls(())

    def to_wire(self) -> dict[str, object]:
        return {"schema": self.schema, "presets": [record.to_wire() for record in self.presets]}

    @classmethod
    def parse(cls, value: object) -> DashboardPresetDocument:
        wire = _exact(value, frozenset(("schema", "presets")), "preset collection")
        if wire["schema"] != PRESET_SCHEMA:
            raise DashboardPresetValidationError("unsupported dashboard preset schema")
        if not isinstance(wire["presets"], list):
            raise DashboardPresetValidationError("preset collection presets must be an array")
        records = tuple(DashboardPresetRecord.parse(item) for item in wire["presets"])
        return cls(records)

    def with_saved(
        self, record: DashboardPresetRecord, clock: Callable[[], datetime]
    ) -> DashboardPresetDocument:
        now = clock().astimezone(UTC)
        existing = next((item for item in self.presets if item.name == record.name), None)
        saved = replace(record, created_at=existing.created_at if existing else now, updated_at=now)
        return DashboardPresetDocument(
            tuple(saved if item.name == saved.name else item for item in self.presets)
            if existing
            else (*self.presets, saved)
        )

    def with_deleted(self, name: str) -> DashboardPresetDocument:
        return DashboardPresetDocument(
            tuple(record for record in self.presets if record.name != name)
        )


def preset_from_launch(
    name: str, launch: DashboardLaunch, *, now: datetime | None = None
) -> DashboardPresetRecord:
    """Create a complete user-local trusted Dashboard preset record."""
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    return DashboardPresetRecord(
        validate_preset_name(name),
        timestamp,
        timestamp,
        launch.process,
        launch.host,
        tuple(launch.panes),
        launch.language,
    )
