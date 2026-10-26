from __future__ import annotations

import re

_COMMANDS = (
    "chart",
    "dashboard",
    "animate",
    "dataset",
    "text",
)

_TUI_COMMANDS = ("timeline", "calendar", "stack", "ranking", "monitor")

_DATASET_COMMANDS = ("list", "add-local")

_CUSTOM_COMMANDS = ("timeline", "calendar", "stack", "ranking")

_TEXT_PRESETS = ("time-state",)

_DURATION_PATTERN = re.compile(r"(?P<value>[1-9][0-9]*)(?P<unit>[mh])$")

_PANE_FORBIDDEN_OPTIONS = frozenset(
    {
        "--interval",
        "--no-watch",
        "--watch",
        "--ascii",
        "--demo",
        "--lang",
        "--ccusage-bin",
        "--query-timeout",
        "--timezone",
        "--pane",
        "--columns",
        "--spotlight",
        "--refresh-interval",
        "--sampling-interval",
        "--header-style",
        "--header-summary",
        "--header-interval",
        "--help",
        "--version",
        "-h",
    }
)


def _explicit_fields(argv: list[str]) -> frozenset[str]:
    fields = set()
    for argument in argv:
        if not argument.startswith("--"):
            continue
        name = argument[2:].split("=", 1)[0].replace("-", "_")
        aliases = {
            "theme": "color_scheme",
            "column_weight": "column_weights",
            "row_weight": "row_weights",
        }
        fields.add(aliases.get(name, name))
    return frozenset(fields)
