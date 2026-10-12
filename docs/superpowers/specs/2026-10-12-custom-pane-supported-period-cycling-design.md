# Custom Pane Supported Period Cycling

## Goal

Prevent a Custom historical Pane from issuing a period that its selected Metric and chart kind explicitly declare as unsupported. A Dataset that omits `periods` retains the existing dynamic behavior: the Host cycles its generic period list and the Dataset may accept or reject each request.

## Current Problem

The Dataset chooser records `metric_periods` before the chart kind is selected and always derives it from the selected Metric's Ranking capability. A subsequently selected Timeline, Calendar, or Stack Pane can therefore inherit Ranking's period list. Period adjustment then cycles the wrong values and can produce an `unsupported_query` response.

Persisted or already-created panes can also contain stale `metric_periods`, so correcting only Pane creation would not protect those paths.

## Design

### Chart-specific period selection

Introduce a small helper that accepts a V2 Metric descriptor and chart kind and returns that chart capability's ordered `periods` when it is a historical capability. It returns an empty tuple when the chart does not declare periods.

Both Dataset chooser flows will derive `metric_periods` only after the user selects the final chart kind:

- the standalone/synchronous chooser path;
- the Dashboard modal chooser path.

They will no longer cache Ranking periods at Metric-selection time.

### Adjustment authority

When handling `p` or `P` for a live Custom Pane, use the current chart capability's non-empty `periods` as the authoritative cycle list. This protects old presets and panes whose stored `metric_periods` are stale. If the capability does not declare periods, preserve the Pane configuration's current behavior and generic Host cycle.

The ordered declared list controls forward/reverse wrapping. A one-item list leaves the configuration unchanged and shows the existing restricted-period feedback.

### Compatibility

V1 capabilities and V2 capabilities with omitted or empty `periods` remain unrestricted by the Host. No protocol, persistence schema, or Dataset behavior changes are required.

## Error Handling

No unsupported period request should be emitted when a non-empty period list is declared. Existing Dataset error handling remains in place for dynamic compatibility constraints and for Datasets that do not declare periods.

## Tests

Add regression coverage for:

1. selecting a non-Ranking chart whose period list differs from Ranking and verifying the Pane receives the selected chart's periods;
2. Dashboard adjustment preferring the live selected-chart capability over stale stored `metric_periods`;
3. forward and reverse cycling staying within the declared ordered list;
4. an omitted period list retaining generic period cycling.

## Scope

This change only affects period selection for Custom historical panes. It does not alter granularity, grouping, Metric switching, Monitor windows, or protocol validation.
