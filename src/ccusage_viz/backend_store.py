"""Small, private backend selection store; no query data or shell configuration."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ccusage_viz.errors import QueryError

SCHEMA = "ccuv.backend/v1"


@dataclass(frozen=True)
class BackendChoice:
    backend: str
    executable: str


def ccuv_state_root() -> Path:
    # Dataset package exports its service eagerly; import only after module initialization.
    from ccusage_viz.datasets.paths import ccuv_state_root as state_root

    return state_root()


def config_path() -> Path:
    return ccuv_state_root() / "backend.json"


def load_choice() -> BackendChoice | None:
    path = config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise QueryError("error.backend", detail=f"{path}: {exc}") from exc
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"schema", "backend", "executable"}:
            raise ValueError("invalid configuration fields")
        if data["schema"] != SCHEMA or data["backend"] not in {"official", "enhanced"}:
            raise ValueError("unknown schema or distribution")
        executable = data["executable"]
        if not isinstance(executable, str) or not executable or "\x00" in executable:
            raise ValueError("invalid executable")
        if data["backend"] == "official" and executable != "ccusage":
            raise ValueError("official backend must use ccusage on PATH")
        if data["backend"] == "enhanced" and not Path(executable).is_absolute():
            raise ValueError("enhanced executable must be an absolute path")
        return BackendChoice(data["backend"], executable)
    except (ValueError, TypeError) as exc:
        raise QueryError(
            "error.backend", detail=f"{path}: {exc}; back up and repair/remove this file first"
        ) from exc


def save_choice(choice: BackendChoice) -> None:
    # Never overwrite damaged or future-version configuration.
    load_choice()
    path = config_path()
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".backend-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                {"schema": SCHEMA, "backend": choice.backend, "executable": choice.executable},
                stream,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise QueryError("error.backend", detail=f"{path}: {exc}") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def discover_choices() -> tuple[BackendChoice, ...]:
    choices = []
    if shutil.which("ccusage"):
        choices.append(BackendChoice("official", "ccusage"))
    if enhanced := shutil.which("my-ccusage"):
        choices.append(BackendChoice("enhanced", str(Path(enhanced).absolute())))
    return tuple(choices)


def executable_path(choice: BackendChoice) -> str | None:
    return shutil.which(choice.executable)


def resolve_executable(executable: str = "ccusage", *, explicit: bool = False) -> str:
    """Resolve at acquisition time, without pinning paths in copied commands/presets."""
    if explicit or executable != "ccusage":
        return executable
    if choice := load_choice():
        if executable_path(choice) is None:
            raise QueryError("error.backend_unavailable", binary=choice.executable)
        return choice.executable
    choices = discover_choices()
    return choices[0].executable if choices else executable
