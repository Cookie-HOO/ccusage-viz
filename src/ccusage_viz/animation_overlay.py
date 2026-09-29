"""Run-local text and command overlays for animation hosts.

This module intentionally owns no terminal input, rendering loop, or pane lifecycle.
Hosts poll :class:`AnimationOverlayRuntime` and paint its normalized rows.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from ccusage_viz.formatting import (
    clip_width,
    display_width,
    pad_width,
    replace_width,
    slice_width,
    strip_ansi,
    truncate_width,
)
from ccusage_viz.i18n import Translator
from ccusage_viz.lifecycle import FixedIntervalScheduler

OVERLAY_POSITIONS = (
    "top-left",
    "top-center",
    "top-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)
OVERLAY_COLORS = (
    "auto",
    "white",
    "bright-white",
    "cyan",
    "bright-cyan",
    "green",
    "bright-green",
    "yellow",
    "bright-yellow",
    "magenta",
    "bright-magenta",
    "red",
    "bright-red",
    "blue",
    "bright-blue",
    "black",
    "bright-black",
)
INTERVAL_PRESETS = (5.0, 10.0, 30.0, 60.0, 300.0, 900.0, 3600.0)
MAX_OUTPUT_BYTES = 4 * 1024
MAX_HISTORY = 20
COMMAND_TIMEOUT_SECONDS = 30.0

SourceMode = Literal["text", "command", "time-band"]


@dataclass(frozen=True, slots=True)
class OverlayConfig:
    text: str | None = None
    command: str | None = None
    time_band: bool = False
    position: str = "bottom-center"
    color: str = "auto"
    interval: float = 60.0
    max_width: int = 40

    def __post_init__(self) -> None:
        if sum(source is not None for source in (self.text, self.command)) + self.time_band > 1:
            raise ValueError("text, command, and time-band are mutually exclusive")
        if self.position not in OVERLAY_POSITIONS:
            raise ValueError(f"unsupported overlay position: {self.position}")
        if self.color not in OVERLAY_COLORS:
            raise ValueError(f"unsupported overlay color: {self.color}")
        if self.interval < 5 or not float(self.interval) < float("inf"):
            raise ValueError("overlay interval must be finite and at least five seconds")
        if self.max_width < 1:
            raise ValueError("overlay max width must be positive")

    @property
    def mode(self) -> SourceMode | None:
        if self.text is not None:
            return "text"
        if self.command is not None:
            return "command"
        if self.time_band:
            return "time-band"
        return None


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    command: str
    started_at: datetime
    duration: float
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool


@dataclass(slots=True)
class OverlayHistoryTableState:
    """Run-local selection and dimensions for one command-history table."""

    selected: ExecutionRecord | None = None
    selected_index: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OverlayHistoryTable:
    """Rendered history rows and the record selected by the active table."""

    body: str
    selected: ExecutionRecord | None


@dataclass(frozen=True, slots=True)
class OverlayPlacement:
    row: int
    column: int
    text: str


@dataclass(slots=True)
class OverlayPresentation:
    """Mutable, run-local presentation settings derived from an overlay config."""

    position: str
    color: str
    max_width: int
    offset_x: int = 0
    offset_y: int = 0


_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_CONTROL = re.compile(
    r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|P.*?\x1b\\|\[[0-?]*[ -/]*[@-~]|[()][0-9A-Za-z])",
    re.DOTALL,
)
_SAFE_STYLE = {0, 1, 2, 3, 4, 22, 23, 24, 39}
_FOREGROUNDS = {*range(30, 38), *range(90, 98)}
_ANSI_FOREGROUNDS = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
    "bright-black": 90,
    "bright-red": 91,
    "bright-green": 92,
    "bright-yellow": 93,
    "bright-blue": 94,
    "bright-magenta": 95,
    "bright-cyan": 96,
    "bright-white": 97,
}


def sanitize_ansi(value: str, *, color: str = "auto") -> str:
    """Keep only safe SGR foreground/style sequences from command output."""
    cleaned = (
        _CONTROL.sub(lambda match: match.group() if _SGR.fullmatch(match.group()) else "", value)
        .replace("\r", "")
        .replace("\t", "")
    )
    output: list[str] = []
    position = 0
    selected = _ANSI_FOREGROUNDS.get(color)
    for match in _SGR.finditer(cleaned):
        output.append(cleaned[position : match.start()])
        values = [int(item) for item in match.group(1).split(";") if item] or [0]
        safe = [value for value in values if value in _SAFE_STYLE]
        foregrounds = [value for value in values if value in _FOREGROUNDS]
        if selected is not None and 0 not in safe:
            safe = [value for value in safe if value != 39]
            safe.append(selected)
        elif foregrounds:
            safe.extend(foregrounds)
        if safe:
            output.append(f"\x1b[{';'.join(map(str, safe))}m")
        position = match.end()
    output.append(cleaned[position:])
    return "".join(output)


def normalized_lines(value: str, *, width: int, color: str = "auto") -> tuple[str, ...]:
    """Produce at most three safe, non-wrapping display rows."""
    rows = sanitize_ansi(value, color=color).splitlines()
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    if len(rows) > 3:
        rows = [*rows[:2], rows[2] + "…"]
    return tuple(_truncate_line(row, width) for row in rows)


def _truncate_line(value: str, width: int) -> str:
    result = truncate_width(value, width)
    return f"{result}\x1b[0m" if "\x1b[" in result and not result.endswith("\x1b[0m") else result


def compose_overlay_row(row: str, placement: OverlayPlacement, *, width: int) -> str:
    """Replace a display-cell span without splitting ANSI sequences or wide glyphs."""

    return replace_width(row, placement.column, placement.text, width=width)


def unbounded_overlay_placements(
    lines: tuple[str, ...],
    *,
    width: int,
    height: int,
    position: str,
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[OverlayPlacement, ...]:
    """Place rows at an anchor without clipping them to the source viewport."""
    if width < 1 or not lines:
        return ()
    vertical, horizontal = position.split("-", 1)
    start = (0 if vertical == "top" else height - len(lines)) + offset_y
    places: list[OverlayPlacement] = []
    for offset, line in enumerate(lines):
        line_width = display_width(line)
        if horizontal == "left":
            column = offset_x
        elif horizontal == "center":
            column = (width - line_width) // 2 + offset_x
        else:
            column = width - line_width + offset_x
        places.append(OverlayPlacement(start + offset, column, line))
    return tuple(places)


def clip_overlay_placements(
    placements: tuple[OverlayPlacement, ...], *, width: int, height: int
) -> tuple[OverlayPlacement, ...]:
    """Clip placements to a display-cell canvas without splitting wide glyphs."""
    if width < 1:
        return ()
    visible: list[OverlayPlacement] = []
    for placement in placements:
        if not 0 <= placement.row < height:
            continue
        text_width = display_width(placement.text)
        start = max(0, -placement.column)
        available = min(text_width - start, width - max(0, placement.column))
        text = slice_width(placement.text, start, available)
        if text:
            visible.append(OverlayPlacement(placement.row, max(0, placement.column), text))
    return tuple(visible)


def overlay_placements(
    lines: tuple[str, ...],
    *,
    width: int,
    height: int,
    position: str,
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[OverlayPlacement, ...]:
    """Place rows at their anchor, cropping any portion shifted offscreen."""
    return clip_overlay_placements(
        unbounded_overlay_placements(
            lines,
            width=width,
            height=height,
            position=position,
            offset_x=offset_x,
            offset_y=offset_y,
        ),
        width=width,
        height=height,
    )


def time_band_key(wall: datetime) -> str:
    """Return the localized time-band key for a local wall-clock value."""
    hour = wall.hour
    if hour < 6:
        return "dashboard.clock_sleep"
    if hour < 9:
        return "dashboard.clock_morning"
    if hour < 12:
        return "dashboard.clock_work"
    if hour < 14:
        return "dashboard.clock_lunch"
    if hour < 18:
        return "dashboard.clock_work"
    return "dashboard.clock_evening"


def next_time_band_boundary(wall: datetime) -> datetime:
    """Return the next local time-band boundary after ``wall``."""
    for hour in (6, 9, 12, 14, 18, 24):
        if wall.hour < hour:
            if hour == 24:
                return (wall + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return wall.replace(hour=hour, minute=0, second=0, microsecond=0)
    raise AssertionError("local hour must be in range")


def _decode_capped(value: bytes) -> tuple[str, bool]:
    return value[:MAX_OUTPUT_BYTES].decode(errors="replace"), len(value) > MAX_OUTPUT_BYTES


def _run_command(command: str) -> ExecutionRecord:
    started_at = datetime.now().astimezone()
    started = time.monotonic()
    shell = os.environ.get("SHELL") or ("cmd.exe" if os.name == "nt" else "/bin/sh")
    args = [shell, "/c" if os.name == "nt" else "-c", command]
    try:
        completed = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        stdout, stdout_truncated = _decode_capped(completed.stdout)
        stderr, stderr_truncated = _decode_capped(completed.stderr)
        return ExecutionRecord(
            command,
            started_at,
            time.monotonic() - started,
            completed.returncode,
            False,
            stdout,
            stderr,
            stdout_truncated,
            stderr_truncated,
        )
    except subprocess.TimeoutExpired as error:
        stdout, stdout_truncated = _decode_capped(error.stdout or b"")
        stderr, stderr_truncated = _decode_capped(error.stderr or b"")
        return ExecutionRecord(
            command,
            started_at,
            time.monotonic() - started,
            None,
            True,
            stdout,
            stderr,
            stdout_truncated,
            stderr_truncated,
        )
    except OSError as error:
        return ExecutionRecord(
            command,
            started_at,
            time.monotonic() - started,
            None,
            False,
            "",
            str(error),
            False,
            False,
        )


def format_execution_record(record: ExecutionRecord) -> str:
    """Return complete diagnostic text for one command execution."""

    outcome = "timed out" if record.timed_out else f"exit {record.exit_code}"
    stdout = record.stdout or "(no stdout)"
    stderr = record.stderr or "(no stderr)"
    return "\n".join(
        (
            f"$ {record.command}",
            f"{outcome} · {record.duration:.2f}s",
            f"stdout{' (truncated)' if record.stdout_truncated else ''}: {stdout}",
            f"stderr{' (truncated)' if record.stderr_truncated else ''}: {stderr}",
        )
    )


def _history_outcome(record: ExecutionRecord) -> str:
    if record.timed_out:
        return "timeout"
    if record.exit_code == 0:
        return "OK"
    return f"exit {record.exit_code}"


def _history_cell(value: str) -> str:
    return " ".join(strip_ansi(value).replace("\r", "").splitlines()).strip()


def render_history_table(
    records: tuple[ExecutionRecord, ...],
    state: OverlayHistoryTableState,
    *,
    available_width: int,
    available_height: int,
    empty: str,
) -> OverlayHistoryTable:
    """Render a selectable, width-safe command-history table."""

    width = max(1, available_width)
    visible = min(len(records), max(1, available_height - 2))
    if not records:
        state.selected = None
        state.selected_index = 0
        state.offset = 0
        return OverlayHistoryTable(clip_width(empty, width), None)

    if state.selected in records:
        selected_index = records.index(state.selected)
    else:
        selected_index = min(max(0, state.selected_index), len(records) - 1)
        state.selected = records[selected_index]
    state.selected_index = selected_index
    state.offset = min(max(0, state.offset), max(0, len(records) - visible))
    if selected_index < state.offset:
        state.offset = selected_index
    elif selected_index >= state.offset + visible:
        state.offset = selected_index - visible + 1

    # Time and elapsed duration identify each execution, so preserve both at
    # every usable history width.  Wider hosts get the complete five-column
    # table; narrower ones trade command/output detail for the timing fields.
    compact_result_width = 2
    time_width = 8
    duration_width = 5
    if width >= 28:
        result_width = 7
        detail_width = width - (2 + result_width + time_width + duration_width + 4)
        command_width = max(1, detail_width * 3 // 5)
        output_width = max(1, detail_width - command_width)
        layout = "full"
        columns = [
            ("result", result_width),
            ("time", time_width),
            ("took", duration_width),
            ("command", command_width),
            ("output", output_width),
        ]
    elif width >= 18:
        result_width = compact_result_width
        summary_width = max(0, width - (2 + time_width + duration_width + result_width + 3))
        layout = "compact"
        columns = [("time", time_width), ("took", duration_width), ("rs", result_width)]
        if summary_width:
            columns.append(("summary", summary_width))
    else:
        result_width = compact_result_width
        layout = "timing"
        columns = [("time", time_width), ("took", duration_width), ("rs", result_width)]
    header = "  " + " ".join(pad_width(label, column_width) for label, column_width in columns)
    rows = [clip_width(header, width), "─" * width]
    for index, record in enumerate(
        records[state.offset : state.offset + visible], start=state.offset
    ):
        output = _history_cell(record.stdout)
        if record.stderr:
            output = (
                f"{output} · stderr: {_history_cell(record.stderr)}"
                if output
                else (f"stderr: {_history_cell(record.stderr)}")
            )
        if record.stdout_truncated or record.stderr_truncated:
            output = f"{output} (truncated)".strip()
        outcome = pad_width(truncate_width(_history_outcome(record), result_width), result_width)
        timing = [
            pad_width(record.started_at.strftime("%H:%M:%S"), time_width),
            pad_width(truncate_width(f"{record.duration:.2f}s", duration_width), duration_width),
        ]
        if layout == "full":
            cells = [
                outcome,
                *timing,
                pad_width(
                    truncate_width(_history_cell(record.command), command_width), command_width
                ),
                truncate_width(output or "(no output)", output_width),
            ]
        elif layout == "compact":
            summary = f"{_history_cell(record.command)} · {output or '(no output)'}"
            cells = [*timing, outcome]
            if summary_width:
                cells.append(truncate_width(summary, summary_width))
        else:
            cells = [*timing, outcome]
        row = f"{'›' if index == selected_index else ' '} " + " ".join(cells)
        rows.append(clip_width(row, width))
    return OverlayHistoryTable("\n".join(rows), state.selected)


def move_history_selection(
    state: OverlayHistoryTableState, records: tuple[ExecutionRecord, ...], step: int
) -> None:
    """Move selection through newest-first records without crossing boundaries."""

    if not records:
        return
    current = records.index(state.selected) if state.selected in records else state.selected_index
    state.selected_index = min(max(0, current + step), len(records) - 1)
    state.selected = records[state.selected_index]


class AnimationOverlayRuntime:
    """Pollable command runtime with generation-safe visual output."""

    def __init__(self, config: OverlayConfig | None = None) -> None:
        self.config = config or OverlayConfig()
        self.presentation = OverlayPresentation(
            self.config.position, self.config.color, self.config.max_width
        )
        self.text_draft = self.config.text or ""
        self.command_draft = self.config.command or ""
        self.output = self.config.text or ""
        self.history: deque[ExecutionRecord] = deque(maxlen=MAX_HISTORY)
        self._generation = 0
        self._future: Future[ExecutionRecord] | None = None
        self._future_generation = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccuv-overlay")
        self._scheduler: FixedIntervalScheduler | None = None
        self.next_due: float | None = None
        self._activate(now=time.monotonic())

    def _activate(self, *, now: float) -> None:
        self._scheduler = (
            FixedIntervalScheduler(self.config.interval, now=now)
            if self.config.command is not None
            else None
        )
        self.next_due = now if self.config.command is not None else None

    def apply(self, config: OverlayConfig, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self._generation += 1
        self.config = config
        self.presentation = OverlayPresentation(config.position, config.color, config.max_width)
        self.text_draft = config.text if config.text is not None else self.text_draft
        self.command_draft = config.command if config.command is not None else self.command_draft
        self.output = config.text or ""
        self._activate(now=current)

    def poll(
        self,
        *,
        now: float | None = None,
        translator: Translator | None = None,
        wall: datetime | None = None,
    ) -> bool:
        """Advance command/time-band output and return whether rendered output changed."""
        current = time.monotonic() if now is None else now
        changed = False
        if self.config.time_band:
            if translator is None:
                raise ValueError("time-band overlays require a translator")
            local_wall = datetime.now().astimezone() if wall is None else wall
            output = translator.text(time_band_key(local_wall))
            if output != self.output:
                self.output = output
                changed = True
            boundary = next_time_band_boundary(local_wall)
            self.next_due = current + max(0.0, (boundary - local_wall).total_seconds())
        future = self._future
        if future is not None and future.done():
            self._future = None
            try:
                record = future.result()
            except Exception as error:
                record = ExecutionRecord(
                    self.config.command or "",
                    datetime.now().astimezone(),
                    0.0,
                    None,
                    False,
                    "",
                    str(error),
                    False,
                    False,
                )
            self.history.appendleft(record)
            if self._future_generation == self._generation:
                self.output = record.stdout
                changed = True
        if self.config.command is not None:
            due = self.next_due is not None and current >= self.next_due
            if due:
                if self._scheduler is not None:
                    self._scheduler.due(now=current)
                    self.next_due = self._scheduler.next_opportunity
                if self._future is None:
                    self._future_generation = self._generation
                    self._future = self._executor.submit(_run_command, self.config.command)
        return changed

    def cycle_interval(self, step: int = 1, *, now: float | None = None) -> bool:
        """Cycle a command interval and rebuild its fixed baseline."""
        if self.config.command is None:
            return False
        index = min(
            range(len(INTERVAL_PRESETS)),
            key=lambda item: abs(INTERVAL_PRESETS[item] - self.config.interval),
        )
        config = replace(
            self.config,
            interval=INTERVAL_PRESETS[(index + step) % len(INTERVAL_PRESETS)],
        )
        self.apply(config, now=now)
        return True

    def apply_draft(self, mode: SourceMode, value: str, *, now: float | None = None) -> None:
        """Commit one retained source draft as the active declarative overlay."""
        if mode == "text":
            self.text_draft = value
            self.apply(replace(self.config, text=value, command=None, time_band=False), now=now)
        elif mode == "command":
            self.command_draft = value
            self.apply(replace(self.config, text=None, command=value, time_band=False), now=now)
        else:
            raise ValueError("time-band overlays do not have an editable source draft")

    def cycle_position(self, step: int = 1) -> None:
        """Move through anchor positions without changing the declared config."""
        index = OVERLAY_POSITIONS.index(self.presentation.position)
        self.presentation.position = OVERLAY_POSITIONS[(index + step) % len(OVERLAY_POSITIONS)]

    def adjust_offset(self, *, dx: int = 0, dy: int = 0) -> None:
        """Accumulate an unrestricted, run-local display-cell offset."""
        self.presentation.offset_x += dx
        self.presentation.offset_y += dy

    def reset_offset(self) -> None:
        """Return to the selected anchor without changing it."""
        self.presentation.offset_x = 0
        self.presentation.offset_y = 0

    def lines(self, *, available_width: int) -> tuple[str, ...]:
        return normalized_lines(
            self.output,
            width=min(self.presentation.max_width, available_width),
            color=self.presentation.color,
        )

    def unbounded_placements(self, *, width: int, height: int) -> tuple[OverlayPlacement, ...]:
        """Return source-viewport-relative placements without clipping."""
        return unbounded_overlay_placements(
            self.lines(available_width=self.presentation.max_width),
            width=width,
            height=height,
            position=self.presentation.position,
            offset_x=self.presentation.offset_x,
            offset_y=self.presentation.offset_y,
        )

    def placements(self, *, width: int, height: int) -> tuple[OverlayPlacement, ...]:
        """Return safe, visible placements for the current runtime presentation."""
        return overlay_placements(
            self.lines(available_width=width),
            width=width,
            height=height,
            position=self.presentation.position,
            offset_x=self.presentation.offset_x,
            offset_y=self.presentation.offset_y,
        )

    def history_text(self, *, empty: str = "No command executions yet.") -> str:
        """Return the bounded command record history as a readable text document."""
        if not self.history:
            return empty
        return "\n\n".join(format_execution_record(record) for record in self.history)

    def close(self) -> None:
        self._generation += 1
        self._executor.shutdown(wait=False, cancel_futures=True)
