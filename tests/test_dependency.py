from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.backend_store import BackendChoice, save_choice
from ccusage_viz.bootstrap import build_provider_registry
from ccusage_viz.core.time import DateRange
from ccusage_viz.dependency import ensure_ccusage, ensure_provider_dependencies
from ccusage_viz.errors import QueryError
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    CustomChartConfig,
    CustomCommandSource,
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


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr("ccusage_viz.backend_store.ccuv_state_root", lambda: tmp_path)
    monkeypatch.setattr("ccusage_viz.backend_store.shutil.which", lambda name: None)


def test_skips_demo_and_custom(monkeypatch):
    monkeypatch.setattr(
        "ccusage_viz.backend_store.load_choice", lambda: pytest.fail("no state reads")
    )
    ensure_ccusage(options(demo="small"), load_translator("en"))
    ensure_ccusage(options(ccusage_bin="/custom/ccusage"), load_translator("en"))
    ensure_ccusage(options(explicit=frozenset({"ccusage_bin"})), load_translator("en"))


def test_provider_preflight(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ccusage_viz.dependency.ensure_ccusage", lambda current, tr: calls.append(current)
    )
    registry = build_provider_registry()
    demo, real = options(demo="small"), options()
    ensure_provider_dependencies(demo, registry, load_translator("en"))
    ensure_provider_dependencies(real, registry, load_translator("en"))
    assert calls == [real]


def test_custom_standalone_skips(monkeypatch):
    custom = replace(
        options(),
        chart=CustomChartConfig(
            "timeline",
            CustomCommandSource("reading", ("reader", "ccuv")),
            DateRange(date(2026, 1, 1), date(2026, 1, 2)),
        ),
    )
    monkeypatch.setattr(
        "ccusage_viz.dependency.ensure_ccusage", lambda *args: pytest.fail("custom")
    )
    ensure_provider_dependencies(custom, build_provider_registry(), load_translator("en"))


@pytest.mark.parametrize("commands", [{"ccusage"}, {"my-ccusage"}])
def test_one_discovered_never_prompts(monkeypatch, commands):
    monkeypatch.setattr(
        "ccusage_viz.backend_store.shutil.which",
        lambda name: f"/bin/{name}" if name in commands else None,
    )
    monkeypatch.setattr("ccusage_viz.backend.setup", lambda *args: pytest.fail("setup"))
    ensure_ccusage(options(), load_translator("en"))


def test_missing_noninteractive(monkeypatch):
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("ccusage_viz.backend.setup", lambda *args: pytest.fail("setup"))
    with pytest.raises(QueryError, match="error.ccusage_missing"):
        ensure_ccusage(options(), load_translator("en"))


@pytest.mark.parametrize("commands", [set(), {"ccusage", "my-ccusage"}])
def test_missing_or_two_interactive_uses_setup(monkeypatch, commands):
    calls = []
    monkeypatch.setattr(
        "ccusage_viz.backend_store.shutil.which",
        lambda name: f"/bin/{name}" if name in commands else None,
    )
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.dependency.sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("ccusage_viz.backend.setup", lambda tr: calls.append(tr))
    ensure_ccusage(options(), load_translator("en"))
    assert len(calls) == 1


def test_saved_missing_no_fallback(monkeypatch):
    save_choice(BackendChoice("enhanced", "/missing/my-ccusage"))
    monkeypatch.setattr(
        "ccusage_viz.backend_store.shutil.which",
        lambda name: "/bin/ccusage" if name == "ccusage" else None,
    )
    with pytest.raises(QueryError, match="error.backend_unavailable"):
        ensure_ccusage(options(), load_translator("en"))
