# Official Dataset Catalog Item/Description Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render official Dataset catalog entries as primary item rows with subordinate descriptions instead of a three-column table.

**Architecture:** Keep catalog entry formatting and viewport projection local to `tui.py`. Build each entry as a variable-height row block, derive selected block geometry from those blocks, and reuse the existing display-width wrapping and clipping helpers.

**Tech Stack:** Python 3.12, pytest, existing terminal formatting utilities

**Spec:** `docs/superpowers/specs/2026-10-17-official-dataset-catalog-item-description-design.md`

## Global Constraints

- The primary line is `title · dataset-id`, preceded by the selection gutter.
- The description aligns with primary item text and wraps to at most two lines.
- Remove the Name / Dataset ID / Summary table header and separator.
- Preserve item-based selection and keep the complete selected block visible when possible.
- Every rendered line must fit the requested terminal display width.
- Do not change catalog acquisition, installation, preview, or error behavior.

---

### Task 1: Item/description catalog rows and variable-height viewport

**Files:**
- Modify: `src/ccusage_viz/tui.py:4199-4255`
- Test: `tests/test_tui_dashboard.py:263-306`

**Interfaces:**
- Consumes: catalog entries exposing `id`, localized `title`, and localized `summary`; `wrap_width`, `truncate_width`, `clip_width`, and `_chooser_viewport` conventions.
- Produces: `_official_catalog_item_rows(entry, translator, *, selected, width) -> tuple[str, ...]`, `_official_catalog_rows(...) -> list[str]`, and `_official_catalog_viewport(...) -> tuple[str, int]` with item-aligned viewport offsets.

- [ ] **Step 1: Write failing hierarchy and width tests**

Replace table-oriented expectations with assertions that the first row is `› Dataset 0 · dataset-0`, description rows begin with two spaces, headers are absent, long summaries occupy at most two subordinate lines, Chinese rows fit by `display_width`, and narrow widths do not overflow.

- [ ] **Step 2: Write a failing variable-height viewport test**

Create entries with one-line and two-line summaries, select the last entry in a short viewport, and assert the selected primary line and its final description line are visible while no table header is present.

- [ ] **Step 3: Run focused tests to verify failure**

Run: `uv run pytest tests/test_tui_dashboard.py -k 'official_catalog_table or official_catalog_item or official_catalog_viewport' -q`

Expected: FAIL because the current renderer emits table headers, splits item identity into columns, and assumes exactly two rows per entry.

- [ ] **Step 4: Implement item block rendering**

Add `_official_catalog_item_rows()` that reserves a two-cell selection gutter, formats `localized title · id` as the primary line, wraps the localized summary within `width - 2`, limits it to two rows, changes the final truncated row to end in `…`, and clips every result to `width`. Make `_official_catalog_rows()` flatten these blocks without headers.

- [ ] **Step 5: Implement item-aware viewport projection**

Build all item blocks, calculate each block's `[start, end)` physical-row span, clamp the physical offset, and move it enough to reveal the selected block. When a selected block fits in the available height, keep all its rows visible; when it cannot fit, prioritize its primary row and the available following description rows.

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest tests/test_tui_dashboard.py -k 'official_catalog' -q`

Expected: PASS.

- [ ] **Step 7: Run adjacent chooser and formatting tests**

Run: `uv run pytest tests/test_tui_dashboard.py tests/test_formatting.py -q`

Expected: PASS.

- [ ] **Step 8: Run lint and whitespace checks**

Run: `uv run ruff check src/ccusage_viz/tui.py tests/test_tui_dashboard.py && git diff --check`

Expected: PASS.

- [ ] **Step 9: Commit implementation**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py docs/superpowers/plans/2026-10-17-official-dataset-catalog-item-description.md
git commit -m "fix: separate catalog items from descriptions"
```
