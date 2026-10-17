# Dashboard Dataset Chooser Empty-State Design

## Goal

Prevent the Dashboard Dataset chooser from crashing when no ready dataset source or no selectable V2 metric exists.

## Scope

The Dashboard's nonblocking `DashboardDatasetModalState` flow in `src/ccusage_viz/tui.py` only.

## Behavior

### Empty ready-source list

When the chooser reaches the `source` stage with `modal.statuses == ()`, it must render the existing localized `status.datasets_empty` message instead of normalizing the selection index with `len(entries)`. `j`, `k`, Enter, and contextual help must not index the empty list. Escape returns to the pane chooser as it does today.

### Empty V2 metric list

A V2 descriptor whose metric chooser has no selectable metric rows must not enter the `metric` stage. It remains in the source chooser and displays a localized unavailable error. This prevents both the initial `selectable[0]` access and later modulo navigation by zero.

### Existing choices

Nonempty source, metric, and chart-kind lists retain their current selection, navigation, submission, layout, and localization behavior. No new translation keys are required: source empty state uses `status.datasets_empty`; metric unavailability uses the existing `status.dataset_unavailable` text.

## Testing

Add Dashboard integration regressions that drive the existing keyboard path to an empty source list and to a registered V2 descriptor with no metrics. Each test verifies `run_tui()` exits cleanly after Ctrl-C and captures the expected localized empty/unavailable text. Existing metric-selection behavior remains covered by the current Dashboard metric modal test.
