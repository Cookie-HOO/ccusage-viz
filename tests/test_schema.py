from datetime import date

import pytest

from ccusage_viz.domain import SourceKind
from ccusage_viz.errors import SchemaError
from ccusage_viz.query.models import QueryKind
from ccusage_viz.schema import parse_usage_records


def usage(**extra: object) -> dict[str, object]:
    return {
        "inputTokens": 2,
        "outputTokens": 3,
        "cacheReadTokens": 5,
        "cacheCreationTokens": 7,
        "totalTokens": 20,
        **extra,
    }


def test_parse_unified_daily_by_agent_allows_additive_fields() -> None:
    payload = {
        "daily": [
            {
                "period": "2026-01-02",
                "future": True,
                "agents": [
                    usage(
                        agent="claude",
                        unknown="allowed",
                        modelBreakdowns=[
                            {
                                "modelName": "sonnet",
                                "inputTokens": 1,
                                "outputTokens": 2,
                                "cacheReadTokens": 3,
                                "cacheCreationTokens": 4,
                                "newField": 1,
                            }
                        ],
                    )
                ],
            }
        ],
        "totals": {},
        "addedTopLevel": {},
    }
    (record,) = parse_usage_records(QueryKind.UNIFIED_DAILY, payload)
    assert record.day == date(2026, 1, 2)
    assert record.agent == "claude"
    assert record.source is SourceKind.UNIFIED_DAILY
    assert record.usage.other == 3
    assert record.models[0].usage.total == 10
    assert record.models[0].usage.other == 0


def test_parse_claude_instances() -> None:
    payload = {"projects": {"-Users-me-project": [usage(date="2026-05-16")]}}
    (record,) = parse_usage_records(QueryKind.CLAUDE_DAILY_PROJECTS, payload)
    assert record.day == date(2026, 5, 16)
    assert record.project is not None
    assert record.project.key == ("claude", "-Users-me-project")
    assert record.source is SourceKind.CLAUDE_DAILY_PROJECTS


def test_parse_claude_instances_accepts_empty_daily_response() -> None:
    payload = {
        "daily": [],
        "totals": {
            "cacheCreationTokens": 0,
            "cacheReadTokens": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalCost": -0.0,
            "totalTokens": 0,
        },
    }
    assert parse_usage_records(QueryKind.CLAUDE_DAILY_PROJECTS, payload) == ()


@pytest.mark.parametrize("payload", [{}, {"daily": [{}]}, {"projects": None}])
def test_parse_claude_instances_rejects_other_non_project_responses(payload: object) -> None:
    with pytest.raises(SchemaError):
        parse_usage_records(QueryKind.CLAUDE_DAILY_PROJECTS, payload)


@pytest.mark.parametrize("container", ["sessions", "session", "data"])
def test_parse_codex_synthetic_session_shapes(container: str) -> None:
    payload = {container: [usage(session="abc", projectPath="/tmp/project", projectName="demo")]}
    (record,) = parse_usage_records(QueryKind.CODEX_SESSIONS, payload)
    assert record.day is None
    assert record.agent == "codex"
    assert record.project is not None
    assert record.project.raw_id == "/tmp/project"
    assert record.project.display_name == "demo"


def test_codex_cwd_takes_precedence_over_storage_directory() -> None:
    payload = {"sessions": [usage(cwd=r"C:\\work\\repo", directory="2026/06/04")]}

    (record,) = parse_usage_records(QueryKind.CODEX_SESSIONS, payload)

    assert record.project is not None
    assert record.project.key == ("codex", r"C:\\work\\repo")
    assert record.project.display_name == "repo"


def test_codex_directory_is_never_a_project_identity() -> None:
    payload = {"sessions": [usage(directory="2026/06/04", projectName="04")]}

    (record,) = parse_usage_records(QueryKind.CODEX_SESSIONS, payload)

    assert record.project is not None
    assert record.project.key == ("codex", "unassigned-codex")
    assert record.project.display_name == "Unassigned Codex"


def test_parse_codex_model_map_with_official_project() -> None:
    payload = {
        "sessions": [
            usage(
                projectPath="/workspace/api",
                directory="2026/06/04",
                models={"gpt-5": usage(reasoningOutputTokens=2)},
            )
        ]
    }
    (record,) = parse_usage_records(QueryKind.CODEX_SESSIONS, payload)
    assert record.project is not None
    assert record.project.key == ("codex", "/workspace/api")
    assert record.project.display_name == "api"
    assert record.models[0].model == "gpt-5"
    assert record.models[0].usage.other == 3


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda row: row.pop("inputTokens"), "missing field"),
        (lambda row: row.__setitem__("outputTokens", "3"), "expected integer"),
        (lambda row: row.__setitem__("cacheReadTokens", -1), "non-negative"),
        (lambda row: row.__setitem__("totalTokens", 1), "exceed"),
    ],
)
def test_token_fields_are_strict(mutation, reason: str) -> None:
    row = usage(agent="claude")
    mutation(row)
    with pytest.raises(SchemaError) as caught:
        parse_usage_records(
            QueryKind.UNIFIED_DAILY,
            {"daily": [{"period": "2026-01-02", "agents": [row]}]},
        )
    assert caught.value.key == "error.schema"
    assert reason in str(caught.value.values["reason"])
