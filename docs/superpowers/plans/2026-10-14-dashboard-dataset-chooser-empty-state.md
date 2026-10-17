# Dashboard Dataset Chooser Empty-State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Dashboard dataset and V2 metric selection safe when their selectable lists are empty.

**Architecture:** Keep empty-state handling inside the existing nonblocking Dashboard modal lifecycle. Rendering avoids list index normalization for an empty source list; source selection refuses to transition to the metric step when there are no selectable metrics. Existing localized strings communicate the state.

**Tech Stack:** Python 3.11+, pytest, terminal TUI.

**Spec:** `docs/superpowers/specs/2026-10-14-dashboard-dataset-chooser-empty-state-design.md`

## Global Constraints

- Change only the Dashboard `DashboardDatasetModalState` flow in `src/ccusage_viz/tui.py`.
- Use existing `status.datasets_empty` and `status.dataset_unavailable` localization keys; add no translation keys.
- Preserve all behavior for nonempty source, metric, and chart-kind lists.

---

## File Structure

- Modify: `src/ccusage_viz/tui.py` — safely render and handle empty Dashboard source and V2 metric selections.
- Modify: `tests/test_tui_dashboard.py` — reproduce and verify each empty-list path through `run_tui()`.

### Task 1: Cover and fix an empty ready-source list

**Files:**
- Modify: `tests/test_tui_dashboard.py`
- Modify: `src/ccusage_viz/tui.py:9067-9110,9396-9439`

**Interfaces:**
- Consumes: `DashboardDatasetModalState.statuses: tuple[object, ...]`, `modal.stage == "source"`.
- Produces: a source-stage modal that renders `translator.text("status.datasets_empty")` and never indexes `modal.statuses` when it is empty.

- [ ] **Step 1: Write the failing integration test**

Add a test with a `DatasetService.ready_registered_sources()` stub returning `()`, and feed Dashboard events `m`, `r`, `k`, Enter, Ctrl-C. Capture frames through a `FramePainter` stub and assert:

```python
assert tui_module.run_tui(options, load_translator("en")) == 0
assert "No datasets installed" in rendered
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_tui_dashboard.py -k empty_ready_source -v`

Expected: FAIL with `ZeroDivisionError: integer modulo by zero` at `modal.index %= len(entries)`.

- [ ] **Step 3: Implement the minimal source empty state**

In `_paint_dataset_modal()`, branch before `modal.index %= len(entries)`:

```python
if not entries:
    body = translator.text("status.datasets_empty")
else:
    modal.index %= len(entries)
    # retain current row construction and viewport rendering
```

In `handle_dataset_modal()` only evaluate source-stage help, navigation, and Enter selection when `entries` is nonempty; always retain Escape-to-pane behavior.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_tui_dashboard.py -k empty_ready_source -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py
git commit -m "fix: handle empty dashboard dataset chooser"
```

### Task 2: Cover and prevent an empty V2 metric list

**Files:**
- Modify: `tests/test_tui_dashboard.py`
- Modify: `src/ccusage_viz/tui.py:9410-9469`

**Interfaces:**
- Consumes: `V2ProbeDescriptor`, `_dataset_metric_chooser_rows(descriptor, translator)`, and its selectable `MetricChooserRow.metric_index` values.
- Produces: source-stage handling that sets `modal.error = translator.text("status.dataset_unavailable")` rather than indexing `selectable[0]` or entering `metric` when `selectable == ()`.

- [ ] **Step 1: Write the failing integration test**

Create one ready registered source whose `V2ProbeDescriptor.metrics` is empty. Drive `m`, `r`, `k`, Enter, Enter, Ctrl-C and capture frames. Assert:

```python
assert tui_module.run_tui(options, load_translator("en")) == 0
assert "Unavailable" in rendered
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_tui_dashboard.py -k empty_v2_metric -v`

Expected: FAIL with an `IndexError` from `selectable[0]`.

- [ ] **Step 3: Implement the metric transition guard**

In source-stage Enter handling, compute `selectable`. If it is empty, set the unavailable error and leave stage, index, and offset in the source chooser. Otherwise, retain default metric resolution, reset offset, and transition to `metric`.

- [ ] **Step 4: Run both focused regressions and the existing metric modal test**

Run:

```bash
pytest tests/test_tui_dashboard.py -k 'empty_ready_source or empty_v2_metric' -v
pytest tests/test_tui_custom.py::test_dashboard_metric_modal_wraps_to_target_pane_and_submits_selected_metric -v
```

Expected: all PASS.

- [ ] **Step 5: Run lint and the relevant test modules**

Run:

```bash
ruff check src/ccusage_viz/tui.py tests/test_tui_dashboard.py
pytest tests/test_tui_dashboard.py tests/test_tui_custom.py
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py
git commit -m "fix: guard empty dashboard metric chooser"
```
