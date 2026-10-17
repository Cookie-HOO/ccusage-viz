# Remove Ranking Movement Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Ranking charts and Monitor Ranking/List views while removing every rank-position change indicator and retaining activity and numeric-value change indicators.

**Architecture:** Delete both rank-movement paths: prior-period `Rank Δ` presentation facts and refresh-to-refresh rank tracking. Keep `RefreshDeltas` as the sole live-change tracker, and simplify rendering contracts so ordinal rank is current-state display data only.

**Tech Stack:** Python 3.12+, dataclasses, pytest, Ruff, ty

**Spec:** `docs/superpowers/specs/2026-10-13-remove-ranking-movement-indicators-design.md`

## Global Constraints

- Retain every Ranking chart type, query capability, current ordering, Top N behavior, search, scrolling, and copy/link behavior.
- Retain historical previous-value comparison (`vs prior`) and its `New` value state.
- Retain Monitor activity markers and numeric value-delta arrows, including pending-state suppression.
- Do not overwrite unrelated working-tree changes.
- Add no replacement rank-movement API or compatibility shim.

## File Structure

- `src/ccusage_viz/render/ranking_presentation.py`: historical Ranking layout and refresh markers; remove rank comparison fields/column while retaining value comparisons.
- `src/ccusage_viz/render/ranking.py`: native Monitor Ranking/List rendering; retain activity and value markers only.
- `src/ccusage_viz/render/base.py`, `src/ccusage_viz/render/surfaces.py`, `src/ccusage_viz/historical_render.py`: remove rank-delta render plumbing.
- `src/ccusage_viz/render/custom_ranking_preparation.py`, `src/ccusage_viz/custom_models.py`, `src/ccusage_viz/custom_protocol.py`: remove historical previous-rank facts without affecting previous values.
- `src/ccusage_viz/deltas.py`, `src/ccusage_viz/monitor_component.py`, `src/ccusage_viz/monitor.py`, `src/ccusage_viz/watch.py`, `src/ccusage_viz/tui.py`: remove refresh rank tracking and state.
- Existing focused test modules validate rendering, protocol parsing, and host integration.

---

### Task 1: Remove historical prior-rank presentation

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/render/custom_ranking_preparation.py`
- Modify: `src/ccusage_viz/render/ranking_viewport.py`
- Modify if the field is public there: `src/ccusage_viz/custom_models.py`
- Modify if the wire field is parsed there: `src/ccusage_viz/custom_protocol.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_render.py`
- Test: `tests/test_custom_protocol.py`
- Test: `tests/test_custom_component.py`
- Test: `tests/test_custom_ranking_scroll.py`

**Interfaces:**
- Consumes: `RankingPresentationEntry.previous` and `comparison_ready` for numeric prior-period comparisons.
- Produces: historical Ranking output with `Current`, `Share`, and `vs prior` fields but no `Rank Δ`, prior-rank glyph, or `New in ranking` state.

- [ ] **Step 1: Change focused tests to describe the reduced historical comparison**

Update fixtures containing `previous_rank` so they provide only `previous` and `comparison_ready`. Assert numeric comparison remains visible and the rank column does not:

```python
assert "vs prior" in rendered
assert "+200" in rendered
assert "Rank Δ" not in rendered
assert "New in ranking" not in rendered
```

For Custom protocol tests, remove acceptance/round-trip expectations for `previous_rank`; if supplied on an otherwise valid series, assert it is rejected as an unknown field according to the protocol's existing strict-field behavior.

- [ ] **Step 2: Run focused tests to verify they fail**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py tests/test_custom_protocol.py tests/test_custom_component.py tests/test_custom_ranking_scroll.py -k 'ranking and (comparison or previous or viewport)' -q
```

Expected: FAIL because prior-rank fields and the `Rank Δ` column still exist.

- [ ] **Step 3: Remove prior-rank data and layout**

Delete `RankingPresentationEntry.previous_rank` and all prior-rank sorting/calculation. Remove `rank_comparison_visible`, `rank_change_width`, the rank-comparison tuple field, header, and row cell from historical rendering and viewport column measurement. Delete the now-unused `label.ranking_column_rank_change` and `label.ranking_new_rank` locale entries. Remove equivalent previous-rank model/protocol/preparation fields while leaving `previous`, `comparison_ready`, and numeric delta formatting unchanged.

- [ ] **Step 4: Run focused historical tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py tests/test_custom_protocol.py tests/test_custom_component.py tests/test_custom_ranking_scroll.py -k 'ranking' -q
```

Expected: PASS; historical value comparison remains covered and no rank movement presentation remains.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/render/custom_ranking_preparation.py src/ccusage_viz/render/ranking_viewport.py src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_render.py tests/test_custom_protocol.py tests/test_custom_component.py tests/test_custom_ranking_scroll.py
git commit -m "refactor: remove historical rank movement comparisons"
```

### Task 2: Preserve only Monitor activity and value movement markers

**Files:**
- Modify: `src/ccusage_viz/render/ranking.py`
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `RenderContext.deltas: Mapping[Hashable, float] | None`.
- Produces: Monitor Ranking/List and historical refresh rows with `(activity, value_marker)` only; positive/negative/zero numeric changes keep their existing glyph and color behavior.

- [ ] **Step 1: Add focused marker assertions**

Replace rank-arrow fixtures with value-delta fixtures and assert both retained signals and removed rank signals:

```python
context = replace(base_context, deltas={"alpha": 5, "beta": -2})
rendered = render_ranking(model, context)
assert "●" in strip_ansi(rendered)
assert "↑" in strip_ansi(rendered)
assert "↓" in strip_ansi(rendered)
```

Also assert pending rendering suppresses both activity and value markers, and cover `style="list"` plus a Ranking style.

- [ ] **Step 2: Run marker tests to verify the old contract fails**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py -k 'ranking and (activity or refresh or monitor or list)' -q
```

Expected: at least one FAIL while tests or renderer still expect rank markers.

- [ ] **Step 3: Simplify marker rendering**

Change `_refresh_markers` to accept only `deltas` and return `tuple[str, str]` for activity and value marker. In native Monitor rendering, delete `rank_growth`, `rank_change`, and `rank_marker`; adjust prefixes and list rows so spacing remains aligned without a blank rank-marker slot. Keep the current `Other`, pending, ASCII, color, and numeric zero behavior.

- [ ] **Step 4: Run rendering tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/render/ranking.py src/ccusage_viz/render/ranking_presentation.py tests/test_render.py
git commit -m "refactor: keep only monitor value movement markers"
```

### Task 3: Delete rank-delta contracts and live tracking

**Files:**
- Modify: `src/ccusage_viz/deltas.py`
- Modify: `src/ccusage_viz/render/base.py`
- Modify: `src/ccusage_viz/render/surfaces.py`
- Modify: `src/ccusage_viz/historical_render.py`
- Modify: `src/ccusage_viz/monitor_component.py`
- Modify: `src/ccusage_viz/monitor.py`
- Modify: `src/ccusage_viz/watch.py`
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_layout.py`
- Test: `tests/test_monitor_component.py`
- Test: `tests/test_monitor.py`
- Test: `tests/test_watch.py`
- Test: `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: `RefreshDeltas` and `RenderContext.deltas` from Tasks 1-2.
- Produces: host/component render calls with no `rank_deltas` or `ranking_rank_deltas` arguments and no `RefreshRanks` state.

- [ ] **Step 1: Update component and host tests**

Delete the `RefreshRanks` unit test and fake-component `rank_deltas` fields. Replace Dashboard context-capture expectations with:

```python
assert captured["deltas"] == {"sonnet": 25.0}
assert "rank_deltas" not in captured
```

Add or retain an acceptance test proving two Monitor samples populate `component.deltas` and render activity/value markers after rank state is gone.

- [ ] **Step 2: Run host tests to verify failures**

Run:

```bash
uv run pytest -o addopts='' tests/test_tui_layout.py tests/test_monitor_component.py tests/test_monitor.py tests/test_watch.py tests/test_tui_dashboard.py -k 'rank or delta or ranking' -q
```

Expected: FAIL because production signatures and state still expose rank deltas.

- [ ] **Step 3: Remove state and plumbing**

Delete `RefreshRanks` from `deltas.py`. Remove `rank_deltas` from `RenderContext` and `SurfacePresentation`. Remove `ranking_rank_deltas` parameters from historical render helpers. In `MonitorComponent`, remove `rank_changes`, its property, acceptance updates, preview copies, and clearing. In standalone Monitor, watch, and Dashboard hosts, remove rank tracker imports/state, `previous_ranks`, `_refresh_ranks`, accepted-refresh calls, and rank-delta render arguments. Keep all value tracker initialization/clear/preview logic intact.

- [ ] **Step 4: Run integration tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_tui_layout.py tests/test_monitor_component.py tests/test_monitor.py tests/test_watch.py tests/test_tui_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/deltas.py src/ccusage_viz/render/base.py src/ccusage_viz/render/surfaces.py src/ccusage_viz/historical_render.py src/ccusage_viz/monitor_component.py src/ccusage_viz/monitor.py src/ccusage_viz/watch.py src/ccusage_viz/tui.py tests/test_tui_layout.py tests/test_monitor_component.py tests/test_monitor.py tests/test_watch.py tests/test_tui_dashboard.py
git commit -m "refactor: remove rank delta tracking pipeline"
```

### Task 4: Verify repository consistency and regressions

**Files:**
- Modify only files from Tasks 1-3 if verification exposes an omission.

**Interfaces:**
- Consumes: completed reduced Ranking contracts.
- Produces: a clean source tree with no rank-movement identifiers or localized UI copy.

- [ ] **Step 1: Search for stale rank-movement code**

Run:

```bash
rg -n 'RefreshRanks|rank_deltas|ranking_rank_deltas|previous_rank|ranking_column_rank_change|ranking_new_rank|Rank Δ|New in ranking' src tests
```

Expected: no matches. Generic current-rank fields, ranking chart names, and numeric `deltas` remain.

- [ ] **Step 2: Run static checks**

Run:

```bash
uv run ruff check src/ccusage_viz tests
uv run ty check src/ccusage_viz
```

Expected: PASS, or only documented baseline diagnostics unrelated to this change.

- [ ] **Step 3: Run focused regression suite**

Run:

```bash
uv run pytest -o addopts='' tests/test_render.py tests/test_custom_protocol.py tests/test_custom_component.py tests/test_custom_ranking_scroll.py tests/test_monitor_component.py tests/test_monitor.py tests/test_watch.py tests/test_tui_layout.py tests/test_tui_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 4: Run the full suite and inspect the diff**

Run:

```bash
uv run pytest -o addopts='' -q
git diff --check
git status --short
git diff --stat HEAD~3..HEAD
```

Expected: all non-baseline tests pass; no whitespace errors; changes are limited to rank-movement removal and corresponding tests/docs.

- [ ] **Step 5: Commit any verification fixes**

If Step 1-4 required changes:

```bash
git add src tests
git commit -m "test: verify ranking movement removal"
```

If no changes were required, do not create an empty commit.

## Self-review

- **Spec coverage:** Task 1 removes historical prior-rank comparison; Task 2 preserves activity/value arrows while removing row rank arrows; Task 3 removes all live rank tracking and contracts; Task 4 verifies no stale identifiers and protects Ranking behavior.
- **Placeholder scan:** no deferred implementation or unspecified test steps remain.
- **Type consistency:** `RenderContext.deltas` is the only change-marker contract across renderers and hosts; no later task consumes removed rank fields.
