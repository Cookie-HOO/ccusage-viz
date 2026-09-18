from __future__ import annotations

import os
import sys

from ccusage_viz.dependency import ensure_ccusage
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions


def _preflight_runtime(options: CommandOptions) -> None:
    if options.command == "dashboard":
        from ccusage_viz.tui import validate_panel_fragments

        validate_panel_fragments(options)
    if not interactive_streams():
        raise UsageError("error.tty")
    if options.was_explicit("interval") and options.command == "dashboard":
        raise UsageError("error.arguments", detail="dashboard does not support --interval")
    if os.environ.get("TERM") == "dumb" and not options.ascii:
        raise UsageError("error.arguments", detail="TERM=dumb requires explicit --ascii")


def run(options: CommandOptions, translator: Translator) -> int:
    _preflight_runtime(options)
    ensure_ccusage(options, translator)
    if options.command == "dashboard":
        from ccusage_viz.tui import run_tui

        return run_tui(options, translator)
    if options.command == "monitor":
        from ccusage_viz.monitor import run_monitor

        return run_monitor(options, translator)

    from ccusage_viz.watch import run_once, run_watch

    if options.no_watch:
        return run_once(options, translator)
    return run_watch(options, translator)


def interactive_streams() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
