from __future__ import annotations

import sys
from dataclasses import replace

from ccusage_viz.i18n import Translator
from ccusage_viz.options import CommandOptions, refresh_date_range
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.terminal import InteractiveScreen, inspect_terminal


def run(options: CommandOptions, translator: Translator) -> int:
    # The complete pipeline is composed here so one-shot and Watch share semantics.
    if options.command == "monitor":
        from ccusage_viz.monitor import run_monitor

        return run_monitor(options, translator)

    from ccusage_viz.watch import load_snapshot, run_appearance_picker, run_once, run_watch

    if options.pick:
        current = replace(options, date_range=refresh_date_range(options.date_range))
        inspect_terminal(
            current.command,
            no_color=current.no_color,
            ascii=current.ascii,
        )
        runner = QueryRunner(current.ccusage_bin, timeout=current.timeout)
        snapshot = load_snapshot(current, runner)
        screen = InteractiveScreen(sys.stdout)
        try:
            picked = run_appearance_picker(current, translator, snapshot, screen)
            if picked is None:
                return 0
            if picked.options.watch is not None:
                return run_watch(
                    picked.options,
                    translator,
                    seed=picked.seed,
                    screen=screen,
                )
            return 0
        finally:
            screen.finish()
    if options.watch is not None:
        return run_watch(options, translator)
    output = run_once(options, translator)
    print(output)
    return 0


def interactive_streams() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
