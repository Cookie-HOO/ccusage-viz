from __future__ import annotations

import sys

from ccusage_viz.dependency import ensure_ccusage
from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions


def run(options: CommandOptions, translator: Translator) -> int:
    # The complete pipeline is composed here so one-shot and Watch share semantics.
    ensure_ccusage(options, translator)
    if options.command == "dashboard":
        from ccusage_viz.tui import run_tui

        return run_tui(options, translator)
    if options.command == "monitor":
        from ccusage_viz.monitor import run_monitor

        return run_monitor(options, translator)

    from ccusage_viz.watch import run_once, run_watch

    if options.watch is not None:
        return run_watch(options, translator)
    output = run_once(options, translator)
    print(output)
    return 0


def interactive_streams() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
