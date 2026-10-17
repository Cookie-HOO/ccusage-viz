from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ccusage_viz.command_parsing.common import _COMMANDS, _TUI_COMMANDS
from ccusage_viz.command_parsing.errors import _invalid_choice_error
from ccusage_viz.errors import UsageError


class ShortCircuitKind(StrEnum):
    HELP = "help"
    VERSION = "version"


@dataclass(frozen=True, slots=True)
class ShortCircuitRoute:
    kind: ShortCircuitKind
    command: str | None = None
    language: str | None = None


def probe_short_circuit(argv: list[str]) -> ShortCircuitRoute | None:
    """Identify side-effect-free routes before configuration or runtime setup."""
    if argv == ["--version"]:
        return ShortCircuitRoute(ShortCircuitKind.VERSION)
    help_flags = {"-h", "--help"}
    if not any(argument in help_flags for argument in argv):
        return None
    command = next((argument for argument in argv if argument in _COMMANDS), None)
    if command == "chart":
        chart_kind = next((argument for argument in argv if argument in _TUI_COMMANDS), None)
        if chart_kind is not None:
            command = f"chart {chart_kind}"
    language = None
    for index, argument in enumerate(argv[:-1]):
        if argument == "--lang" and argv[index + 1] in {"en", "zh"}:
            language = argv[index + 1]
            break
    return ShortCircuitRoute(ShortCircuitKind.HELP, command, language)


def _inject_default_command(argv: list[str]) -> list[str]:
    if not argv:
        return ["chart", "timeline"]
    if argv[0] in _COMMANDS or argv[0] in {"-h", "--help", "--version"}:
        return argv
    leading: list[str] = []
    remaining = list(argv)
    while remaining and remaining[0] == "--lang":
        if len(remaining) < 2:
            return ["chart", "timeline", *argv]
        leading.extend(remaining[:2])
        remaining = remaining[2:]
    if remaining and remaining[0] in _COMMANDS:
        return [remaining[0], *leading, *remaining[1:]]
    if remaining and remaining[0] in _TUI_COMMANDS:
        return [*leading, *remaining]
    return ["chart", "timeline", *argv]


def _top_level_typo(raw_args: list[str], error: UsageError) -> UsageError:
    if error.key != "error.arguments":
        return error
    remaining = list(raw_args)
    while len(remaining) >= 2 and remaining[0] == "--lang":
        remaining = remaining[2:]
    if not remaining:
        return error
    rejected = remaining[0]
    if rejected.startswith("-") or rejected in _COMMANDS or rejected in _TUI_COMMANDS:
        return error
    detail = error.values.get("detail")
    if not isinstance(detail, str) or f"unrecognized arguments: {rejected}" not in detail:
        return error
    return _invalid_choice_error(detail, rejected, _COMMANDS, kind="command")
