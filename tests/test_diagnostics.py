from io import StringIO

import pytest

from ccusage_viz.diagnostics import (
    color_enabled,
    format_error,
    is_transient_unified_daily_database_error,
    transient_query_recovery_lines,
)
from ccusage_viz.errors import QueryError, SchemaError
from ccusage_viz.i18n import load_translator


class Stream(StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_schema_diagnostic_is_localized() -> None:
    rendered = format_error(
        SchemaError("error.schema", path="$.projects", reason="expected object"),
        load_translator("en"),
    )
    assert rendered != "error.schema"
    assert "$.projects" in rendered
    assert "expected object" in rendered


@pytest.mark.parametrize(
    "stderr",
    (
        "SQLITE_BUSY: database is locked at /private/example.db",
        'CliError("Failed to inspect Antigravity database")',
    ),
)
def test_transient_unified_daily_database_errors_have_safe_recovery_copy(stderr: str) -> None:
    error = QueryError("error.ccusage_failed", query="unified_daily", code=1, stderr=stderr)

    assert is_transient_unified_daily_database_error(error)
    assert transient_query_recovery_lines(error, load_translator("en"), initial=False) == (
        "The next refresh may recover; press r to try now.",
    )
    assert transient_query_recovery_lines(error, load_translator("zh"), initial=True) == (
        "用量数据暂时不可用。",
        "下次刷新可能恢复；现在可按 r 重试。",
    )


@pytest.mark.parametrize(
    "error",
    (
        QueryError(
            "error.ccusage_failed",
            query="unified_daily_agent_observation",
            code=1,
            stderr="SQLITE_BUSY",
        ),
        QueryError(
            "error.ccusage_failed", query="unified_daily", code=1, stderr="invalid argument"
        ),
        QueryError("error.ccusage_timeout", query="unified_daily", seconds=10),
        SchemaError("error.schema", path="$.projects", reason="expected object"),
        RuntimeError("SQLITE_BUSY"),
    ),
)
def test_only_known_unified_daily_database_errors_are_classified(error: BaseException) -> None:
    assert not is_transient_unified_daily_database_error(error)
    assert transient_query_recovery_lines(error, load_translator("en"), initial=False) is None


def test_redirected_and_explicitly_disabled_diagnostics_are_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert color_enabled(Stream(False)) is False
    assert color_enabled(Stream(True), no_color=True) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled(Stream(True)) is True
