from __future__ import annotations

import ctypes
import locale
import os
import plistlib
import sys
from dataclasses import dataclass
from pathlib import Path

from ccusage_viz.locales import CATALOGS


def _language_code(locale_name: str | None) -> str | None:
    if not locale_name:
        return None
    normalized = locale_name.split(":", 1)[0].split(".", 1)[0].replace("-", "_").casefold()
    return "zh" if normalized.startswith("zh") else "en"


def _system_ui_locale() -> str | None:
    if sys.platform.startswith("win"):
        try:
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):  # type: ignore[attr-defined]
                return buffer.value
        except (AttributeError, OSError):
            return None
    if sys.platform == "darwin":
        try:
            path = Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist"
            languages = plistlib.loads(path.read_bytes()).get("AppleLanguages", ())
            if languages and isinstance(languages[0], str):
                return languages[0]
        except (OSError, plistlib.InvalidFileException, AttributeError):
            return None
    return None


def detect_language(locale_name: str | None = None) -> str:
    if locale_name is not None:
        return _language_code(locale_name) or "en"
    candidates = (
        os.environ.get("CCUV_LANG"),
        _system_ui_locale(),
        os.environ.get("LANGUAGE"),
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
    )
    for candidate in candidates:
        if (language := _language_code(candidate)) is not None:
            return language
    try:
        return _language_code(locale.getlocale()[0]) or "en"
    except (ValueError, TypeError):
        return "en"


@dataclass(frozen=True, slots=True)
class Translator:
    language: str
    messages: dict[str, str]

    def dimension(self, value: str) -> str:
        if value in {"composition", "agent", "model", "project"}:
            return self.messages[f"label.{value}"]
        return value

    def text(self, key: str, **values: object) -> str:
        rendered_values = values
        dimension = values.get("dimension")
        if isinstance(dimension, str):
            rendered_values = {**values, "dimension": self.dimension(dimension)}
        return self.messages[key].format(**rendered_values)


def load_translator(language: str | None) -> Translator:
    selected = language or detect_language()
    return Translator(selected, dict(CATALOGS[selected]))
