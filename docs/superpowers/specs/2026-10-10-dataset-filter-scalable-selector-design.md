# Dataset Filter Scalable Selector Design

**Date:** 2026-10-10

## Goal

Make the interactive Dataset (Custom-command) filter selector practical for filters with many options, without changing the native ccusage filter selector.

## Scope

This change applies only to `src/ccusage_viz/custom_filter_draft.py`, which backs Dataset/Custom-command filter editing in standalone Custom Monitor and Dashboard Custom panes. The native selector in `filter_draft.py` is explicitly out of scope.

The selector will add local option search, selection and result counts, a current-tab clear command, independently scrollable long option lists, and a one-to-three-column option layout.

## Interaction

### Search

- `/` enters a local search editor for the active Dataset filter tab.
- While editing, printable input and paste append to the query and Backspace removes one character. The list redraws immediately after each change.
- Matching is a literal, case-insensitive (`casefold()`) substring search over the localized visible option label of the active tab.
- Enter leaves search editing active state off but preserves a non-empty query and its filtered list.
- Escape during search clears the query and leaves search editing. Escape while not editing cancels the whole filter draft, preserving existing cancel semantics.
- Switching filter tabs clears the active search query and returns focus/scroll to the beginning of the newly selected tab. Existing selected values in every tab are retained.
- If no option matches, show a localized empty-result message rather than an empty, unexplained list.

### Counts

The body below the tab row includes localized counts for the active tab:

- With no query: selected count and total displayed-option count, e.g. `Selected 3 / 120`.
- With a query: selected count, matching count, and total displayed-option count, e.g. `Selected 3 / Matching 8 / 120`.

The selected count is the number of selected visible Dataset option IDs for the active filter. The total and match counts use the de-duplicated `_display_options()` list, matching what the user can select.

### Selection and clearing

- Space keeps its existing behavior: toggle the focused option.
- Lowercase `c` clears every selected option in the active filter tab only. It does not touch selections in other Dataset filter tabs.
- Enter applies the draft and Esc outside search cancels it, as before.

### Columns and navigation

- The selector starts at one column.
- Uppercase `C` cycles columns `1 → 2 → 3 → 1`.
- Options are distributed in row-major order across equal-width columns. Each option appears exactly once.
- `j`/Down and `k`/Up move vertically within the current visual column. At an incomplete final row, movement clamps to the existing item in the target column rather than selecting a nonexistent cell.
- Existing `h`/Left and `l`/Right/Tab continue to switch Dataset filter tabs; they do not move between option columns.
- Changing query, tab, or column count normalizes the focused option index to the available result set and resets the viewport to show it.

### Scrolling

- The editor receives the host-provided body height in addition to width. The host continues to reserve terminal chrome as it does today.
- The option grid renders only the rows that fit below its fixed tab, search, count, and empty-state chrome.
- A viewport row offset is maintained for the active result grid. When `j`/`k` moves focus outside the visible row range, the offset advances or retreats so the focused row is visible. The render includes localized/portable continuation indicators when rows exist above and/or below the viewport.
- If the terminal leaves no room for an option row, safely render fixed chrome and no option rows; navigation and selection remain valid internally.

## Architecture

Extend `CustomFilterDraft` with ephemeral editor state:

- search query and search-editing flag;
- one-based column count constrained to 1–3;
- focused option identity/index for the current filtered display list; and
- grid viewport row offset.

Keep filter selection values in the existing immutable `CustomFilters` shape so application and query behavior remain unchanged. Add focused pure helpers in `custom_filter_draft.py` for localized searchable results, count derivation, row-major grid geometry, focus movement, viewport normalization, and body rendering. The existing `run_custom_filter_editor()` remains the entry point, with an added height argument supplied by existing standalone and Dashboard filter-editor paint wrappers.

Search uses the same user-facing semantics as Ranking search (slash initiation, `casefold()` literal matching, immediate local redraw, Enter retention, Escape clearing), but remains wholly local to the modal filter draft. It does not submit a Dataset query or mutate accepted component configuration until Enter applies the draft.

Add localized status strings in both `locales/en.py` and `locales/zh.py` for filter search, counts, no matches, scroll continuation, and expanded controls.

## Error Handling and Compatibility

- Empty filters and tabs with zero declared options remain safe and retain their existing unavailable behavior.
- Duplicate bilingual labels remain de-duplicated by `_display_options()` before filtering, counting, layout, and selection.
- Unknown/previously selected option IDs remain stored in the draft as today, but are not counted as selectable displayed options.
- `Ctrl-C` continues to raise `KeyboardInterrupt`.
- Existing native filter keyboard behavior and all Dataset query/filter wire formats remain unchanged.

## Testing

Add focused `tests/test_custom_filter_draft.py` coverage for:

1. localized, case-insensitive search; Enter persistence; Escape search clearing; and no-result rendering;
2. localized selected/total and selected/matching/total counts using de-duplicated options;
3. lowercase `c` clearing only the active tab;
4. `C` cycling through one, two, three, then one column and row-major item placement;
5. vertical movement in multi-column grids, including incomplete final rows;
6. viewport offset and continuation indicators after focus moves beyond a one-screen list;
7. existing selection, localization, duplicate-label, apply, and cancel behavior.

Run the focused test module and the broader TUI/custom-filter test selection after implementation.

## Acceptance Criteria

In a Dataset filter with more options than can fit on screen, users can search visible localized labels, see selected/matching/total counts, clear just the active tab with `c`, move through a visibly scrolling list, and cycle compact one-, two-, and three-column layouts with `C`. Applying remains explicit through Enter, cancellation leaves accepted filters intact, and native ccusage filters are unaffected.
