# Custom Ranking Scrollbar Hover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make overflowing Custom Ranking scrollbars render as a compact line-and-colored-thumb indicator until the pointer enters their right-side gutter.

**Architecture:** Extend terminal mouse reporting to emit unpressed pointer motion. The Dashboard owns an ephemeral hovered scrollbar pane index, derives it from the already-rendered `Scrollbar` geometry and current pane layout, and passes a boolean through the Custom Ranking render call. The flat and grouped renderers retain one-cell gutter geometry and change only their glyph styling based on that boolean.

**Tech Stack:** Python 3.11+, pytest, ANSI terminal rendering, SGR mouse reporting.

**Spec:** `docs/superpowers/specs/2026-10-14-custom-ranking-scrollbar-hover-design.md`

## Global Constraints

- Apply only to overflowing Custom Ranking results, including both flat and grouped renderers.
- Reserve exactly the existing one-cell scrollbar gutter in both compact and hover states; switching state must not alter widths, wrapping, offsets, or scrollbar geometry.
- Default state is compact: muted thin-line track and highlight-colored thumb range.
- Hover state is the existing full scrollbar appearance: `█` / `#` bold highlight thumb and `│` / `|` muted track.
- Use all-motion terminal mouse reporting; unpressed motion must not start drag, page, focus, or scroll.
- Clear hover state for overlays/non-chart body, missing scrollbar, layout changes, and pointer exit.
- Preserve all existing wheel, track-click, thumb-drag, ASCII, color-scheme, and no-color behavior.

---

### Task 1: Enable and decode unpressed pointer motion

**Files:**
- Modify: `src/ccusage_viz/tui_input.py:46-57`
- Modify: `tests/test_tui_input.py:135-166`

**Interfaces:**
- Consumes: `MouseEvent(button: int, x: int, y: int, pressed: bool, modifiers: int)`.
- Produces: existing `MouseEvent` instances for SGR all-motion reports, including reports whose button field is `3` and whose `pressed` field is `False`.

- [ ] **Step 1: Write the failing terminal-mode assertion**

In `tests/test_tui_input.py`, extend `test_tui_input_mode_disables_mouse_and_restores_terminal_on_error` so the exact expected output includes all-motion enable/disable sequences:

```python
assert output.getvalue() == tui_input_module._MOUSE_ENABLE + tui_input_module._MOUSE_DISABLE
assert "?1003h" in tui_input_module._MOUSE_ENABLE
assert "?1003l" in tui_input_module._MOUSE_DISABLE
```

Add a decoder test near the existing mouse decoding tests:

```python
def test_tui_input_decodes_unpressed_motion() -> None:
    decoder = InputDecoder()
    decoder.feed("\x1b[<35;20;5M")
    assert decoder.next() == MouseEvent(3, 20, 5, False, 0b100000)
```

- [ ] **Step 2: Run the targeted tests to verify the motion test fails**

Run: `pytest tests/test_tui_input.py -q`

Expected: the new mode assertion fails because `_MOUSE_ENABLE` has no `?1003h` and `_MOUSE_DISABLE` has no `?1003l`; do not change the decoder button mapping unless the new decode assertion demonstrates a real defect.

- [ ] **Step 3: Enable SGR all-motion reports**

In `src/ccusage_viz/tui_input.py`, change the constants only, preserving paired lifecycle behavior:

```python
_MOUSE_ENABLE = "\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h\x1b[?2004h"
_MOUSE_DISABLE = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l"
```

The existing parser already creates a `MouseEvent` for a non-wheel SGR report and calculates `pressed` from the final `M`/`m`; preserve that behavior so the all-motion report is harmlessly represented as `MouseEvent(3, ..., False, _MOUSE_MOTION)`.

- [ ] **Step 4: Run the input tests**

Run: `pytest tests/test_tui_input.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the input capability**

```bash
git add src/ccusage_viz/tui_input.py tests/test_tui_input.py
git commit -m "feat: enable terminal scrollbar hover tracking"
```

### Task 2: Add a shared compact scrollbar painter and wire both ranking renderers

**Files:**
- Modify: `src/ccusage_viz/scrollbar.py:1-55`
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py:21-226`
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py:217-640`
- Modify: `tests/test_custom_ranking_scroll.py:1430-1505`

**Interfaces:**
- Consumes: `Scrollbar`, `RenderContext`, `ColorScheme`, and `hovered: bool` passed by each Custom Ranking renderer.
- Produces: `scrollbar_mark(bar: Scrollbar, row: int, context: RenderContext, hovered: bool) -> tuple[str, str, bool]`, returning `(glyph, color, bold)` for one gutter cell.
- Produces: optional keyword-only `scrollbar_hovered: bool = False` on `render_custom_ranking_viewport(...)` and `render_grouped_custom_ranking_viewport(...)`.

- [ ] **Step 1: Write failing renderer tests for flat and grouped viewports**

Add tests in `tests/test_custom_ranking_scroll.py` using existing `render(...)`, `projection(...)`, `grouped_projection(...)`, `context(...)`, and ANSI stripping helpers. First render overflow with the default parameter, then render it with `scrollbar_hovered=True`. Assert the same `Scrollbar` dataclass geometry in both cases and assert glyph distinction at a non-thumb track row and a thumb row.

Use assertions shaped as follows (adapt helper names to the existing test module):

```python
compact = render(model, viewport, ctx, scrollbar=True)
bar = viewport.scrollbar
assert bar is not None
hovered = render(model, viewport, ctx, scrollbar=True, scrollbar_hovered=True)
assert viewport.scrollbar == bar
compact_rows = strip_ansi(compact).splitlines()
hovered_rows = strip_ansi(hovered).splitlines()
track_row = next(row for row in range(bar.top, bar.top + bar.height) if not bar.on_thumb(row))
assert compact_rows[track_row][-1] == "│"
assert hovered_rows[track_row][-1] == "│"
assert compact_rows[bar.thumb_top][-1] == "│"
assert hovered_rows[bar.thumb_top][-1] == "█"
```

For ASCII contexts, assert `"|"` and `"#"` equivalents. Cover both the flat and grouped renderer paths and confirm their `column`, `top`, `height`, `thumb_top`, and `thumb_size` do not change.

- [ ] **Step 2: Run renderer tests to verify the hover assertions fail**

Run: `pytest tests/test_custom_ranking_scroll.py -q`

Expected: FAIL because neither renderer accepts `scrollbar_hovered` and the idle thumb is currently full-width `█`/`#`.

- [ ] **Step 3: Implement a pure glyph/style selector**

Add this function to `src/ccusage_viz/scrollbar.py` (the colors are passed in rather than importing palette code, keeping geometry independent from themes):

```python
def mark_at(
    self, row: int, *, ascii: bool, hovered: bool, highlight: str, muted: str
) -> tuple[str, str, bool]:
    """Return the glyph, color, and bold state for one scrollbar gutter cell."""
    if hovered and self.on_thumb(row):
        return ("#" if ascii else "█", highlight, True)
    return ("|" if ascii else "│", highlight if self.on_thumb(row) else muted, False)
```

Use `row` rather than `y` to match the renderer’s viewport-local coordinate convention. This preserves a visible compact track line while making the thumb identifiable by highlight color only.

- [ ] **Step 4: Thread hover state through both renderer signatures and painters**

Add `scrollbar_hovered: bool = False` beside `scrollbar: bool = False` in both renderer signatures. In each existing `if gutter ...` drawing loop, replace local `thumb`/`mark` construction with:

```python
mark, color, bold = bar.mark_at(
    row,
    ascii=context.ascii,
    hovered=scrollbar_hovered,
    highlight=scheme.highlight,
    muted=scheme.muted,
)
```

Then call `styled_text(mark, color, context, bold=bold)`. Do not change gutter calculation, `Scrollbar` construction, row padding, clipping, or viewport state.

- [ ] **Step 5: Run targeted renderer and scrollbar tests**

Run: `pytest tests/test_scrollbar.py tests/test_custom_ranking_scroll.py -q`

Expected: PASS.

- [ ] **Step 6: Commit renderer behavior**

```bash
git add src/ccusage_viz/scrollbar.py src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/grouped_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "feat: add compact custom ranking scrollbar state"
```

### Task 3: Track gutter hover in Dashboard and pass it into rendering

**Files:**
- Modify: `src/ccusage_viz/tui.py:2040-2135`
- Modify: `src/ccusage_viz/tui.py:5715-5725`
- Modify: `src/ccusage_viz/tui.py:8260-8345`
- Modify: `src/ccusage_viz/tui.py:9800-9825`
- Modify: `tests/test_custom_ranking_dashboard_scroll.py:227-305`

**Interfaces:**
- Consumes: `MouseEvent`, `displayed_layout`, `displayed_header_rows`, `frame_style`, `focused`, `panes`, and the viewport’s existing `Scrollbar.contains(x, y)` method.
- Produces: local `scrollbar_hovered_pane: int | None`, where the value is a pane index only while its active Custom Ranking scrollbar gutter contains the pointer.
- Produces: `scrollbar_hovered=scrollbar_hovered_pane == pane_index` in the existing viewport renderer call path.

- [ ] **Step 1: Write failing Dashboard hover tests**

In `tests/test_custom_ranking_dashboard_scroll.py`, add a flat-ranking test that uses the fixture’s `run`, `panes`, `frames`, and `layouts`. At a callback after first paint, obtain `bar = panes[0].ranking_viewport.scrollbar` and `rect = layouts[-1].pane(0)`. Send an unpressed motion event positioned at the thumb:

```python
MouseEvent(
    3,
    rect.left + bar.column + 1,
    rect.top + bar.thumb_top + 1,
    False,
    0b100000,
)
```

On the next callback, assert the frame’s gutter character for that screen row is `"█"`. Then send an unpressed motion event one cell left of the gutter and assert on the subsequent callback that the same thumb’s gutter character is `"│"`. Record `offset` before both moves and assert it is unchanged; assert no focus callback was added.

Add an equivalent grouped-ranking test by configuring the existing fixture model with `grouped_projection()` as done by `test_grouped_dashboard_scrollbar_drag_uses_active_viewport`. This validates the active grouped viewport is used rather than the inactive flat one.

Add an overlay-clearing assertion: after a hover, open an existing blocking overlay through its established keyboard trigger, then assert a repaint no longer contains a full-thumb glyph in the former gutter position. Keep this assertion only if the fixture’s overlay trigger and frames are stable; otherwise unit-test the state-clear branch via the existing event callback pattern.

- [ ] **Step 2: Run the Dashboard tests to verify failure**

Run: `pytest tests/test_custom_ranking_dashboard_scroll.py -q`

Expected: FAIL because unpressed `MouseEvent` instances are ignored before a hover state is recorded and rendering receives no hover flag.

- [ ] **Step 3: Add Dashboard hover state and render propagation**

Near the existing `scrollbar_drag: tuple[int, int] | None = None` local state in `dashboard(...)`, declare:

```python
scrollbar_hovered_pane: int | None = None
```

Extend the internal custom-pane render function’s inputs as needed so the render-args construction near `_render_custom_historical` includes:

```python
scrollbar_hovered=scrollbar_hovered_pane == pane_index
```

Thread `pane_index` and the hover boolean through only the Dashboard chart-render call chain. Calls outside Dashboard rely on the renderer default and require no changes.

- [ ] **Step 4: Add a dedicated unpressed-motion handler**

Near `handle_scrollbar_drag`, define `handle_scrollbar_hover(event: MouseEvent) -> bool`. It must return `False` unless all of these are true: chart body is active, `displayed_layout` exists, no blocking overlay/modal is active, event is unpressed, and `event.modifiers & 0b100000` is set. For qualifying events:

```python
grid_x = event.x - 1
grid_y = event.y - displayed_header_rows - 1
selected = layout_pane_at(displayed_layout, grid_x, grid_y)
hovered: int | None = None
if selected is not None:
    pane = panes[selected]
    viewport = pane.active_ranking_viewport if isinstance(pane, TuiCustomPane) else None
    if viewport is not None and viewport.active and viewport.scrollbar is not None:
        rect = displayed_layout.pane(selected)
        framed = frame_style != "none" or selected == focused
        interior_column = grid_x - rect.left - int(framed)
        interior_row = grid_y - rect.top - int(framed)
        if viewport.scrollbar.contains(interior_column, interior_row):
            hovered = selected
if scrollbar_hovered_pane == hovered:
    return False
scrollbar_hovered_pane = hovered
return True
```

Declare `nonlocal scrollbar_hovered_pane`. The `True` return signals the main loop to redraw, not that the event is a click. Do not modify `scrollbar_drag`, `viewport.offset`, focus, or `last_click`.

For blocked/non-motion events, clear a non-`None` `scrollbar_hovered_pane` and return whether it changed, except leave drag behavior independent. At the same places that invalidate layouts/viewports or enter blocking overlays, clear it defensively.

- [ ] **Step 5: Call hover handling before click handling without consuming drag events**

In the primary Dashboard mouse-event dispatch near `tui.py:9809`, invoke the hover handler only for an unpressed motion event before `handle_scrollbar_drag` and `handle_pane_mouse`:

```python
if isinstance(event, MouseEvent):
    hover_changed = handle_scrollbar_hover(event)
    if handle_scrollbar_drag(event):
        continue
    if handle_pane_mouse(event):
        continue
    if hover_changed:
        continue
```

Preserve the existing event-loop redraw path rather than adding a separate renderer invocation. Verify all other `MouseEvent` dispatch sites that can run while Dashboard is active either invoke this same handler or explicitly clear hover when they replace `displayed_layout`/open a blocking view.

- [ ] **Step 6: Run Dashboard regression tests**

Run: `pytest tests/test_custom_ranking_dashboard_scroll.py tests/test_tui_dashboard.py -q`

Expected: PASS, including existing track-click, drag, and wheel tests.

- [ ] **Step 7: Commit Dashboard behavior**

```bash
git add src/ccusage_viz/tui.py tests/test_custom_ranking_dashboard_scroll.py
git commit -m "feat: expand custom ranking scrollbar on hover"
```

### Task 4: Run full validation and inspect the final diff

**Files:**
- Verify: `src/ccusage_viz/tui_input.py`
- Verify: `src/ccusage_viz/scrollbar.py`
- Verify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Verify: `src/ccusage_viz/render/grouped_ranking_viewport.py`
- Verify: `src/ccusage_viz/tui.py`
- Verify: `tests/test_tui_input.py`
- Verify: `tests/test_scrollbar.py`
- Verify: `tests/test_custom_ranking_scroll.py`
- Verify: `tests/test_custom_ranking_dashboard_scroll.py`

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: a validated feature branch with no changes outside the designed scope.

- [ ] **Step 1: Run formatter/linter checks used by the project**

Read `pyproject.toml` to use the repository’s configured commands. Then run:

```bash
uv run ruff check src/ccusage_viz tests
uv run ruff format --check src/ccusage_viz tests
```

Expected: PASS. If formatting fails, run `uv run ruff format` only on modified Python files, then repeat both checks.

- [ ] **Step 2: Run the complete test suite**

Run: `uv run pytest -q`

Expected: PASS. If a failure is unrelated to the changed files, record the test name and failure output before deciding whether it is pre-existing; do not weaken existing assertions.

- [ ] **Step 3: Inspect scope and behavior-sensitive diff**

Run:

```bash
git diff HEAD~3..HEAD --check
git diff HEAD~3..HEAD -- src/ccusage_viz/tui_input.py src/ccusage_viz/scrollbar.py src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/grouped_ranking_viewport.py src/ccusage_viz/tui.py tests/test_tui_input.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py
```

Confirm: all-motion mode is disabled on exit; idle thumb is color-only rather than full glyph; only the hovered active gutter is expanded; and drag/click geometry is unchanged.

- [ ] **Step 4: Commit any formatting-only repair if needed**

```bash
git status --short
git add <only-files-changed-by-formatting>
git commit -m "style: format scrollbar hover changes"
```

Skip this step when there are no formatting-only changes.

## Plan Self-Review

- **Spec coverage:** Task 1 covers all-motion input and safe decode. Task 2 covers compact/hover visual states, both renderer types, shared geometry, ASCII, color, and no-color behavior through existing `styled_text`. Task 3 covers viewport hit testing, redraw only on state transitions, clearing conditions, and non-interference with drag/click/wheel/focus. Task 4 validates regressions and scope.
- **Placeholder scan:** No TBD/TODO or deferred implementation steps remain; each code task identifies signatures, concrete state, control flow, and test commands.
- **Type consistency:** `scrollbar_hovered: bool` is the renderer keyword in Task 2 and the exact keyword passed in Task 3. `scrollbar_hovered_pane: int | None` is Dashboard-only. `Scrollbar.mark_at(...)` receives viewport-local rows, matching `Scrollbar.contains`/`on_thumb` use in current renderers.
