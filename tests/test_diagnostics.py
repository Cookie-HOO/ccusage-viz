from io import StringIO

import pytest

from ccusage_viz.diagnostics import color_enabled, format_error, highlight_matches
from ccusage_viz.errors import SchemaError, UsageError
from ccusage_viz.i18n import load_translator


class Stream(StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_highlight_matches_is_case_insensitive_and_unicode_safe() -> None:
    assert "\x1b[38;5;220m\x1b[1mAlPh\x1b[0m" in highlight_matches("  - AlPhabet", "alph", 220)
    assert "\x1b[38;5;220m\x1b[1mß\x1b[0m" in highlight_matches("  - Straße", "ss", 220)


def test_ambiguous_diagnostic_highlights_candidates_only() -> None:
    error = UsageError(
        "error.selector_ambiguous",
        selector="alph",
        dimension="model",
        candidates="  - Alpha\n  - Alphabet",
    )
    rendered = format_error(error, load_translator("en"), color=True)
    assert rendered.count("\x1b[38;5;") == 2
    assert "matches multiple" in rendered


def test_schema_diagnostic_is_localized() -> None:
    rendered = format_error(
        SchemaError("error.schema", path="$.projects", reason="expected object"),
        load_translator("en"),
    )
    assert rendered != "error.schema"
    assert "$.projects" in rendered
    assert "expected object" in rendered


def test_redirected_and_explicitly_disabled_diagnostics_are_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert color_enabled(Stream(False)) is False
    assert color_enabled(Stream(True), no_color=True) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled(Stream(True)) is True
