from __future__ import annotations

from dataclasses import replace
from datetime import date
from subprocess import CompletedProcess

import pytest

from ccusage_viz.bootstrap import build_provider_registry
from ccusage_viz.core.time import DateRange
from ccusage_viz.dependency import ensure_ccusage, ensure_provider_dependencies
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    ProcessConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)


def options(**changes: object) -> StandaloneLaunch:
    process = ProcessConfig(query_timeout=2)
    host = StandaloneHostConfig(ascii=True, watch=False)
    explicit = changes.pop("explicit", frozenset())
    if "demo" in changes:
        host = replace(host, demo_size=changes.pop("demo"))
    if "ccusage_bin" in changes:
        process = replace(process, ccusage_bin=changes.pop("ccusage_bin"))
    return StandaloneLaunch(
        process,
        host,
        TimelineConfig("timeline", DateRange(date(2026, 1, 1), date(2026, 1, 2))),
        explicit,
    )


def test_dependency_preflight_skips_demo_and_custom_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: pytest.fail(name))

    ensure_ccusage(options(demo="small"), load_translator("en"))
    ensure_ccusage(options(ccusage_bin="/custom/ccusage"), load_translator("en"))
    ensure_ccusage(options(explicit=frozenset({"ccusage_bin"})), load_translator("en"))


def test_provider_dependency_preflight_uses_effective_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[StandaloneLaunch] = []
    monkeypatch.setattr(
        "ccusage_viz.dependency.ensure_ccusage",
        lambda current, _translator: calls.append(current),
    )
    registry = build_provider_registry()

    demo = options(demo="small")
    ccusage = options()
    ensure_provider_dependencies(demo, registry, load_translator("en"))
    ensure_provider_dependencies(ccusage, registry, load_translator("en"))

    assert calls == [ccusage]


def test_dependency_preflight_skips_existing_ccusage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: "/bin/ccusage")

    ensure_ccusage(options(), load_translator("en"))


def test_dependency_preflight_noninteractive_never_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: None)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)

    def unexpected_install(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not install")

    monkeypatch.setattr("ccusage_viz.dependency.subprocess.run", unexpected_install)

    with pytest.raises(QueryError) as caught:
        ensure_ccusage(options(), load_translator("en"))

    assert caught.value.key == "error.ccusage_missing"


@pytest.mark.parametrize("response", ["", "y", "Y"])
def test_dependency_preflight_affirmative_input_installs_and_verifies_path(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    lookups = iter((None, "/usr/local/bin/npm", "/usr/local/bin/ccusage"))
    calls: list[tuple[list[str], bool, bool]] = []
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: next(lookups))
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: response)

    def run(command: list[str], *, shell: bool, check: bool) -> CompletedProcess[str]:
        calls.append((command, shell, check))
        return CompletedProcess(command, 0)

    monkeypatch.setattr("ccusage_viz.dependency.subprocess.run", run)

    ensure_ccusage(options(), load_translator("en"))

    assert calls == [(["/usr/local/bin/npm", "install", "-g", "ccusage"], False, False)]


@pytest.mark.parametrize("response", ["n", "N", "no", " ", "anything"])
def test_dependency_preflight_nonaffirmative_input_cancels(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: None)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: response)
    monkeypatch.setattr(
        "ccusage_viz.dependency.subprocess.run",
        lambda *args, **kwargs: pytest.fail("must not install"),
    )

    with pytest.raises(QueryError) as caught:
        ensure_ccusage(options(), load_translator("en"))

    assert caught.value.key == "error.ccusage_missing"


def test_dependency_preflight_reports_missing_npm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: None)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    with pytest.raises(QueryError) as caught:
        ensure_ccusage(options(), load_translator("en"))

    assert caught.value.key == "error.npm_missing"


def test_dependency_preflight_reports_install_and_path_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    lookups = iter((None, "/bin/npm"))
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: next(lookups))
    monkeypatch.setattr(
        "ccusage_viz.dependency.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 7),
    )
    with pytest.raises(QueryError) as caught:
        ensure_ccusage(options(), load_translator("en"))
    assert caught.value.key == "error.ccusage_install_failed"
    assert caught.value.values == {"code": 7}

    lookups = iter((None, "/bin/npm", None))
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: next(lookups))
    monkeypatch.setattr(
        "ccusage_viz.dependency.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0),
    )
    with pytest.raises(QueryError) as caught:
        ensure_ccusage(options(), load_translator("en"))
    assert caught.value.key == "error.ccusage_install_path"
