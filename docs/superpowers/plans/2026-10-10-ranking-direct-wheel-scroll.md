# Ranking Direct Wheel Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Directly scroll overflowing native and Custom historical Ranking panes under the mouse pointer without inertia or event backlog.

**Architecture:** Decode individual SGR reports as `WheelEvent`, apply an integer screen-relative row step to ephemeral Ranking viewport metadata, and render once after all immediately available reports in an input turn are incorporated. Hosts retain no velocity, timer, target, or deferred movement state.

**Tech Stack:** Python 3.12+, terminal SGR mouse reports, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-direct-wheel-scroll-design.md`

## Global Constraints

- Applies only to overflowing native and Custom historical Rankings in Dashboard and standalone hosts.
- Use `max(1, visible_rows // 8)` rendered rows per signed wheel report.
- Pointer targeting includes a Dashboard pane border and never changes focus.
- Do not retain velocity, target offset, animation/timer state, or queued future displacement.
- Coalesce buffered reports in one input turn and repaint at most once.
- Never call provider, Custom command, query coordinator, scheduler, or persistence paths for wheel input.

---

### Task 1: Replace Kinetic Policy with Pure Direct Offset Policy

**Files:**
- Modify: `src/ccusage_viz/ranking_scroll.py`
- Modify: `tests/test_ranking_scroll.py`

**Interfaces:**
- Produces `RankingViewport(offset: int = 0, total_rows: int = 0, visible_rows: int = 0)`.
- Produces `advance_ranking_wheel(viewport: RankingViewport, *, delta: int) -> RankingViewport`.

- [ ] **Step 1: Write failing direct-step tests**

```python
def test_wheel_moves_one_eighth_of_visible_rows_without_retained_motion() -> None:
    viewport = RankingViewport(offset=0, total_rows=100, visible_rows=24)
    moved = advance_ranking_wheel(viewport, delta=1)
    assert moved.offset == 3
    assert advance_ranking_wheel(moved, delta=-1).offset == 0
    assert moved == advance_ranking_wheel(moved, delta=0)
```

Include tests for short panes (`visible_rows=3` moves one row) and top/bottom clamping.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ranking_scroll.py -q`

Expected: FAIL because the old module owns kinetic state and time integration.

- [ ] **Step 3: Implement the direct policy**

```python
@dataclass(frozen=True, slots=True)
class RankingViewport:
    offset: int = 0
    total_rows: int = 0
    visible_rows: int = 0


def advance_ranking_wheel(viewport: RankingViewport, *, delta: int) -> RankingViewport:
    step = max(1, viewport.visible_rows // 8)
    offset = min(viewport.maximum_offset, max(0, viewport.offset + (step if delta > 0 else -step)))
    return replace(viewport, offset=offset)
```

Delete kinetic constants/state/frame functions.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_ranking_scroll.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/ranking_scroll.py tests/test_ranking_scroll.py
git commit -m "refactor: use direct ranking wheel offsets"
```

### Task 2: Remove Kinetic Loops and Apply Direct Wheel Handling in Hosts

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/watch.py`
- Modify: `tests/test_tui_dashboard.py`
- Modify: `tests/test_tui_custom.py`
- Modify: `tests/test_watch.py`

**Interfaces:**
- Consumes `WheelEvent` and `advance_ranking_wheel()`.
- Pane/session state keeps only `ranking_viewport`.

- [ ] **Step 1: Write failing host tests**

```python
def test_pointed_unfocused_ranking_wheel_moves_directly_and_never_ticks() -> None:
    # Feed one WheelEvent into a 24-visible-row ranking pane, then a timeout and Ctrl-C.
    # Assert its first displayed row advanced by three rows, focus did not change,
    # no provider submission occurred after startup, and the timeout had no repaint.
```

Cover native and Custom Dashboard and standalone hosts.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py -k 'wheel and ranking' -q`

Expected: FAIL because current hosts have kinetic state/frames.

- [ ] **Step 3: Implement direct event handling**

Delete `ranking_kinetic`, `kinetic_owner`, kinetic deadlines, 60Hz read timeouts, and calls to frame integration. On a wheel report, identify the eligible pointed viewport, call `advance_ranking_wheel()` once per report, and paint only if its integer offset changed. Keep existing mouse clicks and key behavior.

When the input decoder already has complete buffered reports, drain only consecutive `WheelEvent`s in the same host input turn, route each report, and issue one paint if any route changed its viewport. Stop draining on a non-wheel event; preserve it for normal processing.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py -k 'wheel and ranking' -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py
git commit -m "feat: scroll rankings directly with wheel input"
```

### Task 3: Regression Validation

- [ ] **Step 1: Run checks**

```bash
uv run ruff check src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui_input.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py
uv run pytest tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py -q
uv run pytest -q
```

Expected: PASS other than known pre-existing failures unrelated to wheel scrolling.

- [ ] **Step 2: Inspect whitespace and scope**

```bash
git diff --check
git status --short
```
