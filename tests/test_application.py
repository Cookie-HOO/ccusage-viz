from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

import ccusage_viz.application as application
from ccusage_viz.core.time import DateRange
from ccusage_viz.errors import UsageError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ChartPresentation,
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)


def options(**changes: object) -> StandaloneLaunch:
    host_changes = {}
    if "ascii" in changes:
        host_changes["ascii"] = changes.pop("ascii")
    if "no_watch" in changes:
        host_changes["watch"] = not changes.pop("no_watch")
    host = StandaloneHostConfig(ascii=False, demo_size="small", interval=10)
    host = replace(host, **host_changes)
    base = StandaloneLaunch(
        ProcessConfig(query_timeout=30),
        host,
        TimelineConfig(
            "timeline",
            DateRange(date(2026, 1, 1), date(2026, 1, 14)),
            presentation=ChartPresentation(),
        ),
    )
    return replace(base, **changes)


def test_preflight_rejects_noninteractive_streams_before_dependency_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: False)

    def unexpected_dependency_check(*_args: object) -> None:
        raise AssertionError("dependency check must not run")

    monkeypatch.setattr(application, "ensure_provider_dependencies", unexpected_dependency_check)

    with pytest.raises(UsageError, match="error.tty"):
        application.run(options(), load_translator("en"))


@pytest.mark.parametrize("ascii", (False, True))
def test_preflight_requires_explicit_ascii_for_dumb_terminal(
    monkeypatch: pytest.MonkeyPatch, ascii: bool
) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: True)
    monkeypatch.setenv("TERM", "dumb")
    dependency_calls: list[StandaloneLaunch] = []
    monkeypatch.setattr(
        application,
        "ensure_provider_dependencies",
        lambda current, _registry, _translator: dependency_calls.append(current),
    )
    monkeypatch.setattr("ccusage_viz.watch.run_watch", lambda *_args: 7)

    if ascii:
        assert application.run(options(ascii=True), load_translator("en")) == 7
        assert len(dependency_calls) == 1
    else:
        with pytest.raises(UsageError, match="error.arguments"):
            application.run(options(), load_translator("en"))
        assert dependency_calls == []


def test_historical_modes_share_one_lifecycle_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(application, "interactive_streams", lambda: True)
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(application, "ensure_provider_dependencies", lambda *_args: None)
    received: list[StandaloneLaunch] = []
    monkeypatch.setattr(
        "ccusage_viz.watch.run_watch",
        lambda selected, _translator: received.append(selected) or len(received),
    )

    assert application.run(options(no_watch=True), load_translator("en")) == 1
    assert application.run(options(no_watch=False), load_translator("en")) == 2
    assert [selected.host.watch for selected in received] == [False, True]
