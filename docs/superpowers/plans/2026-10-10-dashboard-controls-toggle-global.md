# Dashboard Controls Toggle Global Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Dashboard control-bar toggle hint from chart browsing controls to global operations.

**Architecture:** Keep the existing `controls_hidden` state and `c` key handler unchanged. Change only the Dashboard-local operation label and its documentation/test assertions; standalone labels remain untouched.

**Tech Stack:** Python, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-dashboard-controls-toggle-global-design.md`

## Global Constraints

- `c` remains a Dashboard chart-browse toggle.
- It is presented in Dashboard global operations, not ordinary chart controls.
- Do not change standalone control hints or behavior.

---

### Task 1: Move Dashboard Toggle Copy and Verify Interaction

**Files:**
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Modify: `tests/test_tui_dashboard.py`

- [ ] **Step 1: Write failing Dashboard copy assertion**

```python
def test_dashboard_global_operations_advertise_controls_toggle() -> None:
    assert "c show or hide controls" in load_translator("en").text("status.tui_global_operations")
```

- [ ] **Step 2: Run the focused test**

Run: `uv run pytest tests/test_tui_dashboard.py -k global_operations -q`

Expected: FAIL because the global operations label lacks `c`.

- [ ] **Step 3: Update localized copy and docs**

Add `c show or hide controls` / `c 显示或隐藏控制栏` to `status.tui_global_operations`. Remove Dashboard-specific `c` wording from the browse-control documentation, retaining the actual key behavior entry as a global Dashboard operation.

- [ ] **Step 4: Run validation**

Run:

```bash
uv run ruff check src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_dashboard.py
uv run pytest tests/test_tui_dashboard.py -k global_operations -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py docs/usage.md docs/usage.zh-CN.md tests/test_tui_dashboard.py docs/superpowers/specs/2026-10-10-dashboard-controls-toggle-global-design.md docs/superpowers/plans/2026-10-10-dashboard-controls-toggle-global.md
git commit -m "docs: present dashboard controls toggle as global"
```
