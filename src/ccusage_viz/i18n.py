from __future__ import annotations

import locale
from dataclasses import dataclass

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


def load_translator(language: str | None) -> Translator:
    selected = language or detect_language()
    return Translator(selected, dict(CATALOGS[selected]))
