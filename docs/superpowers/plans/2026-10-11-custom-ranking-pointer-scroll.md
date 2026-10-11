# Custom Ranking Pointer Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scroll only Dashboard Custom historical Ranking panes under the pointer, with immediate single-line steps and bounded visible rendering.

**Architecture:** Decode wheel reports separately and batch consecutive buffered reports without reordering input. A pane-local viewport retains prepared presentation/layout facts and a display-line offset. The existing Ranking renderer gains an opt-in prepared window path; Dashboard routes pointer events and consumes visible hit geometry without changing data lifecycles.

**Tech Stack:** Python 3.11–3.13, existing SGR mouse protocol, pytest, Ruff, uv; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-11-custom-ranking-pointer-scroll-design.md`

## Global Constraints

- Only Dashboard Custom historical Ranking is scrollable; native/monitor/standalone paths retain their behavior.
- Each event moves one display line when `visible_rows > 0`, clamped after each event. No acceleration, inertia, scroll timer, or configuration mutation.
- Fixed chrome stays fixed; descriptions and separators count as display lines.
- Preparation may scan the data once. Warm scrolling must not scan/format the full list or rebuild full-list hit lookups.
- Preserve keyboard/click/paste semantics, decoder safety limits, and unrelated user changes.

---

## File boundaries

- `src/ccusage_viz/tui_input.py`: immutable wheel event, SGR validation, ordered bounded buffered draining.
- `src/ccusage_viz/render/ranking_viewport.py` (new): session viewport, prepared layout metadata, display-line slicing/hits.
- `src/ccusage_viz/render/ranking_presentation.py`: opt-in reusable preparation and windowed row formatting using existing visual primitives.
- `src/ccusage_viz/render/custom.py`: cache localized/filter-matched Custom entries and global facts for the opt-in viewport path.
- `src/ccusage_viz/tui.py`: attach viewport to Custom panes, route pointer input, integrate fixed chrome, visible hit targets and reconciliation.
- `tests/test_tui_input.py`, `tests/test_custom_ranking_scroll.py` (new), `tests/test_tui_dashboard.py`: decoder, deterministic viewport/performance, and real host-loop tests.

### Task 1: Wheel input without per-event backlog

**Interfaces:** `WheelEvent(delta: int, x: int, y: int, modifiers: int = 0)`; `InputDecoder.drain_wheel() -> Iterator[WheelEvent]` consumes consecutive complete vertical wheel reports only.

- [ ] Add decoding tests, including `decoder.feed("\x1b[<65;20;5M")` followed by `assert decoder.next() == WheelEvent(1, 20, 5)`; fragmented sequences; releases/horizontal/motion rejection.
- [ ] Run `uv run pytest tests/test_tui_input.py -q` and verify the new event import initially fails.
- [ ] Implement the event union/decoder branch and buffer-only drain. Bypass overload pacing only for a complete vertical wheel report. Preserve keys/clicks/paste at the batch boundary.

```python
for event in decoder.drain_wheel():
    # Host applies each report in order; do not combine signed deltas first.
    handle_wheel(event)
```

- [ ] Test a wheel burst followed by click/key, ensuring all wheel events drain at one timestamp and non-wheel input remains available.
- [ ] Run decoder tests and Ruff; review the diff before continuing.

### Task 2: Prepared Custom Ranking display-line viewport

**Interfaces:** `RankingViewport` owns `offset`, `total_rows`, `visible_rows`, current preparation, and visible hit rows; `scroll(delta: int) -> bool` performs direct bounded movement. The renderer accepts an optional `viewport: RankingViewport | None = None`; default callers remain unwindowed.

- [ ] Add pure offset tests:

```python
viewport = RankingViewport(offset=0, total_rows=100, visible_rows=10)
assert viewport.scroll(1)
assert viewport.offset == 1
assert viewport.scroll(-1)
assert viewport.offset == 0
assert not viewport.scroll(-1)
```

- [ ] Run `uv run pytest tests/test_custom_ranking_scroll.py -q`, confirming absence of the module.
- [ ] Implement reusable preparation of scalar row facts, stable columns, full-list comparison fallback, and cached description heights/line-prefix offsets. Locate overlapping entries with binary search; format only overlapping entries. Generate stable-ID hit rows while formatting, not by matching visible rank text against the full model.

```python
first = max(0, bisect_right(line_starts, viewport.offset) - 1)
stop = bisect_left(line_starts, viewport.offset + viewport.visible_rows)
# Render entries [first:stop], clip partial leading/trailing lines.
```

- [ ] Add Custom projection caching keyed by accepted model identity plus layout/search/configuration inputs, with separate transient presentation output. Query change resets offset; model refresh/Top/resize clamps it; source/metric/group/filter/period change resets it.
- [ ] Add tests for detailed descriptions (existing two-line cap), every spacing mode, partial rows, stable columns/totals/scales, empty search, comparison tables, and copied/link markers. Build a 10,000-entry projection and instrument preparation/row formatting to prove warm work is visible-window bounded.
- [ ] Run `uv run pytest tests/test_custom_ranking_scroll.py tests/test_render.py tests/test_custom_component.py -q`; review unwindowed fixtures and the diff.

### Task 3: Dashboard routing and geometry

**Consumes:** `WheelEvent`, `InputDecoder.drain_wheel`, `RankingViewport`, optional viewport rendering. **Produces:** Custom-only hover scrolling in the existing Dashboard loop.

- [ ] Add a Dashboard loop test with a real long Custom Ranking pane and another focused pane. Feed a wheel report over the Custom pane; assert offset changes but focus/queries do not.
- [ ] Run the new test and verify it fails before integration.
- [ ] Attach a session-local viewport to `TuiCustomPane`; pass it only from Dashboard Custom historical Ranking rendering. Allocate fixed summary/title/search/count/columns and audit/notices around its visible body. Store the same displayed layout/header geometry used by the painter for pointer lookup.

```python
if isinstance(event, WheelEvent):
    before = tuple(p.ranking_viewport.offset for p in custom_panes)
    handle_wheel(event)
    for buffered in decoder.drain_wheel():
        handle_wheel(buffered)
    if before != tuple(p.ranking_viewport.offset for p in custom_panes):
        paint()
    continue
```

- [ ] Reject wheel input in modal/editor/help/log/history/chooser modes, non-chart body views, native/monitor/non-ranking panes, and pending-only/empty output. Clear stale hits when content is not eligible. Keep adjustment mode and focus unchanged.
- [ ] Use viewport visible stable-ID hit targets for copying/link activation, preserving existing copy payload and feedback. Do not call the full-list copy lookup on warm viewport rendering/clicks.
- [ ] Test two independent panes, borders/header/footer/gaps, fullscreen/framing, no-op bounds, multiple wheel reports with one paint, search/reset/resize, copied feedback, and excluded chart types.
- [ ] Run `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py tests/test_tui_input.py tests/test_custom_ranking_scroll.py -q` and review host lifecycle isolation.

### Task 4: Regression and final review

- [ ] Run `uv run ruff check` for changed source/tests and `git diff --check`.
- [ ] Run `uv run pytest -q`; distinguish any existing failures from new failures, using baseline evidence when necessary.
- [ ] Review cache invalidation, line bounds, batching order, modal ownership, direct event speed semantics, and absence of changes to standalone/native behavior.
- [ ] Mark the spec approved and plan steps complete only for verified work. Report test results and any manual terminal validation not performed. Leave unrelated files untouched.

## Plan review

All spec sections map to Tasks 1–3 and verification in Task 4. Public names match across tasks. No background workers, package changes, keyboard features, or broad Dashboard refactor are included. Execute inline in the current session as requested; no subagent tool is available.

## Single-line refinement (user approved)

**Files:** `src/ccusage_viz/render/ranking_viewport.py`, `tests/test_custom_ranking_scroll.py`, `tests/test_custom_ranking_dashboard_scroll.py`, and this plan/spec.

**Interface:** Keep `RankingViewport.scroll(delta: int) -> bool`; change only its per-report distance. Do not change decoder batching, host routing, frame scheduling, or unrelated chart types.

- [x] Update offset and visible copy/link expectations for one-line movement. Add repeated isolated-report tracking through descriptions and separators, plus step/boundary checks at several pane heights.

```python
viewport = RankingViewport(total_rows=100, visible_rows=10)
assert viewport.scroll(1)
assert viewport.offset == 1
assert viewport.scroll(-1)
assert viewport.offset == 0
```

- [x] Run `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py -q`; the old three-line code failed 18 assertions/tests (37 passed).
- [x] Replace the displacement with the signed input, leaving zero-height rejection and clamping intact:

```python
before = self.offset
self.offset += delta
self.clamp()
return self.offset != before
```

- [x] Run the updated viewport/host tests, input/renderer regressions, Ruff and `git diff --check`; run the full suite and compare known baseline failures. Code remains uncommitted for review.

**Refinement verification:** 330 focused tests passed; full suite: 1538 passed, the same 6 baseline failures listed below. Ruff and whitespace checks passed. New tests cover one-line movement at heights 1/2/10/30, repeated tracked-row movement with all spacing modes and descriptions, and updated Dashboard batch/copy/link/boundary expectations. Only `RankingViewport.scroll` changed in production code; physical-device feel still needs user validation.

## Initial implementation execution record — 2026-10-11

- [x] Task 1: distinct wheel events, ordered buffer-only draining, safety and input-order tests. New decoder tests failed before implementation and pass afterward.
- [x] Task 2: direct display-line viewport, prepared columns/heights/aggregates, binary-search windows, stable-ID hits, invalidation and 10,000-entry work-count tests. New viewport tests failed before implementation and pass afterward.
- [x] Task 3: Dashboard pointer routing, displayed-frame geometry, batch repaint, fixed chrome/notices, and copy/link handling. Tested real host loops with preaccepted data and lifecycle request instrumentation.
- [x] Task 4: focused tests, full suite, Ruff, focused type checking, and whitespace review completed. No claim of physical-device validation.

### Implementation refinements

Custom projection preparation lives in the new `src/ccusage_viz/render/custom_ranking_viewport.py` adapter rather than modifying `render/custom.py`. Dashboard opts into it through `_render_custom_projection`; unwindowed Custom/standalone rendering stays on the existing path. Host-loop tests live in `tests/test_custom_ranking_dashboard_scroll.py` to keep existing large test files unchanged. New scrolling state is attached only to `TuiCustomPane`.

### Verification results

- Focused renderer, Custom component, input, and new viewport/host tests: **319 passed**.
- Full suite: **1527 passed, 6 failed**. The six failures match the baseline captured before viewport implementation: `test_wrap_text_rows_preserves_paragraphs_and_display_width`, `test_dashboard_ranking_search_timeout_finishes_editing_without_clearing_query`, `test_ranking_top_above_available_projects_keeps_all_available_projects`, and three existing `test_tui_header.py` failures (`test_dashboard_header_uses_host_summary_and_tracks_global_theme`, `test_header_refresh_uses_missing_coverage_then_current_day`, `test_header_none_keeps_title_without_unknown_detail`).
- Ruff on all changed source/tests and `git diff --check`: pass.
- `ty check` on the two new renderer modules, Ranking presentation, and input decoder: pass. The existing large `tui.py` does not pass project type checking; no claim of whole-project type cleanliness.
- Physical mouse/trackpad feel has not been manually verified. No unrelated Weread design/plan files were edited or staged. Implementation changes remain in the working tree for review.

