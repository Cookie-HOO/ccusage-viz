from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from typing import cast

import pytest

from ccusage_viz.core.time import DateRange
from ccusage_viz.coverage import DateCoverage, DateInterval
from ccusage_viz.domain import Notice
from ccusage_viz.errors import UsageError
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import (
    CalendarConfig,
    ChartPresentation,
    MonitorConfig,
    ProcessConfig,
    RankingConfig,
    StackConfig,
    StandaloneHostConfig,
    StandaloneLaunch,
    TimelineConfig,
)
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.terminal import InteractiveScreen, Terminal
from ccusage_viz.watch import (
    RefreshResult,
    RuntimeAdjustmentResult,
    UsageSnapshot,
    _controls_line,
    _notice_lines,
    _paint,
    _paint_status,
    _refresh,
    _refreshing_status,
    _render,
    _watch_status,
    load_snapshot,
    run_once,
    run_runtime_adjustment,
)


def options(*, command: str = "ranking", demo: str | None = "small") -> StandaloneLaunch:
    date_range = DateRange(date(2026, 1, 1), date(2026, 1, 14), None)
    presentation = ChartPresentation(theme="no-color")
    chart = (
        TimelineConfig("timeline", date_range, presentation=presentation, top=3, other="hide")
        if command == "timeline"
        else CalendarConfig("calendar", date_range, presentation=presentation)
        if command == "calendar"
        else StackConfig("stack", date_range, presentation=replace(presentation, style="stacked"))
        if command == "stack"
        else RankingConfig(
            "ranking",
            date_range,
            presentation=replace(presentation, style="bar"),
            by="project",
            top=10,
            other="hide",
        )
        if command == "ranking"
        else MonitorConfig("monitor", 3600, presentation=replace(presentation, style="bars"))
    )
    return StandaloneLaunch(
        ProcessConfig(ccusage_bin="/not/invoked", query_timeout=2),
        StandaloneHostConfig(ascii=True, demo_size=demo, watch=False),
        chart,
    )


def test_one_shot_paints_one_complete_interactive_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []

    class Screen:
        def __init__(self, stream: object) -> None:
            events.append(("init", stream))

        def paint(self, *args: object, **kwargs: object) -> None:
            events.append(("paint", *args, kwargs))

        def finish(self) -> None:
            events.append(("finish",))

    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, False, True),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch._refresh",
        lambda *args, **kwargs: RefreshResult("complete chart", ("notice",), 0.25),
    )
    monkeypatch.setattr("ccusage_viz.watch.InteractiveScreen", Screen)

    assert run_once(options(), load_translator("en")) == 0
    assert [event[0] for event in events] == ["init", "paint", "finish"]
    assert events[1][1] == "complete chart"
    assert events[1][-1]["height"] == 30


def test_watch_paint_places_footer_last_without_refresh_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint(
        "summary\nchart\n",
        "status",
        "r refresh · m adjust · Space pause",
        ("! warning one", "! warning two"),
    )
    assert capsys.readouterr().out == (
        "\x1b[H\x1b[2Jstatus\nsummary\nchart\n"
        "! warning one\n! warning two\nr refresh · m adjust · Space pause"
    )


def test_watch_paint_pads_controls_to_fixed_final_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint("chart", "status", ("adjustment", "controls"), ("warning",), height=6)
    assert capsys.readouterr().out == "\x1b[H\x1b[2Jstatus\nchart\n\nwarning\nadjustment\ncontrols"


def test_watch_paint_keeps_footer_visible_if_body_is_too_tall(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint("one\ntwo\nthree\nfour", "status", "controls", ("warning",), height=5)
    assert capsys.readouterr().out == "\x1b[H\x1b[2Jstatus\none\ntwo\nwarning\ncontrols"


def test_watch_refresh_only_repaints_the_status_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint_status("ccusage 1.96s · refresh every 5s · refreshing")
    assert capsys.readouterr().out == "\x1b[H\x1b[2Kccusage 1.96s · refresh every 5s · refreshing"


def test_refreshing_hint_is_dimmed_only_when_color_is_enabled() -> None:
    translator = load_translator("en")
    status = "ccusage 1.96s · refresh every 5s"

    assert _refreshing_status(status, translator, color=False) == f"{status} · refreshing"
    assert _refreshing_status(status, translator, color=True) == (
        f"{status} · \x1b[2mrefreshing\x1b[0m"
    )


@pytest.mark.parametrize(
    ("paused", "running", "expected"),
    [
        (False, False, "ccusage 1.83s · refresh every 5s"),
        (True, False, "ccusage 1.83s · paused"),
        (True, True, "ccusage 1.83s · paused · refreshing"),
        (False, True, "ccusage 1.83s · refresh every 5s · refreshing"),
    ],
)
def test_watch_status_is_derived_from_pause_and_refresh_state(
    paused: bool,
    running: bool,
    expected: str,
) -> None:
    assert (
        _watch_status(
            "ccusage 1.83s",
            load_translator("en"),
            interval=5,
            paused=paused,
            running=running,
            color=False,
        )
        == expected
    )


def test_loading_status_can_show_pause_before_first_result() -> None:
    assert (
        _watch_status(
            "Loading…",
            load_translator("en"),
            interval=5,
            paused=True,
            running=True,
            color=False,
        )
        == "Loading… · paused · refreshing"
    )


def test_notice_lines_use_redundant_glyph_color_and_width() -> None:
    translator = load_translator("en")
    colored = _notice_lines(
        ("A warning that is intentionally much too long",),
        width=18,
        color=True,
        ascii=False,
        translator=translator,
    )[0]
    plain = _notice_lines(
        ("warning",),
        width=18,
        color=False,
        ascii=True,
        translator=translator,
    )[0]

    assert strip_ansi(colored).startswith("⚠ ")
    assert "\x1b[38;5;130m" in colored
    assert "\x1b[48;" not in colored
    assert display_width(colored) <= 18
    assert plain == "! warning"
    assert "\x1b[" not in plain


def test_controls_are_dimmed_and_clipped_to_one_row() -> None:
    colored = _controls_line("r refresh · m adjust · Space pause", width=20, color=True)
    plain = _controls_line("r refresh · m adjust · Space pause", width=20, color=False)

    assert colored.startswith("\x1b[2m") and colored.endswith("\x1b[0m")
    assert display_width(colored) == 20
    assert plain == "r refresh · m adjust"
    assert "\x1b[" not in plain


def test_ranking_render_shows_daily_summary_and_separate_scope_warning() -> None:
    scope_notice = Notice("notice.summary_excludes_session_agent", {"agent": "Codex"})
    rendered = _render(
        options(),
        load_translator("en"),
        Terminal(100, 30, False, True),
        (),
        (),
        coverage=DateCoverage.from_interval(date(2025, 12, 25), date(2026, 1, 14)),
        summary_notices=(scope_notice,),
    )

    assert rendered.chart.splitlines()[0] == (
        "Today’s tokens 0; vs yesterday = unchanged; vs last We = unchanged"
    )
    assert rendered.notices == (
        "Summary excludes Codex project-session usage; ccusage has no per-day values",
    )
    assert rendered.notices[0] not in rendered.chart


def test_render_normalizes_standalone_ranking_title() -> None:
    rendered = _render(
        options(),
        load_translator("en"),
        Terminal(100, 30, False, True),
        (),
        (),
        normalize_titles=True,
    )

    assert "Project · Ranking · 2026-01-01–2026-01-14" in rendered.chart


def test_render_keeps_notices_separate_from_chart() -> None:
    rendered = _render(
        options(),
        load_translator("en"),
        Terminal(100, 30, False, True),
        (),
        (Notice("notice.project_agent_omitted", {"agent": "Codex"}),),
        coverage=DateCoverage.from_interval(date(2025, 12, 25), date(2026, 1, 14)),
    )

    assert rendered.notices == ("Codex omitted: ccusage does not expose project data",)
    assert rendered.notices[0] not in rendered.chart
    lines = rendered.chart.splitlines()
    assert lines[0] == "Today’s tokens 0; vs yesterday = unchanged; vs last We = unchanged"
    assert lines[1].strip() == "Ranking · 2026-01-01–2026-01-14"
    assert lines[2] == "No token usage found for the selected range."


def test_one_shot_reserves_one_more_row_than_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    heights: list[int] = []

    def capture_height(model, context) -> str:
        heights.append(context.height)
        return "chart"

    monkeypatch.setattr("ccusage_viz.watch.render_ranking", capture_height)
    runner = cast(QueryRunner, object())
    terminal = Terminal(100, 30, False, True)
    translator = load_translator("en")

    _refresh(options(), translator, terminal, runner)
    _refresh(options(), translator, terminal, runner, reserve_prompt=True)
    _refresh(options(), translator, terminal, runner, control_rows=1)

    assert heights == [29, 28, 28]


@pytest.mark.parametrize(
    ("command", "by", "keys", "expected"),
    [
        (
            "timeline",
            "total",
            ("b", "+", "a", "o", "\n"),
            {"by": "agent", "top": 4, "other": "show"},
        ),
        (
            "ranking",
            "project",
            ("b", "+", "a", "o", "\n"),
            {"by": "agent", "top": 11, "other": "show"},
        ),
        (
            "stack",
            "total",
            ("a", "c", "\n"),
            {"cache": "split"},
        ),
        ("calendar", "total", ("a", "\n"), {}),
    ],
)
def test_runtime_adjustment_updates_display_options_from_retained_snapshot(
    command: str,
    by: str,
    keys: tuple[str, ...],
    expected: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    inputs = iter(keys)
    rendered_snapshots: list[UsageSnapshot] = []
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(inputs))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )
    original_render_snapshot = __import__(
        "ccusage_viz.watch", fromlist=["render_snapshot"]
    ).render_snapshot

    def capture_render_snapshot(*args, **kwargs):
        rendered_snapshots.append(args[3])
        return original_render_snapshot(*args, **kwargs)

    monkeypatch.setattr("ccusage_viz.watch.render_snapshot", capture_render_snapshot)
    snapshot = UsageSnapshot((), (), 0.25)
    current = options(command=command)
    if command in {"timeline", "ranking"}:
        current = replace(current, chart=replace(current.chart, by=None if by == "total" else by))

    result = run_runtime_adjustment(
        current,
        load_translator("en"),
        snapshot,
        cast(InteractiveScreen, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert all(getattr(result.options.chart, field) == value for field, value in expected.items())
    assert rendered_snapshots and all(item is snapshot for item in rendered_snapshots)
    assert result.options.chart.filters.agents == current.chart.filters.agents
    assert result.options.chart.filters.models == current.chart.filters.models
    assert result.options.chart.filters.projects == current.chart.filters.projects


def test_runtime_adjustment_retains_last_chart_until_an_invalid_draft_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paints: list[tuple[object, ...]] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            paints.append(args)

    keys = iter(("s", "\n", "s", "\n"))
    calls = 0
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, False, True),
    )

    def render(current, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise UsageError("error.stack_stacked_width", width=100)
        return RefreshResult("chart", (), 0.25, args[2], current)

    monkeypatch.setattr("ccusage_viz.watch.render_snapshot", render)
    current = replace(
        options(command="stack"),
        chart=replace(
            options(command="stack").chart,
            date_range=DateRange(date(2026, 1, 1), date(2026, 1, 7), None),
        ),
    )
    result = run_runtime_adjustment(
        current,
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert calls == 3
    assert any(args[0] == "chart" and "too narrow" in str(args[3]) for args in paints)


def test_runtime_adjustment_pages_match_dashboard_and_weekdays_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controls: list[object] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            controls.append(args[2])

    keys = iter(("k", "a", "k", "b", "a", "b", "\n"))
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        options(command="timeline"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.weekdays == "hide"
    assert result.options.chart.by == "agent"
    assert "Quick settings" in str(controls[0])
    assert "Advanced settings" in str(controls[1])
    assert "k weekdays" in str(controls[1])
    assert "WEEKDAYS hide" in str(controls[2])


def test_project_adjustment_explains_missing_retained_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paints: list[tuple[object, ...]] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            paints.append(args)

    keys = iter(("b", "b", "b", "\x1b"))
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        options(command="timeline"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
    )

    assert result is None
    assert any("project data is not in this preview" in str(args[1]) for args in paints)


def test_runtime_adjustment_copy_uses_adjusted_display_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    keys = iter(("b", "+", "a", "o", "y", "\x1b"))
    copied: list[str] = []
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )
    monkeypatch.setattr(
        "ccusage_viz.watch.copy_command", lambda command: copied.append(command) or True
    )

    result = run_runtime_adjustment(
        replace(
            options(command="timeline"),
            chart=replace(
                options(command="timeline").chart,
                by=None,
                top=3,
                presentation=replace(
                    options(command="timeline").chart.presentation, theme="no-color"
                ),
            ),
        ),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
    )

    assert result is None
    assert copied == [
        "ccuv timeline --since 2026-01-01 --until 2026-01-14 --by agent --top 4 "
        "--no-watch --demo small --ascii"
    ]


def test_runtime_adjustment_normalizes_timeline_area_when_grouping_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    keys = iter(("b", "\n"))
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_runtime_adjustment(
        replace(
            options(command="timeline"),
            chart=replace(
                options(command="timeline").chart,
                by=None,
                presentation=replace(options(command="timeline").chart.presentation, style="area"),
            ),
        ),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
    )

    assert isinstance(result, RuntimeAdjustmentResult)
    assert result.options.chart.by == "agent"
    assert result.options.chart.presentation.style == "linear"


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_demo_snapshot_uses_requested_size_once_without_query_runner(
    size: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated: list[str] = []

    class Runner:
        def run(self, plan):
            raise AssertionError("demo must not invoke ccusage")

    def generate(selected, date_range):
        generated.append(selected)
        return ()

    monkeypatch.setattr("ccusage_viz.watch.generate_demo", generate)
    snapshot = load_snapshot(
        replace(
            options(command="timeline"),
            host=replace(options(command="timeline").host, demo_size=size),
        ),
        cast(QueryRunner, Runner()),
    )

    assert snapshot.records == ()
    assert snapshot.coverage == DateCoverage.from_interval(date(2026, 1, 1), date(2026, 1, 14))
    assert generated == [size]


def test_successful_empty_daily_query_still_records_requested_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Runner:
        def run(self, plan):
            from ccusage_viz.query.models import QueryResult

            return tuple(QueryResult(query.kind, {}) for query in plan.queries)

    monkeypatch.setattr("ccusage_viz.watch.parse_usage_records", lambda kind, data: ())
    snapshot = load_snapshot(
        replace(
            options(command="timeline"),
            host=replace(options(command="timeline").host, demo_size=None),
        ),
        cast(QueryRunner, Runner()),
    )

    assert snapshot.records == ()
    assert snapshot.coverage.covers(DateInterval(date(2026, 1, 1), date(2026, 1, 14)))


def test_snapshot_retains_daily_coverage_when_project_ranking_also_uses_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Runner:
        def run(self, plan):
            from ccusage_viz.query.models import QueryResult

            return tuple(QueryResult(query.kind, {}) for query in plan.queries)

    monkeypatch.setattr("ccusage_viz.watch.parse_usage_records", lambda kind, data: ())
    snapshot = load_snapshot(
        replace(
            options(command="ranking"),
            host=replace(options(command="ranking").host, demo_size=None),
        ),
        cast(QueryRunner, Runner()),
    )

    assert snapshot.coverage == DateCoverage.from_interval(date(2026, 1, 1), date(2026, 1, 14))
    assert snapshot.summary_notices == (
        Notice("notice.summary_excludes_session_agent", {"agent": "Codex"}),
    )


def test_demo_refresh_never_invokes_query_runner() -> None:
    class Runner:
        def run(self, plan):
            raise AssertionError("demo must not invoke ccusage")

    result = _refresh(
        options(),
        load_translator("en"),
        Terminal(100, 30, False, True),
        cast(QueryRunner, Runner()),
    )
    assert "Ranking" in result.chart
    assert result.notices == ()
    assert result.elapsed >= 0


@pytest.mark.skipif(os.name != "posix", reason="PTY smoke test is POSIX-only")
def test_demo_watch_reports_pause_immediately_and_restores_terminal() -> None:
    import pty
    import select
    import subprocess
    import termios
    import time

    master, slave = pty.openpty()
    env = {
        **os.environ,
        "COLUMNS": "100",
        "LINES": "30",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ccusage_viz",
            "ranking",
            "--demo",
            "small",
            "--interval",
            "5",
            "--ascii",
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        text=False,
        env=env,
        close_fds=True,
    )
    output = bytearray()
    deadline = time.monotonic() + 5
    try:
        while time.monotonic() < deadline and b"Ranking" not in output:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                output.extend(os.read(master, 8192))
        assert b"Ranking" in output

        os.write(master, b" ")
        pause_deadline = time.monotonic() + 1
        while time.monotonic() < pause_deadline and b"paused" not in output:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                output.extend(os.read(master, 8192))
        assert b"paused" in output

        os.write(master, b"\x03")
        assert process.wait(timeout=3) == 0
        while True:
            readable, _, _ = select.select([master], [], [], 0.1)
            if not readable:
                break
            try:
                output.extend(os.read(master, 8192))
            except OSError:
                break
        assert output.endswith((b"\n", b"\r\n"))
        after = termios.tcgetattr(slave)
        assert after[3] & termios.ICANON
        assert after[3] & termios.ECHO
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)
