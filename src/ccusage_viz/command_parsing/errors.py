from __future__ import annotations

import argparse
import ast
import re
from difflib import get_close_matches
from typing import Any, Literal, Never

from ccusage_viz.errors import UsageError


def _invalid_choice_error(
    detail: str,
    rejected: str,
    choices: tuple[str, ...],
    *,
    kind: Literal["command", "preset"],
) -> UsageError:
    matches = get_close_matches(rejected, choices, n=2, cutoff=0.7)
    values: dict[str, object] = {
        "detail": detail,
        "commands" if kind == "command" else "choices": ", ".join(choices),
    }
    key = "error.invalid_subcommand" if kind == "command" else "error.invalid_preset"
    if len(matches) == 1:
        values["suggestion"] = matches[0]
        return UsageError(f"{key}_suggestion", **values)
    return UsageError(key, **values)


def _rejected_subcommand(
    message: str,
    metavar: str | None,
    choices: tuple[str, ...],
) -> str | None:
    if metavar is None or not choices:
        return None
    rendered_choices = (
        ", ".join(choices),
        ", ".join(repr(choice) for choice in choices),
    )
    choices_pattern = "|".join(re.escape(rendering) for rendering in rendered_choices)
    match = re.fullmatch(
        rf"argument {re.escape(metavar)}: invalid choice: (.+) "
        rf"\(choose from (?:{choices_pattern})\)",
        message,
    )
    if match is None:
        return None
    try:
        rejected = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError):
        return None
    return rejected if isinstance(rejected, str) else None


class LocalizedParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self._choice_choices: tuple[str, ...] = ()
        self._choice_metavar: str | None = None
        self._choice_kind: Literal["command", "preset"] = "command"

    def set_choice_metadata(
        self,
        choices: tuple[str, ...],
        *,
        metavar: str,
        kind: Literal["command", "preset"],
    ) -> None:
        self._choice_choices = choices
        self._choice_metavar = metavar
        self._choice_kind = kind

    def set_subcommand_choices(self, choices: tuple[str, ...]) -> None:
        action = next(
            (action for action in self._actions if isinstance(action, argparse._SubParsersAction)),
            None,
        )
        metavar = action.metavar if action is not None else None
        if isinstance(metavar, str):
            self.set_choice_metadata(choices, metavar=metavar, kind="command")

    def error(self, message: str) -> Never:
        rejected = _rejected_subcommand(
            message,
            self._choice_metavar,
            self._choice_choices,
        )
        if rejected is not None:
            raise _invalid_choice_error(
                message,
                rejected,
                self._choice_choices,
                kind=self._choice_kind,
            )
        if (
            self._choice_kind == "preset"
            and self._choice_metavar is not None
            and message == f"the following arguments are required: {self._choice_metavar}"
        ):
            raise UsageError(
                "error.invalid_preset",
                detail=message,
                choices=", ".join(self._choice_choices),
            )
        raise UsageError("error.arguments", detail=message)
