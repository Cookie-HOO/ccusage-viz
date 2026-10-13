# Ranking List Label-Priority Design

## Goal

Make historical Ranking `list` style a sparse, left-aligned list that maximizes visible label text. Apply the behavior consistently to native and Custom Dataset rankings, including grouped Custom rankings.

## Scope

- `list` only; bar/dot/dots styles retain existing comparison and copy behavior.
- Historical native and Custom Dataset Ranking renderers.
- Both ordinary and grouped Custom Ranking viewport paths.

## Rendering behavior

For `list` rows:

1. Keep the rank and current value so the result remains a Ranking.
2. Remove row copy affordances (`⊞` / `✓`), project-link marker space, and Custom copy hit targets.
3. Remove rank movement, refresh/activity, and value-movement indicators.
4. Do not center rows; begin the rank column at the pane’s left edge.
5. Exclude comparison columns (value delta, rank delta, and percentage) from list rows and headers, even at detailed density.
6. Allocate all reclaimed width to the label, bounded only by the available row width. Labels truncate only when they cannot fit beside rank and current value.
7. Suppress Custom Ranking’s copy-all control in list mode.

Headings and search/count chrome retain their existing behavior. Descriptions continue to follow existing density rules.

## Architecture

Centralize the list-specific layout and marker suppression in `render_historical_ranking()` so native Ranking and ordinary Custom Ranking share it. Ensure `formatted_label()` does not append copy or link markers in list style. The list branch bypasses comparison-grid calculation and builds a left-aligned `rank label value` row from the complete width budget.

In grouped Custom Rankings, make group headings use the same list priorities: omit copy/link embellishments and comparison fields, widening group labels. Do not register per-row copy hits or copy-all hits when the active style is `list`.

Viewport caches must include any style-dependent geometry they already need so switching between list and a graphical style cannot reuse incompatible measurements.

## Validation

Add focused renderer tests covering native, ordinary Custom, and grouped Custom list output at wide and constrained widths. Assert labels expand beyond the former shared label cap, output has no leading centering padding, contains no copy or movement markers, and omits comparison columns/copy-all controls. Retain regression tests that verify non-list styles preserve their existing markers and interactions.
