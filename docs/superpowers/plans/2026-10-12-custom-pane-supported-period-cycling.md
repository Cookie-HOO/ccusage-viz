# Custom Pane Supported Period Cycling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure Custom historical panes cycle only periods declared by the selected Metric's current chart capability, while preserving generic cycling when periods are omitted.

**Architecture:** Add one focused helper in `tui.py` to project chart-specific periods from a V2 Metric descriptor. Use it after chart-kind selection in both Dataset chooser paths, and normalize the live Dashboard adjustment input from the current capability so stale persisted `metric_periods` cannot override current declarations.

**Tech Stack:** Python 3.12+, frozen dataclasses, pytest, existing ccusage-viz TUI and Custom Dataset V2 models.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-pane-supported-period-cycling-design.md`

## Global Constraints

- A non-empty capability `periods` tuple is authoritative and retains its declared order.
- An omitted or empty capability `periods` tuple preserves generic Host period cycling.
- No protocol or persistence schema changes.
- Scope is limited to Custom historical panes; Monitor behavior is unchanged.

---

### Task 1: Resolve Periods from the Selected Chart Kind

**Files:**
- Modify: `src/ccusage_viz/tui.py:4152-4318`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `V2MetricDescriptor.capabilities.charts` and `V2HistoricalChartCapability.periods`.
- Produces: `_custom_metric_periods(metric: V2MetricDescriptor, kind: str) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing helper tests**

Add tests constructing one V2 Metric with Timeline periods `("7d", "30d")`, Ranking periods `("all",)`, and Calendar with no declared periods. Assert:

```python
assert tui_module._custom_metric_periods(metric, "timeline") == ("7d", "30d")
assert tui_module._custom_metric_periods(metric, "ranking") == ("all",)
assert tui_module._custom_metric_periods(metric, "calendar") == ()
assert tui_module._custom_metric_periods(metric, "missing") == ()
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `uv run pytest tests/test_tui_custom.py -k custom_metric_periods -q`

Expected: FAIL because `_custom_metric_periods` does not exist.

- [ ] **Step 3: Implement the helper and update the synchronous chooser**

Add:

```python
def _custom_metric_periods(metric: V2MetricDescriptor, kind: str) -> tuple[str, ...]:
    capability = metric.capabilities.charts.get(kind)
    return capability.periods if isinstance(capability, V2HistoricalChartCapability) else ()
```

In `_choose_dataset_pane_config`, stop deriving periods from Ranking during Metric selection. After `_choose_dataset_view` returns the final `view`, derive:

```python
metric_periods = _custom_metric_periods(metric, view) if isinstance(descriptor, V2ProbeDescriptor) else ()
```

and pass that value to `default_custom_pane`.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_tui_custom.py -k 'custom_metric_periods or probe_capability' -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "fix: resolve custom periods by chart kind"
```

---

### Task 2: Apply Chart-Specific Periods in the Dashboard Modal

**Files:**
- Modify: `src/ccusage_viz/tui.py:8950-9130`
- Test: `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: `_custom_metric_periods(metric: V2MetricDescriptor, kind: str)` from Task 1.
- Produces: a finalized Custom Pane whose `chart.metric_periods` belongs to the selected chart kind.

- [ ] **Step 1: Write a failing Dashboard modal regression test**

Drive the installed Dataset modal through a V2 Metric that declares different Timeline and Ranking periods, select Timeline, intercept `finish_dataset_modal`, and assert:

```python
assert captured.chart.kind == "timeline"
assert captured.chart.metric_periods == ("7d", "30d")
```

The fixture must declare Ranking periods `("all",)` so the old Ranking-derived behavior fails clearly.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `uv run pytest tests/test_tui_dashboard.py -k dataset_modal_uses_selected_chart_periods -q`

Expected: FAIL with `metric_periods == ("all",)` instead of `("7d", "30d")`.

- [ ] **Step 3: Derive periods at modal completion**

Remove the Ranking capability lookup from the Metric-selection branch. In the installed-chart confirmation branch, find the selected Metric by `modal.metric_id`, derive periods for `modal.chart_kinds[modal.index]` with `_custom_metric_periods`, and pass the result directly to `default_custom_pane`.

Keep `modal.metric_periods` empty while navigating so chart-kind selection is the only authority during creation.

- [ ] **Step 4: Run modal and Custom TUI tests**

Run: `uv run pytest tests/test_tui_dashboard.py -k dataset_modal -q && uv run pytest tests/test_tui_custom.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py
git commit -m "fix: bind dataset modal periods to selected chart"
```

---

### Task 3: Preserve Relative `all` Semantics During Metric Switching

**Files:**
- Modify: `src/ccusage_viz/custom_metric_switching.py:70-86`
- Test: `tests/test_custom_metric_switching.py`

**Interfaces:**
- Consumes: `normalize_switch_config(config, target, "period")`.
- Produces: an `all` `DateRange` with the protocol anchor, `period="all"`, and `relative_until=True`.

- [ ] **Step 1: Write the failing regression test**

Create target Metrics whose sole supported periods are `1d` and `all`. Normalize an initially relative `all` configuration to `1d`, then normalize back to `all`, and assert:

```python
assert one_day.date_range.period == "1d"
assert one_day.date_range.relative_until
assert all_time.date_range.since == date(1971, 1, 1)
assert all_time.date_range.period == "all"
assert all_time.date_range.relative_until
```

Build a render context from the returned configuration and assert the heading contains `· all` and does not contain `1971-01-01`.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `uv run pytest tests/test_custom_metric_switching.py -k all_remains_relative -q`

Expected: FAIL because the switch-created `all` range has `relative_until == False`.

- [ ] **Step 3: Fix the `all` DateRange construction**

Change the special case to:

```python
DateRange(
    date(1971, 1, 1),
    config.date_range.until,
    relative_until=True,
    period="all",
)
```

Do not change the anchor, general rendering, or Dataset interpretation.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_custom_metric_switching.py tests/test_render.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_metric_switching.py tests/test_custom_metric_switching.py
git commit -m "fix: preserve relative all metric period"
```

---

### Task 4: Make Live Capability Authoritative During Period Adjustment

**Files:**
- Modify: `src/ccusage_viz/tui.py:9800-9840`
- Test: `tests/test_tui_custom.py` or `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: `_custom_capability_for_component(component) -> CustomChartCapability | None` and existing `adjust_custom_chart(chart, key)`.
- Produces: a temporary adjustment base whose `metric_periods` uses current non-empty capability periods.

- [ ] **Step 1: Write failing adjustment tests**

Cover both required branches:

```python
stale = replace(base, metric_periods=("all",))
capability = CustomChartCapability(("day",), (), (), periods=("7d", "30d"))
effective = replace(stale, metric_periods=capability.periods)
assert adjust_custom_chart(effective, "p").date_range.period == "30d"
assert adjust_custom_chart(effective, "P").date_range.period == "30d"
```

Add an integration assertion through the Dashboard key handler that the submitted configuration never uses `"all"`. Also retain or add a test proving an empty capability period list leaves a Pane with empty `metric_periods` on generic cycling.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_tui_custom.py -k 'live_capability_periods or undeclared_periods' -q`

Expected: the stale-period case fails by selecting `"all"` or not changing to the declared period.

- [ ] **Step 3: Normalize the adjustment base**

Immediately before handling `p/P`, compute:

```python
period_base = (
    replace(base, metric_periods=capability.periods)
    if capability is not None and capability.periods
    else base
)
updated = adjust_custom_chart(period_base, key)
```

Submit `updated` through the existing `apply_custom_query` mutation. Use `period_base.metric_periods` for restricted-period feedback. Do not replace an empty list, because omission intentionally retains generic behavior.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
uv run pytest tests/test_options.py tests/test_tui_custom.py tests/test_tui_dashboard.py -q
uv run pytest -q
```

Expected: all tests PASS.

- [ ] **Step 5: Run static checks**

Run: `uv run ruff check src tests`

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py tests/test_tui_dashboard.py
git commit -m "fix: constrain custom pane period cycling"
```
