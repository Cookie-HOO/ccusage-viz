from dataclasses import replace
from datetime import date

import pytest

from ccusage_viz.application import run
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CommandOptions, DateRange
from ccusage_viz.watch import AppearancePickerResult, RefreshResult, UsageSnapshot


def options(*, watch: float | None = None) -> CommandOptions:
    return CommandOptions(
        command="timeline",
        date_range=DateRange(date(2026, 1, 1), date(2026, 1, 14), None),
        by="total",
        top=3,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=watch,
        demo="small",
        ccusage_bin="/not/invoked",
        timeout=2,
        no_color=False,
        ascii=True,
        pick=True,
    )


def test_picker_confirmation_without_watch_does_not_run_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = RefreshResult("chart", (), 0.1)
    selected = replace(options(), color_scheme="nord")

    monkeypatch.setattr("ccusage_viz.application.inspect_terminal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ccusage_viz.watch.load_snapshot", lambda current, runner: UsageSnapshot((), (), 0.1)
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_appearance_picker",
        lambda current, translator, snapshot, screen: AppearancePickerResult(selected, seed),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_once",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not rerun")),
    )

    assert run(options(), load_translator("en")) == 0


def test_picker_confirmation_seeds_watch_with_selected_theme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = RefreshResult("chart", (), 0.1)
    selected = replace(options(watch=5), color_scheme="nord")
    handed_off: list[tuple[str, RefreshResult]] = []

    monkeypatch.setattr("ccusage_viz.application.inspect_terminal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ccusage_viz.watch.load_snapshot", lambda current, runner: UsageSnapshot((), (), 0.1)
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_appearance_picker",
        lambda current, translator, snapshot, screen: AppearancePickerResult(selected, seed),
    )

    def watch(current, translator, *, seed, screen):
        handed_off.append((current.color_scheme, seed))
        return 0

    monkeypatch.setattr("ccusage_viz.watch.run_watch", watch)

    assert run(options(watch=5), load_translator("en")) == 0
    assert handed_off == [("nord", seed)]


def test_picker_query_failure_happens_before_screen_paint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = RuntimeError("query failed")

    monkeypatch.setattr("ccusage_viz.application.inspect_terminal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ccusage_viz.watch.load_snapshot",
        lambda current, runner: (_ for _ in ()).throw(error),
    )

    with pytest.raises(RuntimeError, match="query failed"):
        run(replace(options(), demo=None), load_translator("en"))

    assert capsys.readouterr().out == ""


def test_picker_cancellation_does_not_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ccusage_viz.application.inspect_terminal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ccusage_viz.watch.load_snapshot", lambda current, runner: UsageSnapshot((), (), 0.1)
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_appearance_picker",
        lambda current, translator, snapshot, screen: None,
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_once",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not continue")),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.run_watch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not continue")),
    )

    assert run(options(watch=5), load_translator("en")) == 0
