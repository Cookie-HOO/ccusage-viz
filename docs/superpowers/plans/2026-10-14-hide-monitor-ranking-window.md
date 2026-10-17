# Hide Monitor Ranking Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide rolling-window UI information for Monitor `ranking`, `ranking-dot`, and `list` styles while retaining it for temporal Monitor styles.

**Architecture:** Reuse the existing `monitor_shows_window_control(chart)` predicate as the single presentation-policy source. The standalone Monitor adjustment picker will select a new no-window status template and omit the window value whenever this predicate is false; its action list already applies the same predicate. Dashboard adjustment bindings already suppress `w` for these styles and need regression coverage only.

**Tech Stack:** Python 3, pytest, existing locale dictionaries and terminal UI renderer.

**Spec:** `docs/superpowers/specs/2026-10-14-hide-monitor-ranking-window-design.md`

## Global Constraints

- Preserve `MonitorConfig.window_seconds`; do not alter sampling, query, or reconfiguration behavior.
- Hide window information only for `ranking`, `ranking-dot`, and `list` as defined by `is_monitor_ranking_style()`.
- Restore normal window display automatically for temporal styles.
- Keep `cumulative-bars` on its existing day/granularity status template.
- Do not modify unrelated, currently uncommitted work.

---

## File Structure

- Modify `src/ccusage_viz/locales/en.py`: add the English Monitor quick-adjustment template without a window field.
- Modify `src/ccusage_viz/locales/zh.py`: add the corresponding Chinese template.
- Modify `src/ccusage_viz/monitor.py`: choose the no-window template and avoid supplying a window value for ranking/list presentations.
- Modify `tests/test_monitor.py`: exercise standalone Monitor adjustment rendering for ranking/list and temporal styles.
- Modify `tests/test_tui_dashboard.py`: assert Dashboard’s existing state-aware action builder hides `w` for all three non-temporal styles and restores it for a temporal style.

### Task 1: Make Monitor adjustment status style-aware

**Files:**
- Modify: `src/ccusage_viz/locales/en.py: status.monitor_adjust_quick`
- Modify: `src/ccusage_viz/locales/zh.py: status.monitor_adjust_quick`
- Modify: `src/ccusage_viz/monitor.py: pick_appearance.paint_picker`
- Test: `tests/test_monitor.py`
- Test: `tests/test_tui_dashboard.py: test_monitor_attachment_adjustment_actions_are_localized`

**Interfaces:**
- Consumes: `monitor_shows_window_control(chart: MonitorConfig) -> bool` from `ccusage_viz.options`.
- Consumes: `is_monitor_distribution(chart: MonitorConfig) -> bool` from `ccusage_viz.options`.
- Produces: standalone quick-adjustment status text that has no `WINDOW`/`窗口` segment for `ranking`, `ranking-dot`, and `list`, with the existing status retained for temporal styles.

- [ ] **Step 1: Write the failing Dashboard binding regression test**

Extend `test_monitor_attachment_adjustment_actions_are_localized` in `tests/test_tui_dashboard.py` with these assertions after constructing the existing `ranking` chart:

```python
for style in ("ranking", "ranking-dot", "list"):
    chart = replace(ranking, presentation=replace(ranking.presentation, style=style))
    actions = tui_module._pane_adjustment_actions(
        "monitor", "quick", load_translator("en"), chart=chart
    )
    assert not any(action.text.startswith("w window") for action in actions)

line = replace(ranking, presentation=replace(ranking.presentation, style="line"))
line_actions = tui_module._pane_adjustment_actions(
    "monitor", "quick", load_translator("en"), chart=line
)
assert any(action.text.startswith("w window") for action in line_actions)
```

- [ ] **Step 2: Run the Dashboard regression test to establish the baseline**

Run: `pytest tests/test_tui_dashboard.py::test_monitor_attachment_adjustment_actions_are_localized -v`

Expected: PASS, documenting that the Dashboard binding policy already matches the required styles before changing standalone status text.

- [ ] **Step 3: Write failing standalone Monitor adjustment-status tests**

In `tests/test_monitor.py`, add a parameterized test using the existing `monitor_host.run_monitor` harness conventions. Configure each launch with `MonitorConfig` presentation styles `ranking`, `ranking-dot`, `list`, and `line`; feed keys `("a", "\x03")` so the quick adjustment picker paints once then Monitor exits. Capture each `Screen.paint` frame as text and assert:

```python
assert ("WINDOW" in picker_frame) is expects_window
assert ("w window" in picker_frame) is expects_window
```

Use `expects_window=False` for `ranking`, `ranking-dot`, and `list`, and `expects_window=True` for `line`. Stub the runtime, registry, component, terminal, `input_mode`, and `read_key` using the established standalone monitor tests in the same module; the component only needs the `candidate`, `accepted_options`, sampling fields, `submit`, `render`, and `fail` attributes/methods reached before the picker opens.

- [ ] **Step 4: Run the new standalone test and verify it fails**

Run: `pytest tests/test_monitor.py -k 'adjustment and window' -v`

Expected: FAIL for the three non-temporal styles because `status.monitor_adjust_quick` currently includes `WINDOW {window}` and `paint_picker()` always passes `window` for every non-distribution style.

- [ ] **Step 5: Add no-window localized status templates**

In `src/ccusage_viz/locales/en.py`, directly after `status.monitor_adjust_quick`, add:

```python
"status.monitor_adjust_quick_no_window": "DENSITY {density} · EVERY {interval}s · BY {mode} · TOP {top} · {theme} · {style}",
```

In `src/ccusage_viz/locales/zh.py`, directly after its `status.monitor_adjust_quick`, add:

```python
"status.monitor_adjust_quick_no_window": "密度 {density} · 每 {interval}秒 · 分组 {mode} · TOP {top} · {theme} · {style}",
```

- [ ] **Step 6: Select the no-window template in the standalone picker**

In `src/ccusage_viz/monitor.py`, change the non-distribution branch that currently unconditionally calls `quick_values.update(window=window)` so it only adds the window when `monitor_shows_window_control(chart)` is true:

```python
elif monitor_shows_window_control(chart):
    quick_values.update(window=window)
```

Update the `state_key` selection so quick non-distribution Monitor ranking/list styles select `"status.monitor_adjust_quick_no_window"`; preserve `"status.monitor_distribution_adjust_quick"` for distributions and existing `status.monitor_adjust_{adjustment_page}` selection for all other cases:

```python
state_key = (
    "status.monitor_adjust_advanced"
    if adjustment_page == "advanced"
    else "status.monitor_distribution_adjust_quick"
    if is_monitor_distribution(chart)
    else "status.monitor_adjust_quick_no_window"
    if not monitor_shows_window_control(chart)
    else f"status.monitor_adjust_{adjustment_page}"
)
```

- [ ] **Step 7: Run focused tests and verify the behavior**

Run:

```bash
pytest tests/test_monitor.py -k 'adjustment and window' -v
pytest tests/test_tui_dashboard.py::test_monitor_attachment_adjustment_actions_are_localized -v
```

Expected: PASS. Ranking/list styles have neither the status window field nor `w window`; line retains both; Dashboard actions continue to expose `w` only where applicable.

- [ ] **Step 8: Run the relevant broader suites**

Run:

```bash
pytest tests/test_monitor.py tests/test_tui_dashboard.py tests/test_i18n.py -q
```

Expected: PASS with no localization-key, standalone Monitor lifecycle, or Dashboard adjustment regressions.

- [ ] **Step 9: Commit the implementation**

```bash
git add src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py src/ccusage_viz/monitor.py tests/test_monitor.py tests/test_tui_dashboard.py
git commit -m "fix: hide monitor ranking window details"
```
