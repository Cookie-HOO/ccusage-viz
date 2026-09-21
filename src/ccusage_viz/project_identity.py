from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal, TypeAlias
from unicodedata import normalize

from ccusage_viz.domain import ProjectRef
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors

ProjectAggregation: TypeAlias = Literal["name", "exact"]
PROJECT_AGGREGATIONS: tuple[ProjectAggregation, ...] = ("name", "exact")
ProjectGroupKey: TypeAlias = tuple[str, ...]

_OPAQUE_PATH_MARKERS = frozenset(
    {"project", "projects", "repo", "repos", "workspace", "workspaces", "src"}
)
_HOME_PATH_PREFIX = ("users",)
_GENERIC_PROJECT_NAMES = frozenset({"project", "unknown", "untitled"})


@dataclass(frozen=True, slots=True)
class ExactProjectDisplayKey:
    """Monitor-only exact identity with a separately stored safe display label."""

    agent: str
    raw_id: str
    label: str = field(compare=False, hash=False)


@dataclass(frozen=True, slots=True)
class ProjectGroup:
    """A display-only group of exact, agent-scoped project identities."""

    key: ProjectGroupKey
    label: str
    members: tuple[ProjectRef, ...]


def _opaque_project_name(raw_id: str) -> str | None:
    """Extract a project leaf from ccusage's path-encoded opaque identifiers."""
    if not raw_id.startswith("-"):
        return None
    parts = tuple(part for part in raw_id.strip("-").split("-") if part)
    if tuple(part.casefold() for part in parts[:1]) == _HOME_PATH_PREFIX and len(parts) == 2:
        return parts[-1] if _is_safe_display_name(parts[-1]) else None
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


def _is_displayable_path_leaf(value: str) -> bool:
    """Reject short numeric directory leaves that do not identify a project."""
    return _is_safe_display_name(value) and not (value.isdecimal() and len(value) <= 4)


def normalized_project_leaf(project: ProjectRef) -> str | None:
    """Return a projection-only key for a safe, non-generic display leaf.

    This deliberately does not decode opaque path representations or alter the
    upstream ``ProjectRef.key`` identity.
    """
    value = normalize("NFC", project.display_name).strip()
    if not _is_safe_display_name(value) or value.casefold() in _GENERIC_PROJECT_NAMES:
        return None
    return value.casefold()


def project_display_name(raw_id: str) -> str:
    """Return a safe project basename or recognized opaque project leaf."""
    value = raw_id.rstrip("/\\")
    if value and ("/" in value or "\\" in value):
        leaf = PurePath(value.replace("\\", "/")).name
        return leaf if _is_displayable_path_leaf(leaf) else "Project"
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


def exact_project_label(project: ProjectRef, projects: Iterable[ProjectRef]) -> str:
    """Return an exact-project label; the agent is displayed separately."""
    pool = unique_projects(projects)
    names = _display_names(pool)
    display_name = names[project.key]
    same_agent = tuple(
        item for item in pool if item.agent == project.agent and names[item.key] == display_name
    )
    if len(same_agent) <= 1:
        return display_name
    return f"{display_name} {same_agent.index(project) + 1}"


def exact_project_display_key(
    project: ProjectRef, projects: Iterable[ProjectRef]
) -> ExactProjectDisplayKey:
    """Return Monitor's exact identity with its safe project display label."""
    return ExactProjectDisplayKey(
        project.agent, project.raw_id, exact_project_label(project, projects)
    )


def exact_project_agent(key: object) -> str | None:
    """Return the agent from a Historical or Monitor exact-project key."""
    if isinstance(key, ExactProjectDisplayKey):
        return key.agent
    if (
        isinstance(key, tuple)
        and len(key) == 4
        and key[:2] == ("project", "exact")
        and isinstance(key[2], str)
    ):
        return key[2]
    return None


def exact_project_display_label(key: ExactProjectDisplayKey) -> str:
    """Format a Monitor exact-project key for compatible serialized data."""
    return f"{key.agent} · {key.label}"


def project_label(project: ProjectRef, projects: Iterable[ProjectRef]) -> str:
    """Return a deterministic, recognizable, presentation-safe selector label."""
    pool = unique_projects(projects)
    names = _display_names(pool)
    display_name = names[project.key]
    peers = tuple(item for item in pool if names[item.key] == display_name)
    if len(peers) <= 1:
        return display_name
    same_agent = tuple(item for item in peers if item.agent == project.agent)
    if len(same_agent) == 1:
        return f"{display_name} ({project.agent})"
    return f"{display_name} ({project.agent} {same_agent.index(project) + 1})"


def merged_project_label(members: Iterable[ProjectRef]) -> str:
    """Return a stable, safe display label for a same-name project group."""
    return min(
        (normalize("NFC", member.display_name).strip() for member in members),
        key=lambda value: (value.casefold(), value),
    )


def _path_suffix_parts(raw_id: str) -> tuple[tuple[str, ...], ...]:
    normalized = normalize("NFC", raw_id).replace("\\", "/").strip("/")
    parts = tuple(part.casefold() for part in normalized.split("/") if part)
    return tuple(parts[index:] for index in range(len(parts) - 1, -1, -1))


def _path_suffix_aliases(raw_id: str) -> tuple[str, ...]:
    return tuple("-".join(parts) for parts in _path_suffix_parts(raw_id))


def _codex_suffix_aliases(project: ProjectRef) -> tuple[str, ...]:
    if project.agent != "codex" or "/" not in project.raw_id and "\\" not in project.raw_id:
        return ()
    return _path_suffix_aliases(project.raw_id)


def _claude_suffix_aliases(project: ProjectRef) -> tuple[str, ...]:
    if project.agent != "claude" or not project.raw_id.startswith("-"):
        return ()
    parts = tuple(
        part.casefold() for part in normalize("NFC", project.raw_id).strip("-").split("-") if part
    )
    return tuple("-".join(parts[index:]) for index in range(len(parts) - 1, -1, -1))


def _claude_codex_pairs(pool: tuple[ProjectRef, ...]) -> dict[tuple[str, str], str]:
    """Return conservative one-to-one Claude/Codex display-group aliases."""
    codex = tuple(project for project in pool if project.agent == "codex")
    alias_counts: dict[str, int] = {}
    aliases_by_codex: dict[tuple[str, str], tuple[str, ...]] = {}
    paths_by_alias: dict[str, set[tuple[str, ...]]] = {}
    for project in codex:
        aliases = _codex_suffix_aliases(project)
        aliases_by_codex[project.key] = aliases
        if aliases:
            for alias, parts in zip(aliases, _path_suffix_parts(project.raw_id), strict=True):
                alias_counts[alias] = alias_counts.get(alias, 0) + 1
                paths_by_alias.setdefault(alias, set()).add(parts)

    selected: dict[str, ProjectRef] = {}
    for project in codex:
        alias = next(
            (
                item
                for item in aliases_by_codex[project.key]
                if alias_counts[item] == 1 and len(paths_by_alias[item]) == 1
            ),
            None,
        )
        if alias is not None:
            selected[alias] = project

    ambiguous_aliases = {alias for alias, paths in paths_by_alias.items() if len(paths) > 1}
    matches_by_claude: dict[tuple[str, str], tuple[str, ...]] = {}
    claudes_by_alias: dict[str, list[ProjectRef]] = {}
    for project in pool:
        if project.agent != "claude":
            continue
        aliases = _claude_suffix_aliases(project)
        if any(alias in ambiguous_aliases for alias in aliases):
            continue
        matches = tuple(alias for alias in aliases if alias in selected)
        if len(matches) == 1:
            matches_by_claude[project.key] = matches
            claudes_by_alias.setdefault(matches[0], []).append(project)

    pairs: dict[tuple[str, str], str] = {}
    for claude_key, (alias,) in matches_by_claude.items():
        claudes = claudes_by_alias[alias]
        if len(claudes) == 1:
            pairs[claude_key] = alias
            pairs[selected[alias].key] = alias
    return pairs


def project_groups(
    projects: Iterable[ProjectRef], aggregation: ProjectAggregation = "name"
) -> dict[tuple[str, str], ProjectGroup]:
    """Index exact projects into stable projection groups.

    Name groups pair only unambiguous Claude/Codex source projects. Parent-path
    aliases are comparison keys only; exact upstream identities remain intact.
    """
    pool = unique_projects(projects)
    pair_aliases = _claude_codex_pairs(pool) if aggregation == "name" else {}
    grouped: dict[ProjectGroupKey, list[ProjectRef]] = {}
    for project in pool:
        alias = pair_aliases.get(project.key)
        key = (
            ("project", "name", alias)
            if alias is not None
            else ("project", "exact", project.agent, project.raw_id)
        )
        grouped.setdefault(key, []).append(project)

    result: dict[tuple[str, str], ProjectGroup] = {}
    for key, members in grouped.items():
        ordered = tuple(sorted(members, key=lambda item: item.key))
        if key[1] == "name":
            label = merged_project_label(ordered)
        else:
            label = exact_project_label(ordered[0], pool)
        group = ProjectGroup(key, label, ordered)
        for member in ordered:
            result[member.key] = group
    return result


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
