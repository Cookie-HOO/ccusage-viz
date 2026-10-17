# Custom Filter Wrapped Tabs Design

**Date:** 2026-10-13

## Goal

Make Dataset Custom filter tabs wrap cleanly at the terminal edge, retain correct mouse hit testing for every rendered tab row, and remove stale chart content when entering the filter editor.

## Scope

Only the Custom/Dataset filter editor changes. Native `filter_draft.py` filtering and filter semantics remain unchanged.

## Layout model

`custom_filter_draft.py` will own one pure tab-layout helper. Given choices, accepted filters, language, active index, and terminal width, it produces unstyled tab records containing:

- filter index;
- complete count-inclusive tab text (`Label n/m`, with brackets for the active tab);
- one-based terminal x start and exclusive x end;
- one-based terminal y row.

Tabs are added in declaration order. A tab is never split between rows. Before a tab is added, its preceding ` · ` separator and its display width are considered; if they do not fit, the tab starts at column 1 of the following row. Separators belong to neither adjacent tab, including at a line boundary. A tab wider than the available terminal width uses the existing width clipping only as an unavoidable narrow-terminal fallback.

The renderer decorates and emits this shared layout. Mouse hit testing consumes exactly the same records and matches only the record's `(x, y)` bounds. Therefore clicks on a separator, empty trailing cells, or another row do not select a tab.

## Editor vertical geometry

The existing fixed two-row chrome assumption becomes dynamic: tab-row count plus the optional search row plus the selection/search status row. The option viewport renderer, normalization/clamping, continuation indicators, and option mouse hit testing all consume this same derived chrome-row count. This keeps visible option placement and its one-based click coordinates aligned after tabs wrap.

## Repaint lifecycle

Custom filter editor transitions form a modal rendering boundary in both directions:

- The first filter-editor frame is fully repainted rather than diffed against the preceding chart/adjustment frame.
- The first caller frame after the editor returns is also fully repainted, whether the editor returns by Apply, Cancel, or idle timeout.
- Consecutive frames while the editor remains open may use normal incremental updates.

This prevents residual text from the larger chart frame appearing in the shorter filter modal and prevents filter-frame content from overlapping the restored Dashboard or standalone browsing frame.

## Tests

Extend `tests/test_custom_filter_draft.py` with coverage for:

- wrapping tabs by terminal display width without splitting a tab;
- display-width-safe Chinese/localized tab labels;
- click selection for tabs on first and later wrapped rows;
- separators and unoccupied coordinates producing no tab hit;
- option click coordinates and viewport rows shifting correctly beneath multi-row tabs.

Add focused host-level tests as appropriate to assert a forced repaint for the filter editor's first frame and the caller's first restored frame after Apply, Cancel, and idle timeout, while preserving normal incremental behavior for subsequent frames.

## Non-goals

- No horizontal tab scrolling.
- No change to filter value serialization, selection modes, search behavior, or explicit Apply/Cancel behavior.
- No palette or style redesign.
