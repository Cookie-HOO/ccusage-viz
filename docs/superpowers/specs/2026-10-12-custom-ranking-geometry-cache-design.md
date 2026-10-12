# Custom Ranking geometry cache for pane focus

**Date:** 2026-10-12  
**Status:** Approved direction; awaiting specification review

## Goal

Eliminate repeated full-list description wrapping when a Dashboard Custom Ranking pane is selected and then returned to the Dashboard. Preserve the existing focus border, interior size change, scroll position, scrollbar, and hit behavior.

## Profiling evidence

A dedicated `py-spy` recording repeatedly entered and exited the `recentrepo` pane. The two transitions produced symmetric hotspots:

- enter-pane paint and pane render: 9,057 samples (7.00%);
- exit-pane paint and pane render: 9,036 samples (6.98%);
- `render_custom_ranking_viewport()` per side: about 6.8–6.9%;
- `RankingViewport.prepare_lines()` per side: about 5.5–5.6%;
- `wrap_width()` / `display_width()` per side: about 4.1–4.2%;
- terminal `row_updates()`: about 0.1%.

The focus transition changes a frame-less pane's interior width and height by two cells. The Ranking geometry key therefore alternates between width `W` and `W-2`. `RankingViewport` retains only the latest geometry, so every transition scans all stable entries and wraps all visible descriptions again.

## Scope

Only the Dashboard Custom historical Ranking viewport geometry cache changes. This work does not change:

- focus interaction or key bindings;
- pane borders, content dimensions, or layout;
- Dashboard query, history, scheduling, or repaint semantics;
- native Ranking, standalone Custom Ranking, Custom Monitor, or text views;
- terminal cell-diff behavior.

A later optimization may avoid clearing unrelated pane render caches on focus-only paints. It is explicitly outside this change because profiling identifies Ranking geometry rebuild as the dominant cost.

## Design

### Geometry snapshots

`RankingViewport` retains a bounded least-recently-used collection of completed geometry snapshots. A snapshot contains only scalar/layout facts:

- a copy of `RankingColumns` widths and `description_width`;
- `starts`;
- `heights`;
- `total_rows`.

It does not contain styled text, rendered rows, hit targets, scrollbar objects, chrome, or copied-marker state.

The existing renderer-owned geometry key remains authoritative. It includes the effective interior width and every current fact that can alter column widths, wrapping, chrome-dependent geometry, description visibility, or spacing. Theme and style remain excluded because they do not alter row geometry.

### Capacity and eviction

Keep the two most recently used geometry snapshots per `RankingViewport`.

Two entries cover the measured focus pattern:

- Dashboard pane at width `W`;
- focused pane at width `W-2`.

A third geometry input evicts the least recently used snapshot. This prevents unbounded memory growth during terminal resizes or repeated density/spacing changes. Each snapshot has O(number of matching entries) integer tuples, so the bound is mandatory.

### Cache lifecycle

- A stable-data rebuild clears all geometry snapshots because starts, heights, columns, and totals belong to the prior entry sequence.
- `RankingViewport.clear()` clears the collection.
- On a geometry-key hit, restore a defensive copy of mutable column widths plus the immutable tuples and total row count. Do not call `measure_ranking_columns()` or `prepare_lines()`.
- On a miss, run the existing exact scalar measurement and line preparation, clamp the offset, then save the completed snapshot.
- Restoring a snapshot retains the current numerical display-line offset and then clamps it against the restored range and current visible height as today.
- Search/source/language/unit changes retain existing reset/data invalidation behavior.

### Ownership and mutation safety

`RankingColumns.width()` mutates its internal dictionary during measurement. Cached snapshots must not share that mutable dictionary with the active renderer. Store copied width mappings and construct a fresh active `RankingColumns` on every restore. `starts` and `heights` are immutable tuples and may be shared.

Window render, copy/link hits, copy-all placement, scrollbar construction, and transient copy markers remain uncached and are rebuilt from the current visible window.

## Correctness requirements

- The first transition to a new width may perform one scalar full-list geometry build.
- Returning to a previously used width performs zero calls to `measure_ranking_columns()`, `RankingViewport.prepare_lines()`, description wrapping, or full-list formatting.
- Re-entering the pane after both width variants are warm also performs zero geometry builds.
- Cached and freshly computed geometry produce identical content, total rows, scroll clamp, scrollbar, and hit coordinates.
- Data/search/language/unit replacement cannot restore stale geometry.
- Capacity never exceeds two snapshots.

## Validation

Add deterministic renderer tests that:

1. Warm width `W`, render width `W-2`, then alternate between both while monkeypatching measurement and `prepare_lines()` to fail; assert both widths restore successfully.
2. Use a large Ranking with descriptions, comparison columns, non-compact spacing, and a nonzero offset; compare output, scrollbar, and copy/link hits before and after restoration.
3. Assert stable-data changes clear cached snapshots and require fresh geometry.
4. Assert three distinct geometry keys retain only the two most recently used snapshots and evict the oldest.
5. Verify offset retention and clamp after restoration at different pane heights.
6. Run the existing Dashboard focus/exit path through its test fixture and assert `prepare_lines()` is called at most once for each width, not once per transition.

Run focused Custom Ranking, Dashboard interaction, scrollbar, and pane repaint tests; run Ruff and whitespace checks; then run the full suite and compare against the established six-test baseline.
