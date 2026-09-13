from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable
from datetime import date, timedelta

from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    ChangeDirection,
    DailySummary,
    PercentChange,
    RankingEntry,
    RankingModel,
    Series,
    StackModel,
    TimelineModel,
)
from ccusage_viz.domain import Notice, TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.options import DateRange
from ccusage_viz.project_identity import project_label, resolve_projects, unique_projects
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors

_OTHER_KEY = ("other",)
_TOTAL_KEY = ("total",)


def date_axis(date_range: DateRange) -> tuple[date, ...]:
    return tuple(date_range.since + timedelta(days=offset) for offset in range(date_range.days))


def _simple_selection(
    selectors: Iterable[str], values: Iterable[str], dimension: str
) -> tuple[str, ...]:
    unique = tuple(sorted(set(values), key=str.casefold))
    return resolve_selectors(
        selectors,
        (SelectorCandidate(value, value, (value,)) for value in unique),
        dimension=dimension,
    )


def _resolve_available(
    selectors: tuple[str, ...], values: Iterable[str], dimension: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve known selectors and retain unmatched literals as no-data selections."""
    resolved: list[str] = []
    missing: list[str] = []
    pool = tuple(values)
    for selector in selectors:
        try:
            matches = _simple_selection((selector,), pool, dimension)
        except UsageError as exc:
            if exc.key != "error.selector_no_match":
                raise
            missing.append(selector)
        else:
            resolved.extend(matches)
    return tuple(dict.fromkeys(resolved)), tuple(dict.fromkeys(missing))


def _usage_for_models(record: UsageRecord, selected: set[str]) -> TokenUsage | None:
    matches = (item.usage for item in record.models if item.model in selected)
    usage = sum(matches, start=TokenUsage.zero())
    return usage if usage.total > 0 else None


def filter_records(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    agents: Iterable[str] = (),
    models: Iterable[str] = (),
    projects: Iterable[str] = (),
) -> tuple[tuple[UsageRecord, ...], tuple[Notice, ...]]:
    """Apply OR within each selector kind and AND across selector kinds."""
    records = tuple(records)
    ranged = tuple(
        record
        for record in records
        if record.day is None or date_range.since <= record.day <= date_range.until
    )
    notices: list[Notice] = []

    agent_selectors = tuple(agents)
    resolved_agents, unmatched_agents = _resolve_available(
        agent_selectors, (record.agent for record in records), "agent"
    )
    selected_agents = set(resolved_agents)

    project_records = (
        record for record in records if not agent_selectors or record.agent in selected_agents
    )
    all_projects = unique_projects(
        record.project for record in project_records if record.project is not None
    )
    project_selectors = tuple(projects)
    resolved_projects = []
    unmatched_projects = []
    for selector in project_selectors:
        try:
            resolved_projects.extend(resolve_projects((selector,), all_projects))
        except UsageError as exc:
            if exc.key != "error.selector_no_match":
                raise
            unmatched_projects.append(selector)
    resolved_projects = list(dict.fromkeys(resolved_projects))
    unmatched_projects = list(dict.fromkeys(unmatched_projects))
    selected_projects = {item.key for item in resolved_projects}

    model_records = (
        record
        for record in records
        if (not agent_selectors or record.agent in selected_agents)
        and (
            not project_selectors
            or (record.project is not None and record.project.key in selected_projects)
        )
    )
    all_models = tuple(item.model for record in model_records for item in record.models)
    model_selectors = tuple(models)
    resolved_models, unmatched_models = _resolve_available(model_selectors, all_models, "model")
    selected_models = set(resolved_models)

    filtered: list[UsageRecord] = []
    available_agents: set[str] = set()
    available_projects: set[tuple[str, str]] = set()
    available_models: set[str] = set()
    missing_breakdown = False
    for record in ranged:
        if agent_selectors and record.agent not in selected_agents:
            continue
        available_agents.add(record.agent)
        if project_selectors and (
            record.project is None or record.project.key not in selected_projects
        ):
            continue
        if record.project is not None:
            available_projects.add(record.project.key)
        usage = record.usage
        breakdowns = record.models
        if model_selectors:
            if not breakdowns:
                missing_breakdown = True
                continue
            selected_breakdowns = tuple(
                item for item in breakdowns if item.model in selected_models
            )
            usage = _usage_for_models(record, selected_models) or TokenUsage.zero()
            if usage.total == 0:
                continue
            breakdowns = selected_breakdowns
        available_models.update(item.model for item in breakdowns)
        filtered.append(
            UsageRecord(record.day, record.agent, usage, record.source, record.project, breakdowns)
        )

    missing_agents = (*unmatched_agents, *(selected_agents - available_agents))
    if missing_agents:
        notices.append(
            Notice(
                "notice.selected_no_data",
                {
                    "dimension": "agent",
                    "values": ", ".join(sorted(set(missing_agents), key=str.casefold)),
                },
            )
        )
    missing_projects = tuple(
        item for item in resolved_projects if item.key not in available_projects
    )
    if missing_projects or unmatched_projects:
        notices.append(
            Notice(
                "notice.selected_no_data",
                {
                    "dimension": "project",
                    "values": ", ".join(
                        (
                            *(project_label(item, resolved_projects) for item in missing_projects),
                            *unmatched_projects,
                        )
                    ),
                },
            )
        )
    missing_models = (*unmatched_models, *(selected_models - available_models))
    if missing_models:
        notices.append(
            Notice(
                "notice.selected_no_data",
                {
                    "dimension": "model",
                    "values": ", ".join(sorted(set(missing_models), key=str.casefold)),
                },
            )
        )
    if missing_breakdown:
        notices.append(Notice("notice.model_breakdown_missing"))
    return tuple(filtered), tuple(notices)


def _group_items(
    records: Iterable[UsageRecord], by: str | None
) -> tuple[tuple[Hashable, str, date, TokenUsage], ...]:
    records = tuple(records)
    projects = unique_projects(record.project for record in records if record.project is not None)
    output: list[tuple[Hashable, str, date, TokenUsage]] = []
    for record in records:
        day = record.day or date.min
        if by is None:
            output.append((_TOTAL_KEY, "Total", day, record.usage))
        elif by == "agent":
            output.append((("agent", record.agent), record.agent, day, record.usage))
        elif by == "project" and record.project is not None:
            output.append(
                (record.project.key, project_label(record.project, projects), day, record.usage)
            )
        elif by == "model":
            known_total = sum((item.usage.total for item in record.models), start=0)
            for breakdown in record.models:
                output.append((("model", breakdown.model), breakdown.model, day, breakdown.usage))
            residual = record.usage.total - known_total
            if residual > 0:
                output.append((_OTHER_KEY, "Other", day, _component_usage(residual)))
    return tuple(output)


def _has_invalid_model_attribution(records: Iterable[UsageRecord], by: str | None) -> bool:
    return by == "model" and any(
        sum((item.usage.total for item in record.models), start=0) > record.usage.total
        for record in records
    )


def _ranked_groups(
    grouped: dict[Hashable, tuple[str, dict[date, TokenUsage]]],
) -> list[tuple[Hashable, str, dict[date, TokenUsage]]]:
    return sorted(
        ((key, label, values) for key, (label, values) in grouped.items()),
        key=lambda item: (
            -sum(usage.total for usage in item[2].values()),
            item[1].casefold(),
            repr(item[0]),
        ),
    )


def _grouped_daily(
    records: Iterable[UsageRecord], by: str | None
) -> dict[Hashable, tuple[str, dict[date, TokenUsage]]]:
    grouped: dict[Hashable, tuple[str, dict[date, TokenUsage]]] = {}
    for key, label, day, usage in _group_items(records, by):
        if key not in grouped:
            grouped[key] = (label, defaultdict(TokenUsage.zero))
        grouped[key][1][day] = grouped[key][1][day] + usage
    return grouped


def _top_other(
    groups: list[tuple[Hashable, str, dict[date, TokenUsage]]],
    *,
    top: int | None,
    show_other: bool,
) -> tuple[list[tuple[Hashable, str, dict[date, TokenUsage], bool]], int]:
    regular = [(key, label, values) for key, label, values in groups if key != _OTHER_KEY]
    residual = next((values for key, _, values in groups if key == _OTHER_KEY), None)
    excluded_groups = regular[top:] if top is not None else []
    visible_groups = regular if top is None else regular[:top]
    visible = [(key, label, values, False) for key, label, values in visible_groups]
    if residual is not None or (show_other and excluded_groups):
        other: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
        if residual is not None:
            for day, usage in residual.items():
                other[day] = other[day] + usage
        if show_other:
            for _, _, values in excluded_groups:
                for day, usage in values.items():
                    other[day] = other[day] + usage
        visible.append((_OTHER_KEY, "Other", other, True))
    return visible, len(excluded_groups)


def _percent_change(current: int, baseline: int) -> PercentChange:
    if current == baseline:
        return PercentChange(ChangeDirection.UNCHANGED)
    if baseline == 0:
        return PercentChange(ChangeDirection.FROM_ZERO)
    if current > baseline:
        return PercentChange(ChangeDirection.INCREASE, (current - baseline) / baseline * 100)
    return PercentChange(ChangeDirection.DECREASE, (baseline - current) / baseline * 100)


def _daily_summary(
    days: tuple[date, ...], values: tuple[TokenUsage, ...], *, enabled: bool
) -> DailySummary | None:
    if not enabled or not days:
        return None
    by_day = dict(zip(days, values, strict=True))
    current_day = days[-1]
    yesterday = current_day - timedelta(days=1)
    previous_week = current_day - timedelta(days=7)
    current = by_day[current_day].total
    return DailySummary(
        current_day,
        current,
        _percent_change(current, by_day.get(yesterday, TokenUsage.zero()).total),
        _percent_change(current, by_day.get(previous_week, TokenUsage.zero()).total),
        previous_week,
    )


def build_timeline(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    by: str | None = None,
    top: int | None = None,
    show_other: bool = False,
    include_summary: bool = True,
    notices: Iterable[Notice] = (),
) -> TimelineModel:
    records = tuple(records)
    days = date_axis(date_range)
    groups, excluded = _top_other(
        _ranked_groups(_grouped_daily(records, by)), top=top, show_other=show_other
    )
    series = tuple(
        Series(key, label, tuple(values.get(day, TokenUsage.zero()) for day in days), is_other)
        for key, label, values, is_other in groups
    )
    model_notices = tuple(notices)
    if _has_invalid_model_attribution(records, by):
        model_notices += (Notice("notice.model_overattributed"),)
    if show_other and top is not None and groups and excluded == 0:
        model_notices += (Notice("notice.other_not_needed", {"count": len(groups), "top": top}),)
    visible_values = tuple(
        sum((item.values[index] for item in series), TokenUsage.zero())
        for index in range(len(days))
    )
    summary = (
        _daily_summary(
            days,
            visible_values,
            enabled=include_summary and not date_range.fixed_bounds,
        )
        if series
        else None
    )
    return TimelineModel(days, series, model_notices, summary)


def build_calendar(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    include_summary: bool = True,
    notices: Iterable[Notice] = (),
) -> CalendarModel:
    totals: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
    for record in records:
        if record.day is not None:
            totals[record.day] = totals[record.day] + record.usage
    days = date_axis(date_range)
    values = tuple(totals[day] for day in days)
    return CalendarModel(
        tuple(CalendarDay(day, value) for day, value in zip(days, values, strict=True)),
        tuple(notices),
        _daily_summary(
            days,
            values,
            enabled=include_summary and not date_range.fixed_bounds,
        ),
    )


def _component_usage(amount: int) -> TokenUsage:
    return TokenUsage(amount, 0, 0, 0, 0, amount)


def build_stack(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    split_cache: bool = False,
    include_summary: bool = True,
    notices: Iterable[Notice] = (),
) -> StackModel:
    totals: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
    for record in records:
        if record.day is not None:
            totals[record.day] = totals[record.day] + record.usage
    days = date_axis(date_range)
    definitions = [("input", lambda value: value.input), ("output", lambda value: value.output)]
    if split_cache:
        definitions.extend(
            [
                ("cache_read", lambda value: value.cache_read),
                ("cache_creation", lambda value: value.cache_creation),
            ]
        )
    else:
        definitions.append(("cache", lambda value: value.cache_read + value.cache_creation))
    if any(value.other for value in totals.values()):
        definitions.append(("other", lambda value: value.other))
    components = tuple(
        Series(
            ("component", name), name, tuple(_component_usage(getter(totals[day])) for day in days)
        )
        for name, getter in definitions
    )
    values = tuple(totals[day] for day in days)
    return StackModel(
        days,
        components,
        tuple(notices),
        _daily_summary(
            days,
            values,
            enabled=include_summary and not date_range.fixed_bounds,
        ),
    )


def build_ranking(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    by: str,
    top: int | None = None,
    show_other: bool = False,
    include_summary: bool = True,
    notices: Iterable[Notice] = (),
) -> RankingModel:
    records = tuple(records)
    ranked_groups = _ranked_groups(_grouped_daily(records, by))
    denominator = sum(
        (sum(values.values(), start=TokenUsage.zero()) for _, _, values in ranked_groups),
        start=TokenUsage.zero(),
    )
    groups, excluded = _top_other(ranked_groups, top=top, show_other=show_other)
    entries = tuple(
        RankingEntry(
            key,
            label,
            sum(values.values(), start=TokenUsage.zero()),
            is_other,
        )
        for key, label, values, is_other in groups
    )
    model_notices = tuple(notices)
    if _has_invalid_model_attribution(records, by):
        model_notices += (Notice("notice.model_overattributed"),)
    if show_other and top is not None and groups and excluded == 0:
        model_notices += (Notice("notice.other_not_needed", {"count": len(groups), "top": top}),)
    days = date_axis(date_range)
    daily_totals: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
    for record in records:
        if record.day is not None:
            daily_totals[record.day] = daily_totals[record.day] + record.usage
    values = tuple(daily_totals[day] for day in days)
    return RankingModel(
        entries,
        date_range,
        model_notices,
        denominator,
        _daily_summary(days, values, enabled=include_summary and not date_range.fixed_bounds),
    )
