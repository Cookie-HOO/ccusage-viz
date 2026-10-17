# Hide Custom Monitor Ranking Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove view and source-window facts from Custom Monitor headings in `ranking`, `ranking-dot`, and `list` styles while preserving them for temporal styles.

**Architecture:** `CustomMonitorComponent._display_period_label()` owns style-specific duration copy. It will return an empty label for the existing shared monitor-ranking-style predicate; `heading()` will join only nonempty title fragments. The existing cumulative-bars branch remains first and unchanged.

**Tech Stack:** Python 3, pytest, Custom Monitor component.

**Spec:** `docs/superpowers/specs/2026-10-14-hide-custom-monitor-ranking-window-design.md`

## Global Constraints

- Preserve display-window and source-window configuration and all collection/projection behavior.
- Omit both view and data-window facts only for `ranking`, `ranking-dot`, and `list`.
- Retain duration facts for temporal styles.
- Retain cumulative-bars’ current dedicated heading.
- Do not overwrite unrelated uncommitted work.

---

## File Structure

- Modify `src/ccusage_viz/custom_monitor_component.py`: suppress the duration heading fragment for monitor ranking/list styles and avoid a dangling separator.
- Modify `tests/test_custom_monitor_component.py`: cover all non-temporal styles in English and Chinese and one temporal control case.

### Task 1: Suppress Custom Monitor ranking heading durations

**Files:**
- Modify: `src/ccusage_viz/custom_monitor_component.py: CustomMonitorComponent.heading and _display_period_label`
- Modify: `tests/test_custom_monitor_component.py: heading test near test_metric_switch_updates_heading`

**Interfaces:**
- Consumes: `is_monitor_ranking_style(style: str) -> bool` from `ccusage_viz.options`.
- Produces: `CustomMonitorComponent.heading(*, language: str) -> str` with no view/data-window fragment for Custom Monitor ranking/list styles.

- [ ] **Step 1: Write the failing parameterized component test**

Replace the direct ranking-style heading assertions in `tests/test_custom_monitor_component.py` with a parameterized test that creates the existing accepted component and applies each style:

```python
@pytest.mark.parametrize("style", ("ranking", "ranking-dot", "list"))
def test_ranking_style_heading_omits_view_and_data_window(style: str) -> None:
    component = _accepted_metric_component(style=style)

    assert component.heading(language="en") == "Model · Requests"
    assert component.heading(language="zh") == "模型 · 请求数"
```

Add a temporal control in the same test module:

```python
def test_temporal_custom_monitor_heading_keeps_view_and_data_window() -> None:
    component = _accepted_metric_component(style="line")

    assert component.heading(language="en") == "Model · Requests · view 1h · data window 90s"
    assert component.heading(language="zh") == "模型 · 请求数 · 视图 1h · 数据窗口 90s"
```

Use the exact existing fixture/helper setup in that module rather than changing data construction outside these tests.

- [ ] **Step 2: Run the heading tests and verify they fail**

Run: `uv run pytest tests/test_custom_monitor_component.py -k 'heading and (ranking or temporal)' -v`

Expected: ranking/list assertions fail because the component currently appends `view 1h · data window 90s` to all non-cumulative styles. The temporal control passes.

- [ ] **Step 3: Implement the minimal component policy**

Import `is_monitor_ranking_style` in `src/ccusage_viz/custom_monitor_component.py`. In `_display_period_label()`, after the cumulative-bars return path and before calculating `view`, add:

```python
if is_monitor_ranking_style(self.candidate.presentation.style):
    return ""
```

In `heading()`, filter the duration fragment while joining so no trailing separator is rendered:

```python
return " · ".join(
    part for part in (group, title, self._display_period_label(language)) if part
)
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
uv run pytest tests/test_custom_monitor_component.py -k 'heading and (ranking or temporal)' -v
uv run pytest tests/test_custom_monitor.py::test_monitor_adjustments_cycle_display_window_and_distribution_day -v
```

Expected: PASS. All three ranking/list styles omit both duration facts; line retains them; cumulative-bars heading remains covered by the existing adjustment test.

- [ ] **Step 5: Run the Custom Monitor suite**

Run: `uv run pytest tests/test_custom_monitor_component.py tests/test_custom_monitor.py tests/test_tui_custom.py -q`

Expected: PASS. If an unrelated pre-existing worktree failure occurs, record its test name and error without changing unrelated code.

- [ ] **Step 6: Commit the implementation**

```bash
git add src/ccusage_viz/custom_monitor_component.py tests/test_custom_monitor_component.py
git commit -m "fix: hide custom monitor ranking window details"
```
