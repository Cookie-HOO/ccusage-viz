# Custom Ranking Scrollbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persistent overflow scrollbars with draggable thumbs on Dashboard Custom historical Ranking panes only.

**Architecture:** Add pure scrollbar geometry/grab mapping and optional viewport gutter rendering. Introduce separate button-motion events and enable terminal motion reporting only during captured drags. Dashboard uses displayed-frame geometry to arbitrate scrollbar input before clicks and batch repainting without touching data lifecycles.

**Tech Stack:** Existing Python 3.11+, SGR terminal input, pytest, Ruff, uv; no dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-ranking-scrollbar-design.md`

## Global Constraints

- Preserve existing one-line wheel work and all unrelated working-tree changes.
- Overflow bars are always visible, never hover-only or timer-hidden.
- No query/refresh/config/history work from scrollbar input.
- No new drag timers, inertial motion, key bindings, or behavior in standalone/native/monitor charts.
- Test before implementation, then execute inline in the current session.

---

### Task 1: Pure scrollbar and optional viewport painting

**Files:** Create `src/ccusage_viz/scrollbar.py`, `tests/test_scrollbar.py`; modify `render/ranking_viewport.py`, `render/custom_ranking_viewport.py`, `tui.py` only at the Dashboard Custom renderer boundary; add renderer tests in `tests/test_custom_ranking_scroll.py`.

**Interfaces:** `Scrollbar(column, top, height, total_rows, visible_rows, offset)` exposes `thumb_size`, `thumb_top`, `maximum_offset`, `travel`, `contains(x, y)`, `page_offset(y)`. `ScrollbarGrab(bar, pointer_y)` exposes `offset_at(pointer_y)`.

- [x] Write pure tests and verify missing-module failure:

```python
bar = Scrollbar(79, 3, 20, 100, 20, 0)
assert bar.thumb_size == 4
assert bar.thumb_top == 3
assert ScrollbarGrab(bar, 4).offset_at(4) == 0
assert ScrollbarGrab(bar, 4).offset_at(100) == 80
```

- [x] Implement bounded integer proportional mapping, preserving the initial offset on a stationary grab, endpoints, page clicks, and zero travel.
- [x] Extend `RankingViewport` with `body_top` and optional `scrollbar` metadata; expose opt-in `scrollbar=True` in `render_custom_ranking_viewport`, used only by Dashboard. Reserve one column, render current content at reduced width, append styled track/thumb only to body rows; translate metadata by summary rows. Keep ordinary tests/callers unwindowed unless opting in.
- [x] Test persistent idle overflow, exact-fit disappearance, descriptions/spacing, fixed chrome, ASCII/palette, tiny sizes, wheel-thumb synchronization, and clipping of copy/link geometry. Run `uv run pytest tests/test_scrollbar.py tests/test_custom_ranking_scroll.py -q`.

### Task 2: Safe drag motion input

**Files:** Modify `src/ccusage_viz/tui_input.py`, `tests/test_tui_input.py`.

**Interfaces:** `MouseMotionEvent(button, x, y, modifiers)` is distinct from `MouseEvent`; `InputDecoder.drain_mouse_motion()` drains consecutive complete primary-button motions; `set_mouse_motion_reporting(enabled: bool)` writes `1002` mode transitions.

- [x] Write decoding, fragmented motion, invalid/horizontal/wheel exclusion, batch-boundary and cleanup tests before adding the event.

```python
decoder.feed("\x1b[<32;80;9M\x1b[<0;80;9m")
assert decoder.next(now=0) == MouseMotionEvent(0, 80, 9, 0)
assert list(decoder.drain_mouse_motion()) == []
assert decoder.next(now=0) == MouseEvent(0, 80, 9, False, 0)
```

- [x] Implement separate event decoding, bounded buffer draining and motion-only pacing bypass. Normal input mode is unchanged until capture; cleanup always disables `1002`.
- [x] Run `uv run pytest tests/test_tui_input.py -q` and Ruff.

### Task 3: Dashboard capture lifecycle

**Files:** Modify `src/ccusage_viz/tui.py`; extend `tests/test_custom_ranking_dashboard_scroll.py`.

**Consumes:** `Scrollbar`, `ScrollbarGrab`, `MouseMotionEvent`, `set_mouse_motion_reporting`, viewport metadata.

- [x] Add host-loop tests using the existing accepted-data fixture for page clicks and thumb dragging; verify missing integration fails.
- [x] Track rendered pane terminal-coordinate bars. Before normal mouse clicks, start a grab or page a viewport without setting focus/copying/updating double-click state. Record stable pane identity, prepared layout identity, and initial bar geometry.
- [x] During motion, retain the latest consecutively buffered motion, apply `grab.offset_at(event.y)` once, and paint only on actual movement. Consume release to cancel, including outside the pane. Escape cancels without entering normal key handling. Other keys/wheels cancel then route normally.

```python
if isinstance(event, MouseMotionEvent) and drag is not None:
    for event in decoder.drain_mouse_motion():
        pass
    viewport.offset = grab.offset_at(event.y)
```

- [x] On paint, invalidate capture if geometry/list preparation/eligibility changes; modal/chooser/editor/log/history/blocking body views clear it. Exception-safe terminal cleanup restores reporting. At rest, motion events never become clicks.
- [x] Test no-jump grab, bottom/top travel, leaving horizontally, release/Escape, resize/search/pending/modal cancellation, one paint per burst and preserved following input, no query/focus/copy leakage, persistent bars and wheel sync.

### Task 4: Review and regression

- [x] Run focused scrollbar/input/Custom/renderer/host tests, Ruff, focused `ty`, and `git diff --check`.
- [x] Run full suite and compare the six existing baseline failures. Review no-data lifecycle mutation, reduced-width hit geometry, no leaked capture, preserved single-line wheel behavior, and no full-list warm scroll work.
- [x] Record results and any limitations. Do not claim physical-device validation or modify unrelated code. Leave functional changes in the working tree.

## Self-review

Each spec behavior maps to Tasks 1–3 and their tests. Task 4 covers regressions. Width reduction is opt-in so standalone/native paths retain their rendering; motion reports are activated only for an actual drag. No new persisted configuration or external APIs are needed.

## Results

- Implemented pure `Scrollbar`/`ScrollbarGrab` geometry (`src/ccusage_viz/scrollbar.py`), opt-in viewport gutter rendering, a distinct `MouseMotionEvent` with `drain_mouse_motion()` and `set_mouse_motion_reporting()` (`1002` only during capture), and the Dashboard capture lifecycle (press to grab thumb/page track, button-held motion to drag, release/Escape/key/wheel/geometry-change to cancel).
- Tests: `tests/test_scrollbar.py`, `tests/test_tui_input.py`, renderer tests in `tests/test_custom_ranking_scroll.py`, and host-loop drag/page/cancel tests in `tests/test_custom_ranking_dashboard_scroll.py` all pass. Ruff clean on `src`/`tests`; `ty` shows the same 86 pre-existing diagnostics with and without the change.
- Full suite: only the six pre-existing baseline failures remain (`test_text_viewport`, two `test_tui_dashboard`, three `test_tui_header`); no new failures introduced.
- Limitation: physical terminal/trackpad drag feel was not manually validated; behavior is covered only by decoded-event tests.
