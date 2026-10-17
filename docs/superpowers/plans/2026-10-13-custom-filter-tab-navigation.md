# Custom Filter Tab Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Tab as a next-dimension key in Dataset Custom Filter without changing native Filter or other Custom Filter behavior.

**Architecture:** Extend the existing non-search, non-help horizontal-navigation branch in `run_custom_filter_editor()` so Tab shares the current Right Arrow path. Add one focused event-loop regression proving Tab changes the active dimension before toggling an option.

**Tech Stack:** Python 3.12+, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-13-custom-filter-tab-navigation-design.md`

## Global Constraints

- Modify Dataset Custom Filter only.
- Do not modify native `filter_draft.py`.
- Tab switches dimensions only outside search editing and help.
- Preserve all existing arrow, help, search, selection, rendering, footer, and Ctrl-C behavior.

---

### Task 1: Restore Custom Filter Tab navigation

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Test: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: `CustomFilterDraft.move_filter(step, choices)` and the existing event dispatch order.
- Produces: Tab dispatches to `draft.move_filter(1, choices)` in the same branch as Right Arrow.

- [ ] **Step 1: Write the failing regression test**

Use the existing two-dimension `CHOICES` fixture. Send Tab, Space, and Enter; assert the selected value belongs to the second `source` dimension.

```python
def test_custom_filter_editor_tab_switches_to_next_filter_dimension() -> None:
    events = iter((KeyEvent("\t"), KeyEvent(" "), KeyEvent("\r")))
    result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80, height=12,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(events),
    )
    assert result == (("source", ("app",)),)
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `uv run pytest tests/test_custom_filter_draft.py::test_custom_filter_editor_tab_switches_to_next_filter_dimension -v`

Expected: FAIL because Tab is currently ignored and Space toggles the first `category` option.

- [ ] **Step 3: Implement the minimal key-route change**

Change only the next-dimension branch:

```python
elif key in {"\t", "\x1b[C"}:
    draft = draft.move_filter(1, choices)
```

Do not move this branch before search/help handling; the existing event order guarantees Tab remains ignored in help and does not switch during search editing.

- [ ] **Step 4: Run Custom Filter regressions**

Run: `uv run pytest tests/test_custom_filter_draft.py -q`

Expected: PASS.

- [ ] **Step 5: Run relevant host and lint checks**

Run: `uv run pytest tests/test_tui_custom.py tests/test_custom_monitor.py -q`

Run: `uv run ruff check src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py
git commit -m "feat: restore custom filter tab navigation"
```

## Self-Review

- **Spec coverage:** One task covers the sole requested behavior and explicitly preserves search/help dispatch order.
- **Placeholder scan:** Test, implementation, commands, and expected outcomes are concrete.
- **Type consistency:** No interfaces or types change; Tab reuses `move_filter(1, choices)`.
