from ccusage_viz.project_identity import (
    exact_project_display_key,
    exact_project_display_label,
    exact_project_label,
    make_project_ref,
    merged_project_label,
    project_groups,
    project_label,
    resolve_projects,
    unique_projects,
)


def test_project_identity_is_agent_scoped() -> None:
    claude = make_project_ref("claude", "/work/app")
    codex = make_project_ref("codex", "/work/app")
    assert claude.key != codex.key


def test_opaque_claude_identity_uses_its_safe_project_leaf() -> None:
    project = make_project_ref("claude", "-home-example-projects-my-app")
    assert project.display_name == "my-app"
    assert "home" not in project.display_name
    assert "projects" not in project.display_name


def test_home_directory_opaque_id_uses_the_home_directory_name() -> None:
    project = make_project_ref("claude", "-Users-bytedance")

    assert project.display_name == "bytedance"


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


def test_same_exact_display_name_expands_across_agents() -> None:
    projects = (
        make_project_ref("claude", "/work/a/app", "app"),
        make_project_ref("codex", "/work/b/app", "app"),
        make_project_ref("claude", "/work/tool", "tool"),
    )
    assert resolve_projects(("APP",), projects) == projects[:2]
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
    assert groups[projects[0].key].label == "app"
    assert groups[projects[1].key].label == "app"


def test_projects_deduplicate_by_agent_and_raw_id() -> None:
    projects = (
        make_project_ref("codex", "/home/example/projects/project-a", "first"),
        make_project_ref("codex", "/home/example/projects/project-a", "second"),
    )
    assert unique_projects(projects) == projects[:1]
