# Preserve Top on Group Switch Design

**Status:** Approved

## Goal

Make `b` / `B` grouping changes preserve the current Top selection for every built-in and Custom chart. Group switching owns only the grouping and any required style compatibility adjustment; it must not create, clear, or restore a Top value.

## Scope

- Built-in Timeline, Stack, Ranking, and Monitor adjustments.
- Custom historical charts and Custom Monitor grouping adjustments in standalone and Dashboard hosts, through their shared grouping helper.
- Regression tests for both directions of grouping cycling.

No CLI default, Dataset descriptor-default, metric-switch fallback, Top increment/decrement, query, rendering, or persistence behavior changes are included.

## Behavior

For each `b` or `B` operation:

1. Compute the next permitted `by` / `group_by` as today.
2. Retain the exact existing `top` value.
   - `None` remains `None`.
   - Any positive integer remains the same integer.
3. Retain the existing presentation style when compatible with the new grouping; otherwise choose the existing compatibility fallback style.
4. Do not use chart-kind host defaults (`3` or `10`) and do not clear Top when changing to an ungrouped Timeline state.

This applies symmetrically to forward (`b`) and reverse (`B`) cycling.

## Boundaries and data flow

- `options.adjust_chart()` is the single adjustment path for built-in charts in standalone and Dashboard contexts. Its `b/B` branch will replace only `by` and possibly `presentation`, carrying `chart.top` unchanged.
- `tui._cycle_custom_grouping()` is the shared Custom grouping path used by standalone Custom adjustment and Dashboard Custom panes. It will replace only `group_by` and possibly `presentation`, carrying `config.top` unchanged.
- The Custom Monitor early return is covered by the same invariant: it changes `group_by` only and retains `config.top`.

## Error handling

Existing no-op behavior remains unchanged when no grouping is available or cycling cannot select a different grouping. Existing style compatibility handling remains unchanged. Since the operation does not validate or synthesize a Top value, it introduces no new errors.

## Tests

Add focused unit tests that establish:

- Built-in Timeline preserves `None` when `b` enters a grouping and when later cycling reaches `None` again.
- Built-in charts preserve a concrete Top value across grouping cycles, including reverse cycling.
- Custom historical grouping preserves both `None` and a concrete Top value across forward and reverse cycles, including the transition to/from an ungrouped choice where supported.
- Custom Monitor grouping preserves both states as well.
- Existing style compatibility fallback still occurs independently of Top retention.

Run the targeted options and TUI Custom/Dashboard tests, followed by formatting/lint checks for touched files.
