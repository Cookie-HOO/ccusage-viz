from __future__ import annotations

import shutil
import subprocess
import sys

from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions

_DEFAULT_CCUSAGE = "ccusage"
_INSTALL_COMMAND = "npm install -g ccusage"


def ensure_ccusage(options: CommandOptions, translator: Translator) -> None:
    if (
        options.demo is not None
        or options.was_explicit("ccusage_bin")
        or options.ccusage_bin != _DEFAULT_CCUSAGE
    ):
        return
    if shutil.which(_DEFAULT_CCUSAGE) is not None:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise QueryError("error.ccusage_missing", binary=_DEFAULT_CCUSAGE)

    print(translator.text("prompt.ccusage_install", command=_INSTALL_COMMAND))
    try:
        response = input(translator.text("prompt.ccusage_install_confirm"))
    except (EOFError, KeyboardInterrupt):
        raise QueryError("error.ccusage_missing", binary=_DEFAULT_CCUSAGE) from None
    if response:
        raise QueryError("error.ccusage_missing", binary=_DEFAULT_CCUSAGE)

    npm = shutil.which("npm")
    if npm is None:
        raise QueryError("error.npm_missing")
    try:
        completed = subprocess.run([npm, "install", "-g", "ccusage"], shell=False, check=False)
    except OSError as exc:
        raise QueryError("error.ccusage_install_start", detail=str(exc)) from exc
    if completed.returncode != 0:
        raise QueryError("error.ccusage_install_failed", code=completed.returncode)
    if shutil.which(_DEFAULT_CCUSAGE) is None:
        raise QueryError("error.ccusage_install_path")
