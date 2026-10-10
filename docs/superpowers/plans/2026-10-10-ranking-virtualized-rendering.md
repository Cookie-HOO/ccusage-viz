# Ranking Virtualized Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render only visible Dataset Ranking entries in Dashboard so large project lists remain responsive.

**Architecture:** Extend shared Ranking presentation with an optional entry viewport and explicit visible entry metadata. Dashboard computes a pane window and uses the metadata for click targets; unwindowed callers preserve existing output.

**Tech Stack:** Python, terminal ANSI/OSC-8 rendering, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-virtualized-rendering-design.md`

## Global Constraints

- Keep unwindowed Ranking output unchanged.
- Retain full-list semantic calculations but do not construct per-entry rendered strings outside the requested window.
- Do not restore wheel scrolling.

### Task 1: Shared Ranking viewport contract

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Test: `tests/test_render.py`

- [ ] Add an optional entry-window argument and renderer result metadata.
- [ ] Format only selected entries after full-list global measurements.
- [ ] Test rank/scale/total correctness at nonzero offset and unchanged unwindowed output.

### Task 2: Dashboard visible window and hit metadata

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_dashboard.py`

- [ ] Compute visible entry count from pane interior body height.
- [ ] Request first window normally and adjustment offset window in pane adjustment mode.
- [ ] Store explicit visible copy/link rectangles rather than scan full text.
- [ ] Test large Dataset Ranking hit target and adjustment offset clamp behavior.

### Task 3: Verification

- [ ] Run `uv run ruff check src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/render/custom.py src/ccusage_viz/tui.py`.
- [ ] Run `uv run pytest tests/test_render.py tests/test_tui_dashboard.py tests/test_tui_custom.py -q`.
- [ ] Run `git diff --check`.
