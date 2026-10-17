# Dashboard Dataset Hot Probe and Metric Heading Scroll Design

## Goal

Make the Dashboard Dataset chooser reflect a Dataset command's current Metric declaration when the user selects it, and correct the V2 Metric chooser's first-group upward scroll behavior.

## Scope

Only the nonblocking Dashboard `DashboardDatasetModalState` path in `src/ccusage_viz/tui.py` and its Dashboard/Custom TUI regression coverage.

## Decisions and alternatives

### Dataset descriptor freshness

1. **Reuse the descriptor captured when the chooser opened.** Lowest cost, but newly added Metrics are invisible until the Dashboard is reopened or a separate manager refresh occurs.
2. **Refresh every ready Dataset as the chooser opens.** Current data, but wastes work and delays opening even when the user selects only one Dataset.
3. **Probe only the Dataset confirmed by Enter (selected).** The Dashboard stays responsive and the selected Dataset's Metric chooser is current. **Chosen.**

### First group heading behavior

1. **Sticky group headers.** Gives persistent context, but changes the chooser's presentation and was not requested.
2. **Treat headers as ordinary scroll rows, with a one-step reveal before wrap.** When the selected first Metric has hidden leading rows, Up reveals them without changing selection; once visible, the next Up wraps to the last Metric. **Chosen.**
3. **Always wrap selection at the first Metric.** Preserves old navigation but keeps the heading inaccessible through the expected single extra Up action.

## Dataset hot probe

When the user presses Enter on a ready Dataset source in the Dashboard chooser:

1. The modal enters a dedicated pending state and submits a background operation that probes only the selected registration/source.
2. The target pane continues to render normally; the modal shows a localized loading notice and ignores duplicate selection input while pending. Escape may return to the source chooser and must prevent a stale result from changing it.
3. On success, validate that the probe reports the selected Dataset ID. Replace that Dataset entry's in-memory descriptor/status snapshot with the fresh descriptor; persist the snapshot through the existing Dataset service behavior where appropriate.
4. Build the Metric rows, default Metric selection, descriptions, supported chart kinds, and defaults from this fresh descriptor. Consequently, Metrics added or removed externally become available immediately after reselecting the Dataset.
5. On Probe failure, return to the source stage with the selected item retained, preserve the previous stored descriptor, and show the formatted Dataset error. Do not transition to the Metric or kind stage.

No automatic refresh is added for unselected sources, and existing V1 source behavior remains compatible: a successful fresh V1 probe continues directly to chart-kind selection.

## First group-heading reveal

Metric rows remain the existing ordinary scrollable rows; headings are not sticky.

For `k`/Up while the selected Metric is the first selectable Metric:

- If its leading group heading or other preceding presentation rows are above the viewport, decrement only `modal.offset` enough to reveal the immediately preceding row. Keep the selected Metric unchanged.
- If all leading rows are already visible, retain the existing wrap behavior and select the final selectable Metric.
- At all other selected Metrics, retain the existing previous-selectable-Metric behavior and normal viewport projection.

Thus, when opening on the first Metric with its heading clipped, first Up reveals the heading and second Up wraps to the final Metric. If the heading is already visible initially, first Up wraps immediately.

## Error handling

- The hot-probe transition guards absent/empty selectable Metric rows exactly as the current source-to-Metric transition does.
- A mismatched Dataset ID and protocol/command failure are handled as Dataset-probe errors; no stale asynchronous completion may mutate a modal that was cancelled or moved to another state.
- Existing empty ready-source and empty Metric protections continue to apply.

## Testing

Add regressions that verify:

1. Selecting a registered V2 Dataset runs a fresh Probe and renders a Metric that was absent in the descriptor captured at chooser open.
2. A fresh-Probe failure stays in the source chooser, retains the old selection, and exposes the error without entering the Metric chooser.
3. With a constrained Metric viewport where the first group heading is above the visible first Metric, first Up changes only the viewport to reveal that heading; second Up selects/wraps to the final Metric.
4. When the first group heading is initially visible, first Up immediately wraps to the final selectable Metric.
5. Existing Dataset chooser, V1 Dataset, grouped Metrics, and empty-list regressions remain green.
