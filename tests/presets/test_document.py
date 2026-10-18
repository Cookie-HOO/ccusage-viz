from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from math import nan

import pytest

from ccusage_viz.presets.document import DashboardPresetDocument, preset_from_launch
from ccusage_viz.presets.values import DashboardPresetValidationError

from .helpers import NOW, _launch


def test_document_rejects_unknown_fields_nonfinite_values_and_duplicate_names() -> None:
    record = preset_from_launch("review", _launch(), now=NOW)
    wire = DashboardPresetDocument((record,)).to_wire()

    unknown = deepcopy(wire)
    unknown["presets"][0]["host"]["surprise"] = "no"
    with pytest.raises(DashboardPresetValidationError, match="unknown"):
        DashboardPresetDocument.parse(unknown)

    nonfinite = deepcopy(wire)
    nonfinite["presets"][0]["host"]["refresh_interval"] = nan
    with pytest.raises(DashboardPresetValidationError, match="finite"):
        DashboardPresetDocument.parse(nonfinite)

    duplicates = deepcopy(wire)
    duplicates["presets"].append(deepcopy(duplicates["presets"][0]))
    with pytest.raises(DashboardPresetValidationError, match="unique"):
        DashboardPresetDocument.parse(duplicates)


def test_preset_language_round_trips_and_legacy_record_defaults_to_unspecified() -> None:
    record = preset_from_launch("review", replace(_launch(), language="zh"), now=NOW)
    wire = DashboardPresetDocument((record,)).to_wire()

    assert wire["presets"][0]["language"] == "zh"
    assert DashboardPresetDocument.parse(wire).presets[0].language == "zh"

    legacy = deepcopy(wire)
    del legacy["presets"][0]["language"]
    assert DashboardPresetDocument.parse(legacy).presets[0].language is None


def test_document_save_overwrite_preserves_created_at_and_updates_timestamp() -> None:
    original = preset_from_launch("review", _launch(), now=NOW)
    replacement = preset_from_launch("review", _launch(), now=NOW + timedelta(days=1))
    saved = DashboardPresetDocument((original,)).with_saved(
        replacement, lambda: NOW + timedelta(days=2)
    )

    assert saved.presets[0].created_at == NOW
    assert saved.presets[0].updated_at == NOW + timedelta(days=2)
    assert saved.with_deleted("review").presets == ()
