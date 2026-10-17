from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TypeAlias

from ccusage_viz.core.custom_ranking_time import TimestampRange, resolve_custom_ranking_range
from ccusage_viz.options import (
    CustomChartPaneConfig,
    CustomCommandSource,
    DashboardLaunch,
    EmptyPaneConfig,
    PaneConfig,
)
from ccusage_viz.presets.document import DashboardPresetRecord
from ccusage_viz.presets.values import DashboardPresetValidationError

DatasetSourceResolver: TypeAlias = Callable[[str], CustomCommandSource]


def materialize_preset(
    record: DashboardPresetRecord,
    source_resolver: DatasetSourceResolver,
    *,
    now: datetime | None = None,
) -> DashboardLaunch:
    """Resolve durable Dataset IDs and return a fresh ordinary Dashboard launch."""

    panes: list[PaneConfig] = []
    for pane in record.panes:
        if isinstance(pane, CustomChartPaneConfig):
            chart = pane.chart
            if (
                isinstance(chart.date_range, TimestampRange)
                and chart.date_range.relative_until
                and chart.date_range.period is not None
            ):
                timezone = record.host.timezone or "UTC"
                anchor = now or datetime.now(UTC)
                chart = replace(
                    chart,
                    date_range=resolve_custom_ranking_range(
                        chart.date_range.period, now=anchor, timezone=timezone
                    ),
                )
            if chart.source.source_kind == "command":
                panes.append(replace(pane, chart=chart))
                continue
            source = source_resolver(chart.source.dataset_id)
            if source.dataset_id != chart.source.dataset_id or source.source_kind != "installed":
                raise DashboardPresetValidationError(
                    "custom Dataset resolver returned an unsafe source"
                )
            panes.append(replace(pane, chart=replace(chart, source=source)))
        else:
            panes.append(pane)
    return DashboardLaunch(record.process, record.host, tuple(panes))  # type: ignore[arg-type]


def empty_preset_launch(launch: DashboardLaunch) -> DashboardLaunch:
    """Keep a resolved preset's topology/settings while replacing all pane content."""

    return replace(launch, panes=tuple(EmptyPaneConfig() for _ in launch.panes))
