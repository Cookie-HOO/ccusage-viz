from __future__ import annotations

import argparse
import math
import shlex
from dataclasses import replace
from typing import cast

from ccusage_viz.command_parsing.common import _DURATION_PATTERN
from ccusage_viz.core.time import system_timezone, validate_timezone
from ccusage_viz.errors import UsageError
from ccusage_viz.options import (
    CalendarConfig,
    ChartPresentation,
    CustomChartConfig,
    CustomCommandSource,
    Density,
    Filters,
    MonitorConfig,
    RankingConfig,
    StackConfig,
    TimelineConfig,
    compatible_styles,
    resolve_date_range,
)


def _parse_window(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value)
    if match is None:
        raise UsageError("error.window_invalid", value=value)
    seconds = int(match["value"]) * (60 if match["unit"] == "m" else 3600)
    if not 5 * 60 <= seconds <= 24 * 3600:
        raise UsageError("error.window_range")
    return seconds


def _chart_kind(namespace: argparse.Namespace) -> str:
    return getattr(namespace, "chart_kind", None) or namespace.command or "timeline"


def _chart_from_namespace(namespace: argparse.Namespace, *, timezone: str | None = None):
    command = _chart_kind(namespace)
    if getattr(namespace, "partition_by", None) is not None:
        raise UsageError(
            "error.arguments",
            detail="--partition-by requires a custom chart selected with --dataset",
        )
    filters = Filters(
        tuple(namespace.agent), tuple(namespace.model), tuple(getattr(namespace, "project", ()))
    )
    style = (
        getattr(namespace, "style", None)
        or compatible_styles(command, getattr(namespace, "by", None))[0]
    )
    presentation = ChartPresentation(
        theme=namespace.color_scheme,
        style=style,
        legend=getattr(namespace, "legend", "below-title"),
        density=cast(
            Density,
            getattr(namespace, "density", "full" if command == "ranking" else "detailed"),
        ),
    )
    top = getattr(namespace, "top", None)
    if command in {"timeline", "monitor"} and namespace.by is not None and top is None:
        top = 3
    if command == "monitor":
        if style != "cumulative-bars" and presentation.legend == "values":
            presentation = replace(presentation, legend="below-title")
        return MonitorConfig(
            kind="monitor",
            window_seconds=_parse_window(namespace.window),
            filters=filters,
            presentation=presentation,
            by=namespace.by,
            top=top,
        )
    date_range = resolve_date_range(
        command,
        period=namespace.period,
        since=namespace.since,
        until=namespace.until,
        timezone=timezone,
    )
    if command == "timeline":
        return TimelineConfig(
            "timeline",
            date_range,
            filters,
            presentation,
            namespace.by,
            top,
            namespace.other,
            namespace.granularity,
            namespace.weekdays,
        )
    if command == "calendar":
        return CalendarConfig("calendar", date_range, filters, presentation)
    if command == "stack":
        return StackConfig(
            "stack",
            date_range,
            filters,
            presentation,
            namespace.cache,
            namespace.granularity,
            namespace.weekdays,
            namespace.by,
            top if top is not None else 10,
            namespace.other,
        )
    return RankingConfig(
        "ranking",
        date_range,
        filters,
        presentation,
        namespace.by,
        top if top is not None else 10,
        namespace.other,
    )


def _request_timezone(namespace: argparse.Namespace) -> str:
    try:
        timezone = getattr(namespace, "timezone", None)
        return validate_timezone(timezone) if timezone else system_timezone()
    except ValueError as exc:
        raise UsageError("error.arguments", detail=str(exc)) from exc


def _custom_chart_from_namespace(
    namespace: argparse.Namespace,
    *,
    timezone: str | None = None,
    explicit: frozenset[str] = frozenset(),
) -> CustomChartConfig:
    unsupported = explicit & {"agent", "model", "project", "by", "cache"}
    if unsupported:
        names = ", ".join(f"--{name.replace('_', '-')}" for name in sorted(unsupported))
        raise UsageError(
            "error.arguments",
            detail=f"{names} cannot be combined with --dataset; use --filter or --group-by",
        )
    filters: dict[str, set[str]] = {}
    for value in namespace.custom_filters:
        filter_id, separator, option_id = value.partition("=")
        if not separator or not filter_id or not option_id:
            raise UsageError("error.arguments", detail="--filter must use ID=OPTION")
        filters.setdefault(filter_id, set()).add(option_id)
    if namespace.command_text is None:
        if namespace.dataset is None:
            raise UsageError("error.arguments", detail="--dataset or --command is required")
        from ccusage_viz.datasets.service import DatasetService

        source = DatasetService().command_source(namespace.dataset)
    else:
        try:
            command_argv = tuple(shlex.split(namespace.command_text))
        except ValueError as exc:
            raise UsageError(
                "error.arguments", detail="--command contains invalid shell quoting"
            ) from exc
        if not command_argv:
            raise UsageError("error.arguments", detail="--command must not be empty")
        if namespace.dataset is None:
            raise UsageError("error.arguments", detail="--command requires --dataset")
        source = CustomCommandSource(namespace.dataset, command_argv)
    kind = _chart_kind(namespace)
    group_by = namespace.group_by
    partition_by = getattr(namespace, "partition_by", None)
    if partition_by is not None and kind != "ranking":
        raise UsageError("error.arguments", detail="--partition-by is only valid for ranking")
    if partition_by is not None and group_by is None:
        raise UsageError("error.arguments", detail="partition_by requires a non-null group_by")
    if partition_by is not None and partition_by == group_by:
        raise UsageError("error.arguments", detail="partition_by and group_by must differ")
    top = getattr(namespace, "top", None)
    if kind == "monitor" and group_by is not None and top is None:
        top = 3
    if kind == "ranking" and group_by is None and top == 10 and "top" not in explicit:
        top = None
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    if top is not None and group_by is None:
        raise UsageError("error.top_requires_by")
    style = namespace.style or (
        "points" if kind == "monitor" else compatible_styles(kind, group_by)[0]
    )
    if style not in compatible_styles(kind, group_by):
        raise UsageError("error.style_incompatible", style=style, mode=group_by or "total")
    date_range = resolve_date_range(
        "timeline" if kind == "monitor" else kind,
        period=getattr(namespace, "period", None),
        since=getattr(namespace, "since", None),
        until=getattr(namespace, "until", None),
        timezone=timezone,
    )
    return CustomChartConfig(
        kind=kind,
        source=source,
        date_range=date_range,
        filters=tuple(
            (filter_id, tuple(sorted(option_ids)))
            for filter_id, option_ids in sorted(filters.items())
        ),
        presentation=ChartPresentation(
            theme=namespace.color_scheme,
            style=style,
            legend=getattr(namespace, "legend", "below-title"),
            density=cast(
                Density, namespace.density or ("full" if kind == "ranking" else "detailed")
            ),
        ),
        group_by=group_by,
        top=top,
        other=getattr(namespace, "other", "show"),
        granularity=getattr(namespace, "granularity", "day"),
        weekdays=getattr(namespace, "weekdays", "show"),
        initial_explicit=explicit
        & {
            "period",
            "since",
            "until",
            "partition_by",
            "group_by",
            "top",
            "filter",
            "granularity",
            "other",
            "style",
            "color_scheme",
            "window",
        },
        metric_id=namespace.metric,
        partition_by=partition_by,
    )


def _validate_chart(
    namespace: argparse.Namespace, chart, *, explicit: frozenset[str], demo: str | None
) -> float:
    top = getattr(chart, "top", None)
    by = getattr(chart, "by", None)
    if top is not None and top < 1:
        raise UsageError("error.top_positive")
    command = _chart_kind(namespace)
    if command in {"timeline", "monitor"} and top is not None and by is None:
        raise UsageError("error.top_requires_by")
    if chart.presentation.style not in compatible_styles(command, by):
        raise UsageError(
            "error.style_incompatible", style=chart.presentation.style, mode=by or "total"
        )
    interval = getattr(namespace, "interval", None)
    if command == "monitor" and interval is None:
        interval = 1.0 if demo is not None else 15.0
    minimum = 1 if command == "monitor" and demo is not None else 5 if command == "monitor" else 2
    if interval is not None and (not math.isfinite(interval) or interval < minimum):
        raise UsageError("error.interval_min", minimum=minimum)
    return interval if interval is not None else 10.0
