# Custom Ranking List Group Copy Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the copy icon and copy interaction for grouped Custom Ranking headings in list style without adding icons to series rows.

**Architecture:** Keep existing `copied_entry_id` state and hit-map format. Update the grouped viewport’s heading label and restrict the current list-style hit suppression to series rows only; list-style group headings then use the same marker and copy action as non-list group headings.

**Tech Stack:** Python 3, pytest, terminal/TUI renderer.

**Spec:** `docs/superpowers/specs/2026-10-17-custom-ranking-list-group-copy-icon-design.md`

## Global Constraints

- Applies only to grouped Custom Ranking rendering.
- List-style group headings display `⊞` before copy and `✓` after copy.
- List-style series and residual/other rows remain icon-free and receive no copy hit target.
- Do not alter clipboard payloads, scrolling, or non-list rendering.

---

### Task 1: Restore list-style group copy affordances

**Files:**
- Modify: `tests/test_custom_ranking_scroll.py:render_grouped`, `tests/test_custom_ranking_scroll.py:test_grouped_list_has_no_copy_or_comparison_affordances`
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py:heading_lines`, hit registration loop

**Interfaces:**
- Consumes: `render_grouped_custom_ranking_viewport(..., copied_entry_id: GroupedIdentity | None, ...)`.
- Produces: `GroupedRankingViewport.hits: dict[int, tuple[GroupedIdentity, int, int | None]]` containing `("group", group_id)` for visible list headings only.

- [ ] **Step 1: Write the failing test**

Extend `render_grouped` with a `copied: tuple[str, ...] | None = None` keyword and pass it to `copied_entry_id`. Replace the list assertion with explicit group/series behavior:

```python
assert "⊞" in output and "→" not in output
assert any(hit[0] == ("group", "coding") for hit in viewport.hits.values())
assert all(hit[0][0] == "group" for hit in viewport.hits.values())

copied = strip_ansi(
    render_grouped(model, viewport, list_context, copied=("group", "coding"))
)
assert "✓" in copied
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_custom_ranking_scroll.py::test_grouped_list_has_no_copy_or_comparison_affordances -v`

Expected: FAIL because list headings omit the marker and list mode leaves `viewport.hits` empty.

- [ ] **Step 3: Write minimal implementation**

In `heading_lines`, always include the existing marker:

```python
label=f"{group.label} | {marker}",
```

Replace the outer `if context.style != "list":` hit-registration guard with an iteration that skips only list-style non-group rows:

```python
for screen_index, source_index in enumerate(source_indexes):
    row = viewport.rows[source_index]
    if row.kind not in {"group", "series"}:
        continue
    if context.style == "list" and row.kind != "group":
        continue
```

Keep the existing residual/other-row exclusion and marker-based column calculation unchanged.

- [ ] **Step 4: Run focused test to verify it passes**

Run: `pytest tests/test_custom_ranking_scroll.py::test_grouped_list_has_no_copy_or_comparison_affordances -v`

Expected: PASS.

- [ ] **Step 5: Run relevant regression tests**

Run: `pytest tests/test_custom_ranking_scroll.py -v`

Expected: PASS.

- [ ] **Step 6: Commit only feature files**

```bash
git add src/ccusage_viz/render/grouped_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "fix: restore grouped list ranking copy icon"
```

Do not stage unrelated pre-existing worktree changes.
