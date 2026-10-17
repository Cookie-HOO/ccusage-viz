# Dataset Filter Click Feedback Design

**Date:** 2026-10-12

## Goal

Make Dataset custom-filter selection mode visible at the option level and make filter-dimension tab mouse hit testing exactly match the text rendered by the editor.

## Scope

This is a focused follow-up to `2026-10-12-dataset-filter-single-select-design.md`. It affects only `src/ccusage_viz/custom_filter_draft.py` and its tests. Native `ccusage` filter editing is out of scope.

## Design

### Option selection marks

The filter mode determines the option selection mark:

- `multi_select` keeps checkbox marks: `[ ]` and `[x]`.
- `single_select` uses radio marks: `( )` and `(●)`.

The focused-option prefix (`›`) and all existing color, search, grid, scrolling, draft, and explicit Apply/Cancel behavior remain unchanged. The differing mark is readable without color and communicates that a single-select option replaces the dimension's previous draft value.

### Dimension tab layout and click targets

The tab row has a single layout helper which produces each tab's plain, un-clipped display segment and its horizontal start/end range. Both rendering and `_filter_index_at()` use that helper.

A segment includes exactly the text shown for that tab: active brackets and the accepted `selected/total` count. The separator (` · `) is not interactive. A click selects a tab only when its terminal x coordinate is inside that segment's display-width interval on the tab row. ANSI styling is applied only after layout, so it cannot affect coordinates.

The tab row remains the first body row (one-based y coordinate 1). Search/status rows and option-grid continuation rows do not participate in tab hit testing. This preserves the editor coordinate contract while preventing the added count text from causing stale hit ranges.

## Tests

Add focused tests that verify:

1. single-select and multi-select option rows render distinct radio/checkbox marks, including selected states;
2. clicks in an inactive tab's rendered count select that tab; and
3. clicks in a separator do not select either neighboring tab.

Run `pytest tests/test_custom_filter_draft.py -v`, then the existing custom TUI tests that cover editor integration.
