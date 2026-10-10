# Dashboard Terminal Controls and Ranking Hit Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add terminal keyboard scrolling in Dashboard pane adjustment mode, make `c` a persistent global controls toggle, and restore Dataset Ranking copy/link hit targets.

**Architecture:** Keep adjustment viewport position as Dashboard-local ephemeral state and apply it only to the host-composed adjustment controls. Route `c` before ordinary Dashboard modes. Maintain final render-coordinate Ranking target records and consume target clicks before double-click pane entry.

**Tech Stack:** Python, terminal SGR mouse input, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-dashboard-terminal-controls-and-ranking-hits-design.md`

## Global Constraints

- No mouse-wheel Ranking scrolling or render-rate wheel scheduling.
- Up/Down changes only adjustment viewport offset; Ctrl+Up/Ctrl+Down pages it.
- `c` persists until another `c`, except literal text drafts own their input.
- Ranking target clicks are single-click actions and consume double-clicks.

### Task 1: Adjustment viewport and global controls state

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_dashboard.py`

**Interfaces:**
- Produces Dashboard-local `adjustment_offset: int` rendered through `render_text_viewport`.
- Consumes `next_text_offset(key, offset, line_count, visible_rows)`.

- [ ] Write tests for line/page adjustment scrolling and persistent `c`.
- [ ] Implement bounded adjustment viewport and universal pre-routing of `c`.
- [ ] Run `uv run pytest tests/test_tui_dashboard.py -k 'adjustment or controls' -q`.

### Task 2: Dataset Ranking single-click targets

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_dashboard.py`

**Interfaces:**
- Produces a target hit handler that consumes copy/link cells before pane double-click mode.
- Consumes final `ranking_copy_rows` render geometry and entry project URL.

- [ ] Write tests for copy/link target single clicks and target double-click consumption.
- [ ] Implement target-first dispatch, copy marker handling, and URL launch handling.
- [ ] Run `uv run pytest tests/test_tui_dashboard.py -k 'ranking and click' -q`.

### Task 3: Verification

- [ ] Run `uv run ruff check src/ccusage_viz/tui.py tests/test_tui_dashboard.py`.
- [ ] Run `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_tui_input.py -q`.
- [ ] Run `git diff --check`.
