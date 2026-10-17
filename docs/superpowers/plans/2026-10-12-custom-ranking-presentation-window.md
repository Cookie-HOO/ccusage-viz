# Custom Ranking Presentation-Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Dashboard Custom historical Ranking style, density, and theme changes render only fixed chrome and the current visible window while retaining the display-line scroll offset whenever valid.

**Architecture:** Split `RankingViewport` preparation into stable data facts and lazily maintained layout facts. Presentation-only changes reuse stable entries and calculate/render only the necessary window; theme reuses geometry outright. Existing full preparation remains the conservative fallback for source/search/language/width changes.

**Tech Stack:** Python 3.11+, dataclasses, existing Ranking renderer, pytest, Ruff, uv; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-ranking-presentation-window-design.md`

## Global Constraints

- Applies only to Dashboard Custom historical Ranking via `render_custom_ranking_viewport()`.
- Retain the existing numerical `RankingViewport.offset`; call `clamp()` only after the new layout range is known.
- Theme changes must not traverse stable entries or rebuild layout facts.
- Style/density changes must not format a full matching list; format chrome and entries intersecting the visible window only.
- Data source, search, language, and width changes retain conservative correctness invalidation.
- Do not change query/refresh lifecycles, native/standalone/monitor paths, persisted settings, or keyboard bindings.
- Preserve currently unrelated unstaged work in `docs/superpowers/plans/2026-10-12-custom-metric-switching.md`, `src/ccusage_viz/render/custom_ranking_viewport.py`, and `tests/test_custom_ranking_scroll.py`.

---

## File structure

- `src/ccusage_viz/render/ranking_viewport.py`: viewport cache boundaries, lazy geometry/index operations, offset clamp semantics.
- `src/ccusage_viz/render/custom_ranking_viewport.py`: separate data identity from presentation identity; request only required geometry and render only the current window.
- `tests/test_custom_ranking_scroll.py`: large-list presentation-change work-count, offset, rendering, and invalidation regressions.
- `tests/test_custom_ranking_dashboard_scroll.py`: Dashboard-level adjustment regression proving the active Custom Ranking pane retains position and interactive targets.

### Task 1: Make viewport preparation identities explicit

**Files:**
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Produces a stable-entry identity independent from `RenderContext.theme`, `RenderContext.style`, and `RenderContext.density`.
- Produces a geometry identity which includes only line-layout inputs: effective width, descriptions visibility, item spacing, and any renderer facts that affect line heights.
- `RankingViewport` retains `offset` through presentation identity changes and calls `clamp()` after geometry updates.

- [ ] **Step 1: Add failing identity and offset tests**

```python
def test_theme_change_reuses_data_and_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    viewport = RankingViewport()
    model = projection(10_000, descriptions=True)
    detailed = context(height=24, density="detailed")
    render(model, viewport, detailed)
    viewport.offset = 1_000
    entries, starts = viewport.entries, viewport.starts

    monkeypatch.setattr(
        RankingViewport, "prepare_lines", lambda *args, **kwargs: pytest.fail("theme rebuilt geometry")
    )
    render(model, viewport, replace(detailed, color=True, color_scheme="dracula"))

    assert viewport.entries is entries
    assert viewport.starts is starts
    assert viewport.offset == 1_000
```

```python
def test_density_change_preserves_offset_then_clamps() -> None:
    viewport = RankingViewport()
    model = projection(100, descriptions=True)
    render(model, viewport, context(height=16, density="detailed"))
    viewport.offset = 100

    render(model, viewport, context(height=16, density="minimal"))

    assert viewport.offset == min(100, viewport.total_rows - viewport.visible_rows)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k 'theme_change_reuses or density_change_preserves' -v`

Expected: FAIL because presentation inputs currently share the single `viewport.key` and force full data/layout preparation.

- [ ] **Step 3: Introduce stable-data and geometry keys**

In `render_custom_ranking_viewport()`, replace the one `key` decision with explicit stable-data and geometry comparisons. Keep the current source identity, search reset behavior, localized label conversion, filtering, prior-rank calculation, `by_id`, aggregate total, and maximum in the stable-data rebuild. Ensure the stable key contains language and all projection facts required for entry text, but excludes style/density/theme.

In `RankingViewport`, add separate fields using existing naming conventions:

```python
source: object | None = None
data_key: object = None
geometry_key: object = None
```

Keep `key` only if needed temporarily for compatibility; otherwise replace it in `clear()` and all callers. A geometry rebuild resets `columns`, calculates required line facts, and then invokes `clamp()`; it does not reset `offset`.

- [ ] **Step 4: Run focused tests to verify data and geometry reuse**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k 'theme_change_reuses or density_change_preserves or refresh_shrink_resize_top_and_source_reset' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "perf: separate custom ranking presentation caches"
```

### Task 2: Bound style/density work to the current display window

**Files:**
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- `RankingViewport.render(...)` continues to accept a function rendering a sequence of `RankingPresentationEntry` values and a rank offset.
- Geometry preparation has a bounded path that does not call `render_historical_ranking()` with every stable entry after a style/density adjustment.
- `RankingViewport.hits`, `Scrollbar`, and `copy_all_hit` continue to describe only the current rendered window.

- [ ] **Step 1: Add a failing large-list bounded-work regression**

```python
@pytest.mark.parametrize("changed", ("style", "density"))
def test_presentation_change_formats_only_visible_entries(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    import ccusage_viz.render.ranking_presentation as presentation

    viewport = RankingViewport()
    model = projection(10_000, descriptions=True, comparison=True)
    initial = context(height=24, density="detailed")
    render(model, viewport, initial)
    viewport.offset = 8_000
    formatted: list[object] = []
    original = presentation._refresh_markers

    def record(entry, **kwargs):
        formatted.append(entry.key)
        return original(entry, **kwargs)

    monkeypatch.setattr(presentation, "_refresh_markers", record)
    changed_context = (
        replace(initial, style="list")
        if changed == "style"
        else replace(initial, density="minimal")
    )
    render(model, viewport, changed_context)

    assert 0 < len(formatted) <= viewport.visible_rows + 4
```

- [ ] **Step 2: Run it to verify the current full preparation fails the work bound**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k presentation_change_formats -v`

Expected: FAIL because style/density currently invokes full-list `render(..., measure=True)` and/or full-entry geometry work.

- [ ] **Step 3: Implement lazy geometry sufficient for the visible range**

Refactor `RankingViewport.prepare_lines()` into a layout operation that can locate the current offset and create enough height/start facts to populate the visible window without invoking the formatted renderer across all entries. Preserve fixed per-entry separators and the existing maximum two description-line policy. The implementation may retain compact scalar metadata per entry; it must not retain complete styled lines.

Use the currently selected `context.style`, descriptions visibility, width, and spacing only for the visible-window range. If an exact total range is needed for the scrollbar, calculate it with scalar text-width/wrap operations, not `render_historical_ranking()` or `_refresh_markers()` for offscreen entries.

Ensure `render_historical_ranking()` is called only for chrome and selected window entries on this path. Do not mutate the stable `viewport.entries` sequence to add a temporary copy marker.

- [ ] **Step 4: Run renderer regressions**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_scrollbar.py -q`

Expected: PASS, including full-output equivalence, descriptions, all spacing modes, scrollbar range, and copy/link hit tests.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/custom_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "perf: window custom ranking presentation changes"
```

### Task 3: Verify Dashboard adjustment integration

**Files:**
- Modify: `tests/test_custom_ranking_dashboard_scroll.py`
- Modify only if required: `src/ccusage_viz/tui.py`

**Interfaces:**
- Dashboard continues to route adjustments through its current options/pane rendering path.
- No new UI command, query operation, or persistence field is introduced.

- [ ] **Step 1: Add a failing Dashboard regression**

Using the existing `dashboard` fixture, set a nonzero `ranking_viewport.offset`, dispatch each existing style/density/theme adjustment event, and assert:

```python
assert pane.ranking_viewport.offset == expected_clamped_offset
assert pane.ranking_viewport.scrollbar is not None
assert pane.ranking_viewport.hits
```

Capture the Custom component generation and scheduler state before each event and assert both are unchanged afterward. Click a visible copy/link hit after adjustment and assert it resolves to the entry currently displayed.

- [ ] **Step 2: Run the Dashboard regression and verify it fails before any needed wiring change**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_dashboard_scroll.py -k presentation -v`

Expected: FAIL only if current adjustment/render integration resets the offset or loses visible interaction geometry.

- [ ] **Step 3: Make the minimal Dashboard-only integration correction**

If Task 1/2 preserves the renderer offset without TUI edits, leave `tui.py` unchanged. Otherwise adjust only the Custom historical Ranking presentation adjustment branch so it retains the viewport state and schedules a paint; do not submit a query, rebuild a scheduler, or change focus.

- [ ] **Step 4: Run Dashboard and related interaction tests**

Run: `uv run pytest -o addopts='' tests/test_custom_ranking_dashboard_scroll.py tests/test_dashboard_repaint.py tests/test_tui_input.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_custom_ranking_dashboard_scroll.py
git commit -m "test: retain custom ranking window across presentation changes"
```

### Task 4: Final verification

**Files:** Review only changed files from Tasks 1–3 and preserve unrelated working-tree changes.

- [ ] **Step 1: Run formatting, lint, and whitespace checks**

Run:

```bash
uv run ruff check src tests
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 2: Run focused suite**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_scrollbar.py tests/test_dashboard_repaint.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the full suite and compare baseline failures**

Run: `uv run pytest -q`

Expected: no new failures. Record any failures and confirm whether they reproduce from the pre-feature baseline.

- [ ] **Step 4: Inspect staged scope before final commit(s)**

Run:

```bash
git status --short
git diff --check HEAD~3..HEAD
```

Expected: only this feature's files are included in its commits; the pre-existing custom metric switching plan and copy-all marker changes remain separately identifiable.

## Self-review

- **Spec coverage:** Task 1 implements layered cache identities and offset preservation. Task 2 enforces bounded style/density formatting and preserves rendering/scrollbar/hit correctness. Task 3 proves Dashboard integration does not query or lose interaction metadata. Task 4 verifies focused and complete regression coverage.
- **Placeholder scan:** No implementation placeholders or undefined interfaces remain; names refer to existing `RankingViewport`, `render_custom_ranking_viewport()`, and renderer behavior.
- **Type consistency:** Cache fields are `object` identities consistent with the current `source`, `key`, and `reset_key` pattern; rendering still accepts `RankingPresentationEntry` tuples.
