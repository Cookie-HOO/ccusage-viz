from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from ccusage_viz.datasets.models import parse_dataset_id


def ccuv_state_root(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Return ccuv's platform-native state root without creating it."""

    values = os.environ if environ is None else environ
    resolved_home = Path.home() if home is None else home
    current_platform = sys.platform if platform is None else platform
    if current_platform == "darwin":
        return resolved_home / "Library" / "Application Support" / "ccuv"
    if current_platform.startswith("win"):
        local_app_data = values.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "ccuv"
        return resolved_home / "AppData" / "Local" / "ccuv"
    state_home = values.get("XDG_STATE_HOME")
    return (Path(state_home) if state_home else resolved_home / ".local" / "state") / "ccuv"


def dataset_state_root(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Return the user-local dataset state root without creating it."""

    return ccuv_state_root(environ=environ, home=home, platform=platform) / "datasets"


def dashboard_preset_state_root(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Return the user-local Dashboard preset root without creating it."""

    return ccuv_state_root(environ=environ, home=home, platform=platform) / "dashboard-presets"


def dataset_directory(root: Path, dataset_id: str) -> Path:
    return root / parse_dataset_id(dataset_id)
