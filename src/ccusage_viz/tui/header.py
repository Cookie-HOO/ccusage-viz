from __future__ import annotations

import shlex
import time
from dataclasses import replace
from datetime import datetime, timedelta

from ccusage_viz import __version__
from ccusage_viz.core.time import DateRange, local_today
from ccusage_viz.coverage import DateInterval
from ccusage_viz.custom_component import custom_date_summary_supported
from ccusage_viz.domain import UsageRecord
from ccusage_viz.formatting import center_text, clip_width, display_width, pad_width, truncate_width
from ccusage_viz.historical_component import UsageSnapshot
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import FixedIntervalScheduler, LifecycleOperation
from ccusage_viz.options import (
    HEADER_SUMMARIES,
    ChartPaneConfig,
    ChartPresentation,
    CustomCommandSource,
    DashboardLaunch,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
    custom_command_sources_equivalent,
)
from ccusage_viz.processing import build_period_summary, required_summary_coverage
from ccusage_viz.query.runtime import QueryRuntime
from ccusage_viz.render.base import RenderContext, styled_text
from ccusage_viz.render.palette import get_color_scheme
from ccusage_viz.render.summary import render_custom_metrics, render_summary
from ccusage_viz.terminal import Terminal
from ccusage_viz.terminal_ui import dimmed
from ccusage_viz.tui.controls import _cycle
from ccusage_viz.tui.models import (
    CustomDashboardSource,
    CustomDashboardSummary,
    DashboardHeader,
    TuiCustomPane,
    TuiPane,
)


def _header_options(
    base: DashboardLaunch, interval: DateInterval | None = None
) -> StandaloneLaunch:
    """Build the dashboard's deliberately unfiltered, all-agent daily query."""
    today = local_today()
    interval = interval or DateInterval(today - timedelta(days=7), today)
    chart = TimelineConfig(
        "timeline",
        DateRange(interval.since, interval.until),
        presentation=ChartPresentation(theme=base.host.theme, style="linear", legend="hidden"),
        other="hide",
    )
    return StandaloneLaunch(
        base.process,
        StandaloneHostConfig(
            provider=base.host.provider,
            ascii=base.host.ascii,
            demo_size=base.host.demo_size,
            interval=base.host.header_interval,
        ),
        chart,
    )


def _new_header(options: DashboardLaunch, runtime: QueryRuntime) -> DashboardHeader:
    return DashboardHeader(
        _header_options(options),
        runtime,
        FixedIntervalScheduler(options.host.header_interval, now=time.monotonic()),
        LifecycleOperation("dashboard:header"),
        summary_period=options.host.header_summary,
        token_enabled=any(isinstance(pane, ChartPaneConfig) for pane in options.panes),
    )


def _custom_source_conflict(
    panes: list[TuiPane], source: CustomCommandSource, *, replacing_index: int | None = None
) -> tuple[CustomCommandSource, CustomCommandSource] | None:
    """Return the existing and proposed sources when their Dataset commands conflict."""

    for index, pane in enumerate(panes):
        if index == replacing_index or not isinstance(pane, TuiCustomPane):
            continue
        existing = pane.component.candidate.source
        if existing.dataset_id == source.dataset_id and not custom_command_sources_equivalent(
            existing, source
        ):
            return existing, source
    return None


def _dashboard_custom_source_conflict(
    panes: list[TuiPane],
) -> tuple[CustomCommandSource, CustomCommandSource] | None:
    """Return the first ambiguous pair of Dataset command sources in the Dashboard."""

    sources: dict[str, CustomCommandSource] = {}
    for pane in panes:
        if not isinstance(pane, TuiCustomPane):
            continue
        source = pane.component.candidate.source
        previous = sources.setdefault(source.dataset_id, source)
        if not custom_command_sources_equivalent(previous, source):
            return previous, source
    return None


def _custom_source_conflict_message(
    conflict: tuple[CustomCommandSource, CustomCommandSource],
    translator: Translator,
    *,
    preset: bool = False,
) -> str:
    """Describe both sides of a Dataset source conflict with shell-safe commands."""

    existing, proposed = conflict
    heading = translator.text(
        "status.tui_preset_source_conflict" if preset else "status.custom_dataset_source_conflict",
        dataset_id=existing.dataset_id,
    )

    def describe(label: str, source: CustomCommandSource) -> str:
        kind = translator.text(f"label.custom_source_{source.source_kind}")
        return translator.text(
            "status.custom_dataset_source_detail",
            label=translator.text(label),
            kind=kind,
            command=shlex.join(source.command_argv),
        )

    return "\n".join(
        (
            heading,
            describe("label.custom_source_existing", existing),
            describe("label.custom_source_proposed", proposed),
        )
    )


def _custom_dashboard_sources(panes: list[TuiPane]) -> tuple[CustomDashboardSource, ...]:
    """Choose the first visible Pane context for each distinct dataset ID."""
    sources: dict[str, CustomDashboardSource] = {}
    for pane in panes:
        if not isinstance(pane, TuiCustomPane):
            continue
        config = pane.component.request_config
        summary_mode = config.metric_summary
        if summary_mode == "none" or not custom_date_summary_supported(config):
            continue
        sources.setdefault(
            config.source.dataset_id,
            CustomDashboardSource(config.source, config, summary_mode),
        )
    return tuple(sources.values())


def _reconcile_custom_dashboard_summaries(
    header: DashboardHeader,
    sources: tuple[CustomDashboardSource, ...],
    *,
    now: float,
) -> tuple[CustomDashboardSummary, ...]:
    """Add/remove Header ownership without replacing same-ID accepted sources."""
    added: list[CustomDashboardSummary] = []
    wanted = {item.source.dataset_id: item for item in sources}
    for dataset_id in tuple(header.custom_summaries):
        if dataset_id not in wanted:
            summary = header.custom_summaries.pop(dataset_id)
            summary.scheduler.shutdown()
            summary.lifecycle.shutdown()
    for dataset_id, selection in wanted.items():
        summary = header.custom_summaries.get(dataset_id)
        if summary is not None:
            if summary.source != selection.source:
                summary.invalidate()
                summary.select(selection.source, ())
                added.append(summary)
            summary.metric_id = selection.config.metric_id if selection.config is not None else None
            summary.summary_mode = selection.summary_mode
            continue
        summary = CustomDashboardSummary(
            selection.source,
            FixedIntervalScheduler(header.scheduler.interval, now=now),
            LifecycleOperation(f"dashboard:header:custom:{dataset_id}"),
        )
        summary.metric_id = selection.config.metric_id
        summary.summary_mode = selection.summary_mode
        header.custom_summaries[dataset_id] = summary
        added.append(summary)
    return tuple(added)


def _invalidate_custom_dashboard_summaries(header: DashboardHeader) -> None:
    for summary in header.custom_summaries.values():
        summary.generation += 1
        summary.lifecycle.detach_active()


def _set_header_theme(header: DashboardHeader, theme: str) -> None:
    header.options = replace(
        header.options,
        chart=replace(
            header.options.chart,
            presentation=replace(header.options.chart.presentation, theme=theme),
        ),
    )


def _cycle_header_summary(period: str, *, step: int = 1) -> str:
    """Cycle Dashboard header summary scopes in either direction."""
    return _cycle(HEADER_SUMMARIES, period, step)


def _next_header_summary(period: str) -> str:
    """Return the next Dashboard header summary scope."""
    return _cycle_header_summary(period)


def _header_refresh_interval(
    header: DashboardHeader, *, aggressive: bool = False, today=None
) -> DateInterval | None:
    period = header.summary_period
    if period == "none":
        return None
    current = today or local_today()
    required = required_summary_coverage(current, period)
    uncovered = tuple(
        missing for interval in required.intervals for missing in header.coverage.missing(interval)
    )
    if uncovered or aggressive:
        intervals = uncovered or required.intervals
        return DateInterval(
            min(item.since for item in intervals), max(item.until for item in intervals)
        )
    return DateInterval(current, current)


def _header_summary(header: DashboardHeader, period: str):
    if period == "none":
        return None
    summary = build_period_summary(
        header.records,
        local_today(),
        period,
        header.coverage,
    )
    return summary


def _replace_header_interval(
    records: tuple[UsageRecord, ...], snapshot: UsageSnapshot
) -> tuple[UsageRecord, ...]:
    intervals = snapshot.coverage.intervals
    retained = tuple(
        record
        for record in records
        if record.day is None
        or not any(item.since <= record.day <= item.until for item in intervals)
    )
    return (*retained, *snapshot.records)


def _dashboard_title_line(title: str, freshness: str, width: int, *, color: bool = True) -> str:
    """Center the title with version left and freshness anchored right."""
    version = f"v{__version__}"
    version_width = display_width(version)
    freshness = truncate_width(freshness, max(0, min(display_width(freshness), width // 2)))
    freshness_width = display_width(freshness)
    title = truncate_width(title, max(0, width - version_width - freshness_width - 2))
    title_width = display_width(title)
    start = max(version_width + 1, (width - title_width) // 2)
    if freshness_width:
        start = min(start, max(version_width + 1, width - freshness_width - title_width - 1))
    version = dimmed(version, color=color)
    line = version + " " * max(1, start - version_width) + title
    gap = max(int(bool(freshness)), width - display_width(line) - freshness_width)
    return pad_width(clip_width(line + " " * gap + freshness, width), width)


def _header_lines(
    header: DashboardHeader,
    style: str,
    translator: Translator,
    terminal: Terminal,
    last_successful_update: datetime | None = None,
) -> list[str]:
    if style == "hidden":
        return []
    context = RenderContext(
        terminal.width,
        1,
        translator,
        color=terminal.color,
        ascii=terminal.ascii,
        color_scheme=header.options.chart.presentation.theme,
    )
    summary = _header_summary(header, header.summary_period) if header.token_enabled else None
    details: list[str] = []
    if header.summary_period != "none":
        if header.token_enabled:
            details.append(
                translator.text("status.loading")
                if summary is None
                else render_summary(summary, context)
            )
        for dataset_id in sorted(header.custom_summaries):
            custom = header.custom_summaries[dataset_id]
            if custom.response is not None:
                rendered = render_custom_metrics(
                    (custom.response.summary.metric,),
                    context,
                    period="range" if custom.summary_mode == "total" else custom.accepted_period,
                    as_of_date=custom.accepted_as_of_date,
                )
                if rendered:
                    details.append(rendered)
            elif custom.error is None:
                details.append(translator.text("status.loading"))
    detail_lines = tuple(line for detail in details for line in detail.splitlines() if line)
    scheme = get_color_scheme(header.options.chart.presentation.theme)
    title = styled_text(
        translator.text("label.dashboard"),
        scheme.highlight,
        RenderContext(
            terminal.width,
            1,
            translator,
            color=terminal.color,
            ascii=terminal.ascii,
            color_scheme=header.options.chart.presentation.theme,
        ),
        bold=True,
    )
    freshness = (
        translator.text("status.updated", time=last_successful_update.strftime("%H:%M:%S"))
        if last_successful_update is not None
        else ""
    )
    if style == "compact":
        return [
            _dashboard_title_line(title, freshness, terminal.width, color=terminal.color),
            *(center_text(line, terminal.width) for line in detail_lines),
        ]
    title_line = _dashboard_title_line(title, freshness, terminal.width, color=terminal.color)
    if style == "banner":
        return [title_line, *(center_text(line, terminal.width) for line in detail_lines)]
    rule = "=" if terminal.ascii else "═"
    styled_rule = styled_text(
        rule * terminal.width,
        scheme.other,
        RenderContext(
            terminal.width,
            1,
            translator,
            color=terminal.color,
            ascii=terminal.ascii,
            color_scheme=header.options.chart.presentation.theme,
        ),
    )
    panel_details = detail_lines or ("",)
    return [
        styled_rule,
        title_line,
        *(center_text(line, terminal.width) for line in panel_details),
        styled_rule,
    ]
