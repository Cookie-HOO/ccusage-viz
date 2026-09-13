from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from typing import cast

import pytest

from ccusage_viz.domain import Notice
from ccusage_viz.formatting import display_width, strip_ansi
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import CommandOptions, DateRange
from ccusage_viz.query.client import QueryRunner
from ccusage_viz.terminal import InteractiveScreen, Terminal
from ccusage_viz.watch import (
    AppearancePickerResult,
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
    run_appearance_picker,
)


def options(*, command: str = "ranking", demo: str | None = "small") -> CommandOptions:
    return CommandOptions(
        command=command,
        date_range=DateRange(date(2026, 1, 1), date(2026, 1, 14), None),
        by="project" if command == "ranking" else "total",
        top=10 if command == "ranking" else 3,
        show_other=False,
        split_cache=False,
        agents=(),
        models=(),
        projects=(),
        watch=None,
        demo=demo,
        ccusage_bin="/not/invoked",
        timeout=2,
        no_color=True,
        ascii=True,
    )


def test_watch_paint_places_footer_last_without_refresh_newline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint(
        "summary\nchart\n",
        "status",
        "q quit · r refresh · Space pause",
        ("! warning one", "! warning two"),
    )
    assert capsys.readouterr().out == (
        "\x1b[H\x1b[2Jstatus\nsummary\nchart\n"
        "! warning one\n! warning two\nq quit · r refresh · Space pause"
    )


def test_watch_paint_pads_controls_to_fixed_final_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _paint("chart", "status", ("adjustment", "controls"), ("warning",), height=6)
    assert capsys.readouterr().out == "\x1b[H\x1b[2Jstatus\nchart\nwarning\n\nadjustment\ncontrols"


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
    colored = _controls_line("q quit · r refresh · Space pause", width=20, color=True)
    plain = _controls_line("q quit · r refresh · Space pause", width=20, color=False)

    assert colored.startswith("\x1b[2m") and colored.endswith("\x1b[0m")
    assert display_width(colored) == 20
    assert plain == "q quit · r refresh ·"
    assert "\x1b[" not in plain


def test_render_keeps_notices_separate_from_chart() -> None:
    rendered = _render(
        options(),
        load_translator("en"),
        Terminal(100, 30, False, True),
        (),
        (Notice("notice.project_agent_omitted", {"agent": "Codex"}),),
    )

    assert rendered.notices == ("Codex omitted: ccusage does not expose project data",)
    assert rendered.notices[0] not in rendered.chart
    lines = rendered.chart.splitlines()
    assert lines[0] == "Today 0; vs yesterday unchanged; vs last We unchanged"
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


def test_appearance_picker_hides_timeline_area_when_grouped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = iter(("j", "j", "j", "\n"))
    rendered_styles: list[str] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )
    original_render = _render

    def capture_render(current, *args, **kwargs):
        rendered_styles.append(current.style)
        return original_render(current, *args, **kwargs)

    monkeypatch.setattr("ccusage_viz.watch._render", capture_render)
    result = run_appearance_picker(
        replace(options(command="timeline", demo="small"), by="model", style="linear"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
    )

    assert isinstance(result, AppearancePickerResult)
    assert rendered_styles == ["linear", "step", "stem", "linear"]


@pytest.mark.parametrize(
    ("command", "by", "keys", "expected"),
    [
        (
            "timeline",
            "total",
            ("b", "+", "o", "u", "\n"),
            {"by": "agent", "top": 4, "show_other": True, "no_summary": True},
        ),
        (
            "ranking",
            "project",
            ("b", "+", "o", "u", "\n"),
            {"by": "agent", "top": 1, "show_other": True, "no_summary": True},
        ),
        (
            "stack",
            "total",
            ("c", "u", "\n"),
            {"split_cache": True, "no_summary": True},
        ),
        ("calendar", "total", ("u", "\n"), {"no_summary": True}),
    ],
)
def test_appearance_picker_adjusts_display_options_from_retained_snapshot(
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
    current = replace(options(command=command), by=by)

    result = run_appearance_picker(
        current,
        load_translator("en"),
        snapshot,
        cast(InteractiveScreen, Screen()),
        adjust_display=True,
    )

    assert isinstance(result, AppearancePickerResult)
    assert all(getattr(result.options, field) == value for field, value in expected.items())
    assert rendered_snapshots and all(item is snapshot for item in rendered_snapshots)
    assert result.options.agents == current.agents
    assert result.options.models == current.models
    assert result.options.projects == current.projects


def test_project_adjustment_explains_missing_retained_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paints: list[tuple[object, ...]] = []

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            paints.append(args)

    keys = iter(("b", "b", "b", "q"))
    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    result = run_appearance_picker(
        options(command="timeline"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
        adjust_display=True,
    )

    assert result is None
    assert any("project data is not in this preview" in str(args[1]) for args in paints)


def test_appearance_picker_copy_uses_adjusted_display_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    keys = iter(("b", "+", "o", "y", "q"))
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

    result = run_appearance_picker(
        replace(options(command="timeline"), by="total", top=3),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
        adjust_display=True,
    )

    assert result is None
    assert copied == [
        "ccusage-viz timeline --since 2026-01-01 --until 2026-01-14 --by agent --top 4 "
        "--show-other --demo small --ascii --no-color"
    ]


def test_appearance_picker_normalizes_timeline_area_when_grouping_changes(
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

    result = run_appearance_picker(
        replace(options(command="timeline"), by="total", style="area"),
        load_translator("en"),
        UsageSnapshot((), (), 0.25),
        cast(InteractiveScreen, Screen()),
        adjust_display=True,
    )

    assert isinstance(result, AppearancePickerResult)
    assert result.options.by == "agent"
    assert result.options.style == "linear"


def test_appearance_picker_cycles_theme_and_style_with_retained_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered_appearances: list[tuple[str, str]] = []
    keys = iter(("n", "j", "k", "p", "\n"))

    class Screen:
        def paint(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr("ccusage_viz.watch._input_mode", nullcontext)
    monkeypatch.setattr("ccusage_viz.watch._read_key", lambda timeout: next(keys))
    monkeypatch.setattr(
        "ccusage_viz.watch.inspect_terminal",
        lambda *args, **kwargs: Terminal(100, 30, True, True),
    )

    original_render = _render

    def capture_render(current, *args, **kwargs):
        rendered_appearances.append((current.color_scheme, current.style))
        return original_render(current, *args, **kwargs)

    monkeypatch.setattr("ccusage_viz.watch._render", capture_render)
    current = replace(options(command="timeline", demo="small"), pick=True)
    snapshot = UsageSnapshot((), (), 0.25)

    result = run_appearance_picker(
        current,
        load_translator("en"),
        snapshot,
        cast(InteractiveScreen, Screen()),
    )

    assert isinstance(result, AppearancePickerResult)
    assert result.options.color_scheme == "classic"
    assert result.options.style == "linear"
    assert result.options.demo == "small"
    assert rendered_appearances == [
        ("classic", "linear"),
        ("vivid", "linear"),
        ("vivid", "step"),
        ("vivid", "linear"),
        ("classic", "linear"),
    ]


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
        replace(options(command="timeline"), demo=size),
        cast(QueryRunner, Runner()),
    )

    assert snapshot.records == ()
    assert generated == [size]


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
def test_appearance_picker_navigates_wraps_and_restores_terminal() -> None:
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
        "TERM": "xterm-256color",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    env.pop("NO_COLOR", None)
    process = subprocess.Popen(  # ty: ignore[no-matching-overload]
        [
            sys.executable,
            "-m",
            "ccusage_viz",
            "timeline",
            "--pick",
            "--demo",
            "small",
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

    def read_until(text: bytes, *, after: int = 0, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and text not in output[after:]:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                output.extend(os.read(master, 8192))
        assert text in output[after:]

    try:
        read_until(
            b"THEME \xc2\xb7 1/10 \xc2\xb7 classic \xc2\xb7 STYLE \xc2\xb7 1/4 \xc2\xb7 linear"
        )
        previous_length = len(output)
        os.write(master, b"p")
        read_until(
            b"THEME \xc2\xb7 10/10 \xc2\xb7 mono \xc2\xb7 STYLE \xc2\xb7 1/4 \xc2\xb7 linear",
            after=previous_length,
        )
        previous_length = len(output)
        os.write(master, b"n")
        read_until(
            b"THEME \xc2\xb7 1/10 \xc2\xb7 classic \xc2\xb7 STYLE \xc2\xb7 1/4 \xc2\xb7 linear",
            after=previous_length,
        )

        os.write(master, b"q")
        exit_deadline = time.monotonic() + 3
        while process.poll() is None and time.monotonic() < exit_deadline:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                output.extend(os.read(master, 8192))
        assert process.poll() == 0
        while True:
            readable, _, _ = select.select([master], [], [], 0.1)
            if not readable:
                break
            try:
                output.extend(os.read(master, 8192))
            except OSError:
                break
        assert output.endswith((b"\n", b"\r\n"))
        assert b"\x1b[38;5;" in output
        assert b"\x1b[38;2;" not in output
        assert b"\x1b[48;" not in output
        after = termios.tcgetattr(slave)
        assert after[3] & termios.ICANON
        assert after[3] & termios.ECHO
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="PTY smoke test is POSIX-only")
def test_appearance_picker_confirmation_hands_demo_snapshot_to_watch() -> None:
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
        "TERM": "xterm-256color",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    env.pop("NO_COLOR", None)
    process = subprocess.Popen(  # ty: ignore[no-matching-overload]
        [
            sys.executable,
            "-m",
            "ccusage_viz",
            "timeline",
            "--pick",
            "--theme",
            "nord",
            "--demo",
            "small",
            "--watch",
            "10",
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

    def read_until(text: bytes, *, after: int = 0, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and text not in output[after:]:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                output.extend(os.read(master, 8192))
        assert text in output[after:]

    try:
        read_until(b"THEME \xc2\xb7 8/10 \xc2\xb7 nord \xc2\xb7 STYLE \xc2\xb7 1/4 \xc2\xb7 linear")
        previous_length = len(output)
        os.write(master, b"\r")
        read_until(b"refresh every 10s", after=previous_length)
        assert b"DEMO DATA \xc2\xb7 small" in output[previous_length:]

        os.write(master, b"q")
        exit_deadline = time.monotonic() + 3
        while process.poll() is None and time.monotonic() < exit_deadline:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                output.extend(os.read(master, 8192))
        assert process.poll() == 0
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
            "--watch",
            "2",
            "--ascii",
            "--no-color",
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

        os.write(master, b"q")
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
