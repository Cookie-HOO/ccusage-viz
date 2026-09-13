from __future__ import annotations

import json
import locale
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ccusage_viz.errors import UsageError
from ccusage_viz.locales import CATALOGS


def detect_language(locale_name: str | None = None) -> str:
    if locale_name is None:
        try:
            locale_name = locale.getlocale()[0]
        except (ValueError, TypeError):
            return "en"
    if not locale_name:
        return "en"
    normalized = locale_name.replace("-", "_").casefold()
    if not normalized.startswith("zh"):
        return "en"
    if any(marker in normalized for marker in ("_tw", "_hk", "_mo", "hant")):
        return "en"
    if any(marker in normalized for marker in ("_cn", "_sg", "hans")) or normalized == "zh":
        return "zh"
    return "en"


def _placeholder_signature(value: str) -> tuple[tuple[str, str | None, str | None], ...]:
    signature = []
    for _, field_name, format_spec, conversion in string.Formatter().parse(value):
        if field_name is not None:
            signature.append((field_name, conversion, format_spec))
    return tuple(sorted(signature))


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UsageError("error.lang_file_duplicate", key=key)
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class Translator:
    language: str
    messages: dict[str, str]

    def text(self, key: str, **values: object) -> str:
        rendered_values = values
        dimension = values.get("dimension")
        if dimension in {"agent", "model", "project"}:
            rendered_values = {**values, "dimension": self.messages[f"label.{dimension}"]}
        return self.messages[key].format(**rendered_values)


def load_translator(language: str | None, lang_file: str | None = None) -> Translator:
    selected = language or detect_language()
    base = dict(CATALOGS[selected])
    if lang_file is None:
        return Translator(selected, base)

    path = Path(lang_file)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UsageError("error.lang_file_read", path=str(path), detail=str(exc)) from exc
    try:
        overrides = json.loads(raw, object_pairs_hook=_reject_duplicates)
    except UsageError:
        raise
    except json.JSONDecodeError as exc:
        raise UsageError("error.lang_file_json", path=str(path), detail=exc.msg) from exc
    if not isinstance(overrides, dict):
        raise UsageError("error.lang_file_object")

    for key, value in overrides.items():
        if key not in base:
            raise UsageError("error.lang_file_unknown", key=key)
        if not isinstance(value, str) or not value.strip():
            raise UsageError("error.lang_file_value", key=key)
        required = _placeholder_signature(base[key])
        if _placeholder_signature(value) != required:
            placeholders = ", ".join(item[0] for item in required) or "(none)"
            raise UsageError("error.lang_file_placeholders", key=key, placeholders=placeholders)
    base.update(overrides)
    return Translator(selected, base)
