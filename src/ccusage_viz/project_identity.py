from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePath

from ccusage_viz.domain import ProjectRef
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors

_OPAQUE_PATH_MARKERS = frozenset(
    {"project", "projects", "repo", "repos", "workspace", "workspaces", "src"}
)


def _opaque_project_name(raw_id: str) -> str | None:
    """Extract a project leaf from ccusage's path-encoded opaque identifiers."""
    if not raw_id.startswith("-"):
        return None
    parts = tuple(part for part in raw_id.strip("-").split("-") if part)
    marker_positions = tuple(
        index for index, part in enumerate(parts) if part.casefold() in _OPAQUE_PATH_MARKERS
    )
    if not marker_positions or marker_positions[-1] == len(parts) - 1:
        return None
    name = "-".join(parts[marker_positions[-1] + 1 :])
    return name if _is_safe_display_name(name) else None


def _is_safe_display_name(value: str) -> bool:
    return bool(
        value
        and value != "Project"
        and not value.startswith("-")
        and "/" not in value
        and "\\" not in value
        and not value.isspace()
    )


def project_display_name(raw_id: str) -> str:
    """Return a safe project basename or recognized opaque project leaf."""
    value = raw_id.rstrip("/\\")
    if value and ("/" in value or "\\" in value):
        return PurePath(value.replace("\\", "/")).name or "Project"
    return _opaque_project_name(raw_id) or "Project"


def make_project_ref(agent: str, raw_id: str, display_name: str | None = None) -> ProjectRef:
    display = display_name or project_display_name(raw_id)
    if not _is_safe_display_name(display):
        display = project_display_name(display)
    return ProjectRef(agent, raw_id, display)


def _display_names(projects: tuple[ProjectRef, ...]) -> dict[tuple[str, str], str]:
    unnamed = tuple(
        sorted(
            (project for project in projects if not _is_safe_display_name(project.display_name)),
            key=lambda project: project.key,
        )
    )
    aliases = {project.key: f"Project {index}" for index, project in enumerate(unnamed, 1)}
    return {project.key: aliases.get(project.key, project.display_name) for project in projects}


def project_label(project: ProjectRef, projects: Iterable[ProjectRef]) -> str:
    """Return a deterministic, recognizable, presentation-safe project label."""
    pool = unique_projects(projects)
    names = _display_names(pool)
    display_name = names[project.key]
    peers = tuple(item for item in pool if names[item.key] == display_name)
    if len(peers) <= 1:
        return display_name
    same_agent = tuple(item for item in peers if item.agent == project.agent)
    if len(same_agent) == 1:
        return f"{display_name} ({project.agent})"
    ordinal = same_agent.index(project) + 1
    return f"{display_name} ({project.agent} {ordinal})"


def unique_projects(projects: Iterable[ProjectRef]) -> tuple[ProjectRef, ...]:
    """Deduplicate by the documented agent-scoped upstream identity."""
    unique: dict[tuple[str, str], ProjectRef] = {}
    for project in projects:
        unique.setdefault(project.key, project)
    return tuple(unique.values())


def resolve_projects(
    selectors: Iterable[str], projects: Iterable[ProjectRef]
) -> tuple[ProjectRef, ...]:
    pool = unique_projects(projects)
    candidates = tuple(
        SelectorCandidate(
            item.key,
            item,
            (
                project_label(item, pool),
                item.display_name,
                item.raw_id,
                f"{item.agent}:{item.raw_id}",
            ),
            label=project_label(item, pool),
        )
        for item in pool
    )

    def expand_display_name(
        selector: str, exact: tuple[SelectorCandidate[ProjectRef], ...]
    ) -> tuple[SelectorCandidate[ProjectRef], ...]:
        display_matches = tuple(
            item for item in exact if item.value.display_name.casefold() == selector.casefold()
        )
        return display_matches or exact

    return resolve_selectors(
        selectors,
        candidates,
        dimension="project",
        expand_exact=expand_display_name,
    )
