# Custom Ranking presentation-window rendering

**Date:** 2026-10-12  
**Status:** Approved design; awaiting specification review

## Goal

When a Dashboard Custom historical Ranking user changes style, density, or theme, update only the fixed chrome and the visible Ranking window rather than preparing or formatting the complete matching list. Preserve the current display-line scroll offset unless the new layout makes it out of range, in which case clamp it.

## Scope

This applies only to Dashboard Custom historical Ranking panes rendered through `render_custom_ranking_viewport()`. It preserves existing pointer scrolling, scrollbar behavior, copy/link hit testing, copy-all, search, and Dashboard pane repaint isolation.

Native Rankings, Custom Monitor, standalone views, query scheduling, persisted options, and keyboard bindings are out of scope.

## Design

### Cache layers

`RankingViewport` separates its current mixed cache into the following conceptual layers:

1. **Stable data layer**
   - Filtered `RankingPresentationEntry` values, `by_id`, totals, maximum, and rank-comparison facts.
   - Rebuilt only when the projection series, search query, or language-dependent entry text changes.
   - It remains independent of theme, style, and density.

2. **Geometry/layout layer**
   - The display-line indexing necessary to locate the current window and calculate scroll ranges.
   - It must not retain a formatted full-list string or ANSI-rendered entry text.
   - Width, descriptions visibility, item spacing, and other properties that truly change wrapping or row height invalidate only the required geometry facts.

3. **Presentation-window layer**
   - Fixed chrome and the entries intersecting the current visible display-line range.
   - It is rendered with the current theme, style, density, copy state, and viewport offset.
   - It supplies current visible copy/link hit geometry and scrollbar metadata.

### Presentation changes

- **Theme changes** do not rebuild the stable data or geometry layers. They format only chrome and the visible entries with the newly selected palette.
- **Style and density changes** must not recreate or format all matching entries. They recompute only the geometry facts needed to render the current display-line window, then format that visible window.
- The old `viewport.offset` is retained across all three changes. Once the new visible row count and total row range are known, `clamp()` enforces the legal range. No presentation change resets the Ranking to the top.
- If a density change hides descriptions or otherwise changes the display-line composition, preserving position means preserving the numerical display-line offset, not attempting to anchor a particular entry at the same screen row.

### Conservative invalidation

The implementation may use the existing full preparation path when correctness requires it:

- A new projection series, changed search query, changed localized text/language, or source replacement rebuilds the stable data layer.
- Width changes may rebuild columns, wrapping, and geometry because they affect visible line layout.
- Changes that alter descriptions visibility or spacing may update the geometry layer, but must not invoke full-list presentation formatting.
- Pending, empty, non-Ranking, and text views retain their existing lifecycle behavior and clear/hide viewport-local interactive metadata as today.

## Correctness requirements

- The current rendered output must match the existing Ranking presentation rules for the selected style, density, and theme.
- Scrollbar visibility, thumb position, and range derive from the corresponding current layout.
- Copy, project-link, and copy-all hit targets are calculated from only the newly rendered visible window and must never overlap the scrollbar gutter.
- Offset remains stable when valid; it clamps only after a layout/range change makes it invalid.
- No style, density, or theme adjustment starts a query, refresh, or data transformation.

## Validation

Add deterministic tests around a large Custom Ranking dataset that prove:

1. Theme changes do not traverse or format offscreen entries, and retain the viewport offset.
2. Style and density changes format only the window/chrome, retain offset when legal, and clamp it when the new range requires it.
3. Visible content, descriptions, spacing, scrollbars, copy-all, copy, and project-link targets remain correct after each presentation change.
4. Data, search, language, and width changes still invalidate enough cached facts to give correct content and geometry.
5. Existing Custom Ranking scrolling, Dashboard interaction, and renderer regressions continue to pass.

Run focused Ranking tests, Ruff, whitespace checks, and the full suite; compare any full-suite failures with the known baseline.
