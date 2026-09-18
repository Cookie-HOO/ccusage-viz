from datetime import date

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.domain import ModelBreakdown, SourceKind, TokenUsage, UsageRecord
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.project_identity import make_project_ref, resolve_projects
from ccusage_viz.transform import build_timeline, filter_records


def _record(day: int, agent: str, project: str, model: str, total: int) -> UsageRecord:
    usage = TokenUsage.from_parts(
        total=total,
        input=total,
        output=0,
        cache_read=0,
        cache_creation=0,
    )
    return UsageRecord(
        date(2026, 1, day),
        agent,
        usage,
        SourceKind.UNIFIED_DAILY,
        make_project_ref(agent, project),
        (ModelBreakdown(model, usage),),
    )


def test_ambiguous_project_diagnostic_uses_distinct_display_names() -> None:
    projects = (
        make_project_ref("claude", "/claude/app"),
        make_project_ref("codex", "/codex/app"),
    )

    with pytest.raises(UsageError) as caught:
        resolve_projects(("pp",), projects)

    assert caught.value.key == "error.selector_ambiguous"
    assert caught.value.values["candidates"] == "  - app (claude)\n  - app (codex)"


def test_project_ambiguity_never_exposes_raw_ids() -> None:
    projects = (
        make_project_ref("claude", "/private/one/app", "app"),
        make_project_ref("claude", "/private/two/app", "app"),
    )

    with pytest.raises(UsageError) as caught:
        resolve_projects(("pp",), projects)

    candidates = str(caught.value.values["candidates"])
    assert candidates == "  - app (claude 1)\n  - app (claude 2)"
    assert "/private" not in candidates


def test_ambiguity_candidates_work_with_strict_language_override(tmp_path) -> None:
    language_file = tmp_path / "language.json"
    language_file.write_text(
        '{"error.selector_ambiguous": "{dimension}/{selector}: {candidates}"}',
        encoding="utf-8",
    )
    translator = load_translator("en", str(language_file))
    projects = (
        make_project_ref("claude", "/claude/app"),
        make_project_ref("codex", "/codex/app"),
    )

    with pytest.raises(UsageError) as caught:
        resolve_projects(("pp",), projects)

    assert translator.text(caught.value.key, **caught.value.values) == (
        "Project/pp:   - app (claude)\n  - app (codex)"
    )


def test_selected_values_without_rows_emit_notices_and_keep_available_groups() -> None:
    records = (
        _record(1, "claude", "/claude/app", "sonnet", 10),
        _record(3, "codex", "/codex/app", "gpt", 20),
    )
    selected_range = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)

    filtered, notices = filter_records(
        records,
        selected_range,
        agents=("claude", "codex"),
        models=("sonnet", "gpt"),
        projects=("app",),
    )

    assert [record.agent for record in filtered] == ["claude"]
    assert [(notice.key, notice.values) for notice in notices] == [
        (
            "notice.selected_no_data",
            {"dimension": "agent", "values": "codex"},
        ),
        (
            "notice.selected_no_data",
            {"dimension": "project", "values": "app (codex)"},
        ),
        (
            "notice.selected_no_data",
            {"dimension": "model", "values": "gpt"},
        ),
    ]

    model = build_timeline(filtered, selected_range, by="agent", notices=notices)
    assert [series.label for series in model.series] == ["claude"]
    assert model.notices == notices
    assert load_translator("zh").text(notices[0].key, **notices[0].values) == (
        "所选Agent无数据：codex"
    )


def test_absent_explicit_selections_do_not_render_unselected_rows() -> None:
    records = (_record(1, "claude", "/claude/app", "sonnet", 10),)
    selected_range = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)

    filtered, notices = filter_records(
        records,
        selected_range,
        agents=("codex",),
        models=("gpt",),
        projects=("missing",),
    )

    assert filtered == ()
    assert [(notice.values["dimension"], notice.values["values"]) for notice in notices] == [
        ("agent", "codex"),
        ("project", "missing"),
        ("model", "gpt"),
    ]


def test_mixed_known_and_absent_model_selection_renders_known_model() -> None:
    records = (_record(1, "claude", "/claude/app", "sonnet", 10),)
    selected_range = DateRange(date(2026, 1, 1), date(2026, 1, 1), None)

    filtered, notices = filter_records(
        records,
        selected_range,
        models=("sonnet", "gpt"),
    )

    assert [record.usage.total for record in filtered] == [10]
    assert [(notice.key, notice.values) for notice in notices] == [
        (
            "notice.selected_no_data",
            {"dimension": "model", "values": "gpt"},
        )
    ]
