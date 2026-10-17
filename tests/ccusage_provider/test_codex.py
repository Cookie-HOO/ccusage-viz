import json
from datetime import date

import pytest

from ccusage_viz.coverage import DateCoverage
from ccusage_viz.errors import QueryError
from ccusage_viz.providers.ccusage_definition import CCUSAGE_DEFINITION
from ccusage_viz.query.models import (
    PhysicalQuery,
    PhysicalResult,
    ProviderRef,
)


def test_codex_normalization_attributes_a_singleton_query_to_its_day() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "cwd": "/workspace/project",
            }
        ]
    }

    (record,) = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    ).records

    assert record.day == date(2026, 1, 3)
    assert record.project is not None
    assert record.project.raw_id == "/workspace/project"
    assert record.usage.total == 20

def test_range_codex_ranking_normalization_anchors_totals_at_interval_end() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_ranking_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 3)),
    )
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "cwd": "/workspace/project",
            }
        ]
    }

    (record,) = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    ).records

    assert record.day == date(2026, 1, 3)
    assert record.project is not None
    assert record.project.raw_id == "/workspace/project"
    assert record.usage.total == 20

def test_codex_normalization_uses_local_session_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr(
        "ccusage_viz.providers.ccusage_fallback.resolve_codex_session_cwds",
        lambda session_ids: {"2026/01/03/rollout-test": "/workspace/from-session"},
    )
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "directory": "2026/01/03",
                "sessionId": "2026/01/03/rollout-test",
            }
        ]
    }

    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    )
    (record,) = fragment.records

    assert record.project is not None
    assert record.project.key == ("codex", "/workspace/from-session")
    assert record.day == date(2026, 1, 3)
    assert fragment.provider_metadata == ()

def test_codex_normalization_falls_back_without_treating_directory_as_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr("ccusage_viz.providers.ccusage_fallback.resolve_codex_session_cwds", lambda _: {})
    payload = {
        "sessions": [
            {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadTokens": 5,
                "cacheCreationTokens": 7,
                "totalTokens": 20,
                "directory": "2026/01/03",
                "sessionId": "2026/01/03/rollout-missing",
            }
        ]
    }

    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(query, json.dumps(payload).encode())
    )
    (record,) = fragment.records

    assert record.project is not None
    assert record.project.display_name == "Unassigned"
    assert record.attribution == "unassigned"
    assert record.session_id == "2026/01/03/rollout-missing"
    assert fragment.provider_metadata == ()

def test_codex_incomplete_attribution_retains_session_on_fixed_project_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 3), date(2026, 1, 3)),
    )
    monkeypatch.setattr("ccusage_viz.providers.ccusage_fallback.resolve_codex_session_cwds", lambda _: {})
    fragment = CCUSAGE_DEFINITION.provider.normalize(
        PhysicalResult(
            query,
            json.dumps(
                {
                    "sessions": [
                        {
                            "sessionId": "2026/01/03/rollout-unassigned",
                            "inputTokens": 2,
                            "outputTokens": 3,
                            "cacheReadTokens": 5,
                            "cacheCreationTokens": 7,
                            "totalTokens": 20,
                        }
                    ]
                }
            ).encode(),
        )
    )

    (record,) = fragment.records
    assert record.project is not None
    assert record.project.display_name == "Unassigned"
    assert record.attribution == "unassigned"
    assert record.session_id == "2026/01/03/rollout-unassigned"

def test_codex_normalization_rejects_non_singleton_coverage() -> None:
    query = PhysicalQuery(
        ProviderRef("ccusage"),
        "codex_sessions",
        coverage=DateCoverage.from_interval(date(2026, 1, 2), date(2026, 1, 3)),
    )

    with pytest.raises(QueryError) as caught:
        CCUSAGE_DEFINITION.provider.normalize(PhysicalResult(query, b'{"sessions": []}'))

    assert caught.value.key == "error.ccusage_codex_date_attribution"
