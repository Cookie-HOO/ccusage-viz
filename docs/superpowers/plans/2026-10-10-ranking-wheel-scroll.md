# Ranking Wheel Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make long native and Custom historical Rankings respond immediately to wheel reports, accelerate only for continued same-direction terminal input, and stop with the final report.

**Architecture:** Decode individual SGR wheel reports rather than a merged delta, then send every report through a shared, pure ranking-scroll policy. Dashboard, native standalone watch, and Custom standalone retain only viewport offset and policy state; each paints only when an actual offset change occurs.

**Tech Stack:** Python 3.12+, terminal SGR mouse input, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-ranking-wheel-scroll-design.md`

## Global Constraints

- Wheel reports are actual terminal input; do not synthesize trailing scroll motion, timers, targets, or catch-up frames.
- First report moves exactly one rendered line; continuous same-direction steps are `1, 2, 4, 8, 12`, capped at `12`.
- Reset acceleration on direction change or elapsed continuity interval; initially use `0.03` seconds.
- Wheel scrolling must not submit queries, refresh providers, manipulate schedulers, or persist Dashboard state.
- Retain existing keyboard, click, paste, malformed-control, and non-Ranking behavior.

---

## File Structure

- Create `src/ccusage_viz/ranking_scroll.py`: pure step policy and minimal mutable state shared by all hosts.
- Modify `src/ccusage_viz/tui_input.py`: emit one unit `WheelEvent` for each decoded SGR report and stop read-ahead draining.
- Modify `src/ccusage_viz/tui.py`: apply policy to Dashboard and Custom standalone Ranking viewports.
- Modify `src/ccusage_viz/watch.py`: use `tui_input_mode` / `read_event` and apply the policy to native standalone Ranking viewport.
- Modify `tests/test_tui_input.py`, create `tests/test_ranking_scroll.py`, and extend host tests.

### Task 1: Individual wheel decoding and pure policy

**Files:**
- Create: `src/ccusage_viz/ranking_scroll.py`
- Modify: `src/ccusage_viz/tui_input.py`
- Test: `tests/test_ranking_scroll.py`
- Test: `tests/test_tui_input.py`

**Interfaces:**
- Produces `RankingWheelState`, `advance_ranking_wheel(state, *, offset, maximum, delta, now) -> tuple[int, RankingWheelState]`.
- Consumes `WheelEvent(delta, x, y)` where every decoded report has `delta in {-1, 1}`.

- [ ] **Step 1: Write failing policy and decoder tests**

```python
def test_ranking_wheel_accelerates_and_resets() -> None:
    state = RankingWheelState()
    offsets = []
    for now in (0.00, 0.01, 0.02, 0.03, 0.04, 0.05):
        offset, state = advance_ranking_wheel(state, offset=sum(offsets), maximum=100, delta=1, now=now)
        offsets.append(offset - sum(offsets))
    assert offsets == [1, 2, 4, 8, 12, 12]


def test_decoder_returns_each_wheel_report_without_merging() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<65;20;5M\x1b[<65;20;5M")
    assert decoder.next(now=0) == WheelEvent(1, 20, 5)
    assert decoder.next(now=0) == WheelEvent(1, 20, 5)
```

- [ ] **Step 2: Run focused tests; verify they fail**

Run: `uv run pytest tests/test_ranking_scroll.py tests/test_tui_input.py -q`
Expected: failure because the policy module does not exist and input returns a merged event.

- [ ] **Step 3: Implement policy and unit decoding**

```python
_WHEEL_STEPS = (1, 2, 4, 8, 12)
_WHEEL_CONTINUITY_SECONDS = 0.03

@dataclass(frozen=True, slots=True)
class RankingWheelState:
    direction: int = 0
    at: float | None = None
    step_index: int = 0


def advance_ranking_wheel(state, *, offset, maximum, delta, now):
    direction = 1 if delta > 0 else -1
    continuing = state.direction == direction and state.at is not None and now - state.at <= _WHEEL_CONTINUITY_SECONDS
    index = min(len(_WHEEL_STEPS) - 1, state.step_index + 1) if continuing else 0
    return min(maximum, max(0, offset + direction * _WHEEL_STEPS[index])), RankingWheelState(direction, now, index)
```

Remove wheel accumulation from `InputDecoder`; return `WheelEvent(-1|1, x, y)` immediately after parsing one wheel report. Remove the zero-time `select()` drain loop from `read_event()`.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_ranking_scroll.py tests/test_tui_input.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py tests/test_ranking_scroll.py tests/test_tui_input.py
git commit -m "fix: dispatch ranking wheel reports immediately"
```

### Task 2: Dashboard wheel policy for native and Custom Ranking

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_tui_dashboard.py`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes `advance_ranking_wheel` and each pane's `chart_offset`, `chart_line_count`, and `chart_visible_rows`.
- Produces a repaint request only if the returned offset differs from the saved offset.

- [ ] **Step 1: Write failing host-facing tests**

Add a test around a small extracted `apply_ranking_wheel` helper proving both `TuiChartPane` and `TuiCustomPane` move from offset `0` to `1` on their first report, advance by `2` on an immediate second report, reset to `1` after a gap/reversal, and return false without mutation at a boundary.

- [ ] **Step 2: Run tests; verify failure**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py -k 'wheel or ranking_scroll' -q`
Expected: failure because native panes have no wheel state/helper and Custom uses the old steps.

- [ ] **Step 3: Implement shared Dashboard handling**

Add `wheel_state: RankingWheelState` to both chart-pane dataclasses. Extract a helper that accepts either historical pane, verifies its body is an overflowing historical Ranking, invokes `advance_ranking_wheel`, saves state, and returns whether offset changed. Route coordinate-hit Dashboard wheel events through this helper for both native `HistoricalChartComponent` and Custom `CustomHistoricalComponent`; retain existing pointer/modal rules. Call `paint()` only on `True`.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py -k 'wheel or ranking_scroll or viewport' -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py tests/test_tui_custom.py
git commit -m "fix: share dashboard ranking wheel scrolling"
```

### Task 3: Standalone native and Custom Ranking wheel support

**Files:**
- Modify: `src/ccusage_viz/watch.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_watch.py`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- Native watch and Custom standalone use `tui_input_mode()` and `read_event()` when interactive.
- Each host uses `advance_ranking_wheel` against chart viewport metadata and forces no query/scheduler action for a wheel event.

- [ ] **Step 1: Write failing standalone tests**

Mock the interactive input sequence as a `WheelEvent(1, 1, 1)` followed by Ctrl-C. Assert a long native Ranking and a long Custom Ranking produce a second frame whose chart starts one rendered row later. Spy on request/submission functions and assert no extra call is made for the wheel event.

- [ ] **Step 2: Run tests; verify failure**

Run: `uv run pytest tests/test_watch.py tests/test_tui_custom.py -k 'wheel and ranking' -q`
Expected: failure because standalone hosts use key-only input and do not retain chart Ranking viewport metadata.

- [ ] **Step 3: Implement standalone viewport integration**

In `watch.py`, retain chart offset/line-count/visible-row metadata for a Ranking chart, use the same fixed-ranking-row viewport composition as Dashboard, and replace interactive `input_mode/read_key` use with `tui_input_mode/read_event` only in the main watch loop. On a wheel event, process only overflowing historical Rankings and call `paint(force=True)` if the policy changes offset.

In Custom standalone, retain Ranking chart viewport metadata, render through `_local_pane_content(... preserve_layout=True, fixed_rows=_ranking_fixed_rows(...))`, use `tui_input_mode/read_event`, and route `WheelEvent` through the same policy. Preserve all existing `KeyEvent` behavior by reading `event.value` only after event type narrowing.

- [ ] **Step 4: Run standalone tests**

Run: `uv run pytest tests/test_watch.py tests/test_tui_custom.py -k 'wheel or ranking or viewport' -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/watch.py src/ccusage_viz/tui.py tests/test_watch.py tests/test_tui_custom.py
git commit -m "feat: scroll standalone rankings with wheel input"
```

### Task 4: Regression validation

**Files:** none unless failures reveal a narrowly related defect.

- [ ] **Step 1: Run formatting and focused regression suites**

Run:
```bash
uv run ruff check src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py
uv run pytest tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py -q
```
Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 3: Inspect diff and commit final fixes only when needed**

```bash
git diff --check
git status --short
```

## Self-Review

- Spec coverage: Tasks 1–3 cover immediate unit decoding, exact acceleration/reset behavior, all requested native/Custom standalone/Dashboard hosts, no synthetic inertia, and repaint isolation. Task 4 covers regressions.
- Placeholder scan: no TBD/TODO or unspecified implementation steps remain.
- Type consistency: `RankingWheelState` and `advance_ranking_wheel` are created before every host integration task and are the only scroll-policy interface.
