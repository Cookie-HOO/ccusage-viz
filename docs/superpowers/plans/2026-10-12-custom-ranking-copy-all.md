# Custom Ranking Copy All Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixed copy-all action to Dashboard Custom historical Rankings that copies every current search match, including off-screen entries.

**Architecture:** Extend pane-local Ranking viewport metadata with one fixed copy-all hit and render-state marker. Reuse prepared filtered Ranking entries and the existing single-entry clipboard formatter; Dashboard resolves the fixed hit before ordinary row-copy/focus handling and owns transient success feedback.

**Tech Stack:** Python 3.11+, existing terminal renderer and SGR mouse input, pytest, Ruff, ty, uv; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-ranking-copy-all-design.md`

## Global Constraints

- Apply only to Dashboard Custom historical Ranking panes.
- Copy the complete current local-search result in Ranking order, including off-screen entries, and exclude `Other`.
- Format each entry exactly like single-entry copy and separate entries with one blank line.
- Keep the marker fixed above scrollable entries; use `⊞`, then transient `✓` after success.
- Do not alter query lifecycles, focus, adjustment mode, links, per-entry copy, scrolling, standalone/native/monitor behavior, or persistence.
- Preserve unrelated working-tree changes.

---

### Task 1: Pure multi-entry clipboard formatting

**Files:**
- Modify: `src/ccusage_viz/tui.py:2360-2420`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `_custom_ranking_clipboard_text(label, description, project_link) -> str`.
- Produces: `_custom_ranking_clipboard_all_text(entries: Iterable[tuple[str, str | None, str | None]]) -> str`.

- [ ] **Step 1: Add failing formatter tests**

Add tests proving exact single-entry parity, Ranking-order preservation, optional-field omission, localized input preservation, and blank-line separation:

```python
def test_custom_ranking_clipboard_all_reuses_single_entry_format() -> None:
    entries = (
        ("Project A", "Read GitHub https://github.com/a", "https://example.com/a"),
        ("项目 B", None, None),
    )
    assert tui._custom_ranking_clipboard_all_text(entries) == (
        "Project A\nRead GitHub https://github.com/a\nhttps://example.com/a\n\n项目 B"
    )
```

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest -o addopts='' tests/test_tui_custom.py -k clipboard_all -q`

Expected: FAIL because `_custom_ranking_clipboard_all_text` does not exist.

- [ ] **Step 3: Implement the formatter by delegating to the existing formatter**

```python
def _custom_ranking_clipboard_all_text(
    entries: Iterable[tuple[str, str | None, str | None]],
) -> str:
    return "\n\n".join(
        _custom_ranking_clipboard_text(label, description, project_link)
        for label, description, project_link in entries
    )
```

Import `Iterable` from `collections.abc` if it is not already available. Do not duplicate markdown-description cleanup.

- [ ] **Step 4: Run formatter and existing per-entry tests**

Run: `uv run pytest -o addopts='' tests/test_tui_custom.py tests/test_custom_component.py -k 'clipboard_all or copy_marker or clipboard_description' -q`

Expected: PASS.

- [ ] **Step 5: Commit the pure formatter**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "feat: format custom ranking copy all payload"
```

---

### Task 2: Render a fixed copy-all marker and expose its hit

**Files:**
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Modify: `src/ccusage_viz/tui.py:400-440,1860-1900,1925-1945`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Extend `RankingViewport` with `copy_all_hit: tuple[int, int] | None` and clear it in reset/inactive paths.
- Extend `render_custom_ranking_viewport(..., copied_all: bool = False) -> str`.
- Extend `_render_custom_projection(..., copied_all: bool = False) -> PaneRender` and thread it only through the Dashboard Custom Ranking path.

- [ ] **Step 1: Add failing viewport presentation tests**

Cover:

```python
def test_copy_all_marker_is_fixed_and_has_one_hit() -> None:
    model = projection(100)
    viewport = RankingViewport()
    first = render(model, viewport, copied_all=False)
    hit = viewport.copy_all_hit
    assert hit is not None
    row, column = hit
    assert first.splitlines()[row][column] == "⊞"

    viewport.scroll(10)
    moved = render(model, viewport, copied_all=False)
    assert viewport.copy_all_hit == hit
    assert moved.splitlines()[row][column] == "⊞"

    copied = render(model, viewport, copied_all=True)
    assert copied.splitlines()[row][column] == "✓"
```

Also assert `copy_all_hit is None` for an empty projection and a no-match search, and assert the marker does not change entry column geometry or the visible-entry count.

- [ ] **Step 2: Verify presentation tests fail**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k copy_all -q`

Expected: FAIL because the argument and hit metadata do not exist.

- [ ] **Step 3: Add pane state and fixed marker rendering**

Add pane-local transient state:

```python
copied_ranking_all_until: float = 0.0
```

Add `copy_all_hit` to `RankingViewport`. In `render_custom_ranking_viewport`, after preparing filtered entries and before slicing scrollable rows:

- include the fixed marker only when at least one prepared entry is not `is_other`;
- append `⊞` or `✓` to an existing fixed chrome row without inserting a new scrollable entry row;
- calculate its visible pane-local `(row, column)` after ANSI stripping;
- clear the hit at function entry and every empty/inactive return;
- leave per-entry `copy_marker` behavior unchanged.

Thread `copied_all=pane.copied_ranking_all_until > time.monotonic()` from `_pane_render` through `_render_custom_projection`. Ensure summary-row translation adjusts `copy_all_hit` exactly as it already adjusts entry hits and scrollbar top.

- [ ] **Step 4: Run viewport and renderer regression tests**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_custom_component.py -q`

Expected: PASS, with bounded warm-scroll formatting tests unchanged.

- [ ] **Step 5: Commit fixed marker rendering**

```bash
git add src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/tui.py tests/test_custom_ranking_scroll.py
git commit -m "feat: render custom ranking copy all action"
```

---

### Task 3: Dashboard copy-all click routing

**Files:**
- Modify: `src/ccusage_viz/tui.py:7690-7850,8130-8200,8940-8980`
- Test: `tests/test_custom_ranking_dashboard_scroll.py`

**Interfaces:**
- Consumes: `RankingViewport.copy_all_hit`, `RankingViewport.entries`, `_custom_ranking_clipboard_all_text(...)`, `copy_command(...)`.
- Produces: `_copy_custom_ranking_all_at(pane, *, row, column, framed, now) -> bool` or an equivalent narrow host-local helper.

- [ ] **Step 1: Add failing real Dashboard tests**

Using the existing 100-entry accepted-data fixture, add tests that click the fixed marker and assert:

```python
assert copied == [
    "\n\n".join(
        f"Project {index}\nDescription {index}\nhttps://example.com/{index}"
        for index in range(1, 101)
    )
]
assert focuses[-1] == -1
assert pane.copied_ranking_all_until > 0
```

Adapt expected descriptions to the fixture's actual data. Add separate assertions for:

- an active search copies all matches, including matches outside the visible viewport;
- `Other` is excluded;
- framed and frameless coordinate translation both work;
- clipboard failure leaves `copied_ranking_all_until == 0` and shows failure feedback;
- the click does not set `copied_ranking_entry_id`, open a link, enter adjustment mode, or add lifecycle requests;
- a no-match search exposes no clickable copy-all action.

- [ ] **Step 2: Verify host tests fail**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_dashboard_scroll.py -k copy_all -q`

Expected: FAIL because marker clicks still reach ordinary pane mouse handling.

- [ ] **Step 3: Implement copy-all hit testing before row copy and focus logic**

Translate mouse coordinates with the same `framed` inset used by `_copy_custom_ranking_entry_at`. Require a primary press and a small marker hit area consistent with per-entry copy. For an active virtualized viewport, build payload entries from all `viewport.entries` where `not entry.is_other`:

```python
payload_entries = tuple(
    (entry.label, entry.description, entry.project_link)
    for entry in pane.ranking_viewport.entries
    if not entry.is_other
)
```

Use `_custom_ranking_copyable_entries()` only as the fallback for a non-virtualized eligible path. Call `copy_command(_custom_ranking_clipboard_all_text(payload_entries))`; on success set `copied_ranking_all_until = now + 1.5`. Show the existing `status.data_copied` / `status.command_copy_failed` feedback. Return `True` so row-copy, link, focus, and double-click handling cannot observe the click.

- [ ] **Step 4: Expire and invalidate transient presentation state**

Extend the existing copied-entry expiry check to clear `copied_ranking_all_until` after 1.5 seconds and repaint once. Hide/reset the hit when rendering pending, error, non-chart, non-Ranking, empty, or no-match content. Do not issue refresh/query/config/history actions.

- [ ] **Step 5: Run host and interaction regressions**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_dashboard_scroll.py tests/test_tui_custom.py tests/test_tui_dashboard.py -q`

Expected: only the repository's already-recorded baseline failures, with all new copy-all and existing row-copy/wheel tests passing.

- [ ] **Step 6: Commit Dashboard interaction**

```bash
git add src/ccusage_viz/tui.py tests/test_custom_ranking_dashboard_scroll.py
git commit -m "feat: copy all displayed custom ranking entries"
```

---

### Task 4: Final verification and documentation alignment

**Files:**
- Modify if test results need recording: `docs/superpowers/plans/2026-10-12-custom-ranking-copy-all.md`

- [ ] **Step 1: Run focused lint and type checks**

```bash
uv run ruff check src/ccusage_viz/tui.py src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py tests/test_tui_custom.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py
uv run ty check src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py
```

Expected: PASS.

- [ ] **Step 2: Run focused feature tests**

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_custom_component.py tests/test_tui_custom.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the full suite and compare the baseline**

```bash
uv run pytest -o addopts='' -q
git diff --check
```

Expected: no new failures beyond the six recorded pre-existing failures: one text wrapping test, two Dashboard tests, and three Dashboard header tests.

- [ ] **Step 4: Review scope and performance invariants**

Confirm from the diff and tests that copy-all uses prepared filtered entries, copies off-screen matches, excludes `Other`, retains per-row copy/link behavior, does no query work, and does not broaden support to standalone/native/monitor charts.

- [ ] **Step 5: Commit any final test/document adjustment**

```bash
git add docs/superpowers/plans/2026-10-12-custom-ranking-copy-all.md tests
git commit -m "test: validate custom ranking copy all"
```

Skip this commit if no files changed in Task 4.

## Self-review

- Spec coverage: presentation, full filtered result semantics, formatting, transient success, hit precedence, exclusions, lifecycle isolation, virtualization, and regression verification are covered by Tasks 1–4.
- Placeholder scan: no deferred implementation steps or undefined behavior remain.
- Type consistency: `copy_all_hit`, `copied_all`, `copied_ranking_all_until`, and `_custom_ranking_clipboard_all_text` use the same names across renderer, host, and tests.
