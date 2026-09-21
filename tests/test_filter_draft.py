from ccusage_viz.domain import ModelBreakdown, ProjectRef, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.filter_draft import (
    FilterChoices,
    FilterDraft,
    discover_filter_choices,
    run_filter_editor,
)
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import Filters


def _usage(total: int) -> TokenUsage:
    return TokenUsage.from_parts(
        total=total,
        input=total,
        output=0,
        cache_read=0,
        cache_creation=0,
    )


def test_filter_choices_use_normalized_facts_and_keep_selected_values() -> None:
    records = (
        UsageRecord(
            None,
            "Claude Code",
            _usage(10),
            SourceKind.CLAUDE_DAILY_PROJECTS,
            ProjectRef("Claude Code", "/safe/a/app", "app"),
            (ModelBreakdown("sonnet", _usage(10)),),
        ),
        UsageRecord(
            None,
            "Codex",
            _usage(20),
            SourceKind.CODEX_SESSIONS,
            ProjectRef("Codex", "/safe/b/app", "app"),
            (ModelBreakdown("gpt", _usage(20)),),
        ),
    )

    choices = discover_filter_choices(
        records,
        Filters(agents=("Missing",), models=("startup",), projects=("private",)),
    )

    assert choices.agents == ("Claude Code", "Codex", "Missing")
    assert choices.models == ("gpt", "sonnet", "startup")
    assert choices.projects == ("app (Claude Code)", "app (Codex)", "private")
    assert choices.unavailable == frozenset()


def test_model_choices_and_toggles_ignore_casing() -> None:
    records = (
        UsageRecord(
            None,
            "Claude Code",
            _usage(30),
            SourceKind.UNIFIED_DAILY,
            models=(
                ModelBreakdown("GPT-5.6-Luna", _usage(10)),
                ModelBreakdown("gpt-5.6-luna", _usage(20)),
            ),
        ),
    )

    choices = discover_filter_choices(records, Filters(models=("GPT-5.6-Luna",)))
    draft = FilterDraft(Filters(models=("GPT-5.6-Luna",)))

    assert choices.models == ("gpt-5.6-luna",)
    assert draft.contains("model", "gpt-5.6-luna")
    assert draft.toggle("model", "gpt-5.6-luna").filters.models == ()


def test_unavailable_project_dimension_keeps_only_existing_selection() -> None:
    records = (UsageRecord(None, "Claude Code", _usage(10), SourceKind.UNIFIED_DAILY),)

    choices = discover_filter_choices(
        records,
        Filters(projects=("startup-project",)),
        include_projects=False,
    )

    assert choices.projects == ("startup-project",)
    assert not choices.is_available("project")


def test_filter_draft_toggles_without_mutating_original_filters() -> None:
    original = Filters(agents=("Claude Code",), models=("sonnet",))
    draft = FilterDraft(original)

    added = draft.toggle("agent", "Codex")
    removed = added.toggle("model", "sonnet")

    assert original == Filters(agents=("Claude Code",), models=("sonnet",))
    assert added.filters.agents == ("Claude Code", "Codex")
    assert removed.filters.models == ()


def test_filter_editor_navigates_toggles_and_commits_complete_draft() -> None:
    keys = iter(("j", " ", "l", " ", "\n"))
    frames: list[tuple[str, str]] = []

    result = run_filter_editor(
        Filters(agents=("Claude Code",)),
        FilterChoices(
            agents=("Claude Code", "Codex"),
            models=("sonnet",),
        ),
        load_translator("en"),
        width=40,
        paint=lambda body, controls: frames.append((body, controls)),
        read_key=lambda: next(keys),
    )

    assert result == Filters(agents=("Claude Code", "Codex"), models=("sonnet",))
    assert "[Agent] · Model · Project" in frames[0][0]
    assert "Space toggle" in frames[0][1]
    assert "Agent · [Model] · Project" in frames[-1][0]


def test_filter_editor_escape_discards_draft() -> None:
    keys = iter((" ", "\x1b"))

    result = run_filter_editor(
        Filters(),
        FilterChoices(agents=("Claude Code",)),
        load_translator("en"),
        width=40,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(keys),
    )

    assert result is None


def test_filter_editor_renders_unavailable_dimension() -> None:
    keys = iter(("\n",))
    frames: list[str] = []

    run_filter_editor(
        Filters(),
        FilterChoices(unavailable=frozenset({"agent", "model", "project"})),
        load_translator("en"),
        width=40,
        paint=lambda body, _controls: frames.append(body),
        read_key=lambda: next(keys),
    )

    assert "No discoverable values" in frames[0]


def test_selected_only_values_are_visible_but_dimension_remains_unavailable() -> None:
    choices = discover_filter_choices((), Filters(models=("startup",)))
    keys = iter(("l", "\n"))
    frames: list[str] = []

    run_filter_editor(
        Filters(models=("startup",)),
        choices,
        load_translator("en"),
        width=40,
        paint=lambda body, _controls: frames.append(body),
        read_key=lambda: next(keys),
    )

    assert not choices.is_available("model")
    assert "No discoverable values" in frames[-1]
    assert "[x] startup" in frames[-1]
