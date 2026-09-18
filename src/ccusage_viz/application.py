from __future__ import annotations

import os
import sys

from ccusage_viz.bootstrap import build_provider_registry
from ccusage_viz.dependency import ensure_provider_dependencies
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import Translator
from ccusage_viz.options import DashboardLaunch, LaunchConfig


def _preflight_runtime(options: LaunchConfig) -> None:
    if not interactive_streams():
        raise UsageError("error.tty")
    if options.was_explicit("interval") and isinstance(options, DashboardLaunch):
        raise UsageError("error.arguments", detail="dashboard does not support --interval")
    if os.environ.get("TERM") == "dumb" and not options.host.ascii:
        raise UsageError("error.arguments", detail="TERM=dumb requires explicit --ascii")


def run(options: LaunchConfig, translator: Translator) -> int:
    _preflight_runtime(options)
    ensure_provider_dependencies(options, build_provider_registry(), translator)
    if isinstance(options, DashboardLaunch):
        from ccusage_viz.tui import run_tui

        return run_tui(options, translator)
    if options.chart.kind == "monitor":
        from ccusage_viz.monitor import run_monitor

        return run_monitor(options, translator)

    from ccusage_viz.watch import run_once, run_watch

    if not options.host.watch:
        return run_once(options, translator)
    return run_watch(options, translator)


def interactive_streams() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
