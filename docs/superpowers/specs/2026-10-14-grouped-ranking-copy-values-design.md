# Grouped Ranking Copy Values

**Date:** 2026-10-14
**Status:** User approved

## Scope

Fix Custom grouped Ranking clipboard actions so their payload contains the same value facts displayed in the TUI. This applies to both an individual group/item copy and the fixed copy-all action. Flat Ranking behavior, query behavior, ordering, search filtering, and clipboard transport remain unchanged.

## Presentation and payload

The existing grouped viewport already prepares localized, display-ready group facts (`display`, `comparison_display`, `share`) and item facts through `RankingPresentationEntry`. Clipboard formatting will add these facts as plain-text fields in TUI display order:

1. label;
2. current displayed value;
3. displayed comparison value, only when the comparison column is visible;
4. displayed percentage, only when the percentage column is visible and the entry/group has a share;
5. copyable description, when present;
6. project link, when present.

A group copy includes its group heading fields followed by its currently visible/matching items. An item copy includes the group label followed by that item fields. Copy-all preserves the current filtered group/item order and separates records with a blank line, including empty matching groups exactly as current behavior does. Synthetic `Other` handling remains unchanged.

Values are sourced from the prepared presentation model rather than rendered terminal rows. Therefore clipboard contents have no alignment padding, ANSI escapes, copy icons, or layout-dependent truncation.

## Architecture

`grouped_ranking_viewport.py` will centralize group and entry clipboard field construction behind helpers that receive the active display policy. The renderer derives that policy from its existing comparison visibility calculation and `projection.show_percentage`, then stores/uses it for all grouped copy paths. The same helpers serve individual-copy and copy-all payloads, preventing divergence.

No protocol, projection, Dashboard mouse routing, or clipboard-command changes are required. The Dashboard continues to call `GroupedRankingViewport.clipboard_text()` and `clipboard_all_text()`.

## Error handling

Clipboard failures and success feedback continue to use the existing Dashboard behavior. If an optional display, comparison, share, description, or link is absent or not currently visible, it is omitted without producing blank fields. Existing search/no-match and inactive viewport reset behavior remains intact.

## Verification

Add focused grouped viewport regression coverage that asserts individual item/group and copy-all payloads include localized current values, visible comparisons, and visible shares. Assert comparison and percentage facts disappear when their TUI columns are suppressed, while descriptions, links, ordering, filtering, empty groups, and `Other` behavior remain covered by existing tests. Run the targeted grouped ranking viewport and Dashboard copy tests.
