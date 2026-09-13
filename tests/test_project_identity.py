from ccusage_viz.project_identity import (
    make_project_ref,
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


def test_unrecognized_opaque_id_uses_a_collection_scoped_alias() -> None:
    projects = (
        make_project_ref("claude", "opaque-one"),
        make_project_ref("claude", "opaque-two"),
    )

    assert project_label(projects[0], projects) == "Project 1"
    assert project_label(projects[1], projects) == "Project 2"


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


def test_projects_deduplicate_by_agent_and_raw_id() -> None:
    projects = (
        make_project_ref("codex", "/home/example/projects/project-a", "first"),
        make_project_ref("codex", "/home/example/projects/project-a", "second"),
    )
    assert unique_projects(projects) == projects[:1]
