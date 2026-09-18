from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

import ccusage_viz.application as application
from ccusage_viz.core.time import DateRange
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CommandOptions


def options(**changes: object) -> CommandOptions:
    base = CommandOptions(
        command="timeline",
        date_range=DateRange(date(2026, 1, 1), date(2026, 1, 14), None),
        by=None,
        top=None,
        other="show",
        cache="combined",
        agents=(),
        models=(),
        projects=(),
        demo="small",
        ccusage_bin="ccusage",
        query_timeout=30,
        no_color=False,
        ascii=False,
        interval=10,
    )
    return replace(base, **changes)


def test_preflight_rejects_noninteractive_streams_before_dependency_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: False)

    def unexpected_dependency_check(*_args: object) -> None:
        raise AssertionError("dependency check must not run")

    monkeypatch.setattr(application, "ensure_ccusage", unexpected_dependency_check)

    with pytest.raises(UsageError, match="error.tty"):
        application.run(options(), load_translator("en"))


@pytest.mark.parametrize("ascii", (False, True))
def test_preflight_requires_explicit_ascii_for_dumb_terminal(
    monkeypatch: pytest.MonkeyPatch, ascii: bool
) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: True)
    monkeypatch.setenv("TERM", "dumb")
    dependency_calls: list[CommandOptions] = []
    monkeypatch.setattr(
        application,
        "ensure_ccusage",
        lambda current, _translator: dependency_calls.append(current),
    )
    monkeypatch.setattr("ccusage_viz.watch.run_watch", lambda *_args: 7)

    if ascii:
        assert application.run(options(ascii=True), load_translator("en")) == 7
        assert len(dependency_calls) == 1
    else:
        with pytest.raises(UsageError, match="error.arguments"):
            application.run(options(), load_translator("en"))
        assert dependency_calls == []


def test_invalid_dashboard_panel_fails_before_dependency_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: True)

    def unexpected_dependency_check(*_args: object) -> None:
        raise AssertionError("dependency check must not run")

    monkeypatch.setattr(application, "ensure_ccusage", unexpected_dependency_check)

    with pytest.raises(UsageError, match="error.arguments"):
        application.run(
            options(command="dashboard", panes=("'",)),
            load_translator("en"),
        )


def test_dashboard_ascii_conflict_fails_before_dependency_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: True)

    def unexpected_dependency_check(*_args: object) -> None:
        raise AssertionError("dependency check must not run")

    monkeypatch.setattr(application, "ensure_ccusage", unexpected_dependency_check)

    with pytest.raises(UsageError, match="error.arguments"):
        application.run(
            options(
                command="dashboard",
                ascii=True,
                panes=("timeline --theme nord",),
            ),
            load_translator("en"),
        )


def test_historical_lifecycle_dispatches_from_no_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: True)
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(application, "ensure_ccusage", lambda *_args: None)
    monkeypatch.setattr("ccusage_viz.watch.run_once", lambda *_args: 3)
    monkeypatch.setattr("ccusage_viz.watch.run_watch", lambda *_args: 4)

    assert application.run(options(no_watch=True), load_translator("en")) == 3
    assert application.run(options(no_watch=False), load_translator("en")) == 4
