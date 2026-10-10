# Ranking Smooth Wheel And Rank Jump Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Smooth direct historical Ranking wheel movement and add debounced focused-Dashboard numeric rank jumps.

**Architecture:** Replace the current burst multiplier with a bounded direct-row sequence and retain only wheel burst metadata. Add a Dashboard-local rank-jump draft with a 400ms deadline; rendering reserves one fixed prompt row and converts a rank ordinal to the corresponding first rendered row at commit.

**Tech Stack:** Python, monotonic time, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-smooth-wheel-and-jump-design.md`

## Global Constraints

- Wheel multipliers are exactly `1, 1, 2, 2, 3`, capped at `3`, with an 80ms reset window.
- Base wheel and arrow-key step is one rendered row.
- No velocity, timers for scroll movement, target offsets, or deferred scrolling.
- Numeric jump is Dashboard-only, focused historical Ranking only, debounced for 400ms, and clamped by rank ordinal.
- Numeric jump input commits before another interaction and never queries or persists.

---

### Task 1: Smooth Direct Wheel Policy

**Files:**
- Modify: `src/ccusage_viz/ranking_scroll.py`
- Modify: `tests/test_ranking_scroll.py`

- [ ] **Step 1: Write failing sequence tests**

```python
def test_direct_wheel_uses_followable_burst_steps() -> None:
    viewport = RankingViewport(total_rows=100, visible_rows=30)
    burst = RankingWheelBurst()
    offsets = []
    for now in (0, .01, .02, .03, .04, .05):
        viewport, burst = advance_ranking_wheel_burst(viewport, burst, delta=1, now=now)
        offsets.append(viewport.offset)
    assert offsets == [1, 2, 4, 6, 9, 12]
```

- [ ] **Step 2: Implement and run tests**

Set the base step to one row and encode the exact multiplier sequence. Keep 80ms/reversal reset and clamping.

Run: `uv run pytest tests/test_ranking_scroll.py -q`

- [ ] **Step 3: Commit**

```bash
git add src/ccusage_viz/ranking_scroll.py tests/test_ranking_scroll.py
git commit -m "fix: smooth direct ranking wheel steps"
```

### Task 2: Dashboard Numeric Rank Jump

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `tests/test_tui_dashboard.py`

- [ ] **Step 1: Write failing helper tests**

```python
def test_ranking_jump_offsets_to_requested_entry_ordinal() -> None:
    rows = ("heading", "1 one", "  description", "2 two", "3 three")
    assert tui_module._ranking_rank_offset(rows, rank=2) == 2
    assert tui_module._ranking_rank_offset(rows, rank=99) == 3
```

- [ ] **Step 2: Implement draft, prompt, and deadline commit**

Add a `RankingJumpState(digits, at)` dashboard-local state, a 400ms deadline in `read_adjustment_event()`, ordinal-to-rendered-line mapping based on numbered Ranking rows, and a fixed `Jump to rank: <digits>_` chrome row. Consume digits only for a focused historical Ranking in ordinary chart browsing. Commit at deadline and before another interaction.

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/test_tui_dashboard.py -k 'ranking and jump' -q
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py
git commit -m "feat: jump dashboard rankings by number"
```

### Task 3: Regression Validation

- [ ] **Step 1: Run checks**

```bash
uv run ruff check src/ccusage_viz/ranking_scroll.py src/ccusage_viz/tui.py tests/test_ranking_scroll.py tests/test_tui_dashboard.py
uv run pytest tests/test_ranking_scroll.py tests/test_tui_input.py tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_watch.py -q
```

- [ ] **Step 2: Commit docs and any validation fixes**

```bash
git add docs/superpowers/specs/2026-10-10-ranking-smooth-wheel-and-jump-design.md docs/superpowers/plans/2026-10-10-ranking-smooth-wheel-and-jump.md
git commit -m "docs: specify smooth ranking scroll and rank jump"
```
