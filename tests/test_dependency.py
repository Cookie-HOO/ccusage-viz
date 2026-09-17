from __future__ import annotations

from dataclasses import replace
from datetime import date
from subprocess import CompletedProcess

import pytest

from ccusage_viz.dependency import ensure_ccusage
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CommandOptions, DateRange


def options(**changes: object) -> CommandOptions:
    base = CommandOptions(
        command="timeline",
        date_range=DateRange(date(2026, 1, 1), date(2026, 1, 2), None),
        by="total",
        top=None,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=None,
        demo=None,
        ccusage_bin="ccusage",
        timeout=2,
        no_color=True,
        ascii=True,
    )
    return replace(base, **changes)


def test_dependency_preflight_skips_demo_and_custom_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: pytest.fail(name))

    ensure_ccusage(options(demo="small"), load_translator("en"))
    ensure_ccusage(options(ccusage_bin="/custom/ccusage"), load_translator("en"))
    ensure_ccusage(options(ccusage_bin_explicit=True), load_translator("en"))


def test_dependency_preflight_skips_existing_ccusage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: "/bin/ccusage")

    ensure_ccusage(options(), load_translator("en"))


def test_dependency_preflight_noninteractive_never_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: None)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    def unexpected_install(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not install")

    monkeypatch.setattr("ccusage_viz.dependency.subprocess.run", unexpected_install)

    with pytest.raises(QueryError) as caught:
        ensure_ccusage(options(), load_translator("en"))

    assert caught.value.key == "error.ccusage_missing"


def test_dependency_preflight_enter_installs_and_verifies_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups = iter((None, "/usr/local/bin/npm", "/usr/local/bin/ccusage"))
    calls: list[tuple[list[str], bool, bool]] = []
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: next(lookups))
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    def run(command: list[str], *, shell: bool, check: bool) -> CompletedProcess[str]:
        calls.append((command, shell, check))
        return CompletedProcess(command, 0)

    monkeypatch.setattr("ccusage_viz.dependency.subprocess.run", run)

    ensure_ccusage(options(), load_translator("en"))

    assert calls == [(["/usr/local/bin/npm", "install", "-g", "ccusage"], False, False)]


@pytest.mark.parametrize("response", ["no", " "])
def test_dependency_preflight_only_empty_input_confirms(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    monkeypatch.setattr("ccusage_viz.dependency.shutil.which", lambda name: None)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: response)

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
