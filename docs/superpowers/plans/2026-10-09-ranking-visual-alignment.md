# Ranking Visual Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Custom Dataset historical Ranking and Monitor Ranking/List visually match their ccuv counterparts with stable title, summary, label, track, and value geometry.

**Architecture:** Keep `render_historical_ranking()` as the sole renderer for historical ccuv and Custom Dataset Rankings. It first derives every row's complete right-side content and reserves fixed left, track, and right columns, then renders each style from that shared geometry. Custom Monitor continues to delegate to the native ranking renderer, replacing only its heading; regression tests protect this delegation boundary.

**Tech Stack:** Python 3.13, pytest, terminal display-width helpers, ANSI-aware rendering.

**Spec:** `docs/superpowers/specs/2026-10-09-ranking-descriptions-design.md`

## Global Constraints

- Do not create a second Custom Dataset historical Ranking layout implementation.
- Historical headings are centered in the full viewport; optional summaries remain left aligned.
- The label column is left aligned, all non-list tracks share one start column, and the right value/proportion column is right aligned.
- Custom-only descriptions begin at the label column and never move the primary-row geometry.
- Cover `dot`, `dots`, bar, and `list` historical styles, plus Monitor `ranking` and `list` equivalence.
- Preserve existing Decimal values, Dataset-owned display text, comparison markers, colour, ASCII, and narrow-terminal behavior.

---

## File Structure

- Modify: `src/ccusage_viz/render/ranking_presentation.py` — shared historical Ranking column allocation and description indentation.
- Modify: `tests/test_custom_component.py` — renderer-level visual geometry coverage for Custom Dataset historical Ranking.
- Modify: `tests/test_render.py` — shared/native historical Ranking alignment coverage where existing renderer fixtures live.
- Modify: `tests/test_tui_custom.py` — Custom Monitor/native Monitor row-equivalence coverage for both compatible styles.

### Task 1: Lock down shared historical Ranking geometry

**Files:**
- Modify: `tests/test_render.py`
- Modify: `src/ccusage_viz/render/ranking_presentation.py`

**Interfaces:**
- Consumes: `render_historical_ranking(entries, *, heading, value_formatter, context, delta_formatter=None, summary="", pending=False, total=None, descriptions_visible=False) -> str`.
- Produces: the same public function, with all non-list rows using a stable label-to-track boundary and a stable right-side value boundary.

- [ ] **Step 1: Write failing shared-renderer geometry tests**

Add a parameterized test that builds three `RankingPresentationEntry` records with differently sized labels and values, passes `summary="Today Token 292.32M"`, and renders `dot`, `dots`, and `bars` at width 100 without colour. Assert that the title has equal display-width padding on both sides (allowing a one-cell odd-width difference), the summary starts in column zero, every row has its track at the same computed column, and every non-space right-side value ends in the same terminal column.

```python
@pytest.mark.parametrize("style", ("dot", "dots", "bars"))
def test_historical_ranking_uses_fixed_three_column_geometry(style: str) -> None:
    context = RenderContext(100, 20, load_translator("en"), color=False, style=style)
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "A", 1000),
            RankingPresentationEntry("b", "A much longer label", 500),
            RankingPresentationEntry("c", "C", 25),
        ),
        heading="Ranking · 14d",
        value_formatter=lambda value: f"{value} Token",
        context=context,
        summary="Today Token 292.32M",
    )
    summary, heading, *rows = output.splitlines()
    assert summary.startswith("Today")
    assert display_width(heading) == context.width
    # Extract the first track glyph/dot and final non-space text positions from rows.
```

- [ ] **Step 2: Run the new tests to verify they expose the old row-dependent layout**

Run: `pytest tests/test_render.py -k fixed_three_column_geometry -v`

Expected: FAIL until the assertions match the renderer's required stable-column behavior.

- [ ] **Step 3: Implement one shared row-measurement pass**

In `render_historical_ranking()`, build rows before drawing marks. For each entry calculate its localized/display value, refresh markers, comparison text, percentage, and complete `right` text. Set `right_width` to the maximum `display_width(right)`. Keep `label_width` fixed for all rows, calculate `rank_width` from the number of entries, then calculate a single `bar_width` from the viewport after subtracting rank/status spaces, label width, inter-column spaces, and `right_width`.

```python
right_width = max((display_width(row.right) for row in rows), default=1)
bar_width = max(8, context.width - (rank_width + 5 + label_width + 2 + right_width))
# every non-list row:
line = (
    f"{rank:>{rank_width}} {rank_marker} {activity} {label} {mark} "
    f"{pad_width(right, right_width, align='right')}"
)
```

Do not alter `RankingPresentationEntry` or callers. Retain `colored_mark()` and `styled_text()` so coloured output has the same visible geometry.

- [ ] **Step 4: Run focused shared renderer tests**

Run: `pytest tests/test_render.py -k 'ranking or historical' -v`

Expected: PASS, including the new three-column parameterization and existing historical Ranking tests.

- [ ] **Step 5: Commit the shared layout implementation**

```bash
git add src/ccusage_viz/render/ranking_presentation.py tests/test_render.py
git commit -m "fix: align historical ranking columns"
```

### Task 2: Preserve Custom Dataset Ranking-specific rows and all styles

**Files:**
- Modify: `tests/test_custom_component.py`
- Modify: `src/ccusage_viz/render/ranking_presentation.py`

**Interfaces:**
- Consumes: `render_custom_projection(projection, context, *, descriptions_visible=False) -> str` and `RankingPresentationEntry.description`.
- Produces: Custom Dataset output whose `dot`, `dots`, `bars`, and `list` styles use the shared geometry; description rows start in the label column.

- [ ] **Step 1: Write failing Custom Dataset style and description-alignment tests**

Add a parameterized test that projects a dataset with two labels of unequal width and Dataset-owned displays, then renders `dot`, `dots`, `bars`, and `list`. For the first three styles assert the first dot/track character has an identical display-width offset in every data row. For `list`, assert labels begin at one fixed offset and right-side display values share a right edge. Add a description assertion that finds the description row and verifies its leading-space width equals the primary label start, rather than the track start.

```python
@pytest.mark.parametrize("style", ("dot", "dots", "bars", "list"))
def test_custom_ranking_keeps_style_specific_columns_aligned(style: str) -> None:
    projection = process_custom_historical(described_response, config(kind="ranking"))
    context = RenderContext(96, 20, load_translator("en"), color=False, style=style)
    lines = render_custom_projection(projection, context, descriptions_visible=True).splitlines()
    # Identify data lines by rank prefix and compare their label/track/value offsets.
```

- [ ] **Step 2: Run the new Custom Dataset renderer tests**

Run: `pytest tests/test_custom_component.py -k 'style_specific_columns or descriptions' -v`

Expected: FAIL if descriptions are indented after rank/status rather than at the label start, or if any style retains an unstable boundary.

- [ ] **Step 3: Align description indentation with the label column**

In `render_historical_ranking()`, use the same prefix width as the primary label's start (`rank_width + 5` in the existing row schema), not a track-derived offset. Wrap from that indent through the viewport end, preserve the two-line cap and ellipsis behavior, and retain muted/dim styling.

```python
label_start = rank_width + 5
indent = " " * min(context.width, label_start)
available = max(1, context.width - display_width(indent))
```

For `list`, construct the full uncentered row from stable left/right columns and call `center_text()` only once on that full row. Do not center labels or values independently.

- [ ] **Step 4: Run Custom Dataset rendering tests**

Run: `pytest tests/test_custom_component.py -k 'ranking or custom_charts_use_native_layout_primitives' -v`

Expected: PASS, including localized Dataset display and description tests.

- [ ] **Step 5: Commit the Custom Dataset alignment coverage**

```bash
git add src/ccusage_viz/render/ranking_presentation.py tests/test_custom_component.py
git commit -m "test: cover custom ranking visual alignment"
```

### Task 3: Protect Custom Monitor native ranking/list delegation

**Files:**
- Modify: `tests/test_tui_custom.py`
- Modify: `src/ccusage_viz/render/custom_monitor.py` only if test failure reveals heading replacement modifies a non-heading row.

**Interfaces:**
- Consumes: `render_custom_monitor(component, context) -> str` and `render_ranking(model, context) -> str`.
- Produces: output where `splitlines()[1:]` equals native Monitor Ranking output after the native heading for style `ranking` and `list`.

- [ ] **Step 1: Write/strengthen an exact Monitor equivalence test**

For each style in `("ranking", "list")`, configure `_custom_monitor_component()` with that presentation style and render it with a non-default width plus both `ascii=True` and `ascii=False`. Render the equivalent `component.ranking_model(language="en")` with `render_ranking()`. Assert the Custom first line is centered Dataset heading and assert all remaining lines exactly match `native.splitlines()[1:]`; assert every rendered row's display width is at most `context.width`.

```python
@pytest.mark.parametrize("style", ("ranking", "list"))
@pytest.mark.parametrize("ascii", (False, True))
def test_custom_monitor_ranking_rows_are_native_equivalent(style: str, ascii: bool) -> None:
    component = _custom_monitor_component()
    component.configure(replace(component.candidate, presentation=replace(component.candidate.presentation, style=style)), data_affecting=False)
    context = RenderContext(93, 16, load_translator("en"), color=False, ascii=ascii, style=style)
    native = render_ranking(component.ranking_model(language="en"), context)
    custom = render_custom_monitor(component, context)
    assert custom.splitlines()[1:] == native.splitlines()[1:]
```

- [ ] **Step 2: Run the Monitor equivalence test**

Run: `pytest tests/test_tui_custom.py -k custom_monitor_ranking_rows_are_native_equivalent -v`

Expected: PASS. If it fails, the failure identifies an unintended row transformation after heading replacement.

- [ ] **Step 3: Make heading replacement explicitly single-line only if required**

If the test fails because `_replace_heading()` does more than replace `splitlines()[0]`, reduce it to reconstruction from the centered replacement heading plus the untouched `rest` tuple:

```python
first, *rest = rendered.splitlines()
del first
return "\n".join((center_text(heading, context.width), *rest))
```

Do not add Custom-specific Monitor ranking measurement or formatting.

- [ ] **Step 4: Run all affected test modules and lint**

Run:

```bash
pytest tests/test_render.py tests/test_custom_component.py tests/test_tui_custom.py -v
ruff check src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/render/custom_monitor.py tests/test_render.py tests/test_custom_component.py tests/test_tui_custom.py
```

Expected: all tests pass and Ruff reports no diagnostics.

- [ ] **Step 5: Commit the Monitor regression guard**

```bash
git add src/ccusage_viz/render/custom_monitor.py tests/test_tui_custom.py
git commit -m "test: lock custom monitor ranking parity"
```

## Final Verification

- [ ] Run the full test suite: `pytest -v`.
- [ ] Inspect `git diff --check` and confirm no whitespace errors.
- [ ] Render or inspect the practical Custom Dataset ranking at a wide terminal width and verify: centered heading, left-aligned summary, vertically aligned tracks, right-aligned values/proportions, and descriptions at the label start.
