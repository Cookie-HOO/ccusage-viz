# Ranking Wheel Burst Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accelerate short same-direction Ranking wheel bursts while retaining immediate, non-inertial scrolling.

**Architecture:** Keep integer viewport offsets and add a small per-viewport wheel-burst state containing only direction, last report timestamp, and multiplier. Each report directly moves content; no timer or deferred action exists.

**Tech Stack:** Python, monotonic time, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-wheel-burst-acceleration-design.md`

## Global Constraints

- Base step is `max(1, visible_rows // 8)`.
- Same-direction reports within 80ms use multipliers `1, 2, 3, 4`, capped at `4`.
- Direction change or a gap of 80ms or more resets to `1`.
- Keyboard scrolling remains at the base step.
- No velocity, timer, target, or queued post-input movement.

---

### Task 1: Add Pure Burst State and Apply It in Hosts

**Files:**
- Modify: `src/ccusage_viz/ranking_scroll.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/watch.py`
- Modify: `tests/test_ranking_scroll.py`

- [ ] **Step 1: Write failing policy test**

```python
def test_same_direction_wheel_burst_accelerates_and_resets() -> None:
    viewport = RankingViewport(total_rows=200, visible_rows=16)
    state = RankingWheelBurst()
    offsets = []
    for now in (0.00, 0.01, 0.02, 0.03, 0.04):
        viewport, state = advance_ranking_wheel_burst(viewport, state, delta=1, now=now)
        offsets.append(viewport.offset)
    assert offsets == [2, 6, 12, 20, 28]
    viewport, state = advance_ranking_wheel_burst(viewport, state, delta=1, now=0.12)
    assert viewport.offset == 30
```

- [ ] **Step 2: Implement and validate**

Add `RankingWheelBurst`, `advance_ranking_wheel_burst()`, Dashboard/standalone state fields, and timestamped wheel routing. Keep arrow keys on `advance_ranking_wheel()`.

Run:

```bash
uv run ruff check src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py
uv run pytest tests/test_ranking_scroll.py tests/test_tui_custom.py tests/test_watch.py -q
```

- [ ] **Step 3: Commit**

```bash
git add src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui.py src/ccusage_viz/watch.py tests/test_ranking_scroll.py docs/superpowers/specs/2026-10-10-ranking-wheel-burst-acceleration-design.md docs/superpowers/plans/2026-10-10-ranking-wheel-burst-acceleration.md
git commit -m "feat: accelerate ranking wheel bursts"
```
