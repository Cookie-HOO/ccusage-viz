from datetime import date

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.processing.projection import build_ranking
from ccusage_viz.project_identity import (
    _clear_short_opaque_labels,
    exact_project_display_key,
    exact_project_display_label,
    exact_project_label,
    make_project_ref,
    merged_project_label,
    project_display_names,
    project_groups,
    project_label,
    resolve_projects,
    unique_projects,
)


def _ranking_records(*projects: ProjectRef) -> tuple[UsageRecord, ...]:
    return tuple(
        UsageRecord(
            date(2026, 1, 1),
            project.agent,
            TokenUsage.from_parts(
                total=index,
                input=index,
                output=0,
                cache_read=0,
                cache_creation=0,
            ),
            SourceKind.CLAUDE_DAILY_PROJECTS,
            project,
        )
        for index, project in enumerate(projects, 1)
    )


def _populate_ranking_label_cache(*projects: ProjectRef, top: int | None = None) -> None:
    build_ranking(
        _ranking_records(*projects),
        DateRange(date(2026, 1, 1), date(2026, 1, 1), None),
        by="project",
        top=top,
    )


def test_project_identity_is_agent_scoped() -> None:
    claude = make_project_ref("claude", "/work/app")
    codex = make_project_ref("codex", "/work/app")
    assert claude.key != codex.key


def test_opaque_claude_labels_strip_only_dynamically_shared_prefix() -> None:
    projects = (
        make_project_ref("claude", "-Users-me-Projects-my-app"),
        make_project_ref("claude", "-Users-me-Projects-other-app"),
    )

    assert all(project.display_name == "Project" for project in projects)
    assert project_display_names(projects) == {
        projects[0].key: "my-app",
        projects[1].key: "other-app",
    }
    assert project_label(projects[0], projects) == "my-app"
    assert project_label(projects[1], projects) == "other-app"


def test_shortened_opaque_labels_are_reused_from_process_cache() -> None:
    _clear_short_opaque_labels()
    first, second = (
        make_project_ref("claude", "-Users-me-Projects-first"),
        make_project_ref("claude", "-Users-me-Projects-second"),
    )

    _populate_ranking_label_cache(first, second)

    assert project_display_names((first,))[first.key] == "first"

    _clear_short_opaque_labels()
    assert project_display_names((first,))[first.key] == "-Users-me-Projects-first"


def test_ranking_cache_uses_the_complete_pool_before_top_selection() -> None:
    _clear_short_opaque_labels()
    first, second = (
        make_project_ref("claude", "-Users-me-Projects-first"),
        make_project_ref("claude", "-Users-me-Projects-second"),
    )

    _populate_ranking_label_cache(first, second, top=1)

    assert project_display_names((second,))[second.key] == "second"


def test_process_cache_keeps_the_shortest_verified_opaque_label() -> None:
    _clear_short_opaque_labels()
    project = make_project_ref("claude", "-Users-me-Projects-work-app")

    _populate_ranking_label_cache(project, make_project_ref("claude", "-Users-me-Projects-other"))
    assert project_display_names((project,))[project.key] == "work-app"

    _populate_ranking_label_cache(
        project, make_project_ref("claude", "-Users-me-Projects-work-tool")
    )
    assert project_display_names((project,))[project.key] == "app"
    assert project_display_names((project,))[project.key] == "app"


def test_opaque_claude_labels_use_deepest_verified_prefix_per_branch() -> None:
    projects = (
        make_project_ref("claude", "-Users-bytedance-Projects-py-ccusage-viz"),
        make_project_ref("claude", "-Users-bytedance-Projects-py-bytedumpflow"),
        make_project_ref("claude", "-Users-bytedance-Projects-py-cmp-xlsx"),
        make_project_ref("claude", "-Users-bytedance-Projects-my-ai"),
        make_project_ref("claude", "-Users-bytedance-Projects-my-ai-tools-custom-proxy"),
        make_project_ref("claude", "-Users-bytedance-Projects-my-tauri-dumpflow-desktop"),
        make_project_ref("claude", "-Users-bytedance-Projects-rust-ccuv-collector"),
        make_project_ref("claude", "-Users-bytedance-Downloads-scratch"),
    )

    assert project_display_names(projects) == {
        projects[0].key: "ccusage-viz",
        projects[1].key: "bytedumpflow",
        projects[2].key: "cmp-xlsx",
        projects[3].key: "ai",
        projects[4].key: "ai-tools-custom-proxy",
        projects[5].key: "tauri-dumpflow-desktop",
        projects[6].key: "rust-ccuv-collector",
        projects[7].key: "Downloads-scratch",
    }


def test_opaque_claude_labels_use_prefixes_from_independent_families() -> None:
    projects = (
        make_project_ref("claude", "-Users-me-Projects-first"),
        make_project_ref("claude", "-Users-me-Projects-second"),
        make_project_ref("claude", "-gsw-dd0c4ac3a7004796005958e66b"),
        make_project_ref("claude", "-gsw-a3f0ed1d13ec4e7c992a6a23b"),
    )

    assert project_display_names(projects) == {
        projects[0].key: "first",
        projects[1].key: "second",
        projects[2].key: "dd0c4ac3a7004796005958e66b",
        projects[3].key: "a3f0ed1d13ec4e7c992a6a23b",
    }


def test_opaque_claude_labels_without_shared_prefix_use_safe_aliases() -> None:
    projects = (
        make_project_ref("claude", "-Users-bytedance"),
        make_project_ref("claude", "-Workspace-other"),
    )

    assert project_display_names(projects) == {
        projects[0].key: "-Users-bytedance",
        projects[1].key: "-Workspace-other",
    }
    assert project_label(projects[0], projects) == "-Users-bytedance"
    assert project_label(projects[1], projects) == "-Workspace-other"


def test_opaque_claude_labels_are_pool_order_independent_and_preserve_identity() -> None:
    projects = (
        make_project_ref("claude", "-Users-me-Projects-Café"),
        make_project_ref("claude", "-users-me-projects-Café"),
        make_project_ref("claude", "-Users-me-Projects-tools"),
    )

    forward = project_display_names(projects)
    reverse = project_display_names(tuple(reversed(projects)))

    assert forward == reverse
    assert forward[projects[0].key] == "Café"
    assert forward[projects[1].key] == "projects-Café"
    assert forward[projects[2].key] == "tools"
    assert projects[0].key == ("claude", "-Users-me-Projects-Café")


def test_opaque_claude_labels_back_off_before_empty_suffixes() -> None:
    projects = (
        make_project_ref("claude", "-Users-me-Projects"),
        make_project_ref("claude", "-Users-me-Projects-app"),
    )

    assert project_display_names(projects) == {
        projects[0].key: "Projects",
        projects[1].key: "Projects-app",
    }


def test_dumpflow_workspace_ids_remove_only_the_proven_shared_prefix() -> None:
    projects = (
        make_project_ref("claude", "-gsw-dd0c4ac3a7004796005958e66b"),
        make_project_ref("claude", "-gsw-a3f0ed1d13ec4e7c992a6a23b"),
    )

    labels = project_display_names(projects)

    assert labels == {
        projects[0].key: "dd0c4ac3a7004796005958e66b",
        projects[1].key: "a3f0ed1d13ec4e7c992a6a23b",
    }
    assert all("gsw" not in label.casefold() for label in labels.values())


def test_opaque_claude_labels_never_accept_raw_identifier_selector() -> None:
    projects = (
        make_project_ref("claude", "-Users-me-Projects-first"),
        make_project_ref("claude", "-Users-me-Projects-second"),
    )

    assert resolve_projects(("FIRST",), projects) == (projects[0],)
    with pytest.raises(UsageError):
        resolve_projects((projects[0].raw_id,), projects)


def test_dynamic_display_names_do_not_change_claude_codex_pairing() -> None:
    claude = make_project_ref("claude", "-Users-me-Projects-app")
    other = make_project_ref("claude", "-Users-me-Projects-tool")
    codex = make_project_ref("codex", "/work/app")

    groups = project_groups((claude, other, codex), "name")

    assert project_label(claude, (claude, other, codex)) == "app (claude)"
    assert groups[claude.key] is groups[codex.key]
    assert groups[claude.key].key == ("project", "name", "app")
    assert groups[other.key].key == ("project", "exact", "claude", other.raw_id)


def test_unrecognized_opaque_id_uses_a_collection_scoped_alias() -> None:
    projects = (
        make_project_ref("claude", "opaque-one"),
        make_project_ref("claude", "opaque-two"),
    )

    assert project_label(projects[0], projects) == "Project 1"
    assert project_label(projects[1], projects) == "Project 2"


def test_numeric_path_leaves_use_collection_scoped_aliases_without_name_aggregation() -> None:
    projects = (
        make_project_ref("codex", "/workspace/04"),
        make_project_ref("codex", "/workspace/12"),
    )

    assert project_label(projects[0], projects) == "Project 1"
    assert project_label(projects[1], projects) == "Project 2"
    groups = project_groups(projects, "name")
    assert groups[projects[0].key].key == ("project", "exact", "codex", "/workspace/04")
    assert groups[projects[1].key].key == ("project", "exact", "codex", "/workspace/12")


def test_same_display_name_requires_a_safe_disambiguated_label() -> None:
    projects = (
        make_project_ref("claude", "/work/a/app", "app"),
        make_project_ref("codex", "/work/b/app", "app"),
        make_project_ref("claude", "/work/tool", "tool"),
    )
    assert resolve_projects(("APP (CLAUDE)",), projects) == (projects[0],)
    assert resolve_projects(("app (codex)",), projects) == (projects[1],)
    assert project_label(projects[0], projects) == "app (claude)"
    assert project_label(projects[1], projects) == "app (codex)"


def test_same_agent_project_names_use_safe_ordinals_without_raw_ids() -> None:
    projects = (
        make_project_ref("claude", "/private/one/app", "app"),
        make_project_ref("claude", "/private/two/app", "app"),
    )

    assert project_label(projects[0], projects) == "app (claude 1)"
    assert project_label(projects[1], projects) == "app (claude 2)"
    assert exact_project_label(projects[0], projects) == "app 1"
    assert exact_project_label(projects[1], projects) == "app 2"
    first = exact_project_display_key(projects[0], projects)
    second = exact_project_display_key(projects[1], projects)
    assert first.agent == second.agent == "claude"
    assert first.label == "app 1"
    assert second.label == "app 2"
    assert exact_project_display_label(first) == "claude · app 1"
    assert exact_project_display_label(second) == "claude · app 2"
    assert "/private" not in exact_project_display_label(first)


def test_cwd_derived_codex_identity_uses_existing_aggregation_rules() -> None:
    claude = make_project_ref("claude", "-home-me-projects-app")
    codex = make_project_ref("codex", "/private/work/app")

    named = project_groups((claude, codex), "name")
    exact = project_groups((claude, codex), "exact")

    assert named[claude.key] is named[codex.key]
    assert exact[claude.key] is not exact[codex.key]
    assert exact[codex.key].key == ("project", "exact", "codex", "/private/work/app")


def test_name_aggregation_disambiguates_codex_duplicate_basename_with_parents() -> None:
    claude = make_project_ref("claude", "-a-b-c-e")
    matching_codex = make_project_ref("codex", "/a/b/c/e")
    other_codex = make_project_ref("codex", "/a/b/d/e")

    groups = project_groups((claude, matching_codex, other_codex), "name")

    assert groups[claude.key] is groups[matching_codex.key]
    assert groups[claude.key].key == ("project", "name", "c-e")
    assert groups[other_codex.key].key == ("project", "exact", "codex", "/a/b/d/e")


def test_name_aggregation_never_merges_within_an_agent() -> None:
    claude = make_project_ref("claude", "-a-b-c-e")
    first_codex = make_project_ref("codex", "/a/b/c/e")
    second_codex = make_project_ref("codex", "/a/b/d/e")
    second_claude = make_project_ref("claude", "-a-b-d-e")

    groups = project_groups((claude, first_codex, second_codex, second_claude), "name")

    assert groups[claude.key].key == ("project", "name", "c-e")
    assert groups[second_claude.key].key == ("project", "name", "d-e")
    assert groups[first_codex.key] is not groups[second_codex.key]


def test_name_pairing_is_independent_of_input_order() -> None:
    projects = (
        make_project_ref("claude", "-a-b-c-e"),
        make_project_ref("codex", "/a/b/c/e"),
        make_project_ref("codex", "/a/b/d/e"),
    )

    forward = project_groups(projects, "name")
    reverse = project_groups(tuple(reversed(projects)), "name")

    assert {key: group.key for key, group in forward.items()} == {
        key: group.key for key, group in reverse.items()
    }


def test_name_aggregation_rejects_multiple_claude_matches_for_one_alias() -> None:
    first = make_project_ref("claude", "-a-b-app")
    second = make_project_ref("claude", "-x-y-app")
    codex = make_project_ref("codex", "/work/app")

    groups = project_groups((first, second, codex), "name")

    assert groups[first.key].key == ("project", "exact", "claude", first.raw_id)
    assert groups[second.key].key == ("project", "exact", "claude", second.raw_id)
    assert groups[codex.key].key == ("project", "exact", "codex", codex.raw_id)


def test_name_aggregation_rejects_claude_match_for_multiple_codex_aliases() -> None:
    claude = make_project_ref("claude", "-a-b-c-e")
    first = make_project_ref("codex", "/a-b-c-e")
    second = make_project_ref("codex", "/b-c-e")

    groups = project_groups((claude, first, second), "name")

    assert groups[claude.key].key == ("project", "exact", "claude", claude.raw_id)
    assert groups[first.key].key == ("project", "exact", "codex", first.raw_id)
    assert groups[second.key].key == ("project", "exact", "codex", second.raw_id)


def test_name_aggregation_rejects_hyphen_flattening_collisions() -> None:
    claude = make_project_ref("claude", "-x-c-e")
    nested = make_project_ref("codex", "/x/c/e")
    hyphenated = make_project_ref("codex", "/x/c-e")

    groups = project_groups((claude, nested, hyphenated), "name")

    assert groups[claude.key].key == ("project", "exact", "claude", claude.raw_id)
    assert groups[nested.key].key == ("project", "exact", "codex", nested.raw_id)
    assert groups[hyphenated.key].key == ("project", "exact", "codex", hyphenated.raw_id)


def test_name_aggregation_normalizes_windows_codex_paths() -> None:
    claude = make_project_ref("claude", "-a-b-c-e")
    codex = make_project_ref("codex", r"C:\\a\\b\\c\\e")
    other = make_project_ref("codex", r"D:\\a\\b\\d\\e")

    groups = project_groups((claude, codex, other), "name")

    assert groups[claude.key] is groups[codex.key]
    assert groups[claude.key].key == ("project", "name", "c-e")
    assert groups[other.key].key == ("project", "exact", "codex", other.raw_id)


def test_name_aggregation_leaves_other_agents_exact() -> None:
    claude = make_project_ref("claude", "-home-me-projects-app")
    codex = make_project_ref("codex", "/work/app")
    other = make_project_ref("other", "/work/app")

    groups = project_groups((claude, codex, other), "name")

    assert groups[claude.key] is groups[codex.key]
    assert groups[other.key].key == ("project", "exact", "other", "/work/app")


def test_name_aggregation_only_merges_one_exact_project_from_each_agent() -> None:
    claude = make_project_ref("claude", "-home-me-projects-app")
    codex = make_project_ref("codex", "/work/app")
    duplicate = make_project_ref("codex", "/archive/app")

    merged = project_groups((claude, codex), "name")
    assert merged[claude.key].key == ("project", "name", "app")
    assert merged[claude.key] is merged[codex.key]

    ambiguous = project_groups((claude, codex, duplicate), "name")
    assert ambiguous[claude.key].key == ("project", "exact", "claude", claude.raw_id)
    assert ambiguous[codex.key].key == ("project", "exact", "codex", codex.raw_id)
    assert ambiguous[duplicate.key].key == ("project", "exact", "codex", duplicate.raw_id)


def test_name_aggregation_label_is_stable_across_member_order_and_spelling() -> None:
    claude = make_project_ref("claude", "-home-me-projects-app", "APP")
    codex = make_project_ref("codex", "/work/app", "App")

    assert merged_project_label((claude, codex)) == "APP"
    assert merged_project_label((codex, claude)) == "APP"
    assert project_groups((codex, claude), "name")[claude.key].label == "APP"


def test_exact_projects_keep_agent_out_of_labels() -> None:
    projects = (
        make_project_ref("claude", "-home-me-projects-app"),
        make_project_ref("codex", "/work/app"),
    )
    groups = project_groups(projects, "exact")
    assert groups[projects[0].key].label == "-home-me-projects-app"
    assert groups[projects[1].key].label == "app"


def test_projects_deduplicate_by_agent_and_raw_id() -> None:
    projects = (
        make_project_ref("codex", "/home/example/projects/project-a", "first"),
        make_project_ref("codex", "/home/example/projects/project-a", "second"),
    )
    assert unique_projects(projects) == projects[:1]
