from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ccusage_viz.domain import UsageRecord, model_identity
from ccusage_viz.formatting import clip_width
from ccusage_viz.i18n import Translator
from ccusage_viz.options import Dimension, Filters
from ccusage_viz.project_identity import project_label, unique_projects

_EMPTY_FILTERS = Filters()


@dataclass(frozen=True, slots=True)
class FilterChoices:
    agents: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    unavailable: frozenset[Dimension] = frozenset()

    def for_dimension(self, dimension: Dimension) -> tuple[str, ...]:
        return getattr(self, f"{dimension}s")

    def is_available(self, dimension: Dimension) -> bool:
        return dimension not in self.unavailable


@dataclass(frozen=True, slots=True)
class FilterDraft:
    filters: Filters
    dimension_index: int = 0
    choice_index: int = 0

    @property
    def dimension(self) -> Dimension:
        return ("agent", "model", "project")[self.dimension_index]

    def selected(self, dimension: Dimension) -> tuple[str, ...]:
        return getattr(self.filters, f"{dimension}s")

    def move_dimension(self, step: int) -> FilterDraft:
        return replace(
            self,
            dimension_index=(self.dimension_index + step) % 3,
            choice_index=0,
        )

    def move_choice(self, step: int, choices: FilterChoices) -> FilterDraft:
        values = choices.for_dimension(self.dimension)
        return replace(
            self,
            choice_index=(self.choice_index + step) % max(1, len(values)),
        )

    def current(self, choices: FilterChoices) -> str | None:
        values = choices.for_dimension(self.dimension)
        return values[self.choice_index % len(values)] if values else None

    def contains(self, dimension: Dimension, value: str) -> bool:
        identity = model_identity if dimension == "model" else str.casefold
        return any(identity(item) == identity(value) for item in self.selected(dimension))

    def toggle(self, dimension: Dimension, value: str) -> FilterDraft:
        field = f"{dimension}s"
        selected = self.selected(dimension)
        identity = model_identity if dimension == "model" else str.casefold
        updated = tuple(item for item in selected if identity(item) != identity(value))
        if len(updated) == len(selected):
            updated = (*selected, value)
        return replace(self, filters=replace(self.filters, **{field: updated}))


def discover_filter_choices(
    records: tuple[UsageRecord, ...],
    selected: Filters = _EMPTY_FILTERS,
    *,
    include_projects: bool = True,
) -> FilterChoices:
    projects = unique_projects(record.project for record in records if record.project is not None)
    discovered_agents = tuple(record.agent for record in records)
    discovered_models = tuple(model.model for record in records for model in record.models)
    discovered_projects = tuple(project_label(project, projects) for project in projects)
    return FilterChoices(
        agents=_values((*selected.agents, *discovered_agents)),
        models=_values((*selected.models, *discovered_models), identity=model_identity),
        projects=_values((*selected.projects, *discovered_projects)),
        unavailable=frozenset(
            dimension
            for dimension, available in (
                ("agent", bool(discovered_agents)),
                ("model", bool(discovered_models)),
                ("project", include_projects and bool(discovered_projects)),
            )
            if not available
        ),
    )


def run_filter_editor(
    filters: Filters,
    choices: FilterChoices,
    translator: Translator,
    *,
    width: int,
    paint: Callable[[str, str], None],
    read_key: Callable[[], str | None],
) -> Filters | None:
    draft = FilterDraft(filters)
    while True:
        paint(
            _render_filter_draft(draft, choices, translator, width),
            translator.text("status.filter_controls"),
        )
        key = read_key()
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "\x1b":
            return None
        if key in {"\r", "\n"}:
            return draft.filters
        if key in {"h", "\x1b[D"}:
            draft = draft.move_dimension(-1)
        elif key in {"l", "\x1b[C", "\t"}:
            draft = draft.move_dimension(1)
        elif key in {"k", "\x1b[A"}:
            draft = draft.move_choice(-1, choices)
        elif key in {"j", "\x1b[B"}:
            draft = draft.move_choice(1, choices)
        elif key == " ":
            value = draft.current(choices)
            if value is not None:
                draft = draft.toggle(draft.dimension, value)


def _render_filter_draft(
    draft: FilterDraft,
    choices: FilterChoices,
    translator: Translator,
    width: int,
) -> str:
    tabs = " · ".join(
        (
            f"[{translator.text(f'label.{dimension}')}]"
            if dimension == draft.dimension
            else translator.text(f"label.{dimension}")
        )
        for dimension in ("agent", "model", "project")
    )
    values = choices.for_dimension(draft.dimension)
    rows = "\n".join(
        clip_width(
            f"{'›' if index == draft.choice_index % len(values) else ' '} "
            f"{'[x]' if draft.contains(draft.dimension, value) else '[ ]'} {value}",
            width,
        )
        for index, value in enumerate(values)
    )
    if not choices.is_available(draft.dimension):
        body = "\n".join(
            part for part in (translator.text("status.filter_unavailable"), rows) if part
        )
    else:
        body = rows
    return f"{clip_width(tabs, width)}\n{body}"


def _values(
    values: tuple[str, ...], *, identity: Callable[[str], str] | None = None
) -> tuple[str, ...]:
    if identity is None:
        return tuple(sorted(set(values), key=lambda value: (value.casefold(), value)))
    return tuple(sorted(dict.fromkeys(identity(value) for value in values)))
