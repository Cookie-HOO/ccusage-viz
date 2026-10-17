# Grouped Ranking Copy Values Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make grouped Custom Ranking individual and copy-all clipboard payloads include the value, visible comparison, and visible percentage shown by the TUI.

**Architecture:** Keep clipboard assembly in `grouped_ranking_viewport.py`, using its prepared group and entry presentation facts rather than parsed terminal rows. Record the active grouped display policy on the viewport during rendering so Dashboard’s existing clipboard calls get exactly the fields visible in the current grouped Ranking geometry. A focused viewport test validates the shared single-group, single-item, and copy-all formatter path.

**Tech Stack:** Python 3.12, dataclasses, Decimal, pytest, existing Custom Ranking rendering and viewport infrastructure.

**Spec:** `docs/superpowers/specs/2026-10-14-grouped-ranking-copy-values-design.md`

## Global Constraints

- Apply only to Custom grouped Ranking clipboard actions; do not alter flat Ranking behavior, query behavior, Dashboard mouse routing, or clipboard transport.
- Preserve current filtered group/item ordering, blank-line record separation, empty-group handling, and synthetic `Other` behavior.
- Use presentation-model fields; clipboard data must not contain terminal alignment padding, ANSI escape sequences, copy icons, or terminal truncation.
- Include comparison only when the grouped comparison column is visible, and share only when percentage is shown and a share exists.

---

## File Structure

- `src/ccusage_viz/render/grouped_ranking_viewport.py` — owns prepared grouped Ranking facts, visibility policy, and all grouped clipboard text formatting.
- `tests/test_custom_ranking_scroll.py` — supplies the grouped fixture and verifies viewport copy payloads independent of Dashboard clipboard I/O.

### Task 1: Preserve display policy and format grouped clipboard facts

**Files:**
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py:50-200, 250-345`
- Test: `tests/test_custom_ranking_scroll.py:245-350`

**Interfaces:**
- Consumes: `GroupedRankingPresentationGroup.display`, `.comparison_display`, `.share`, `.description`, `.link`; `RankingPresentationEntry.display`, `.comparison_display`, `.current`, `.description`, `.project_link`; and renderer-local `comparison_visible` / `projection.show_percentage`.
- Produces: `GroupedRankingViewport.clipboard_text(identity: GroupedIdentity) -> str` and `clipboard_all_text() -> str` payloads that include only currently visible ranking columns.

- [ ] **Step 1: Write the failing viewport regression test**

Add a test after `test_grouped_identity_scrollbar_and_copy_payloads` that constructs `model = replace(grouped_projection(), comparison_available=True)` with current/previous totals and explicit display facts, renders with `context(width=90, density="detailed", period="7d")`, and asserts all three clipboard paths contain current value, delta, and percentage. Use exact plain-text payload fragments so field order is locked:

```python
def test_grouped_copy_payloads_include_rendered_numeric_fields() -> None:
    model = grouped_projection_with_visible_comparisons()
    viewport = GroupedRankingViewport()
    render_grouped(
        model,
        viewport,
        context(width=90, density="detailed", period="7d"),
        copy_all_action=True,
    )

    assert viewport.clipboard_text(("series", "coding", "shared")) == (
        "Coding Model\nSeed\n70 items\n+10 items\n58.3%\n"
        "Details for Seed\nhttps://example.com/coding/shared"
    )
    assert viewport.clipboard_text(("group", "coding")) == (
        "Coding Model\n100 items\n+20 items\n83.3%\n"
        "About Coding Model\nhttps://example.com/coding\n\n"
        "Seed\n70 items\n+10 items\n58.3%\n"
        "Details for Seed\nhttps://example.com/coding/shared\n\n"
        "Sonnet\n30 items\n+10 items\n25.0%\n"
        "Details for Sonnet\nhttps://example.com/coding/sonnet"
    )
    assert viewport.clipboard_all_text().startswith(viewport.clipboard_text(("group", "coding")))
```

In the same test, rerender at `width=40` and assert no copied text contains `+10 items` or `%`; this verifies hidden comparison/share columns are omitted rather than merely being unavailable data.

- [ ] **Step 2: Run the regression test to verify it fails**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py::test_grouped_copy_payloads_include_rendered_numeric_fields -q
```

Expected: FAIL because current group/item payload formatting emits only labels, descriptions, and links.

- [ ] **Step 3: Add viewport display-policy state and pure formatter helpers**

In `GroupedRankingViewport`, add two boolean fields initialized to `False` and reset in `clear()`:

```python
comparison_visible: bool = False
percentage_visible: bool = False
```

Replace `_entry_text`, `_grouped_ranking_series_clipboard_text`, `_grouped_ranking_group_clipboard_text`, and `_grouped_ranking_clipboard_all_text` with helpers that take both visibility booleans. Build fields by filtering empty strings in this exact order:

```python
def _share_text(share: Decimal | None) -> str:
    return f"{share:>5.1%}" if share is not None else ""


def _entry_text(
    entry: RankingPresentationEntry,
    *,
    comparison_visible: bool,
    percentage_visible: bool,
    total: Decimal,
) -> str:
    parts = [entry.label, entry.display or ""]
    if comparison_visible:
        parts.append(entry.comparison_display or "")
    if percentage_visible and total:
        parts.append(_share_text(entry.current / total))
    parts.extend((copyable_description_text(entry.description or ""), entry.project_link or ""))
    return "\n".join(part for part in parts if part)
```

Make the group helper use `group.label`, `group.display`, then `group.comparison_display` only when comparison is visible, then `_share_text(group.share)` only when percentage is visible, followed by its current description/link. Pass `group.total` into each inner entry helper. Thread these booleans through group, series, and all-copy helpers, and have `clipboard_text()` / `clipboard_all_text()` read the stored viewport policy.

Immediately after the renderer calculates `comparison_visible`, set the policy on every render:

```python
viewport.comparison_visible = comparison_visible
viewport.percentage_visible = projection.show_percentage and context.style != "list"
```

Keep `list` style percentage disabled because its rendered rows never show the share column. Do not change row rendering or hit testing.

- [ ] **Step 4: Run the focused viewport tests to verify they pass**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k 'grouped_copy_payloads_include_rendered_numeric_fields or grouped_identity_scrollbar_and_copy_payloads or grouped_copy_all' -q
```

Expected: PASS. Existing grouped clipboard tests must retain their prior ordering/filtering/`Other` assertions, updated only where their exact expected payloads now legitimately include visible numeric facts.

- [ ] **Step 5: Run lint and the grouped Dashboard copy regression suite**

Run:

```bash
uv run ruff check src/ccusage_viz/render/grouped_ranking_viewport.py tests/test_custom_ranking_scroll.py
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py -q
```

Expected: both commands exit 0; Dashboard’s existing copy-all click route receives the richer payload without routing changes.

- [ ] **Step 6: Commit the completed change**

```bash
git add src/ccusage_viz/render/grouped_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "fix: include displayed values in grouped ranking copies"
```

## Plan Self-Review

- **Spec coverage:** Task 1 covers individual group/item and copy-all payloads, presentation-data sourcing, value/comparison/share visibility conditions, descriptions/links, ordering, blank-line behavior, hidden columns, and Dashboard compatibility through the existing click regression suite. It makes no query, protocol, flat-Ranking, or routing change.
- **Placeholder scan:** no TODO/TBD or unspecified test/code steps remain.
- **Type consistency:** `GroupedRankingViewport` remains the sole public clipboard owner; its methods keep their current signatures. Formatting helpers consume `Decimal` totals/shares and return `str`.
