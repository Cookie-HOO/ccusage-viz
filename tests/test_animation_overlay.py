from __future__ import annotations

from datetime import datetime

import pytest

from ccusage_viz.animation_overlay import (
    AnimationOverlayRuntime,
    ExecutionRecord,
    OverlayConfig,
    OverlayHistoryTableState,
    OverlayPlacement,
    _run_command,
    compose_overlay_row,
    format_execution_record,
    move_history_selection,
    normalized_lines,
    overlay_placements,
    render_history_table,
    sanitize_ansi,
)
from ccusage_viz.clock_overlay import main as clock_overlay_main
from ccusage_viz.formatting import strip_ansi


def test_clock_overlay_command_prints_localized_time_band(monkeypatch, capsys) -> None:
    class Clock:
        @classmethod
        def now(cls):
            from datetime import datetime

            return datetime(2026, 9, 29, 12, 30).astimezone()

    monkeypatch.setattr("ccusage_viz.clock_overlay.datetime", Clock)
    monkeypatch.setattr("ccusage_viz.clock_overlay.detect_language", lambda: "en")

    assert clock_overlay_main(["time-state"]) == 0
    assert capsys.readouterr().out.strip() == "🍜 On lunch break…"


def test_overlay_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        OverlayConfig(text="text", command="command")
    with pytest.raises(ValueError, match="position"):
        OverlayConfig(text="text", position="middle")
    with pytest.raises(ValueError, match="color"):
        OverlayConfig(text="text", color="orange")
    with pytest.raises(ValueError, match="five"):
        OverlayConfig(command="date", interval=4)


def test_sanitize_ansi_keeps_safe_foreground_and_strips_terminal_controls() -> None:
    value = "\x1b[1;31;44mred\x1b[0m\x1b]52;c;secret\x07\x1b[2Jdone"

    assert sanitize_ansi(value) == "\x1b[1;31mred\x1b[0mdone"
    assert sanitize_ansi("\x1b[31mred\x1b[0m", color="cyan") == "\x1b[36mred\x1b[0m"


def test_composition_respects_ansi_and_display_cell_offsets() -> None:
    row = "\x1b[31m汉字abcdef\x1b[0m"

    assert "OK" in compose_overlay_row(row, OverlayPlacement(0, 4, "OK"), width=10)
    assert "\x1b[31m" in compose_overlay_row(row, OverlayPlacement(0, 4, "OK"), width=10)


def test_composition_paints_overlay_over_the_animation_row() -> None:
    assert (
        strip_ansi(compose_overlay_row("abcdef", OverlayPlacement(0, 2, "TEXT"), width=6))
        == "abTEXT"
    )


def test_normalized_lines_limits_lines_and_width() -> None:
    assert normalized_lines("\nfirst\n\nsecond\nthird\nfourth\n", width=6) == (
        "first",
        "",
        "secon…",
    )
    assert normalized_lines("abcdef", width=1) == ("…",)


def _record(
    command: str,
    *,
    started_at: datetime = datetime(2026, 9, 29, 12, 34, 56),
    exit_code: int | None = 0,
    timed_out: bool = False,
) -> ExecutionRecord:
    return ExecutionRecord(
        command, started_at, 0.12, exit_code, timed_out, "hello", "", False, False
    )


def test_command_record_preserves_wall_clock_start_and_monotonic_duration(monkeypatch) -> None:
    wall_clock = datetime(2026, 9, 29, 12, 34, 56).astimezone()
    monotonic = iter((100.0, 100.25))

    class Clock:
        @classmethod
        def now(cls):
            return wall_clock

    monkeypatch.setattr("ccusage_viz.animation_overlay.datetime", Clock)
    monkeypatch.setattr("ccusage_viz.animation_overlay.time.monotonic", lambda: next(monotonic))
    monkeypatch.setattr(
        "ccusage_viz.animation_overlay.subprocess.run",
        lambda *args, **kwargs: type(
            "Completed", (), {"stdout": b"", "stderr": b"", "returncode": 0}
        )(),
    )

    record = _run_command("echo hello")

    assert record.started_at == wall_clock
    assert record.duration == 0.25


def test_history_table_selects_and_shows_time_and_duration_when_wide() -> None:
    first = _record("first 汉字 command")
    second = _record("second command", exit_code=1)
    state = OverlayHistoryTableState()

    table = render_history_table(
        (first, second), state, available_width=40, available_height=3, empty="empty"
    )

    assert table.selected is first
    assert "›" in table.body
    assert "time" in table.body
    assert "took" in table.body
    assert "12:34:56" in table.body
    assert "0.12s" in table.body
    assert "first" in table.body
    assert "exit 1" not in table.body
    move_history_selection(state, (first, second), 1)
    table = render_history_table(
        (first, second), state, available_width=40, available_height=3, empty="empty"
    )
    assert table.selected is second
    assert "exit 1" in table.body


def test_history_table_favors_command_width_over_output_width() -> None:
    table = render_history_table(
        (
            ExecutionRecord(
                "command-with-many-details-that-should-be-truncated",
                datetime(2026, 9, 29, 12, 34, 56),
                0.12,
                1,
                False,
                "",
                "output-marker-is-visible",
                False,
                False,
            ),
        ),
        OverlayHistoryTableState(),
        available_width=60,
        available_height=3,
        empty="empty",
    )

    header, _, entry = table.body.splitlines()
    command_start = header.index("command")
    output_start = header.index("output")
    command_width = output_start - command_start - 1
    output_width = 60 - output_start

    assert command_width > output_width
    assert "command-with-many-d…" in entry
    assert "stderr: outpu…" in entry
    assert all(len(strip_ansi(row)) <= 60 for row in table.body.splitlines())


@pytest.mark.parametrize(
    ("width", "has_summary"),
    [(23, True), (22, True), (18, False), (16, False)],
)
def test_history_table_preserves_timing_columns_responsively(width: int, has_summary: bool) -> None:
    table = render_history_table(
        (_record("command"),),
        OverlayHistoryTableState(),
        available_width=width,
        available_height=3,
        empty="empty",
    )

    assert "time" in table.body
    assert "12:34:56" in table.body
    assert "took" in table.body
    assert "0.12s" in table.body
    header, _, entry = table.body.splitlines()
    assert ("su" in header) is has_summary
    assert ("…" in entry) is has_summary
    assert all(len(strip_ansi(row)) <= width for row in table.body.splitlines())


def test_history_table_copy_text_preserves_full_diagnostics() -> None:
    record = ExecutionRecord(
        "echo hello", datetime(2026, 9, 29, 12, 34, 56), 30.0, None, True, "out", "err", True, True
    )

    assert format_execution_record(record) == (
        "$ echo hello\ntimed out · 30.00s\nstdout (truncated): out\nstderr (truncated): err"
    )


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        ("top-left", (0, 0)),
        ("top-center", (0, 4)),
        ("top-right", (0, 8)),
        ("bottom-left", (5, 0)),
        ("bottom-center", (5, 4)),
        ("bottom-right", (5, 8)),
    ],
)
def test_placements_honor_six_anchors(position: str, expected: tuple[int, int]) -> None:
    placement = overlay_placements(("abc",), width=11, height=6, position=position)

    assert (placement[0].row, placement[0].column) == expected


def test_placements_crop_displaced_text_without_splitting_wide_glyphs() -> None:
    left = overlay_placements(("ab汉cd",), width=5, height=1, position="top-left", offset_x=-1)
    right = overlay_placements(("ab汉cd",), width=5, height=1, position="top-left", offset_x=2)

    assert left == (OverlayPlacement(0, 0, "b汉cd"),)
    assert right == (OverlayPlacement(0, 2, "ab"),)


def test_placements_hide_outside_vertical_bounds_without_clamping_offsets() -> None:
    runtime = AnimationOverlayRuntime(OverlayConfig(text="hello", position="top-left"))
    try:
        runtime.adjust_offset(dy=-1)
        assert runtime.placements(width=10, height=2) == ()

        runtime.adjust_offset(dy=1)
        assert runtime.placements(width=10, height=2) == (OverlayPlacement(0, 0, "hello"),)

        runtime.adjust_offset(dx=-10)
        assert runtime.placements(width=10, height=2) == ()
        assert runtime.presentation.offset_x == -10

        runtime.reset_offset()
        assert runtime.presentation.position == "top-left"
        assert runtime.presentation.offset_x == runtime.presentation.offset_y == 0
    finally:
        runtime.close()
