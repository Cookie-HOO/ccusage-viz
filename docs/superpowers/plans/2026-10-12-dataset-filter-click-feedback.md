# Dataset Filter Click Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distinguish single-select controls from multi-select controls and make Dataset filter tab mouse hit testing follow the rendered tab geometry.

**Architecture:** Add small pure presentation helpers in `custom_filter_draft.py`: one resolves an option's selection mark, and one produces unstyled tab segments with display-width ranges. Render the mode-specific marks and decorate the shared segments only after coordinates have been calculated. The existing editor event loop consumes the shared hit testing without changing draft semantics.

**Tech Stack:** Python 3.13, pytest, terminal text rendering, existing `display_width`, `styled_text`, and TUI mouse events.

**Spec:** `docs/superpowers/specs/2026-10-12-dataset-filter-click-feedback-design.md`

## Global Constraints

- Change only the custom Dataset filter editor; native `filter_draft.py` is out of scope.
- `multi_select` uses `[ ]` / `[x]`; `single_select` uses `( )` / `(●)`.
- Tab ranges include rendered active brackets and accepted counts, exclude separators, and use terminal display width.
- Do not change explicit Apply/Cancel, search, grid, scrolling, filter values, or color palette selection.

---

### Task 1: Lock presentation and tab-hit behavior with regression tests

**Files:**
- Modify: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: `_render_custom_filter_draft(draft, choices, translator, width, height=24, *, accepted=None, color=False, color_scheme="no-color") -> str`
- Produces: failing tests for mode-specific marks and coordinates across tab label/count/separator text.

- [ ] **Step 1: Write the failing mark-rendering test**

```python
def test_custom_filter_editor_renders_radio_marks_for_single_select() -> None:
    single = CustomFilter(
        "seed_book", LocalizedText("Book", "图书"),
        (CustomFilterOption("a", LocalizedText("A", "甲")),), "single_select",
    )
    rendered = _render_custom_filter_draft(
        CustomFilterDraft((("seed_book", ("a",)),)), (single, CHOICES[0]),
        load_translator("en"), 80,
    )

    assert "(●) A" in rendered
    assert "[ ] Fiction" in rendered
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `pytest tests/test_custom_filter_draft.py::test_custom_filter_editor_renders_radio_marks_for_single_select -v`

Expected: FAIL because the current renderer uses `[x]` for every selected option.

- [ ] **Step 3: Write the failing tab-coordinate test**

```python
def test_custom_filter_editor_clicks_full_rendered_tab_but_not_separator() -> None:
    events = iter((MouseEvent(0, 17, 1, True, 0), KeyEvent(" "), KeyEvent("\r")))
    result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80, height=12,
        paint=lambda _body, _controls: None, read_key=lambda: next(events),
    )
    assert result == (("source", ("app",)),)
```

Add a direct `_filter_index_at` assertion for the ` · ` separator: it returns `None` rather than either adjacent index.

- [ ] **Step 4: Run the focused test module to verify the new assertions expose the current stale range**

Run: `pytest tests/test_custom_filter_draft.py -v`

Expected: mark test fails; the click test may expose the prior label-only tab range depending on its selected coordinate.

- [ ] **Step 5: Commit the test-only change**

```bash
git add tests/test_custom_filter_draft.py
git commit -m "test: cover custom filter selection marks and tab hit ranges"
```

### Task 2: Share custom-filter tab geometry and render mode-specific marks

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Modify: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: `CustomFilter.mode`, `filter_tab_counts()`, `display_width()`, and one-based `MouseEvent.x`/`MouseEvent.y`.
- Produces: `_selection_mark(choice: CustomFilter, selected: bool) -> str` and a shared tab-layout helper used by `_render_custom_filter_draft()` and `_filter_index_at()`.

- [ ] **Step 1: Implement the selection-mark helper**

```python
def _selection_mark(choice: CustomFilter, selected: bool) -> str:
    if choice.mode == "single_select":
        return "(●)" if selected else "( )"
    return "[x]" if selected else "[ ]"
```

Replace the inline option marker in `_render_custom_filter_draft()` with `_selection_mark(current, option.id in selected)`.

- [ ] **Step 2: Implement shared unstyled tab segments**

Create a helper that takes `choices`, `accepted`, `translator`, and `active_index`, then iterates from x position 1. For each choice it creates the plain segment (`[Label n/m]` when active, otherwise `Label n/m`), calculates `end = position + display_width(segment)`, and retains its index/start/end/plain text. Advance by `display_width(" · ")` after every segment. Return an immutable tuple.

- [ ] **Step 3: Render and hit-test through the shared layout**

In `_render_custom_filter_draft()`, derive `tabs` by styling each shared segment while preserving the existing active/nonzero/muted palette choices and join with ` · `. In `_filter_index_at()`, retain `event.y != 1` as the fast rejection, then return the index whose shared `[start, end)` contains `event.x`; do not treat separator coordinates as a tab.

Pass accepted filters into `_filter_index_at()` from `run_custom_filter_editor()` so its count-inclusive ranges match the tabs painted behind the editor.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_custom_filter_draft.py -v`

Expected: PASS.

- [ ] **Step 5: Run integration regression tests**

Run: `pytest tests/test_tui_custom.py tests/test_custom_component.py -v`

Expected: PASS.

- [ ] **Step 6: Commit implementation**

```bash
git add src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py
git commit -m "fix: align custom filter tab clicks with rendered counts"
```

## Self-review

- **Spec coverage:** Task 1 tests both visual selection modes and tab/separator clicks; Task 2 implements the shared geometry and preserves all stated behavior.
- **Placeholder scan:** No TBD/TODO or deferred behavior remains.
- **Type consistency:** `_selection_mark` accepts `CustomFilter` and `bool`; the tab helper is consumed by both rendering and hit testing with the accepted filters used for tab counts.
