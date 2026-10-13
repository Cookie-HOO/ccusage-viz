# Remove Ranking Movement Indicators Design

**Date:** 2026-10-13

## Goal

Keep historical Ranking charts and Monitor Ranking/List presentations, while removing all rank-position movement information. Monitor rows continue to show the activity indicator and the value-change arrow.

## Scope

- Retain every Ranking chart type, query capability, and ordering behavior.
- Remove rank delta tracking and display from historical Ranking and Monitor Ranking/List render paths.
- Retain historical previous-value comparisons (`vs prior`) because they describe value change rather than ranking-position movement.
- Retain Monitor activity markers and value-delta arrows.
- Remove now-unused rank-delta state, refresh tracking, renderer context plumbing, and tests.

## Design

### Rendering

Historical Ranking rows will no longer render an in-session rank movement arrow. Their table layout will no longer reserve or render the `Rank Δ` column. Existing prior-period value comparisons, including `New` where a prior value is absent, remain unchanged.

Monitor Ranking and List rows will begin directly with their ordinal/list content rather than a rank-movement marker. Their activity marker remains visible when a monitored value changes, and the value-delta arrow remains at the value end. Pending rows continue to suppress dynamic indicators.

### State and data flow

`RenderContext` and presentation-surface contracts will carry only numeric value deltas. Monitor components will stop producing rank deltas. Historical TUI panes and standalone watch rendering will stop retaining previous ranks or calculating rank movement on accepted refreshes.

The underlying sort order remains unchanged: rank is still a current-position label, but no previous-position comparison is calculated or surfaced.

### Tests

Update rendering and host tests to assert that rank movement arrows and `Rank Δ` are absent, while Monitor activity dots and value arrows remain present. Remove rank-tracker-specific tests and expectations. Run focused render, monitor, watch, and dashboard tests, followed by the relevant full suite.

## Alternatives considered

1. **Hide only the visual arrows:** minimal change, but retains dead state and calculations. Rejected.
2. **Keep rank delta as optional API data:** useful only for an unplanned consumer and creates unnecessary contracts. Rejected.
3. **Remove the complete rank-delta pipeline:** removes misleading/noisy UI and unused complexity while preserving all valuable ranking and value-change behavior. Selected.

## Non-goals

- Removing Ranking chart types or their data-source capabilities.
- Changing Top N, ranking sort order, searching, scrolling, copy/link interactions, or historical value-comparison behavior.
- Changing monitor sampling, grouping, or numerical delta calculation.
