from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal, TypeAlias
from unicodedata import normalize

from ccusage_viz.domain import ProjectRef
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors

ProjectAggregation: TypeAlias = Literal["name", "exact"]
ProjectLabelContext: TypeAlias = Literal[0, 1, 2]
PROJECT_AGGREGATIONS: tuple[ProjectAggregation, ...] = ("name", "exact")
ProjectGroupKey: TypeAlias = tuple[str, ...]

_GENERIC_PROJECT_NAMES = frozenset({"project", "unknown", "untitled"})
_SHORT_OPAQUE_LABELS: dict[tuple[str, str], str] = {}
_SHORT_OPAQUE_DEPTHS: dict[tuple[str, str], int] = {}


@dataclass(frozen=True, slots=True)
class _OpaqueLabelCandidate:
    label: str
    removal_depth: int
    cacheable: bool = False


@dataclass(frozen=True, slots=True)
class ExactProjectDisplayKey:
    """Monitor-only exact identity with a separately stored safe display label."""

    agent: str
    raw_id: str
    label: str = field(compare=False, hash=False)


@dataclass(frozen=True, slots=True)
class ProjectDisplayKey:
    """A Monitor display projection that leaves exact counter identity upstream."""

    key: ProjectGroupKey
    label: str = field(compare=False, hash=False)
    agent: str | None = field(default=None, compare=False, hash=False)


@dataclass(frozen=True, slots=True)
class ProjectGroup:
    """A display-only group of exact, agent-scoped project identities."""

    key: ProjectGroupKey
    label: str
    members: tuple[ProjectRef, ...]


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
    """Return a safe basename for a real path, never decode opaque identifiers."""
    value = raw_id.rstrip("/\\")
    if value and ("/" in value or "\\" in value):
        leaf = PurePath(value.replace("\\", "/")).name
        return leaf if _is_displayable_path_leaf(leaf) else "Project"
    return "Project"


def make_project_ref(agent: str, raw_id: str, display_name: str | None = None) -> ProjectRef:
    display = display_name or project_display_name(raw_id)
    if not _is_safe_display_name(display):
        display = project_display_name(display)
    return ProjectRef(agent, raw_id, display)


def _opaque_components(project: ProjectRef) -> tuple[str, ...] | None:
    if project.agent != "claude" or not project.raw_id.startswith("-"):
        return None
    components = tuple(
        normalize("NFC", part) for part in project.raw_id.strip("-").split("-") if part
    )
    return components or None


def _opaque_prefix_depths(
    projects: Iterable[ProjectRef],
) -> dict[tuple[str, str], tuple[int, ...]]:
    """Return every independently proved removable prefix depth per opaque ID.

    Components are opaque tokens. Prefixes are compared case-insensitively, but
    no token is interpreted as a path, namespace, or otherwise meaningful name.
    """
    component_by_key = {
        project.key: components
        for project in projects
        if (components := _opaque_components(project)) is not None
    }
    members_by_prefix: dict[tuple[str, ...], set[tuple[str, str]]] = {}
    for key, components in component_by_key.items():
        normalized = tuple(component.casefold() for component in components)
        for depth in range(1, len(normalized)):
            members_by_prefix.setdefault(normalized[:depth], set()).add(key)

    depths: dict[tuple[str, str], tuple[int, ...]] = {}
    for key, components in component_by_key.items():
        normalized = tuple(component.casefold() for component in components)
        eligible = tuple(
            depth
            for depth in range(1, len(normalized))
            if len(members := members_by_prefix[normalized[:depth]]) >= 2
            and all(len(component_by_key[member]) > depth for member in members)
        )
        if eligible:
            depths[key] = eligible
    return depths


def _opaque_label_candidates(
    project: ProjectRef,
    components: tuple[str, ...],
    depths: tuple[int, ...],
    context: ProjectLabelContext,
) -> tuple[_OpaqueLabelCandidate, ...]:
    """Return shortest-first labels backed by verified opaque-token removal."""
    candidates = [
        _OpaqueLabelCandidate(
            label,
            depth,
            cacheable=True,
        )
        for depth in reversed(depths)
        if _is_safe_display_name(label := "-".join(components[max(0, depth - context) :]))
    ]
    cached = _SHORT_OPAQUE_LABELS.get(project.key)
    cached_depth = _SHORT_OPAQUE_DEPTHS.get(project.key)
    if (
        cached is not None
        and cached_depth is not None
        and cached_depth > 0
        and cached == "-".join(components[cached_depth:])
    ):
        label = "-".join(components[max(0, cached_depth - context) :])
        if _is_safe_display_name(label):
            candidates.append(_OpaqueLabelCandidate(label, cached_depth, cacheable=True))
    return tuple(
        sorted(
            set(candidates),
            key=lambda item: (len(item.label), item.label.casefold(), -item.removal_depth),
        )
    )


def _display_label_key(value: str) -> str:
    return normalize("NFC", value).casefold()


def _resolve_opaque_label_collisions(
    candidates: dict[tuple[str, str], tuple[_OpaqueLabelCandidate, ...]],
    raw_ids: dict[tuple[str, str], str],
    occupied: set[str],
) -> dict[tuple[str, str], _OpaqueLabelCandidate]:
    """Choose the shortest verified opaque labels that do not collide."""
    positions = {key: 0 for key in candidates}
    labels = {
        key: values[0] if values else _OpaqueLabelCandidate(raw_ids[key], 0)
        for key, values in candidates.items()
    }
    while True:
        by_label: dict[str, list[tuple[str, str]]] = {}
        for key, candidate in labels.items():
            by_label.setdefault(_display_label_key(candidate.label), []).append(key)
        advanced = False
        for label, keys in sorted(by_label.items()):
            if label not in occupied and len(keys) == 1:
                continue
            for key in sorted(keys)[1 if label not in occupied else 0 :]:
                if positions[key] + 1 < len(candidates[key]):
                    positions[key] += 1
                    labels[key] = candidates[key][positions[key]]
                    advanced = True
        if not advanced:
            break

    for candidate in labels.values():
        occupied.add(_display_label_key(candidate.label))
    return labels


def project_display_names(
    projects: Iterable[ProjectRef],
    *,
    cache_shortened: bool = False,
    context: ProjectLabelContext = 0,
) -> dict[tuple[str, str], str]:
    """Return deterministic safe display bases for one complete project pool.

    Claude's hyphen-flattened identifiers are opaque. A common leading component
    sequence is therefore removable display-only context, never a reconstructed
    filesystem path or an identity/grouping key. Successfully shortened opaque
    labels remain available for the lifetime of the process when a later pool is
    too narrow to establish the same common prefix again.
    """
    pool = unique_projects(projects)
    opaque = tuple(
        sorted(
            (
                project
                for project in pool
                if _opaque_components(project) is not None and project.display_name == "Project"
            ),
            key=lambda item: item.key,
        )
    )
    depths = _opaque_prefix_depths(opaque)
    names: dict[tuple[str, str], str] = {}
    for project in pool:
        value = normalize("NFC", project.display_name).strip()
        if _is_safe_display_name(value) and value.casefold() not in _GENERIC_PROJECT_NAMES:
            names[project.key] = value

    opaque_candidates: dict[tuple[str, str], tuple[_OpaqueLabelCandidate, ...]] = {}
    raw_ids: dict[tuple[str, str], str] = {}
    for project in opaque:
        components = _opaque_components(project)
        assert components is not None
        raw_ids[project.key] = project.raw_id
        opaque_candidates[project.key] = (
            *_opaque_label_candidates(project, components, depths.get(project.key, ()), context),
            _OpaqueLabelCandidate(project.raw_id, 0),
        )

    opaque_labels = _resolve_opaque_label_collisions(
        opaque_candidates,
        raw_ids,
        {_display_label_key(label) for label in names.values()},
    )
    names.update({key: candidate.label for key, candidate in opaque_labels.items()})
    if cache_shortened and context == 0:
        for key, candidate in opaque_labels.items():
            if candidate.cacheable and candidate.removal_depth > 0:
                components = _opaque_components(
                    next(project for project in opaque if project.key == key)
                )
                assert components is not None
                short_label = "-".join(components[candidate.removal_depth :])
                cached = _SHORT_OPAQUE_LABELS.get(key)
                if cached is None or (len(short_label), short_label.casefold()) < (
                    len(cached),
                    cached.casefold(),
                ):
                    _SHORT_OPAQUE_LABELS[key] = short_label
                    _SHORT_OPAQUE_DEPTHS[key] = candidate.removal_depth

    unnamed = tuple(
        sorted((project for project in pool if project.key not in names), key=lambda item: item.key)
    )
    names.update({project.key: f"Project {index}" for index, project in enumerate(unnamed, 1)})
    return names


def next_project_label_context(context: ProjectLabelContext) -> ProjectLabelContext:
    """Return the next bounded opaque-label restore level."""
    if context == 0:
        return 1
    if context == 1:
        return 2
    return 0


def _clear_short_opaque_labels() -> None:
    """Clear process-local opaque display cache for isolated tests."""
    _SHORT_OPAQUE_LABELS.clear()
    _SHORT_OPAQUE_DEPTHS.clear()


def _display_names(projects: tuple[ProjectRef, ...]) -> dict[tuple[str, str], str]:
    """Backward-compatible internal name for the common display projection."""
    return project_display_names(projects)


def _same_display_name(left: str, right: str) -> bool:
    return normalize("NFC", left).casefold() == normalize("NFC", right).casefold()


def exact_project_label(
    project: ProjectRef,
    projects: Iterable[ProjectRef],
    *,
    labels: dict[tuple[str, str], str] | None = None,
    context: ProjectLabelContext = 0,
) -> str:
    """Return an exact-project label; the agent is displayed separately."""
    pool = unique_projects(projects)
    names = labels or project_display_names(pool, context=context)
    display_name = names[project.key]
    same_agent = tuple(
        item
        for item in sorted(pool, key=lambda item: item.key)
        if item.agent == project.agent and _same_display_name(names[item.key], display_name)
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


def project_display_keys(
    projects: Iterable[ExactProjectDisplayKey],
    aggregation: ProjectAggregation = "name",
    *,
    context: ProjectLabelContext = 0,
) -> dict[ExactProjectDisplayKey, ProjectDisplayKey]:
    """Project Monitor's exact keys into presentation-only project groups."""
    exact = tuple(projects)
    refs = tuple(
        make_project_ref(item.agent, item.raw_id)
        if item.agent == "claude" and item.raw_id.startswith("-") and item.label == "Project"
        else ProjectRef(item.agent, item.raw_id, item.label)
        for item in exact
    )
    groups = project_groups(refs, aggregation, context=context)
    return {
        item: ProjectDisplayKey(
            groups[item.agent, item.raw_id].key,
            groups[item.agent, item.raw_id].label,
            item.agent if aggregation == "exact" else None,
        )
        for item in exact
    }


def project_label(project: ProjectRef, projects: Iterable[ProjectRef]) -> str:
    """Return a deterministic, recognizable, presentation-safe selector label."""
    pool = unique_projects(projects)
    names = _display_names(pool)
    opaque = tuple(item for item in pool if _opaque_components(item) is not None)
    names.update(project_display_names(opaque))
    display_name = names[project.key]
    peers = tuple(item for item in pool if _same_display_name(names[item.key], display_name))
    if len(peers) <= 1:
        return display_name
    same_agent = tuple(
        item for item in sorted(peers, key=lambda item: item.key) if item.agent == project.agent
    )
    if len(same_agent) == 1:
        return f"{display_name} ({project.agent})"
    return f"{display_name} ({project.agent} {same_agent.index(project) + 1})"


def merged_project_label(
    members: Iterable[ProjectRef],
    projects: Iterable[ProjectRef] | None = None,
    *,
    labels: dict[tuple[str, str], str] | None = None,
    context: ProjectLabelContext = 0,
) -> str:
    """Return a stable safe label without influencing project pairing evidence."""
    members = tuple(members)
    names = labels or project_display_names(
        unique_projects(projects if projects is not None else members), context=context
    )
    values = tuple(names[member.key] for member in members)
    proven = tuple(
        names[member.key]
        for member in members
        if _opaque_components(member) is None or names[member.key] != member.raw_id
    )
    return min(
        proven or values,
        key=lambda value: (normalize("NFC", value).casefold(), normalize("NFC", value)),
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
    projects: Iterable[ProjectRef],
    aggregation: ProjectAggregation = "name",
    *,
    cache_shortened: bool = False,
    context: ProjectLabelContext = 0,
) -> dict[tuple[str, str], ProjectGroup]:
    """Index exact projects into stable projection groups.

    Name groups pair only unambiguous Claude/Codex source projects. Parent-path
    aliases are comparison keys only; exact upstream identities remain intact.
    """
    pool = unique_projects(projects)
    labels = project_display_names(pool, cache_shortened=cache_shortened, context=context)
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
            label = merged_project_label(ordered, pool, labels=labels)
        else:
            label = exact_project_label(ordered[0], pool, labels=labels)
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
            (project_label(item, pool),),
            label=project_label(item, pool),
        )
        for item in pool
    )
    return resolve_selectors(selectors, candidates, dimension="project")
