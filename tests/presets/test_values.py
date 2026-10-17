from __future__ import annotations

import pytest

from ccusage_viz.presets.values import DashboardPresetValidationError, validate_preset_name


@pytest.mark.parametrize("name", ("a", "weekly-review", "v2", "a0-9"))
def test_validate_preset_name_accepts_safe_identifiers(name: str) -> None:
    assert validate_preset_name(name) == name

@pytest.mark.parametrize(
    "name", ("", "1start", "Upper", "with_space", "with.dot", "with/slash", "中文")
)
def test_validate_preset_name_rejects_unsafe_identifiers(name: str) -> None:
    with pytest.raises(DashboardPresetValidationError):
        validate_preset_name(name)
