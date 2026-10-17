# Dataset Filter Scalable Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add searchable, counted, scrollable one-to-three-column option selection to Dataset Custom Filter dialogs only.

**Architecture:** Keep selection data in `CustomFilters` and extend `CustomFilterDraft` with ephemeral modal state for query, search editing, viewport, and column count. `custom_filter_draft.py` will own pure grid/layout/rendering helpers and event handling. Dataset hosts pass available terminal height while native filters remain untouched.

**Tech Stack:** Python 3.11+, dataclasses, terminal rendering helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-dataset-filter-scalable-selector-design.md`

## Global Constraints

- Only Dataset/Custom-command filtering (`custom_filter_draft.py`) changes; `filter_draft.py` behavior must remain unchanged.
- `/` search uses localized labels, literal case-insensitive `casefold()` matching, Enter retention, and Esc clearing.
- `c` clears selections only in the active Dataset filter tab.
- `C` cycles `1 → 2 → 3 → 1`; grid layout is row-major.
- All visible terminal strings are localized in English and Simplified Chinese.
- Applying filters remains explicit via Enter and must preserve existing `CustomFilters` wire shape.

---

## File Structure

- Modify: `src/ccusage_viz/custom_filter_draft.py` — draft state, pure list/grid/viewport helpers, modal input dispatch, rendering.
- Modify: `src/ccusage_viz/tui.py` — pass Dataset filter modal height in standalone and Dashboard Custom hosts.
- Modify: `src/ccusage_viz/custom_monitor.py` — pass standalone Custom Monitor filter modal height.
- Modify: `src/ccusage_viz/locales/en.py` — Dataset filter selector labels/status/controls.
- Modify: `src/ccusage_viz/locales/zh.py` — matching Chinese translations.
- Modify: `tests/test_custom_filter_draft.py` — interaction, rendering, grid, and scrolling coverage.
- Modify: `tests/test_i18n.py` — catalog parity remains covered by existing catalog test.

### Task 1: Add pure Dataset filter list and grid state helpers

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Test: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Produces: `CustomFilterDraft.clear(filter_id) -> CustomFilterDraft`, `CustomFilterDraft.cycle_columns() -> CustomFilterDraft`, and helper functions that return filtered `CustomFilterOption` tuples, row-major grid dimensions, and a normalized visible-row range.
- Consumes: `CustomFilter`, `CustomFilterOption`, `LocalizedText`, `CustomFilters`, and `Translator`.

- [ ] **Step 1: Write failing tests for current-tab clearing, search results, and grid cycling**

```python
def test_custom_filter_draft_searches_localized_labels_and_clears_current_tab() -> None:
    draft = CustomFilterDraft((("category", ("fiction",)), ("source", ("app",))))
    assert [option.id for option in _matching_options(CHOICES[0], "fi", load_translator("en"))] == ["fiction"]
    assert draft.clear("category").filters == (("source", ("app",)),)


def test_custom_filter_draft_cycles_one_to_three_columns() -> None:
    draft = CustomFilterDraft(())
    assert draft.cycle_columns().columns == 2
    assert draft.cycle_columns().cycle_columns().columns == 3
    assert draft.cycle_columns().cycle_columns().cycle_columns().columns == 1
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_custom_filter_draft.py -k 'searches_localized or cycles_one' -v`

Expected: FAIL because the helper/state APIs do not yet exist.

- [ ] **Step 3: Extend the immutable draft without changing selected-filter serialization**

```python
@dataclass(frozen=True, slots=True)
class CustomFilterDraft:
    filters: CustomFilters
    filter_index: int = 0
    option_index: int = 0
    query: str = ""
    search_editing: bool = False
    columns: int = 1
    viewport_row: int = 0

    def clear(self, filter_id: str) -> CustomFilterDraft:
        return replace(self, filters=tuple(item for item in self.filters if item[0] != filter_id))

    def cycle_columns(self) -> CustomFilterDraft:
        return replace(self, columns=self.columns % 3 + 1, viewport_row=0)
```

Implement `_matching_options(choice, query, translator)` by filtering `_display_options(choice)` using `query.casefold() in _localized(option.label, translator).casefold()`. Add pure helpers for `rows = ceil(len(options) / columns)`, grid index `row * columns + column`, and clamped focus/viewport ranges.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest tests/test_custom_filter_draft.py -k 'searches_localized or cycles_one' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py
git commit -m "feat: add dataset filter grid state"
```

### Task 2: Render counts, search state, columns, and a scroll viewport

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Test: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Produces: `_render_custom_filter_draft(draft, choices, translator, width, height) -> str` with fixed tabs/search/count rows, viewport-sliced option rows, and continuation status.
- Consumes: the Task 1 draft/grid helpers and `clip_width`, `display_width`, `pad_width` terminal helpers.

- [ ] **Step 1: Write failing rendering tests**

```python
def test_custom_filter_render_reports_selected_matching_and_total_counts() -> None:
    body = _render_custom_filter_draft(
        CustomFilterDraft((("category", ("fiction",)),), query="fi"),
        CHOICES, load_translator("en"), width=80, height=8,
    )
    assert "Selected 1 / Matching 1 / 2" in body
    assert "Search: fi" in body


def test_custom_filter_render_scrolls_multi_column_rows() -> None:
    choices = (_filter_with_options(7),)
    body = _render_custom_filter_draft(
        CustomFilterDraft((), option_index=6, columns=2, viewport_row=2),
        choices, load_translator("en"), width=40, height=5,
    )
    assert "↑" in body
    assert "option-6" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_custom_filter_draft.py -k 'reports_selected or scrolls_multi' -v`

Expected: FAIL because the renderer has neither `height` nor count/grid/viewport output.

- [ ] **Step 3: Implement fixed chrome and width-safe row-major column rendering**

Reserve rows for tabs, search line when query/editing, counts, and top/bottom continuation lines. Calculate `available_rows = max(0, height - fixed_rows - continuation_rows)` and clamp `viewport_row` so the focused row is visible. Render each column at `width // columns`, use `clip_width()` for each selectable row, and use `pad_width()` between columns. Render a localized no-match message for an empty filtered result set and localized above/below indicators only when content is hidden.

- [ ] **Step 4: Run focused rendering tests**

Run: `pytest tests/test_custom_filter_draft.py -k 'reports_selected or scrolls_multi' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py
git commit -m "feat: render scalable dataset filter options"
```

### Task 3: Route Dataset filter modal keys and provide localization

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_filter_draft.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Produces: `run_custom_filter_editor(..., width: int, height: int, ...) -> CustomFilters | None` supporting `/`, printable/paste keys, Backspace, Escape search clearing, `c`, `C`, scrolling navigation, and existing apply/cancel semantics.
- Consumes: Task 1/2 helpers and localized `status.custom_filter_*` messages.

- [ ] **Step 1: Write failing end-to-end editor tests**

```python
def test_custom_filter_editor_search_retains_enter_and_escape_clears_query() -> None:
    frames: list[str] = []
    keys = iter(("/", "f", "i", "\r", "\x1b", "\r"))
    result = run_custom_filter_editor(
        (), CHOICES, load_translator("en"), width=80, height=12,
        paint=lambda body, _controls: frames.append(body), read_key=lambda: next(keys),
    )
    assert result == ()
    assert "Search: fi" in frames[3]
    assert "Search: fi" not in frames[4]


def test_custom_filter_editor_clears_only_active_tab_and_cycles_columns() -> None:
    keys = iter(("C", "C", "C", "c", "\r"))
    result = run_custom_filter_editor(
        (("category", ("fiction",)), ("source", ("app",))), CHOICES,
        load_translator("en"), width=80, height=12,
        paint=lambda _body, _controls: None, read_key=lambda: next(keys),
    )
    assert result == (("source", ("app",)),)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_custom_filter_draft.py -k 'retains_enter or clears_only' -v`

Expected: FAIL because `/`, `c`, `C`, and the required height argument are not implemented.

- [ ] **Step 3: Add localized strings and key dispatch**

Add matching keys in both locales including `label.custom_filter_search`, `status.custom_filter_count`, `status.custom_filter_search_count`, `status.custom_filter_no_matches`, `status.custom_filter_more_above`, `status.custom_filter_more_below`, and revise `status.filter_controls` to include `/ search`, `c clear current`, and `C columns`.

In `run_custom_filter_editor`, dispatch search editing before generic keys: `/` begins editing; printable keys append query; `\x7f`/`\b` removes; Enter ends editing but retains query; Escape clears query and ends editing. Outside editing, `c` calls `clear(current.id)`, `C` cycles columns, and `j`/`k` changes focus then normalizes viewport. On tab change reset `query`, `search_editing`, `option_index`, and `viewport_row`.

- [ ] **Step 4: Run editor and catalog tests**

Run: `pytest tests/test_custom_filter_draft.py tests/test_i18n.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_filter_draft.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_custom_filter_draft.py tests/test_i18n.py
git commit -m "feat: add dataset filter search controls"
```

### Task 4: Supply modal height from Dataset hosts and regression-test

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/custom_monitor.py`
- Modify: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: `run_custom_filter_editor(..., height=...)` from Task 3.
- Produces: all Custom Dataset filter modal call sites provide terminal line count; no native `run_filter_editor()` call changes.

- [ ] **Step 1: Write a call-signature regression test if existing host seams permit it**

```python
def test_custom_filter_editor_short_height_keeps_focused_option_visible() -> None:
    frames: list[str] = []
    keys = iter(("j", "j", "j", "j", "\r"))
    run_custom_filter_editor(
        (), (_filter_with_options(8),), load_translator("en"), width=30, height=6,
        paint=lambda body, _controls: frames.append(body), read_key=lambda: next(keys),
    )
    assert "option-4" in frames[-1]
```

- [ ] **Step 2: Run the regression test to verify the new renderer behavior**

Run: `pytest tests/test_custom_filter_draft.py -k short_height -v`

Expected: PASS after Task 2/3 implementation.

- [ ] **Step 3: Pass terminal height at every Custom Dataset filter editor call site**

```python
edited = run_custom_filter_editor(
    base.filters, filters, translator,
    width=size.columns, height=size.lines,
    paint=paint_custom_filter_editor, read_key=read_custom_filter_key,
)
```

Apply this only to the three Dataset paths: standalone custom historical adjustment in `tui.py`, Dashboard custom adjustment in `tui.py`, and Custom Monitor in `custom_monitor.py`. Keep native `run_filter_editor()` calls unchanged.

- [ ] **Step 4: Run focused and broader regressions**

Run: `pytest tests/test_custom_filter_draft.py tests/test_tui_custom.py tests/test_tui_dashboard.py tests/test_i18n.py -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite and static checks**

Run: `uv run ruff check src tests && uv run pytest -q`

Expected: both commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/custom_monitor.py tests/test_custom_filter_draft.py
git commit -m "feat: enable scrolling dataset filter dialogs"
```
