"""Backend status and shared interactive/Agent setup."""

from __future__ import annotations

import sys

from ccusage_viz.backend_install import REPOSITORY, install_enhanced, install_official, validate
from ccusage_viz.backend_store import (
    BackendChoice,
    discover_choices,
    executable_path,
    load_choice,
    save_choice,
)
from ccusage_viz.errors import QueryError, UsageError
from ccusage_viz.i18n import Translator


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def tool_name(tr: Translator, backend: str) -> str:
    return tr.text(f"backend.name.{backend}")


def status(tr: Translator) -> None:
    saved = load_choice()
    discovered = discover_choices() if saved is None else ()
    choice = saved or (discovered[0] if discovered else None)
    if choice is None:
        print(tr.text("backend.absent"))
    else:
        print(
            tr.text(
                "backend.selection",
                backend=tool_name(tr, choice.backend),
                origin=tr.text("backend.saved" if saved else "backend.discovered"),
            )
        )
        print(
            tr.text("backend.executable", executable=executable_path(choice) or choice.executable)
        )
        try:
            version = validate(choice)
            print(tr.text("backend.version", version=version))
        except QueryError:
            print(tr.text("backend.unavailable"))
    print(tr.text("backend.guidance"))


def ask(tr: Translator, key: str, **values: object) -> str:
    try:
        return input(tr.text(key, **values)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise QueryError("error.backend_cancelled") from None


def select(tr: Translator, saved: BackendChoice | None) -> str:
    default = saved.backend if saved else "official"
    print(tr.text("backend.explanation"))
    default_description = (
        tr.text("backend.default_saved", backend=tool_name(tr, default))
        if saved
        else tr.text("backend.default_new")
    )
    while True:
        answer = ask(tr, "backend.sources", default=default_description)
        if answer in {"y", "yes", "是", "需要"}:
            return "enhanced"
        if answer in {"n", "no", "否", "不需要"}:
            return "official"
        if answer in {"", "?", "unsure", "不确定"}:
            return default
        print(tr.text("backend.invalid_answer"))


def setup(tr: Translator, backend: str | None = None, *, yes: bool = False) -> BackendChoice:
    if not interactive() and (backend is None or not yes):
        raise UsageError("error.backend_noninteractive")
    if yes and backend is None:
        raise UsageError("error.backend_noninteractive")
    saved = load_choice()
    if saved:
        print(
            tr.text(
                "backend.current", backend=tool_name(tr, saved.backend), executable=saved.executable
            )
        )
    selected = backend or select(tr, saved)
    source = (
        "https://github.com/ccusage/ccusage (npm install -g ccusage)"
        if selected == "official"
        else f"https://github.com/{REPOSITORY}/releases"
    )
    print(tr.text("backend.proposal", backend=tool_name(tr, selected), source=source))
    if selected == "enhanced":
        print(tr.text("backend.enhanced_notice"))
    if not yes and ask(tr, "backend.confirm") not in {"y", "yes", "是"}:
        raise QueryError("error.backend_cancelled")
    candidates = discover_choices()
    existing = (
        saved
        if saved and saved.backend == selected
        else next((choice for choice in candidates if choice.backend == selected), None)
    )
    valid = False
    if existing and executable_path(existing):
        try:
            validate(existing)
            valid = True
        except QueryError:
            print(tr.text("backend.unavailable"))
            if not yes and ask(tr, "backend.reinstall") not in {"y", "yes", "是"}:
                raise QueryError("error.backend_cancelled") from None
    choice = (
        existing
        if valid
        else (install_official() if selected == "official" else install_enhanced())
    )
    assert choice is not None
    validate(choice)
    save_choice(choice)
    print(tr.text("backend.ready", backend=tool_name(tr, choice.backend)))
    return choice
