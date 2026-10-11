# Custom Ranking Copy All

**Date:** 2026-10-12
**Status:** User approved

## Scope

Add one copy-all action to the top of Dashboard Custom historical Ranking panes. Do not change native Ranking, Custom Monitor, standalone charts, query behavior, persisted configuration, scrolling, per-entry copying, or project-link opening.

## Presentation

Show a `⊞` action in the fixed Ranking chrome above the entries, using the same visual language as each existing per-entry copy action. Keep it visible while the Ranking has at least one concrete entry matching the active local search/filter. On successful copy, replace it with `✓` for the same short-lived feedback period used by per-entry copying, then restore `⊞`.

The action remains fixed while the entry viewport scrolls. It must not consume an entry row or affect Ranking column alignment. Hide it for empty results, pending-only/error/non-chart views, and when the active search has no matches.

## Copied content

Copy every concrete entry in the current displayed result set, including entries outside the visible scroll window. “Displayed result set” means the current accepted Custom Ranking after local search/filtering. Exclude the synthetic `Other` entry.

Format each entry exactly like existing single-entry copying:

1. localized label;
2. copyable plain-text description, when present;
3. project link, when present.

Join non-empty fields with newlines and separate entries with one blank line. Preserve Ranking order.

Example:

```text
Project A
Description A
https://example.com/a

Project B
Description B
https://example.com/b
```

## Interaction and state

Only a primary-button click on the rendered copy-all marker invokes copying. Hit testing runs before pane focus/double-click handling, so it does not change focus, enter adjustment mode, copy one row, or open a project link. Use the existing clipboard adapter and global copy feedback for success/failure.

Store copy-all success as transient pane-local display state separate from `copied_ranking_entry_id`; copying all must not replace all row markers with checks. Search changes, data replacement, non-Ranking views, and expiration naturally clear or hide the fixed success marker without data/query work.

## Architecture

The Custom Ranking renderer owns the fixed marker placement and returns its pane-local hit coordinate alongside existing viewport metadata. The Dashboard host translates clicks using existing pane/frame geometry. A pure clipboard formatter reuses the existing single-entry formatter for each matched entry, ensuring both paths stay consistent.

For virtualized Rankings, use prepared filtered entries rather than only visible hit rows or a second full projection scan. For the non-virtualized fallback, use the existing `_custom_ranking_copyable_entries()` result. Neither path may initiate queries or format only the current visible window.

## Verification

Test fixed marker rendering and success state, zero-match/empty hiding, scrolling stability, search-filtered copy including off-screen entries, order, `Other` exclusion, localized labels/descriptions, optional links, blank-line separation, and single-entry formatter parity. Dashboard tests cover framed and frameless coordinates, no focus/double-click/per-row/link leakage, clipboard failure feedback, expiry, and no lifecycle requests. Retain existing per-entry copy, wheel scrolling, and bounded virtualized-rendering tests.
