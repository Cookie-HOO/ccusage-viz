from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import Notice, TokenUsage, UsageRecord, model_identity
from ccusage_viz.errors import UsageError
from ccusage_viz.project_identity import project_label, resolve_projects, unique_projects
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors


@dataclass(frozen=True, slots=True)
class FilteredScope:
    records: tuple[UsageRecord, ...]
    notices: tuple[Notice, ...]
    filter_count: int

    @property
    def total(self) -> TokenUsage:
        return sum((record.usage for record in self.records), start=TokenUsage.zero())


def _simple_selection(
    selectors: Iterable[str],
    values: Iterable[str],
    dimension: str,
    *,
    identity: Callable[[str], str] = str,
) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(identity(value) for value in values))
    return resolve_selectors(
        selectors,
        (SelectorCandidate(value, value, (value,)) for value in unique),
        dimension=dimension,
    )


def _resolve_available(
    selectors: tuple[str, ...],
    values: Iterable[str],
    dimension: str,
    *,
    identity: Callable[[str], str] = str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve known selectors and retain unmatched literals as no-data selections."""
    resolved: list[str] = []
    missing: list[str] = []
    pool = tuple(values)
    for selector in selectors:
        try:
            matches = _simple_selection((identity(selector),), pool, dimension, identity=identity)
        except UsageError as exc:
            if exc.key != "error.selector_no_match":
                raise
            missing.append(selector)
        else:
            resolved.extend(matches)
    return tuple(dict.fromkeys(resolved)), tuple(dict.fromkeys(missing))


def _usage_for_models(record: UsageRecord, selected: set[str]) -> TokenUsage | None:
    matches = (item.usage for item in record.models if model_identity(item.model) in selected)
    usage = sum(matches, start=TokenUsage.zero())
    return usage if usage.total > 0 else None


def prepare_filtered_scope(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    agents: Iterable[str] = (),
    models: Iterable[str] = (),
    projects: Iterable[str] = (),
) -> FilteredScope:
    """Resolve independent candidates, then apply AND across selected dimensions."""
    records = tuple(records)
    ranged = tuple(
        record
        for record in records
        if record.day is None or date_range.since <= record.day <= date_range.until
    )
    notices: list[Notice] = []

    agent_selectors = tuple(agents)
    resolved_agents, unmatched_agents = _resolve_available(
        agent_selectors, (record.agent for record in ranged), "agent"
    )
    selected_agents = set(resolved_agents)

    all_projects = unique_projects(
        record.project for record in ranged if record.project is not None
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

    all_models = tuple(item.model for record in ranged for item in record.models)
    model_selectors = tuple(models)
    resolved_models, unmatched_models = _resolve_available(
        model_selectors, all_models, "model", identity=model_identity
    )
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
                item for item in breakdowns if model_identity(item.model) in selected_models
            )
            usage = _usage_for_models(record, selected_models) or TokenUsage.zero()
            if usage.total == 0:
                continue
            breakdowns = selected_breakdowns
        available_models.update(model_identity(item.model) for item in breakdowns)
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
                            *(project_label(item, all_projects) for item in missing_projects),
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
    filter_count = sum(
        bool(selectors) for selectors in (agent_selectors, model_selectors, project_selectors)
    )
    return FilteredScope(tuple(filtered), tuple(notices), filter_count)


def filter_records(
    records: Iterable[UsageRecord],
    date_range: DateRange,
    *,
    agents: Iterable[str] = (),
    models: Iterable[str] = (),
    projects: Iterable[str] = (),
) -> tuple[tuple[UsageRecord, ...], tuple[Notice, ...]]:
    scope = prepare_filtered_scope(
        records,
        date_range,
        agents=agents,
        models=models,
        projects=projects,
    )
    return scope.records, scope.notices
