# Grouped Ranking Viewport Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove sticky grouped headings and restore individual grouped Ranking item copy clicks.

**Architecture:** Keep grouped scrolling as a plain physical-line viewport. Normalize each shared-renderer entry fragment before constructing grouped row geometry so its actual primary row owns the series identity and hit target.

**Tech Stack:** Python 3.11+, pytest, dataclasses, terminal text rendering.

**Spec:** `docs/superpowers/specs/2026-10-14-grouped-ranking-viewport-fixes-design.md`

## Global Constraints

- Do not change numeric search behavior.
- Do not modify protocol, projection calculations, controls, or flat Ranking behavior.
- Preserve unrelated uncommitted work.
- `Other` has no individual copy target.

---

### Task 1: Remove sticky grouped headings

**Files:**
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py`
- Modify: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Consumes: `GroupedRankingViewport.visible_rows`, `total_rows`, and physical `rows`.
- Produces: `maximum_offset() -> int` equal to `max(0, total_rows - visible_rows)` and rendering with no synthetic heading.

- [ ] Replace sticky-specific tests with regression tests asserting that a scrolled group heading is absent and the final physical row is reachable.
- [ ] Run the focused tests and verify they fail under sticky insertion/capacity behavior.
- [ ] Delete sticky state, eligibility logic, geometry facts, synthetic rendering, and capacity compensation; use ordinary physical capacity and scrollbar extent.
- [ ] Run focused viewport tests and commit the independently working removal.

### Task 2: Restore grouped item copy hits

**Files:**
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py`
- Modify: `tests/test_custom_ranking_scroll.py`
- Modify: `tests/test_custom_ranking_dashboard_scroll.py`

**Interfaces:**
- Consumes: shared `render_historical_ranking()` fragments.
- Produces: grouped physical rows whose primary item line has kind `series`, plus `viewport.hits[row] == (("series", group_id, series_id), copy_column, link_column)`.

- [ ] Add a pure viewport regression asserting an inner series identity appears in hits while Other does not.
- [ ] Add a Dashboard mouse regression that clicks the inner marker and verifies group-aware clipboard text.
- [ ] Run both tests and verify failure because only group hits currently exist.
- [ ] Normalize entry fragments by locating the primary rendered item row, dropping renderer-owned leading chrome, and mapping following lines as descriptions.
- [ ] Run focused copy, scrolling, link, and grouped viewport tests.
- [ ] Run formatting/type checks and the broader relevant test files, then commit.
