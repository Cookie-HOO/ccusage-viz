# Custom Filter Wrapped Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap Dataset Custom filter tabs without breaking mouse targeting, and fully repaint both sides of Custom filter modal transitions.

**Architecture:** `custom_filter_draft.py` will derive a single width-aware, unstyled tab geometry used by rendering and mouse hit testing. Its dynamic tab-row count becomes the source of truth for option viewport and click geometry. The three Custom filter hosts will treat the editor as a rendering boundary: force its first frame and force the caller frame immediately after it closes.

**Tech Stack:** Python 3.12+, dataclasses, terminal ANSI rendering, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-13-custom-filter-wrapped-tabs-design.md`

## Global Constraints

- Change Dataset/Custom filter editor behavior only; do not change native `filter_draft.py`.
- Do not change filter serialization, selection modes, search behavior, or explicit Apply/Cancel semantics.
- Tabs retain declaration order and are never split across lines.
- Rendering and mouse hit testing must consume the same tab geometry.
- A separator and trailing unused cells must not select either tab.
- Force only the first modal frame and first restored caller frame; retain incremental painting during normal editor interaction.

---

## File Structure

- Modify `src/ccusage_viz/custom_filter_draft.py`: add shared wrapped-tab geometry, derive chrome height from it, and route rendering and both mouse calculations through it.
- Modify `tests/test_custom_filter_draft.py`: establish display, tab-hit, and option-coordinate regressions for wrapped tab rows.
- Modify `src/ccusage_viz/tui.py`: add forced paint at Custom standalone and Dashboard custom-filter transition boundaries.
- Modify `src/ccusage_viz/custom_monitor.py`: add forced paint at Custom Monitor filter transition boundaries.
- Modify `tests/test_tui_custom.py` and the existing Dashboard/Custom Monitor test modules as needed: observe `FramePainter.paint(..., force=True)` at modal entry and return, including an idle-timeout return.

## Task 1: Shared wrapped tab geometry and dynamic filter-editor chrome

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Test: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: `CustomFilter`, `CustomFilters`, `Translator`, `display_width()`, and existing `filter_tab_counts()`.
- Produces: a private immutable tab record/layout helper carrying `index`, unstyled `text`, selected count, one-based `x` range, and one-based `y` row; a shared chrome-row helper used by editor normalization, rendering, and option hit testing.

- [ ] **Step 1: Write failing tab-layout and wrapped hit-testing tests**

Add a compact three-filter fixture whose English labels force the second and third tabs onto later rows at a chosen width. Assert the tab layout records preserve whole text and positions, and assert clicks select tabs on every occupied row while rejecting a separator and empty trailing cells.

```python
def test_custom_filter_tabs_wrap_without_splitting_and_share_mouse_geometry() -> None:
    translator = load_translator("en")
    layout = _tab_layout(WRAPPED_CHOICES, translator, active_index=0, accepted=(), width=18)

    assert [(tab.text, tab.x_start, tab.x_end, tab.y) for tab in layout] == [
        ("[Category 0/2]", 1, 15, 1),
        ("Source 0/1", 1, 11, 2),
        ("Kind 0/1", 1, 9, 3),
    ]
    assert _filter_index_at(MouseEvent(0, 4, 2, True, 0), layout) == 1
    assert _filter_index_at(MouseEvent(0, 4, 3, True, 0), layout) == 2
    assert _filter_index_at(MouseEvent(0, 16, 1, True, 0), layout) is None
    assert _filter_index_at(MouseEvent(0, 14, 2, True, 0), layout) is None
```

Also add a Chinese-label case that asserts the `y` positions respect double-width display cells rather than Python string length.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `uv run pytest tests/test_custom_filter_draft.py -k 'wrap or mouse_geometry' -v`

Expected: FAIL because `_tab_layout` has no `width` argument or record geometry and `_filter_index_at` accepts raw choices rather than shared layout.

- [ ] **Step 3: Implement the minimal shared geometry**

Introduce a small private frozen record, for example:

```python
@dataclass(frozen=True, slots=True)
class _FilterTab:
    index: int
    text: str
    selected: int
    x_start: int
    x_end: int
    y: int
```

Change `_tab_layout(..., width: int)` to construct these records in declaration order. Start at `(x=1, y=1)`, prepend ` · ` only when the next tab remains on the current line, and otherwise move the whole next tab to `(1, y + 1)`. Clip only an individual tab which itself exceeds `width`. Change `_filter_index_at` to consume the already-computed layout and compare both `event.y` and its `[x_start, x_end)` interval. Render tabs grouped by their `y` record, decorating only after layout construction.

- [ ] **Step 4: Add failing geometry-shift tests for options below wrapped tabs**

Create a two-or-more-row tab layout with an option list. Assert that `_render_custom_filter_draft()` places the first option after all tab rows plus the status row, and that `run_custom_filter_editor()` toggles that option when clicked at the corresponding later one-based row.

```python
def test_custom_filter_option_click_accounts_for_wrapped_tab_rows() -> None:
    events = iter((MouseEvent(0, 2, 4, True, 0), KeyEvent("\r")))
    result = run_custom_filter_editor(
        (), WRAPPED_CHOICES, load_translator("en"), width=18, height=10,
        paint=lambda _body, _controls: None, read_key=lambda: next(events),
    )
    assert result == (("category", ("fiction",)),)
```

- [ ] **Step 5: Implement dynamic chrome height throughout the editor**

Replace the fixed `2 + optional-search-row` behavior with a helper that derives tab row count from the same width-aware layout, then adds the optional search and mandatory status rows. Thread `width` into `_normalise_draft()` and use the helper in `_normalise_draft()`, `_option_index_at()`, and `_render_custom_filter_draft()`. In the event loop, calculate the tab layout once for tab clicks using the current draft state and pass the same width used for rendering.

- [ ] **Step 6: Run all custom-filter tests**

Run: `uv run pytest tests/test_custom_filter_draft.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the independently testable layout change**

```bash
git add src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py
git commit -m "feat: wrap custom filter tabs"
```

## Task 2: Force repaint on every Custom filter-modal entry and return

**Files:**
- Modify: `src/ccusage_viz/tui.py: _run_custom_standalone_adjustment` and Dashboard custom filter route
- Modify: `src/ccusage_viz/custom_monitor.py: Custom Monitor filter route`
- Test: `tests/test_tui_custom.py`
- Test: existing Dashboard and Custom Monitor test files containing their filter interaction coverage

**Interfaces:**
- Consumes: `FramePainter.paint(frame, force=False)`, existing `paint()` closures, `run_custom_filter_editor()` return/exception behavior, and `AdjustmentTimeout`.
- Produces: exactly one forced first editor paint per invocation and one forced restoration paint after every editor exit path.

- [ ] **Step 1: Write failing host-level paint-spy tests**

Use a `FramePainter` test double that records `force` flags, and monkeypatch `run_custom_filter_editor()` to invoke its supplied `paint` callback exactly once then return `None`. Cover the standalone custom adjustment, Dashboard custom adjustment, and Custom Monitor route. Each assertion must establish that the modal callback used `force=True` once and the next caller paint also used `force=True`.

Add a Dashboard idle-timeout test in which the monkeypatched editor raises `AdjustmentTimeout`; assert the existing `end_adjustment()` path restores with a forced paint rather than normal diff painting.

```python
assert screen.force_flags == [False, True, True]
```

The exact sequence may include pre-modal normal paints; assert the two transition frames by their associated frame/status content rather than relying solely on list index.

- [ ] **Step 2: Run transition tests to verify they fail**

Run: `uv run pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'custom and filter and repaint' -v`

Expected: FAIL because editor callbacks call `screen.paint(...)` without `force=True` and callers resume with normal painting.

- [ ] **Step 3: Implement a first-editor-frame force guard in each host**

For every `run_custom_filter_editor()` call site (`tui.py` standalone, `tui.py` Dashboard, `custom_monitor.py`), capture a local `first_filter_frame = True`. Its modal paint callback calls:

```python
screen.paint(frame, force=first_filter_frame)
first_filter_frame = False
```

Preserve each site’s existing `compose_frame()` parameters and event coordinate adjustments. Do not force every modal frame.

- [ ] **Step 4: Force the restored caller frame on all exit paths**

After `run_custom_filter_editor()` returns—regardless of `edited` being `None` or changed—call the enclosing caller `paint(force=True)` or equivalent before processing later loop work. Ensure Dashboard’s `except AdjustmentTimeout` calls its restoration paint with `force=True` after `end_adjustment()`. In Custom Monitor, force a paint after the editor returns before resuming its normal monitor loop. Adapt standalone’s local `paint` closure to accept `force: bool = False` and forward that flag to `screen.paint`.

- [ ] **Step 5: Run focused transition tests**

Run: `uv run pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'custom and filter and repaint' -v`

Expected: PASS.

- [ ] **Step 6: Run the complete relevant regression suite**

Run: `uv run pytest tests/test_custom_filter_draft.py tests/test_tui_custom.py tests/test_tui_dashboard.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the repaint-boundary change**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/custom_monitor.py \
  tests/test_tui_custom.py tests/test_tui_dashboard.py
git commit -m "fix: repaint around custom filter editor"
```

## Self-Review

- **Spec coverage:** Task 1 covers unbroken wrapped tabs, shared rendering/hit geometry, separator rejection, localized display width, and downstream option viewport/click placement. Task 2 covers forced first modal and restored caller frames across Apply/Cancel-style returns and Dashboard idle timeout while leaving in-modal updates incremental.
- **Placeholder scan:** No TBD/TODO or unspecified test cases remain; the exact private interfaces and commands are declared in their tasks.
- **Type consistency:** `_tab_layout` is the sole producer of `_FilterTab` records; `_filter_index_at` consumes those records. Dynamic chrome receives the same width and current tab layout inputs at normalization, render, and mouse-hit sites.
