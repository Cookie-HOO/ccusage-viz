# Ranking List Label-Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make native and Custom Dataset historical Ranking `list` style left-aligned and label-prioritized, without copy affordances or movement/comparison indicators.

**Architecture:** Put list-only row composition in the shared historical Ranking renderer, so native Ranking and ungrouped Custom Ranking get identical label allocation and marker suppression. Make Custom viewports style-aware for geometry and interaction state, and make grouped Custom headings/rows honor the same list constraints.

**Tech Stack:** Python 3.13, pytest, Ruff, ty

**Spec:** `docs/superpowers/specs/2026-10-14-ranking-list-label-priority-design.md`

## Global Constraints

- Apply only when `RenderContext.style == "list"`; dot, dots, bar, and ranking styles must retain current behavior.
- Keep rank and current value in list rows.
- List rows must be left-aligned and allocate reclaimed space to labels.
- List output must not show copy, link, refresh/activity/value-change, rank-change, delta, rank-delta, or percentage indicators.
- Native, ungrouped Custom Dataset, and grouped Custom Dataset historical Rankings must behave consistently.
- Do not modify unrelated pre-existing worktree changes.

---

## File Structure

- `src/ccusage_viz/render/ranking_presentation.py` — shared historical row layout, comparison/header selection, and label decorations.
- `src/ccusage_viz/render/custom_ranking_viewport.py` — list-aware Custom Ranking geometry and copy-all suppression.
- `src/ccusage_viz/render/ranking_viewport.py` — list-aware per-row copy/link hit suppression.
- `src/ccusage_viz/render/grouped_ranking_viewport.py` — list-aware grouped headings, per-row hits, and copy-all suppression.
- `tests/test_render.py` — native/shared list renderer behavior.
- `tests/test_custom_ranking_scroll.py` — ungrouped and grouped viewport output, geometry, and interaction regressions.
- `tests/test_custom_ranking_dashboard_scroll.py` — Dashboard-level Custom copy behavior, if its existing copy-all integration fixture needs a list-style assertion.

### Task 1: Implement shared historical list-row layout

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py:render_historical_ranking`, `measure_ranking_columns`, `render_ranking_heading_row`
- Test: `tests/test_render.py` near `test_historical_ranking_list_keeps_label_and_value_columns_aligned`

**Interfaces:**
- Consumes: `RankingPresentationEntry.copy_marker`, `.project_link`, `RenderContext.style`, `.deltas`, and `.rank_deltas`.
- Produces: `render_historical_ranking(...) -> str` whose `style="list"` rows consist only of left-aligned rank, expanded label, and current value.
- Produces: `render_ranking_heading_row(...) -> tuple[str, ...]` that omits group copy/link/comparison presentation in list style.

- [ ] **Step 1: Write failing shared-renderer tests**

Add a test with an 80-cell list context, a long label, `copy_marker="⊞"`, a project link, previous data, and nonzero `deltas`/`rank_deltas`:

```python
def test_historical_ranking_list_prioritizes_labels_and_omits_auxiliary_indicators() -> None:
    context = RenderContext(
        80, 24, load_translator("en"), color=False, ascii=True,
        style="list", density="detailed", deltas={"api": 2}, rank_deltas={"api": 1},
    )
    output = render_historical_ranking(
        (RankingPresentationEntry(
            "api", "a deliberately long project label that should use list space", 10,
            previous=5, comparison_ready=True, previous_rank=2,
            copy_marker="⊞", project_link="https://example.com/api",
        ),),
        heading="Ranking", value_formatter=str, delta_formatter=lambda value: f"{value:+}",
        context=context, total=10,
    )
    header, row = output.splitlines()[1:]
    assert row.startswith(" 1 ")
    assert "a deliberately long project label" in row
    assert "⊞" not in output and "→" not in output
    assert "^" not in output and "*" not in output
    assert "vs prior" not in output and "Rank Δ" not in output and "%" not in output
    assert "Current" in header and "Scale" not in header
```

Add a second direct `render_ranking_heading_row()` test with `style="list"`, a label containing `" | ⊞"`, a link, delta, and share. Assert the output contains only the plain group label and current value, with neither copy/link symbols nor comparison/share content.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py -k 'list_prioritizes or heading_row' -q
```

Expected: FAIL because the current list mode still includes percentages, movement markers, and label decorations.

- [ ] **Step 3: Implement the minimal shared list branch**

In `render_historical_ranking()`, derive `list_style = context.style == "list"` before marker and comparison calculations. For list style:

```python
rank_marker = activity = value_marker = " "
comparison_visible = growth_visible = rank_comparison_visible = False
show_list_percentage = False
```

Do not append `copy_marker` or the terminal-link marker in `formatted_label()` when `list_style` is true. Bypass the old centered fallback list branch and render each list row directly with this width budget:

```python
rank_prefix = f"{rank:>{rank_width}} "
value_width = max(display_width(value) for ...)
label_width = max(1, context.width - display_width(rank_prefix) - value_width - 1)
row = f"{rank_prefix}{pad_width(truncate_width(label, label_width), label_width)} {pad_width(value, value_width, align='right')}"
```

Build a matching left-aligned header from rank/project/current headings. Never call `center_text()` for row composition. The heading itself remains unchanged. Use the same list branch when `comparison_visible` would otherwise have been true, so detailed list style has no delta/rank-delta/share columns.

In `measure_ranking_columns()`, add an early list-style measurement that records only `current`/`right` value width and a description width calculated after the rank prefix; do not measure comparison columns. In `render_ranking_heading_row()`, add an early list-style path that strips its caller-owned copy suffix/link marker and emits left-aligned label/current fields only.

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py -k 'historical_ranking_list or heading_row' -q
```

Expected: PASS, including existing list alignment coverage updated only where it previously required a percentage.

- [ ] **Step 5: Commit the shared rendering change**

```bash
git add src/ccusage_viz/render/ranking_presentation.py tests/test_render.py
git commit -m "feat: prioritize labels in ranking lists"
```

### Task 2: Suppress Custom Ranking list copy actions and make geometry style-aware

**Files:**
- Modify: `src/ccusage_viz/render/custom_ranking_viewport.py:render_custom_ranking_viewport`
- Modify: `src/ccusage_viz/render/ranking_viewport.py:RankingViewport.render`
- Test: `tests/test_custom_ranking_scroll.py` near `test_copy_all_marker_follows_count_row_and_hides_without_it` and `test_style_and_theme_changes_reuse_data_and_geometry`

**Interfaces:**
- Consumes: shared list output from `render_historical_ranking()` and `RenderContext.style`.
- Produces: a list-style `RankingViewport` with `copy_all_hit is None` and `hits == {}`.
- Produces: a geometry cache key that distinguishes list from graphical styles when their physical row widths/layout differ.

- [ ] **Step 1: Write failing Custom viewport tests**

Add a list-context test for a projection with long labels and links:

```python
def test_list_viewport_has_no_copy_actions_and_expands_labels() -> None:
    viewport = RankingViewport()
    output = strip_ansi(render(projection(20), viewport, replace(context(), style="list"), copy_all_action=True))
    assert viewport.copy_all_hit is None
    assert viewport.hits == {}
    assert "⊞" not in output and "→" not in output
    assert "Project 19" in output
```

Add a geometry regression that renders detailed dot style, records `viewport.starts`, then renders list style. Assert the list render does not reuse incompatible geometry: its output has no copy hits, and `viewport.geometry_key` differs from the dot key. Do not assert starts always differ; labels without descriptions can legitimately retain one physical row.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k 'list_viewport or geometry' -q
```

Expected: FAIL because copy-all and entry copy hits remain active in list mode and styles are intentionally omitted from the geometry key.

- [ ] **Step 3: Implement list viewport interaction and geometry rules**

In `render_custom_ranking_viewport()`, include `context.style` in `geometry_key`, because list width allocation changes renderer geometry. Gate the copy-all block with `context.style != "list"`.

In `RankingViewport.render()`, do not derive click hits when `context.style == "list"`; clear hits remains the existing initial operation. This also prevents a hidden copy/link marker from becoming an actionable stale region.

Keep `copy_marker=lambda entry: ...` in preparation unchanged: non-list styles still need it, while the shared renderer suppresses it in list presentation.

- [ ] **Step 4: Run focused Custom viewport tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k 'copy_all or list_viewport or style_and_theme_changes_reuse_data_and_geometry' -q
```

Expected: PASS. Update the existing style-cache test expectation: style switches may rebuild geometry, but must reuse prepared entries/data and preserve the logical scroll anchor.

- [ ] **Step 5: Commit the Custom viewport change**

```bash
git add src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "fix: disable custom ranking list copy actions"
```

### Task 3: Apply list constraints to grouped Custom Rankings

**Files:**
- Modify: `src/ccusage_viz/render/grouped_ranking_viewport.py:render_grouped_custom_ranking_viewport`
- Test: `tests/test_custom_ranking_scroll.py` near grouped copy-all and hit tests

**Interfaces:**
- Consumes: list-safe `render_historical_ranking()` and `render_ranking_heading_row()` from Task 1.
- Produces: list-style `GroupedRankingViewport` with no copy-all hit, no row hits, and no group copy/link decorations.

- [ ] **Step 1: Write failing grouped viewport test**

Add a grouped projection test with detailed list context:

```python
def test_grouped_list_has_no_copy_or_comparison_affordances() -> None:
    viewport = GroupedRankingViewport()
    output = strip_ansi(render_grouped(
        grouped_projection(), viewport, replace(context(), style="list", density="detailed"),
        copy_all_action=True,
    ))
    assert viewport.copy_all_hit is None
    assert viewport.hits == {}
    assert "⊞" not in output and "→" not in output
    assert "vs prior" not in output and "Rank Δ" not in output
```

Use the existing `render_grouped` helper signature and fixtures exactly; if it currently does not accept a context override, extend only that test helper to forward `ctx`.

- [ ] **Step 2: Run the grouped test to verify it fails**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k grouped_list -q
```

Expected: FAIL because `heading_lines()` unconditionally appends a group copy marker, rows/hits remain copyable, and copy-all remains available.

- [ ] **Step 3: Implement grouped list suppression**

In `heading_lines()`, build `label=group.label` when `context.style == "list"`; keep `f"{group.label} | {marker}"` only for non-list styles. Pass `link=None` in list mode. The Task 1 heading renderer will suppress remaining comparison/share output.

When constructing `marked` in `entry_lines()`, set `copy_marker=None` in list mode. Do not populate `viewport.hits` in the post-body hit scan for list mode. Gate the grouped copy-all block with `context.style != "list"`. Add `context.style` to `geometry_key` because the grouped heading and entry rows now have a different physical layout.

- [ ] **Step 4: Run grouped and non-list regression tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_custom_ranking_scroll.py -k 'grouped and (list or copy_all or hit)' -q
```

Expected: PASS. Existing non-list copy-all and per-entry hit tests remain green.

- [ ] **Step 5: Commit grouped list support**

```bash
git add src/ccusage_viz/render/grouped_ranking_viewport.py tests/test_custom_ranking_scroll.py
git commit -m "fix: simplify grouped ranking list actions"
```

### Task 4: Run full targeted validation

**Files:**
- Modify if assertions need exact behavior updates: `tests/test_render.py`, `tests/test_custom_ranking_scroll.py`, `tests/test_custom_ranking_dashboard_scroll.py`

**Interfaces:**
- Consumes: all renderer and viewport behavior implemented in Tasks 1–3.
- Produces: validation that native and both Custom Ranking paths keep non-list behavior intact.

- [ ] **Step 1: Run static checks**

Run:

```bash
uv run ruff check src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/grouped_ranking_viewport.py tests/test_render.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py
uv run ty check src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/render/custom_ranking_viewport.py src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/render/grouped_ranking_viewport.py
```

Expected: PASS.

- [ ] **Step 2: Run renderer and viewport suites**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py -q
```

Expected: PASS.

- [ ] **Step 3: Run Dashboard Custom regression coverage**

Run:

```bash
uv run pytest -o addopts='' tests/test_tui_custom.py tests/test_tui_dashboard.py -q
```

Expected: PASS, confirming Dashboard event handling continues to work with absent list copy hits.

- [ ] **Step 4: Commit any validation-only test corrections**

```bash
git add tests/test_render.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py
git commit -m "test: cover label-priority ranking lists"
```

Only commit if this task changed files; otherwise leave the working tree unchanged.

## Self-Review

- **Spec coverage:** Task 1 covers left alignment, rank/current retention, label expansion, movement/comparison suppression, and native behavior. Task 2 covers ordinary Custom list copy/copy-all/hit suppression and cache correctness. Task 3 covers grouped Custom labels, links, copy actions, comparison output, and cache correctness. Task 4 validates native, Custom, and Dashboard regression paths.
- **Placeholder scan:** No TBD/TODO or deferred implementation steps remain.
- **Type consistency:** All work uses existing `RenderContext`, `RankingPresentationEntry`, `RankingViewport`, `GroupedRankingViewport`, `render_historical_ranking`, and `render_ranking_heading_row` interfaces; no new cross-module types are required.
