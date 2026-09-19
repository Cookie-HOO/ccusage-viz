from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable
from datetime import date, timedelta

from ccusage_viz.chart_models import (
    CalendarDay,
    CalendarModel,
    PeriodSummary,
    RankingEntry,
    RankingModel,
    Series,
    StackModel,
    TimelineModel,
)
from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage
from ccusage_viz.domain import Notice, TokenUsage, UsageRecord
from ccusage_viz.processing.summaries import build_period_summary, build_range_summary, period_start
from ccusage_viz.project_identity import project_label, unique_projects

_OTHER_KEY = ("other",)
_TOTAL_KEY = ("total",)
_EMPTY_COVERAGE = DateCoverage()


def date_axis(date_range: DateRange) -> tuple[date, ...]:
    return tuple(date_range.since + timedelta(days=offset) for offset in range(date_range.days))


def period_axis(date_range: DateRange, aggregation: str) -> tuple[date, ...]:
    return tuple(dict.fromkeys(period_start(day, aggregation) for day in date_axis(date_range)))


def _aggregate_daily(values: dict[date, TokenUsage], aggregation: str) -> dict[date, TokenUsage]:
    if aggregation == "day":
        return values
    aggregated: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
    for day, usage in values.items():
        aggregated[period_start(day, aggregation)] += usage
    return aggregated


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


def _build_summary(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    period: str,
    coverage: DateCoverage,
    *,
    enabled: bool,
    filter_count: int,
) -> PeriodSummary | None:
    if date_range.fixed_bounds:
        return build_range_summary(
            records,
            date_range,
            coverage,
            enabled=enabled,
            filter_count=filter_count,
        )
    return build_period_summary(
        records,
        date_range.until,
        period,
        coverage,
        enabled=enabled,
        filter_count=filter_count,
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
    aggregation: str = "day",
    coverage: DateCoverage = _EMPTY_COVERAGE,
    filter_count: int = 0,
) -> TimelineModel:
    records = tuple(records)
    days = period_axis(date_range, aggregation)
    groups, excluded = _top_other(
        _ranked_groups(_grouped_daily(records, by)), top=top, show_other=show_other
    )
    series = tuple(
        Series(
            key,
            label,
            tuple(
                _aggregate_daily(values, aggregation).get(day, TokenUsage.zero()) for day in days
            ),
            is_other,
        )
        for key, label, values, is_other in groups
    )
    model_notices = tuple(notices)
    if _has_invalid_model_attribution(records, by):
        model_notices += (Notice("notice.model_overattributed"),)
    if show_other and top is not None and groups and excluded == 0:
        model_notices += (Notice("notice.other_not_needed", {"count": len(groups), "top": top}),)
    summary = _build_summary(
        records,
        date_range,
        aggregation,
        coverage,
        enabled=include_summary,
        filter_count=filter_count,
    )
    return TimelineModel(days, series, model_notices, summary, aggregation)


def build_calendar(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    include_summary: bool = True,
    notices: Iterable[Notice] = (),
    coverage: DateCoverage = _EMPTY_COVERAGE,
    filter_count: int = 0,
) -> CalendarModel:
    records = tuple(records)
    totals: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
    for record in records:
        if record.day is not None:
            totals[record.day] = totals[record.day] + record.usage
    days = date_axis(date_range)
    values = tuple(totals[day] for day in days)
    return CalendarModel(
        tuple(CalendarDay(day, value) for day, value in zip(days, values, strict=True)),
        tuple(notices),
        _build_summary(
            records,
            date_range,
            "day",
            coverage,
            enabled=include_summary,
            filter_count=filter_count,
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
    aggregation: str = "day",
    coverage: DateCoverage = _EMPTY_COVERAGE,
    filter_count: int = 0,
) -> StackModel:
    records = tuple(records)
    totals: dict[date, TokenUsage] = defaultdict(TokenUsage.zero)
    for record in records:
        if record.day is not None:
            totals[record.day] = totals[record.day] + record.usage
    days = period_axis(date_range, aggregation)
    period_totals = _aggregate_daily(totals, aggregation)
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
            ("component", name),
            name,
            tuple(_component_usage(getter(period_totals[day])) for day in days),
        )
        for name, getter in definitions
    )
    return StackModel(
        days,
        components,
        tuple(notices),
        _build_summary(
            records,
            date_range,
            aggregation,
            coverage,
            enabled=include_summary,
            filter_count=filter_count,
        ),
        aggregation,
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
    summary_notices: Iterable[Notice] = (),
    coverage: DateCoverage = _EMPTY_COVERAGE,
    filter_count: int = 0,
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
    summary = _build_summary(
        records,
        date_range,
        "day",
        coverage,
        enabled=include_summary,
        filter_count=filter_count,
    )
    if summary is not None:
        model_notices += tuple(summary_notices)
    visible_regular_total = sum(
        (entry.usage.total for entry in entries if not entry.is_other), start=0
    )
    top_share = (
        visible_regular_total / denominator.total
        if excluded and not show_other and denominator.total > 0
        else None
    )
    return RankingModel(
        entries,
        date_range,
        model_notices,
        denominator,
        summary,
        top if top_share is not None else None,
        top_share,
    )
