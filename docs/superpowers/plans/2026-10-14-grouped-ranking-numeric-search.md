# Grouped Ranking Numeric Search Crash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent grouped Ranking search repaint from crashing when no groups match.

**Architecture:** Keep existing search and layout flow. Make all grouped heading width reductions explicitly safe for an empty `visible` tuple by using generator `default` values.

**Tech Stack:** Python 3.11+, pytest, terminal rendering.

**Spec:** `docs/superpowers/specs/2026-10-14-grouped-ranking-numeric-search-design.md`

## Global Constraints

- Numeric characters remain ordinary searchable text.
- Do not change search matching, ranking calculations, or input routing.
- Preserve unrelated uncommitted work.

---

### Task 1: Empty-safe grouped width measurement

**Files:**
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py`
- Modify: `tests/test_custom_ranking_scroll.py`
- Modify: `tests/test_custom_ranking_dashboard_scroll.py`

**Interfaces:**
- Consumes: `visible: tuple[(GroupedRankingPresentationGroup, entries), ...]`.
- Produces: width integers for `current`, `delta`, `share`, and `right` even when `visible` is empty.

- [ ] Add a direct zero-match grouped viewport regression.
- [ ] Add a Dashboard incremental `/gpt4` regression.
- [ ] Run both tests and verify the empty-width reduction failure.
- [ ] Replace all four splatted `max` reductions with generator reductions using the existing width as `default`.
- [ ] Run focused grouped Ranking and Dashboard tests.
- [ ] Run Ruff and relevant broader tests, then commit only scoped files.
