# Custom Pane Response Warnings Design

**Date:** 2026-10-12

## Problem

A custom Dataset may successfully return chart facts together with protocol `warnings`. GitHub Tools does this for a `1d` Star-growth/heat query when only two days of snapshot coverage are available. The Dashboard currently records these warnings only in the custom log (opened with `L`) and deduplicates them per Dataset/code. Consequently, the chart is visible but its effective data coverage is not.

Existing empty/error chart messages are renderer notices and are not a substitute for successful-response warnings.

## Scope

Render successful chart-response warnings in the owning custom historical Dashboard pane. Preserve the existing custom log as a diagnostic history; do not change Dataset protocol parsing, warning generation, or the global Dashboard layout.

## Design

### Ownership and lifecycle

`CustomHistoricalComponent` owns warnings with the accepted chart response:

- On a successfully accepted primary response, persist that response's warnings alongside the accepted facts.
- A response with no warnings clears warnings from the previously accepted response.
- A failed, stale, comparison-only, or unaccepted response must not alter displayed warnings.
- Switching a metric or period continues to show warnings belonging to the currently accepted chart until replacement data is accepted, matching the component's existing retained-facts behavior.

Warnings are exposed from the component as an immutable pane-specific view. They are not kept in a Dashboard-level `pane -> warnings` side table.

### Rendering

The custom pane render path converts the component's accepted warnings into local pane notices.

- Render notices below the chart body and above the pane's own control/help row.
- Render all warnings in wire order.
- Use the localized protocol text selected by the active UI language.
- Keep the visual warning affordance used for existing notices (for example `!`/warning styling), without depending on emoji availability.
- The notices are constrained by the pane's layout, never appended to the Dashboard-wide footer and never displayed in sibling panes.

### Logging and deduplication

The current custom log recording remains unchanged. Its Dataset/code deduplication remains diagnostic-only and does not control whether the pane renders the current response warning.

## Tests

Add focused component tests proving primary acceptance exposes warnings and that a later warning-free accepted response clears them. Add Dashboard rendering coverage proving a successful custom chart with facts and a warning shows the localized warning in its pane-local notices, and that it does not become a Dashboard-global message.

## Non-goals

- Altering GitHub Tools' `snapshot_history_irregular` warning calculation.
- Changing warning display for probes, summaries, or monitor observations.
- Introducing dismissal, persistence, or a notification center.
