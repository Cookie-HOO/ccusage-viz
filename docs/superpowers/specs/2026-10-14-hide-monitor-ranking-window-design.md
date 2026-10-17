# Hide Monitor Ranking Window Display

## Goal

Avoid displaying Monitor's rolling observation window for the non-temporal ranking presentations: `ranking`, `ranking-dot`, and `list`. The window remains visible whenever the user switches to a time-series Monitor style.

## Approach

Use the existing `is_monitor_ranking_style()` presentation predicate at the Monitor status-rendering boundary. For these three styles, omit the `WINDOW {window}` value from the quick-adjustment status text and omit its `w window` keyboard hint. Keep the underlying `window_seconds` configuration unchanged so sampling, query semantics, and switching back to a time-series style continue to work without loss.

The chart heading already describes the ranking as a current value and does not interpolate a window value, so it requires no change.

## Behavior

- `monitor --style ranking`, `ranking-dot`, and `list` do not show a window in quick adjustment information and do not advertise the window shortcut.
- A time-series style such as `bars`, `line`, `points`, or `line-points` continues to show the configured window and window shortcut.
- `cumulative-bars` retains its separate day/granularity controls.
- Changing from a ranking/list style to a time-series style immediately restores the existing configured window in the UI.

## Testing

Extend Monitor UI rendering tests to assert that ranking styles omit the window control/value and a time-series Monitor style retains it. Existing option tests continue to cover the style predicate.
