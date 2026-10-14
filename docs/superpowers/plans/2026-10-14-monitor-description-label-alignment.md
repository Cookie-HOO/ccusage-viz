# Monitor Description Label Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align every visible Monitor ranking description with the start column of its corresponding label.

**Architecture:** Keep `render_ranking()` as the shared observed-ranking layout for native and Custom Dataset Monitor. Correct its description indent to use the already-rendered rank/status prefix width, then protect the geometry with a focused renderer regression test; Custom Monitor inherits the fix through its existing exact delegation.

**Tech Stack:** Python 3.12+, pytest, Ruff, terminal display-width helpers

**Spec:** `docs/superpowers/specs/2026-10-14-monitor-description-label-alignment-design.md`

## Global Constraints

- Apply the behavior equally to native Monitor and Custom Dataset Monitor.
- Historical Custom Ranking requires no change.
- Preserve the two-line limit, overflow ellipsis, muted styling, density requirements, and suppression for list and `Other` entries.
- Do not change labels, values, displays, sorting, bars, titles, or data handling.

---

### Task 1: Align observed Monitor descriptions with labels

**Files:**
- Modify: `src/ccusage_viz/render/ranking.py: observed ranking description rendering`
- Test: `tests/test_render.py: observed Monitor ranking renderer tests`

**Interfaces:**
- Consumes: `render_ranking(model: RankingModel, context: RenderContext, ...) -> str`, `display_width(value: str) -> int`, and the observed primary-row `prefix` string.
- Produces: observed `ranking` and `ranking-dot` output whose description starts at `display_width(prefix)`, the exact label start column.

- [ ] **Step 1: Write the failing renderer regression test**

Add this parameterized test beside the existing observed-ranking renderer tests:

```python
@pytest.mark.parametrize("style", ("ranking", "ranking-dot"))
def test_monitor_ranking_description_starts_with_label_column(style: str) -> None:
    label = "Provider quota"
    description = "Models available through this quota pool and its current routing policy."
    model = RankingModel(
        (),
        None,
        observed_entries=(
            ScalarRankingEntry("quota", label, 69.2, description=description, display="69.2%"),
        ),
        metric=MetricDescriptor("tokens"),
        observed_scope=ObservedScope(20, "model"),
    )
    render_context = RenderContext(
        56,
        24,
        load_translator("en"),
        color=False,
        ascii=True,
        style=style,
        density="detailed",
    )

    output = render_ranking(model, render_context)
    primary = next(row for row in output.splitlines() if label in row)
    description_rows = [
        row
        for row in output.splitlines()
        if "Models available" in row or "routing policy" in row
    ]

    label_start = display_width(primary.split(label, maxsplit=1)[0])
    assert description_rows
    assert display_width(description_rows[0]) <= render_context.width
    assert display_width(description_rows[0].split("Models available", maxsplit=1)[0]) == label_start
```

The description text is long enough at width 56 to exercise wrapping while the assertion checks the first row's exact display column.

- [ ] **Step 2: Run the test and verify the current indentation fails**

Run:

```bash
uv run pytest tests/test_render.py -k 'monitor_ranking_description_starts_with_label_column' -v
```

Expected: both cases fail because the description currently starts `value_width + 1` cells to the right of the label.

- [ ] **Step 3: Implement the minimal shared-renderer correction**

In the observed-ranking description branch of `render_ranking()`, replace:

```python
indent = " " * min(context.width, display_width(prefix) + value_width + 1)
```

with:

```python
indent = " " * min(context.width, display_width(prefix))
```

Keep the existing available-width calculation, wrapping, two-row cap, ellipsis, and muted styling unchanged.

- [ ] **Step 4: Run focused renderer and Custom Monitor parity tests**

Run:

```bash
uv run pytest tests/test_render.py -k 'observed_ranking or monitor_ranking' -q
uv run pytest tests/test_tui_custom.py::test_custom_monitor_ranking_and_list_keep_native_row_geometry -q
```

Expected: PASS. The renderer tests prove alignment and existing observed behavior; the Custom Monitor parity test proves Custom output continues to inherit native row geometry.

- [ ] **Step 5: Run lint and inspect the scoped diff**

Run:

```bash
uv run ruff check src/ccusage_viz/render/ranking.py tests/test_render.py
git diff --check -- src/ccusage_viz/render/ranking.py tests/test_render.py
git diff -- src/ccusage_viz/render/ranking.py tests/test_render.py
```

Expected: all checks pass, and the diff contains only the indentation correction and focused regression test.

- [ ] **Step 6: Commit the implementation**

```bash
git add src/ccusage_viz/render/ranking.py tests/test_render.py
git commit -m "fix: align monitor descriptions with labels"
```
