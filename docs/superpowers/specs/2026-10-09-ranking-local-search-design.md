# Ranking Local Search Design

**Date:** 2026-10-09

## Goal

Add an immediate, request-free search interaction to Dashboard Ranking panes. It must work consistently for native ccuv Rankings and Custom Dataset historical Rankings.

## Scope

- Applies only to a focused Ranking pane in the interactive Dashboard.
- Search is local to the existing in-memory Ranking model. It never changes a provider query or sends a request.
- Each Ranking pane owns its own ephemeral query. Search state is not persisted in Dashboard presets or undo/redo state.
- Monitor views and non-Ranking chart types are out of scope.

## Interaction

- Press `/` while a Ranking pane is focused to enter its search editor.
- The title remains at the top. Directly below it, render a localized line in the form `Search: <query>` (`搜索：<query>` in Chinese). This line is visible while typing, and remains visible after Enter whenever the query is non-empty.
- In every density except `minimal`, render a second localized auxiliary line beneath the title/search area stating the actual number of currently rendered Ranking entries. It is not the configured Top or Dataset maximum, and updates after local filtering. `minimal` suppresses it; an active search line remains visible even at `minimal` density.
- Printable input, paste, and backspace update the query and redraw immediately.
- Enter leaves editing mode while retaining the query and active filter.
- Escape clears the query and leaves editing mode. The search line then disappears and the unfiltered Ranking returns.
- Existing `+`/`-` Top controls remain available and do not clear search. They retain the query and apply it to the newly available in-memory Ranking entries. Consequently, increasing Top can legitimately create no visible change when no newly included entry matches.

## Matching and Rendering

- Matching is a case-insensitive, literal, contiguous substring match using `casefold()`.
- A row matches when its label or description contains the query.
- Filtering preserves source order and original rank numbers; matches are not re-ranked.
- All matching spans in labels and descriptions receive the active theme highlight colour. Normal description text remains muted/dim.
- Rendering should share filtering and highlighting primitives rather than duplicate native and Custom Dataset behavior.
- If a non-empty query has no matching entries, retain the heading and `Search: <query>` line, then show a localized empty-state message that explicitly says no Ranking entries match the query.

## Architecture

1. Add a small Ranking search state object (query plus editing flag) to query-backed Dashboard pane runtime state.
2. Add pure presentation helpers for casefold substring matching, entry filtering, and ANSI-safe highlighted text construction.
3. Pass the pane query into both native and Custom historical Ranking rendering paths. The shared historical Ranking presentation renderer owns Custom Dataset filtering/highlighting; native Ranking uses the same helper behavior at its native presentation boundary.
4. The Dashboard event loop captures `/` only for focused Ranking panes, routes editor keystrokes before normal pane adjustments, and calls `paint()` after each local change. Search transitions do not call `refresh()`.
5. Top commands stay on their current configuration/query path. They must leave the pane's search state untouched.
6. When creating a Dataset Ranking pane, initialize its period from the Dataset metric/capability default rather than the native `14d` fallback. Once created, explicit user period changes remain authoritative across refreshes, Top changes, and search.

## Edge Cases

- An empty editor query does not filter and has no visible search line.
- Search remains active with a query even if its source momentarily has no entries.
- Density behavior is intentionally distinct: `minimal` shows only required Ranking chrome and rows; `compact` adds the visible-entry count but suppresses Dataset descriptions; `normal` adds the count and preserves current normal summary/comparison behavior; `detailed` is `normal` with Dataset descriptions expanded by default.
- Description-only matches remain included even if descriptions are currently collapsed; when rendered, matching description spans are highlighted.
- Terminal ANSI styling must not alter display-width calculations, truncation, or wrapping.
- Switching/replacing a pane creates fresh pane-local search state; an existing pane retains it across ordinary redraws and Top adjustments.

## Testing

- Unit-test case-insensitive literal matching for label and description, including multiple occurrences.
- Verify renderer output filters without re-ranking, highlights labels/descriptions, emits the localized search line beneath headings, and gives a localized no-results message.
- Cover native and Custom Dataset Ranking paths.
- Exercise `/`, type/paste, backspace, Enter persistence, Escape clearing, and assert those paths do not invoke refresh/query submission.
- Verify `+`/`-` retains the query and that no additional matching row after a Top increase is treated as valid behavior.
- Verify the entry-count line reflects actual rendered entries, honors density visibility, and updates after filtering.
- Verify a newly created Dataset Ranking pane adopts its declared default period, while a manually changed period is retained.
