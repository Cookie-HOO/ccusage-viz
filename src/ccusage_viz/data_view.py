from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from ccusage_viz.chart_models import CalendarModel, RankingModel, StackModel, TimelineModel
from ccusage_viz.domain import TokenUsage
from ccusage_viz.formatting import format_tokens
from ccusage_viz.processing import process_historical
from ccusage_viz.project_identity import ExactProjectDisplayKey, exact_project_display_label

if TYPE_CHECKING:
    from ccusage_viz.historical_component import UsageSnapshot
    from ccusage_viz.i18n import Translator
    from ccusage_viz.options import StandaloneLaunch
    from ccusage_viz.processing.monitor import ObservedBucket
    from ccusage_viz.terminal import Terminal


BodyView = Literal["chart", "command", "full-command", "data-table", "data-json"]
DashboardBodyView = Literal["chart", "full-command"]
CopyKind = Literal["command", "full-command", "data-table", "data-json"]
_BODY_VIEWS: tuple[BodyView, ...] = (
    "chart",
    "command",
    "full-command",
    "data-table",
    "data-json",
)


def next_body_view(view: BodyView) -> BodyView:
    """Return the next transient interactive body view."""
    return _BODY_VIEWS[(_BODY_VIEWS.index(view) + 1) % len(_BODY_VIEWS)]


def next_dashboard_body_view(view: DashboardBodyView) -> DashboardBodyView:
    """Return the next full-screen Dashboard body view."""
    views: tuple[DashboardBodyView, ...] = ("chart", "full-command")
    return views[(views.index(view) + 1) % len(views)]


def body_view_copy_kind(view: BodyView) -> CopyKind | None:
    """Return the payload copied by a body view, if copying is permitted."""
    return None if view == "chart" else view


def body_view_footer_key(view: BodyView, *, monitor: bool = False) -> str:
    """Return the localized footer key for a view and command family."""
    prefix = "status.monitor_" if monitor else "status."
    return f"{prefix}{view.replace('-', '_')}_keys" if view != "chart" else f"{prefix}keys"


def _usage_values(usage: TokenUsage) -> dict[str, int]:
    return {
        "total": usage.total,
        "input": usage.input,
        "output": usage.output,
        "cache_read": usage.cache_read,
        "cache_creation": usage.cache_creation,
        "other": usage.other,
    }


def _historical_model(options: StandaloneLaunch, snapshot: UsageSnapshot):
    from ccusage_viz.options import MonitorConfig

    chart = options.chart
    if isinstance(chart, MonitorConfig):
        raise TypeError("historical data views do not support monitor configurations")
    return process_historical(
        chart,
        snapshot.records,
        notices=snapshot.notices,
        summary_notices=snapshot.summary_notices,
        coverage=snapshot.coverage,
    )


def _exact_project_agent(key: object) -> str | None:
    if (
        isinstance(key, tuple)
        and len(key) == 4
        and key[:2] == ("project", "exact")
        and isinstance(key[2], str)
    ):
        return key[2]
    return None


def _merged_project_alias(key: object) -> str | None:
    if (
        isinstance(key, tuple)
        and len(key) == 3
        and key[:2] == ("project", "name")
        and isinstance(key[2], str)
    ):
        return key[2]
    return None


def _merge_groups(keys: Iterable[object]) -> dict[object, int]:
    aliases = sorted(
        {alias for key in keys if (alias := _merged_project_alias(key)) is not None},
        key=str.casefold,
    )
    return {("project", "name", alias): index for index, alias in enumerate(aliases, start=1)}


def _historical_rows(
    model: TimelineModel | CalendarModel | StackModel | RankingModel,
) -> list[dict[str, object]]:
    if isinstance(model, TimelineModel):
        include_agent = any(_exact_project_agent(series.key) is not None for series in model.series)
        merge_groups = _merge_groups(series.key for series in model.series)
        return [
            {
                "period": day.isoformat(),
                "series": series.label,
                **({"agent": _exact_project_agent(series.key)} if include_agent else {}),
                **({"合并组": merge_groups[series.key]} if series.key in merge_groups else {}),
                "is_other": series.is_other,
                **_usage_values(usage),
            }
            for series in model.series
            for day, usage in zip(model.days, series.values, strict=True)
        ]
    if isinstance(model, CalendarModel):
        return [{"date": item.day.isoformat(), **_usage_values(item.usage)} for item in model.days]
    if isinstance(model, StackModel):
        return [
            {
                "period": day.isoformat(),
                "component": component.label,
                "is_other": component.is_other,
                "total": usage.total,
            }
            for component in model.components
            for day, usage in zip(model.days, component.values, strict=True)
        ]
    include_agent = any(_exact_project_agent(entry.key) is not None for entry in model.entries)
    merge_groups = _merge_groups(entry.key for entry in model.entries)
    return [
        {
            "rank": rank,
            "project": entry.label,
            **({"agent": _exact_project_agent(entry.key)} if include_agent else {}),
            **({"合并组": merge_groups[entry.key]} if entry.key in merge_groups else {}),
            "is_other": entry.is_other,
            **_usage_values(entry.usage),
        }
        for rank, entry in enumerate(model.entries, start=1)
    ]


def _markdown(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    fields = tuple(dict.fromkeys(field for row in rows for field in row))
    header = "| " + " | ".join(fields) + " |"
    separator = "| " + " | ".join("---" for _ in fields) + " |"

    def value(item: object) -> str:
        if item is None:
            return ""
        if isinstance(item, bool):
            return str(item).lower()
        if isinstance(item, int):
            return format_tokens(item)
        return str(item).replace("|", "\\|")

    return "\n".join(
        (
            header,
            separator,
            *("| " + " | ".join(value(row.get(field)) for field in fields) + " |" for row in rows),
        )
    )


def snapshot_data_payload(
    options: StandaloneLaunch, snapshot: UsageSnapshot | None
) -> tuple[str | None, list[dict[str, object]]]:
    """Return chart-model data rows, never raw source records."""
    if snapshot is None:
        return None, []
    model = _historical_model(options, snapshot)
    return options.chart.kind, _historical_rows(model)


def _display_payload(payload: str, terminal: Terminal, *, complete: bool) -> str:
    """Keep textual inspection views compact while preserving copy payloads."""
    if complete:
        return payload
    lines = payload.splitlines()
    visible = max(1, terminal.height - 4)
    if len(lines) <= visible:
        return payload
    return "\n".join((*lines[: max(0, visible - 1)], "…"))


def render_snapshot_data(
    options: StandaloneLaunch,
    snapshot: UsageSnapshot | None,
    translator: Translator,
    terminal: Terminal,
    *,
    view: Literal["data-table", "data-json"] = "data-table",
    complete: bool = False,
) -> str:
    """Render the displayed historical chart model as Markdown or JSON."""
    command, rows = snapshot_data_payload(options, snapshot)
    if command is None:
        return translator.text("message.data_loading")
    if not rows:
        return translator.text("message.no_data")
    payload = (
        json.dumps({"command": command, "rows": rows}, indent=2, ensure_ascii=False)
        if view == "data-json"
        else _markdown(rows)
    )
    return _display_payload(payload, terminal, complete=complete)


def monitor_data_payload(
    buckets: Iterable[ObservedBucket], *, by: str | None
) -> list[dict[str, object]]:
    """Return one row per exact displayed Monitor bucket series value."""
    unit = "tpm" if by in {None, "model"} else "tokens"
    return [
        {
            "ended_at": bucket.ended_wall.isoformat(),
            "series": (
                exact_project_display_label(name)
                if isinstance(name, ExactProjectDisplayKey)
                else name
            ),
            "value": value,
            "unit": unit,
        }
        for bucket in buckets
        for name, value in sorted(bucket.values.items(), key=lambda item: str(item[0]).casefold())
    ]


def render_monitor_data(
    buckets: Iterable[ObservedBucket],
    *,
    by: str | None,
    translator: Translator,
    terminal: Terminal,
    view: Literal["data-table", "data-json"] = "data-table",
    complete: bool = False,
) -> str:
    """Render exact displayed Monitor buckets as Markdown or JSON."""
    rows = monitor_data_payload(buckets, by=by)
    if not rows:
        return translator.text("message.monitor_empty")
    payload = (
        json.dumps({"rows": rows}, indent=2, ensure_ascii=False)
        if view == "data-json"
        else _markdown(rows)
    )
    return _display_payload(payload, terminal, complete=complete)
