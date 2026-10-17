# Dashboard Narrow-pane Hang Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Dashboard pane resizing and narrow Unicode text from blocking the TUI main loop.

**Architecture:** Make the shared Unicode wrapping primitive progress-safe at every positive width. Make the Dashboard layout resolver allocate 4-column by 3-row bands whenever the terminal has room, while degrading to zero-sized bands only when the physical viewport cannot fit every band. The Dashboard renderer detects any rectangle below that normal minimum and emits a bounded placeholder without calling the pane renderer; the compositor and frame helper preserve exact output geometry for zero and tiny rectangles.

**Tech Stack:** Python 3.12+, standard library `unicodedata`, pytest, existing terminal TUI/layout code.

**Spec:** `docs/superpowers/specs/2026-10-14-dashboard-narrow-pane-hang-design.md`

## Global Constraints

- Do not change the TUI's existing `ISIG`/decoded-Ctrl-C model.
- Preserve normal-width Dashboard topology, persisted weight format, and renderer output.
- `wrap_width()` must terminate for all Unicode input and every non-negative requested width.
- Use `MIN_PANE_WIDTH = 4` and the existing `MIN_PANE_HEIGHT = 3` for normal Dashboard band allocation.
- When the physical viewport cannot fit all minimum bands, remain recoverable: do not raise from layout resolution and do not invoke the regular pane renderer for undersized rectangles.

---

## File Structure

- Modify `src/ccusage_viz/formatting.py`: make `wrap_width()` consume an unplaceable wide glyph rather than repeatedly emitting an empty row.
- Modify `tests/test_formatting.py`: specify width-one CJK, emoji, mixed content, whitespace, ANSI, and non-positive-width wrapping behavior.
- Modify `src/ccusage_viz/dashboard_layout.py`: define the Dashboard width minimum, allocate preferred minima when feasible, and use zero-sized overflow bands when physical geometry is impossible.
- Modify `tests/test_dashboard_layout.py`: verify preferred minimum allocation and tiny-terminal recovery.
- Modify `src/ccusage_viz/tui.py`: refuse no-op resize mutations at the geometry minimum; render undersized panes as a bounded placeholder; make framing/composition exact for tiny or zero rectangles.
- Modify `tests/test_tui_dashboard.py`: exercise resize saturation and confirm the undersized-pane path skips `_pane_render` and exits through decoded Ctrl-C.

### Task 1: Guarantee Unicode wrapping makes forward progress

**Files:**
- Modify: `src/ccusage_viz/formatting.py:133-172`
- Test: `tests/test_formatting.py:70-75`

**Interfaces:**
- Consumes: `char_width(char: str) -> int`, `display_width(value: str) -> int`.
- Produces: unchanged public signature `wrap_width(value: str, width: int) -> tuple[str, ...]`; every positive-width invocation returns after consuming or discarding all source characters.

- [ ] **Step 1: Write failing regression tests for unplaceable glyphs**

Add these tests below `test_wrap_width_preserves_word_boundaries_and_wide_character_widths`:

```python
@pytest.mark.parametrize(
    ("value", "width", "expected"),
    [
        ("路由请求数", 1, ("路", "由", "请", "求", "数")),
        ("🙂a", 1, ("🙂", "a")),
        ("a路b", 1, ("a", "路", "b")),
        ("路 由", 1, ("路", "由")),
        ("\x1b[31m路由\x1b[0m", 1, ("\x1b[31m路", "由\x1b[0m")),
    ],
)
def test_wrap_width_consumes_characters_that_exceed_a_one_cell_viewport(
    value: str, width: int, expected: tuple[str, ...]
) -> None:
    assert wrap_width(value, width) == expected


def test_wrap_width_retains_empty_result_for_non_positive_widths() -> None:
    assert wrap_width("路由", 0) == ()
    assert wrap_width("route", -1) == ()
```

For the ANSI case, if the exact escape-sequence distribution is not the current function's stable public behavior, replace only that exact equality assertion with these two assertions while retaining the CJK/emoji exact cases:

```python
rows = wrap_width("\x1b[31m路由\x1b[0m", 1)
assert tuple(strip_ansi(row) for row in rows) == ("路", "由")
assert len(rows) == 2
```

Import `strip_ansi` in the existing formatting import block when using that variant.

- [ ] **Step 2: Run the new tests to verify the current implementation stalls**

Run the individual test under a process-level timeout so the intentional infinite loop cannot block the shell:

```bash
uv run python - <<'PY'
import signal
from ccusage_viz.formatting import wrap_width

def alarm(_signum: int, _frame: object) -> None:
    raise TimeoutError("wrap_width stalled")

signal.signal(signal.SIGALRM, alarm)
signal.setitimer(signal.ITIMER_REAL, 0.2)
try:
    wrap_width("路由请求数", 1)
except TimeoutError as error:
    print(error)
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
PY
```

Expected: prints `wrap_width stalled`. Do not run the newly added pytest case until after Step 3.

- [ ] **Step 3: Implement the minimal progress guarantee**

In the `while display_width(word) > width:` loop in `wrap_width()`, retain the character-scanning loop. Immediately after it, replace the unconditional append/slice with a branch that consumes the first character when `part` is empty:

```python
if not part:
    # A wide glyph cannot fit a one-cell viewport. Emit and consume it so
    # this loop always advances; callers may clip it to their own geometry.
    part, word = word[0], word[1:]
else:
    word = word[len(part) :]
rows.append(part)
```

Do not change the `width <= 0` early return or the word-boundary logic above this loop.

- [ ] **Step 4: Run the formatting test module**

Run:

```bash
uv run pytest tests/test_formatting.py -v
```

Expected: PASS, including the width-one CJK and emoji cases.

- [ ] **Step 5: Commit the wrapping fix**

```bash
git add src/ccusage_viz/formatting.py tests/test_formatting.py
git commit -m "fix: guarantee progress in narrow text wrapping"
```

### Task 2: Allocate Dashboard minimum bands and recover from tiny terminals

**Files:**
- Modify: `src/ccusage_viz/dashboard_layout.py:8-9, 173-194, 264-282`
- Test: `tests/test_dashboard_layout.py:192-211, 219-249`

**Interfaces:**
- Consumes: `resolve_pane_layout(layout, pane_count, width, height, divider_style, column_weights, row_weights)`.
- Produces: `MIN_PANE_WIDTH: int = 4`, retained `MIN_PANE_HEIGHT: int = 3`, and unchanged `resolve_pane_layout(...) -> PaneLayout` which never raises solely because a positive viewport cannot supply one positive cell per logical band.

- [ ] **Step 1: Write failing layout tests**

Add these tests after `test_weighted_geometry_allocates_shared_logical_bands`:

```python
def test_weighted_layout_keeps_each_feasible_dashboard_band_at_its_minimum() -> None:
    layout = resolve_pane_layout(
        layout="1x2",
        pane_count=2,
        width=80,
        height=3,
        column_weights=(1, 1_000),
        row_weights=(1,),
    )

    assert layout.column_sizes == (4, 75)
    assert layout.row_sizes == (3,)


def test_layout_recovers_when_physical_viewport_cannot_fit_all_bands() -> None:
    layout = resolve_pane_layout(
        layout="1x2",
        pane_count=2,
        width=1,
        height=1,
        divider_style="line",
    )

    assert layout.width == 1
    assert layout.height == 1
    assert sum(layout.column_sizes) + layout.gutter == 1
    assert sum(layout.row_sizes) == 1
    assert layout.column_sizes == (0, 0)
    assert layout.row_sizes == (1,)
```

Add `MIN_PANE_WIDTH` to the dashboard-layout import list and assert it explicitly in the feasible test instead of hard-coding `4` where appropriate:

```python
assert layout.column_sizes[0] == MIN_PANE_WIDTH
```

- [ ] **Step 2: Run the targeted tests to verify failure**

Run:

```bash
uv run pytest tests/test_dashboard_layout.py::test_weighted_layout_keeps_each_feasible_dashboard_band_at_its_minimum tests/test_dashboard_layout.py::test_layout_recovers_when_physical_viewport_cannot_fit_all_bands -v
```

Expected: first test fails because the current left band is one cell; second test raises `ValueError: viewport is too small for the configured Dashboard layout`.

- [ ] **Step 3: Implement minimum-aware allocation**

At the constants section add:

```python
MIN_PANE_WIDTH = 4
MIN_PANE_HEIGHT = 3
```

Change the two resolver calls to pass their axis minima:

```python
column_sizes = _allocate_axis(width, resolved_columns, gutter, minimum=MIN_PANE_WIDTH)
row_sizes = _allocate_axis(height, resolved_rows, gutter, minimum=MIN_PANE_HEIGHT)
```

Replace `_allocate_axis` with a `minimum` parameter and these exact branches:

```python
def _allocate_axis(
    total: int, weights: tuple[int, ...], gutter: int, *, minimum: int
) -> tuple[int, ...]:
    available = total - gutter * (len(weights) - 1)
    if available >= minimum * len(weights):
        base = minimum
    elif available >= len(weights):
        base = 1
    else:
        # There is not enough physical space to display every logical band.
        # Keep exact geometry and let Dashboard rendering skip zero rectangles.
        return tuple(0 for _ in weights)
    distributable = available - base * len(weights)
    weight_total = sum(weights)
    products = [distributable * weight for weight in weights]
    sizes = [base + product // weight_total for product in products]
    remainder = available - sum(sizes)
    priorities = sorted(
        range(len(weights)),
        key=lambda index: (products[index] % weight_total, -index),
        reverse=True,
    )
    for index in priorities[:remainder]:
        sizes[index] += 1
    return tuple(sizes)
```

The all-zero overflow result is intentional: it preserves `sum(sizes) + gutters == total` when dividers alone consume the tiny viewport. Do not relax normal-size test invariants to accept zero dimensions.

- [ ] **Step 4: Run Dashboard layout tests**

Run:

```bash
uv run pytest tests/test_dashboard_layout.py -v
```

Expected: PASS. Update only expected geometry tests whose old terminal dimensions were below the newly documented 4×3 feasible-band threshold; retain their topology and gutter assertions.

- [ ] **Step 5: Commit the layout allocator change**

```bash
git add src/ccusage_viz/dashboard_layout.py tests/test_dashboard_layout.py
git commit -m "fix: reserve usable dashboard pane geometry"
```

### Task 3: Saturate interactive resizing and render undersized panes safely

**Files:**
- Modify: `src/ccusage_viz/tui.py:1296-1334, 8196-8241, 8594-8910`
- Test: `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: `MIN_PANE_WIDTH`, `MIN_PANE_HEIGHT`, `resolve_pane_layout(...) -> PaneLayout`, `_pane_render(...) -> PaneRender`.
- Produces: `adjust_pane_weight(pane_index: int, *, axis: str, delta: int) -> bool` records no mutation where a single-share change has no visible geometry effect; undersized Dashboard panes never call `_pane_render`; `_compose_resolved_panes(...) -> str` has exactly `layout.height` rows of display width `layout.width` even with zero-sized rectangles.

- [ ] **Step 1: Write failing Dashboard TUI tests**

Add a focused unit test near the existing layout-editor tests. Use the existing `run_tui` monkeypatch pattern, terminal size `(9, 8)`, hidden header, and two animation panes so no query runtime is needed. Feed enough `}` key events to grow the focused left pane until the right column reaches `MIN_PANE_WIDTH`, then one additional `}` and Ctrl-C. Capture frames and assert that the final two frames have identical pane-divider column positions; this proves the extra resize is a no-op rather than accumulating invisible weight changes.

Add a second test with terminal size `(1, 1)`, two animation panes, and input `KeyEvent("\x03")`. Monkeypatch `_pane_render` to raise `AssertionError("undersized pane rendered")`; retain a collecting `FramePainter`. Assert:

```python
assert tui_module.run_tui(options, load_translator("en")) == 0
assert frames
assert all(len(frame.rows) == 1 for frame in frames)
```

The test must complete without triggering the `_pane_render` assertion. It verifies that the decoder processes Ctrl-C after tiny-layout paint rather than becoming stuck in chart rendering.

- [ ] **Step 2: Run the two new tests to verify failure**

Run:

```bash
uv run pytest tests/test_tui_dashboard.py -k "resize_saturates_at_dashboard_minimum or undersized_dashboard_panes_skip_normal_rendering" -v
```

Expected: failure before the implementation because `_pane_render` is called for tiny rectangles and the resize path continues mutating weights after geometry can no longer change.

- [ ] **Step 3: Make a resize mutation conditional on visible geometry change**

In `adjust_pane_weight`, retain the current `layout` calculation. Before each `record_mutation` call, compute the candidate weights with `adjust_weight`, resolve a candidate layout through `resolve_pane_layout` using the same current terminal/body geometry and the candidate tuple for the adjusted axis, then compare the relevant axis sizes.

Use this pure helper nested next to `adjust_pane_weight`:

```python
def can_adjust_axis(
    layout: ResolvedPaneLayout,
    *,
    axis: str,
    weights: tuple[int, ...],
    index: int,
    delta: int,
) -> bool:
    candidate = adjust_weight(weights, index, delta)
    candidate_layout = resolve_pane_layout(
        layout=active_layout or active_grid,
        pane_count=len(panes),
        width=layout.width,
        height=layout.height,
        divider_style=divider_style,
        column_weights=(candidate if axis == "column" else reconcile_weights(column_weights, layout.topology.columns)),
        row_weights=(candidate if axis == "row" else reconcile_weights(row_weights, layout.topology.rows)),
    )
    before = layout.column_sizes if axis == "column" else layout.row_sizes
    after = candidate_layout.column_sizes if axis == "column" else candidate_layout.row_sizes
    return after != before
```

Inside each `adjust_column`/`adjust_row` closure, assign the candidate only when `can_adjust_axis(...)` is true. Have `adjust_pane_weight` return `False` before `record_mutation` when it is false, so undo history does not receive no-op entries. Keep the existing deterministic neighbor selection in `adjust_weight` unchanged.

- [ ] **Step 4: Add a bounded undersized-pane placeholder and exact tiny framing**

At the start of each `render_panes` loop iteration, before creating a `Terminal` or evaluating `chooser_overlay`, calculate:

```python
undersized = cell_width < MIN_PANE_WIDTH or cell_height < MIN_PANE_HEIGHT
```

For an undersized rectangle, append `clip_width(translator.text("status.tui_pane_too_small"), max(0, cell_width))` when both dimensions are positive; append `""` for a zero-sized rectangle; then `continue`. Add the `status.tui_pane_too_small` locale key in both `src/ccusage_viz/locales/en.py` and `src/ccusage_viz/locales/zh.py` with concise values (`"Pane too small"` and `"子图过小"`). Include both locale files in this task's file list and commit.

Change `_frame` so it no longer enlarges `width` and `height` with `max(4, width), max(3, height)`. Its first branch must return exactly `height` rows that each have display width `width` for `width <= 0`, `height <= 0`, `width < 3`, or `height < 3`; use `_fit_line` and blank padding, with no border glyphs. Preserve the existing framed branch only at `width >= 3 and height >= 3`.

In `_compose_resolved_panes`, do not index `rendered[rect.index][y - rect.top]` for a zero-width or zero-height rect. Filter such rectangles from the `rendered` map and from the `next(...)` pane lookup. The existing gutter/blank filling then produces exact terminal geometry.

- [ ] **Step 5: Run focused and full TUI regressions**

Run:

```bash
uv run pytest tests/test_tui_dashboard.py -k "resize_saturates_at_dashboard_minimum or undersized_dashboard_panes_skip_normal_rendering" -v
uv run pytest tests/test_tui_layout.py tests/test_tui_dashboard.py -v
```

Expected: PASS. If existing assertions snapshot localized controls, update only assertions impacted by the new undersized placeholder; normal-size Dashboard frames must remain unchanged.

- [ ] **Step 6: Run the complete relevant regression suite**

Run:

```bash
uv run pytest tests/test_formatting.py tests/test_dashboard_layout.py tests/test_tui_layout.py tests/test_tui_dashboard.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit the TUI safety path**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_dashboard.py
git commit -m "fix: safely render undersized dashboard panes"
```

## Plan Self-review

- **Spec coverage:** Task 1 implements the universal no-stall wrapper guarantee. Task 2 preserves usable Dashboard geometry and makes physical tiny terminals recoverable. Task 3 prevents invisible resize mutations, avoids invoking arbitrary renderers below the geometry floor, preserves exact compositor bounds, and verifies decoded Ctrl-C remains reachable. The plan intentionally leaves `ISIG` unchanged.
- **Placeholder scan:** No TBD/TODO steps or undefined future interfaces remain. The locale key, constants, helper signature, expected tests, commands, and commit contents are named explicitly.
- **Type consistency:** All tasks retain existing public `wrap_width`, `resolve_pane_layout`, and `adjust_pane_weight` signatures. `MIN_PANE_WIDTH` is introduced in Task 2 and consumed in Task 3.
