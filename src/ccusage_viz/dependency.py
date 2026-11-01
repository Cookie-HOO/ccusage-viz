from __future__ import annotations

import sys

from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import Translator
from ccusage_viz.options import (
    ChartPaneConfig,
    CustomChartConfig,
    DashboardLaunch,
    LaunchConfig,
    StandaloneLaunch,
)
from ccusage_viz.query.registry import ProviderRegistry

_DEFAULT_CCUSAGE = "ccusage"


def ensure_provider_dependencies(
    options: LaunchConfig,
    registry: ProviderRegistry,
    translator: Translator,
) -> None:
    if isinstance(options, DashboardLaunch):
        built_in_panes = tuple(
            pane
            for pane in options.panes
            if isinstance(pane, ChartPaneConfig) and not isinstance(pane.chart, CustomChartConfig)
        )
        if not built_in_panes:
            return
    elif isinstance(options, StandaloneLaunch) and isinstance(options.chart, CustomChartConfig):
        return
    provider_id = "demo" if options.host.demo_size else options.host.provider
    dependencies = registry.get(provider_id).provider.capabilities.dependencies
    for dependency in dependencies:
        if dependency == "ccusage":
            ensure_ccusage(options, translator)
        else:
            raise ValueError(f"unsupported provider dependency: {dependency}")


def ensure_ccusage(options: LaunchConfig, translator: Translator) -> None:
    if (
        options.host.demo_size is not None
        or options.was_explicit("ccusage_bin")
        or options.process.ccusage_bin != _DEFAULT_CCUSAGE
    ):
        return
    from ccusage_viz.backend import setup
    from ccusage_viz.backend_store import discover_choices, executable_path, load_choice

    if saved := load_choice():
        if executable_path(saved) is None:
            raise QueryError("error.backend_unavailable", binary=saved.executable)
        return
    choices = discover_choices()
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if len(choices) == 1 or (choices and not is_interactive):
        return
    if not is_interactive:
        raise QueryError("error.ccusage_missing", binary=_DEFAULT_CCUSAGE)
    setup(translator)
