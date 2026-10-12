# Custom Ranking Geometry Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache the two most recent Custom Ranking geometry layouts so focus entry/exit alternation between widths `W` and `W-2` avoids repeated full-list description wrapping.

**Architecture:** Add immutable geometry snapshots and a two-entry pane-local LRU to `RankingViewport`. Stable-data rebuilds clear the cache; geometry-key hits restore copied columns and immutable starts/heights, while misses use the existing exact scalar measurement and save the result.

**Tech Stack:** Python 3.11+, dataclasses, ordered dictionaries, pytest, Ruff, uv; no dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-ranking-geometry-cache-design.md`

## Global Constraints

- Preserve focus border, pane interior size changes, numerical display-line offset, scrollbars, and current copy/link behavior.
- Cache only scalar geometry, never styled/rendered rows, hits, scrollbars, chrome, or copy feedback.
- Cache capacity is exactly two snapshots per `RankingViewport`.
- Stable data replacement and `clear()` invalidate every snapshot.
- Mutable `RankingColumns.widths` dictionaries are defensively copied on save and restore.
- Existing native, standalone, monitor, query, Dashboard history, and terminal behavior is unchanged.

---

### Task 1: Add bounded geometry snapshot storage

**Files:**
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Add private/focused immutable snapshot type containing column widths, description width, starts, heights, and total rows.
- Add `RankingViewport.restore_geometry(key: object) -> bool`.
- Add `RankingViewport.remember_geometry(key: object) -> None`.
- Add `RankingViewport.invalidate_geometry() -> None`.

- [ ] **Step 1: Write failing bounded-LRU tests**

```python
def test_geometry_cache_restores_copied_columns_and_evicts_lru() -> None:
    viewport = RankingViewport()
    viewport.columns.widths["right"] = 12
    viewport.columns.description_width = 40
    viewport.starts = (0, 1)
    viewport.heights = (1,)
    viewport.total_rows = 1
    viewport.remember_geometry("a")

    viewport.columns.widths["right"] = 99
    assert viewport.restore_geometry("a")
    assert viewport.columns.widths == {"right": 12}
    viewport.columns.widths["right"] = 15
    assert viewport.restore_geometry("a")
    assert viewport.columns.widths == {"right": 12}

    viewport.remember_geometry("b")
    viewport.remember_geometry("c")
    assert not viewport.restore_geometry("a")
    assert viewport.restore_geometry("b")
    assert viewport.restore_geometry("c")
```

- [ ] **Step 2: Run test to verify API is absent**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k geometry_cache_restores -v`

Expected: FAIL because snapshot APIs do not exist.

- [ ] **Step 3: Implement snapshot and LRU**

Use an insertion-ordered `dict[object, RankingGeometry]`; on restore, pop and reinsert the snapshot to mark it recent. On remember, overwrite the key and evict `next(iter(cache))` while length exceeds two. Construct fresh `RankingColumns(dict(snapshot.widths), snapshot.description_width)` on restore.

- [ ] **Step 4: Invalidate from data lifecycle**

`RankingViewport.clear()` calls `invalidate_geometry()`. Stable data rebuild will call the same method from Task 2. Do not reset scroll offset in `invalidate_geometry()`.

- [ ] **Step 5: Run focused viewport tests and commit**

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k geometry_cache -q
uv run ruff check src/ccusage_viz/render/ranking_viewport.py tests/test_custom_ranking_scroll.py
git add src/ccusage_viz/render/ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "perf: cache custom ranking geometry snapshots"
```

### Task 2: Integrate snapshots into renderer preparation

**Files:**
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Modify if needed: `src/ccusage_viz/render/ranking_viewport.py`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Existing complete `geometry_key` remains the snapshot key.
- Stable-data rebuild clears all snapshots before preparing new geometry.
- Geometry hit bypasses `measure_ranking_columns()` and `prepare_lines()`.

- [ ] **Step 1: Add failing focus-width alternation test**

```python
def test_two_warm_widths_skip_all_geometry_work(monkeypatch: pytest.MonkeyPatch) -> None:
    viewport = RankingViewport()
    model = projection(10_000, descriptions=True, comparison=True)
    wide = context(width=100, height=24, density="detailed")
    narrow = replace(wide, width=98)
    render(model, viewport, wide, spacing="line", scrollbar=True)
    render(model, viewport, narrow, spacing="line", scrollbar=True)

    monkeypatch.setattr(
        RankingViewport, "prepare_lines", lambda *args, **kwargs: pytest.fail("rebuilt lines")
    )
    monkeypatch.setattr(
        custom_ranking_viewport_module,
        "measure_ranking_columns",
        lambda *args, **kwargs: pytest.fail("remeasured columns"),
    )
    render(model, viewport, wide, spacing="line", scrollbar=True)
    render(model, viewport, narrow, spacing="line", scrollbar=True)
```

Account for the one-column scrollbar gutter consistently: `geometry_key` uses the effective width after gutter reservation.

- [ ] **Step 2: Run test and verify the single-slot geometry rebuild fails**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k two_warm_widths -v`

Expected: FAIL on the first return to the earlier width.

- [ ] **Step 3: Integrate restore/miss/save flow**

In `render_custom_ranking_viewport()`:

```python
if rebuild_data:
    viewport.invalidate_geometry()
    # existing stable entry preparation

if rebuild_geometry:
    if not viewport.restore_geometry(geometry_key):
        viewport.columns = RankingColumns()
        measure_ranking_columns(...)
        viewport.prepare_lines(...)
        viewport.remember_geometry(geometry_key)
    viewport.clamp()
    viewport.geometry_key = geometry_key
```

Do not save before both columns and line arrays are complete. Do not alter `reset_key` behavior.

- [ ] **Step 4: Add correctness equivalence test**

Use descriptions, comparison, `line` spacing, scrollbar, a nonzero offset, and copied marker. Capture output, total rows, scrollbar, starts/heights, and hits for each width. Alternate back and assert all values match each width's first render except intentionally transient copy marker state.

- [ ] **Step 5: Add data invalidation test**

Warm both widths, replace projection series/search/language/unit, monkeypatch one geometry method to count rather than fail, and assert one fresh build occurs and stale starts/columns are not restored.

- [ ] **Step 6: Run renderer and scrollbar tests; commit**

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_scrollbar.py -q
uv run ruff check src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py tests/test_custom_ranking_scroll.py
git add src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "perf: reuse custom ranking focus geometry"
```

### Task 3: Prove Dashboard focus/exit reuse

**Files:**
- Modify: `tests/test_custom_ranking_dashboard_scroll.py`
- Modify production `src/ccusage_viz/tui.py` only if the test exposes an integration defect.

**Interfaces:**
- Native `m` enters pane adjustment and Escape/Enter exits.
- First encounter of each width may prepare; later alternations must not.

- [ ] **Step 1: Add Dashboard loop regression**

Use the existing accepted-data Dashboard fixture. Spy on `RankingViewport.prepare_lines` while issuing:

```python
KeyEvent("m"), KeyEvent("\x1b"),
KeyEvent("m"), KeyEvent("\x1b")
```

Count geometry builds by effective context width. Assert at most one build per width and exactly two distinct widths for a frame-less Dashboard. Also assert no query/generation/scheduler activity and retained/clamped offset/hits after each transition.

- [ ] **Step 2: Run Dashboard test**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_dashboard_scroll.py -k geometry -v`

Expected: PASS after Task 2 without a TUI production edit.

- [ ] **Step 3: Run interaction regressions and commit**

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_dashboard_scroll.py tests/test_dashboard_repaint.py -q
uv run ruff check tests/test_custom_ranking_dashboard_scroll.py
git add tests/test_custom_ranking_dashboard_scroll.py
git commit -m "test: reuse ranking geometry across pane focus"
```

### Task 4: Final verification

- [ ] **Step 1: Run static checks**

```bash
uv run ruff check src tests
git diff --check
```

- [ ] **Step 2: Run focused suites**

```bash
uv run pytest -o addopts='' \
  tests/test_custom_ranking_scroll.py \
  tests/test_custom_ranking_dashboard_scroll.py \
  tests/test_scrollbar.py \
  tests/test_dashboard_repaint.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `uv run pytest -q`

Expected: no new failures beyond the established six-test baseline.

- [ ] **Step 4: Inspect scope**

```bash
git status --short
git diff --check HEAD~3..HEAD
```

Expected: clean tree; only viewport renderer/tests and approved docs changed.

## Self-review

- **Spec coverage:** Task 1 defines bounded mutation-safe storage; Task 2 integrates exact geometry reuse and invalidation; Task 3 proves native focus/exit behavior; Task 4 covers regressions.
- **Placeholder scan:** No placeholders remain.
- **Type consistency:** Snapshot keys use existing geometry-key objects; snapshots restore fresh `RankingColumns` and immutable tuple facts.
