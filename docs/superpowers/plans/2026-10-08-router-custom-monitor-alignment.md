# Router Custom Monitor Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align Dataset V2 Monitor rendering and adjustment controls with their corresponding native ccuv Monitor surface in Dashboard and standalone; preserve Dataset-native observation semantics and ensure Dataset metric selection remains usable after Esc back-navigation.

**Architecture:** Keep source-owned observations in `CustomMonitorComponent` and add a Dataset-native Monitor presentation projection. Dashboard consumes that projection through the existing Dashboard Monitor render contract; standalone consumes it through the standalone Monitor frame and adjustment contract. Both share style compatibility and local retention behavior without converting Dataset facts to token samples. Attachment playback uses the accepted observation total without deriving a local delta. Reset Dataset chooser state whenever a new source is selected.

**Tech Stack:** Python 3, pytest, ccusage-viz terminal renderers.

**Spec:** `docs/superpowers/specs/2026-10-08-router-custom-monitor-alignment-design.md`

## Global Constraints

- Preserve Dataset-owned total and group values exactly.
- Do not add `Other`, local aggregation, historical comparisons, or percentage shares.
- Sum Dataset Monitor styles are `bars`, `cumulative-bars`, `ranking`, and `list`; value metrics omit `cumulative-bars`.
- `w` changes Dataset Monitor local display retention only; it does not change the Dataset-owned observation query window.
- Cumulative Dataset Monitor coverage marks unobserved intervals rather than silently omitting them.
- Grouping cycles `None` followed by the Dataset-declared group IDs in declaration order.
- After Metric chooser Esc returns to Dataset selection, selecting another V2 Dataset must re-open Metric selection.

---

### Task 1: Source-Owned Window Projection And Presentation

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/custom_monitor_component.py`
- Test: `tests/test_tui_custom.py`
- Test: `tests/test_custom_monitor_component.py`

- [ ] Add failing component tests proving local window re-projection retains Dataset values and turns missing intervals into `UNOBSERVED` cumulative-bar buckets.
- [ ] Add projection tests for bars, cumulative bars, ranking, and list without percentage output or synthetic token facts.
- [ ] Keep source query configuration unchanged by local display-window changes.
- [ ] Expose Dataset metric, grouping, and Monitor-window heading metadata from the source-native projection.
- [ ] Run: `pytest tests/test_custom_monitor_component.py tests/test_tui_custom.py -q`

### Task 2: Dashboard Monitor Alignment

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/custom_monitor_component.py`
- Test: `tests/test_tui_custom.py`

- [ ] Route Dashboard Dataset Monitor through the Dashboard native Monitor rendering contract and remove obsolete component-method calls.
- [ ] Add tests for sum/value presentation cycling, local `w` window cycling, bidirectional grouping, source-owned heading metadata, and attachment activity.
- [ ] Keep Dataset-specific Dashboard logs and command views intact.
- [ ] Run: `pytest tests/test_tui_custom.py tests/test_custom_monitor_component.py -q`

### Task 3: Standalone Monitor Alignment

**Files:**
- Modify: `src/ccusage_viz/custom_monitor.py`
- Modify: `src/ccusage_viz/custom_monitor_component.py`
- Test: `tests/test_custom_monitor.py`

- [ ] Replace the standalone Dataset Monitor's hand-written total/group report with the standalone Monitor rendering and adjustment contract.
- [ ] Reuse its style, theme, density, legend, `w`, and `b/B` semantics; exclude Dashboard pane and attachment behavior.
- [ ] Render Dataset-native metric, group, and window headings.
- [ ] Run: `pytest tests/test_custom_monitor.py -q`

### Task 4: Router Metric Labels

**Files:**
- Modify: `tests/test_custom_protocol.py`

- [ ] Update Router Probe fixture titles to TPM and QPM and assert the parsed titles.
- [ ] Run: `pytest tests/test_custom_protocol.py -q`

### Task 5: Verification

**Files:**
- Test: `tests/test_tui_custom.py`
- Test: `tests/test_custom_monitor.py`
- Test: `tests/test_custom_monitor_component.py`
- Test: `tests/test_custom_protocol.py`

- [ ] Run focused tests and correct regressions.
- [ ] Run the repository formatter/checker if provided by the project.

### Task 6: Dataset Metric Selection Back Navigation

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_dashboard.py`

- [ ] Add an interaction regression test: choose V2 Dataset A, enter Metric choice, press Esc, select V2 Dataset B, and assert B's Metric chooser appears.
- [ ] Clear `chart_kinds`, metrics, and selected-metric metadata immediately before processing a newly selected source.
- [ ] Run: `pytest tests/test_tui_dashboard.py -q`
