# Dashboard Custom Metric Help Design

## Goal

Make Dashboard help describe the focused Pane clearly: show the Custom metric as its own top-level help section above the general controls; keep Pane parameter help meaningful instead of rendering an empty branch; and document the existing same-Group Custom metric switch shortcut.

## Help structure

In Pane adjustment mode, help sections are rendered in this order:

1. **Modes** (unchanged).
2. **Current metric** for an accepted V2 Custom Pane with a resolvable accepted metric. It displays the localized metric title and description. It is independent of the generic controls section, therefore it appears above it.
3. **Controls**, including Mode, Pane parameter adjustment, Pane structure adjustment, and Global common.

The current-metric content is always obtained from the accepted V2 descriptor and accepted configuration. A pending metric-switch request must not alter it. V1 Custom Panes, native Panes, no accepted descriptor, and an unknown accepted metric omit this whole section.

## Pane parameter help

Pane parameter adjustment continues to list chart and animation controls as it does today. For a chart-mode Custom Pane with a V2 current metric that belongs to a declared Metric Group, it additionally displays `m` / `M` for cycling related metrics.

An ungrouped V2 metric and every V1 Custom Pane omit this entry. A grouped metric displays it even if no other same-Group metric supports the current chart kind. This accurately documents the key while preserving feedback for a capability-limited Group.

When a Pane has no actual parameter actions, the branch displays a localized explicit no-parameters message rather than an empty tree node.

## Metric switching and feedback

The existing `m` / `M` behavior remains the single switching implementation:

- `m` selects the next same-Group metric and `M` the previous one, among metrics that support the current chart kind, in descriptor declaration order and with wraparound.
- If fewer than two candidates exist, either key shows the existing localized “no related Metric is available to switch to” notice.
- The feedback uses the Dashboard’s existing transient notice mechanism and expires after three seconds.
- A successful switch remains asynchronous and help continues to describe the accepted metric until the target request is accepted.

No Custom protocol, descriptor fields, request shapes, persistence, or switching normalization rules change.

## Validation

Tests cover:

- Current metric renders as a top-level help section before Controls, localized and accepted-state-only.
- Grouped Custom metric help includes `m` / `M`; ungrouped V2 and V1 Custom help omit it.
- A singleton or kind-incompatible Group still exposes the help entry, and pressing `m` yields the localized notice which expires after three seconds.
- A Pane with no parameters renders the localized no-parameters text.
- Existing V2 switching direction, normalization, pending-state behavior, and non-Custom help behavior remain unchanged.
