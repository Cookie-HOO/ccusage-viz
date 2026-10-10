# Ranking Wheel Scroll Design

**Date:** 2026-10-09

## Goal

Make overflowing native and Custom historical Ranking views scroll responsively in both standalone and Dashboard hosts:

- The first terminal wheel report moves exactly one rendered row and redraws immediately.
- Consecutive same-direction reports accelerate through `1 → 2 → 4 → 8 → 12` rows per report.
- A direction change or a pause outside the continuity window resets the next move to one row.
- The application never synthesizes scroll inertia: when the terminal stops delivering wheel reports, position changes and wheel-driven redraws stop immediately.
- Wheel scrolling remains presentation-only and must not trigger Dashboard/provider refresh work.

## Scope

This applies to overflowing chart bodies for:

- standalone native historical Ranking;
- standalone Custom historical Ranking;
- Dashboard native historical Ranking panes; and
- Dashboard Custom historical Ranking panes.

It does not change keyboard scrolling, non-Ranking charts, monitor rankings, click handling, data acquisition, or persisted Dashboard state.

## Input Contract

`InputDecoder` decodes every complete SGR wheel report as a signed unit (`-1` or `1`). `read_event()` dispatches the first report without waiting for a merge window, then consumes any already-buffered consecutive wheel reports into the same immediate wheel batch. The batch preserves each signed unit so acceleration is calculated exactly per physical report.

The first report updates and redraws the viewport immediately. Later reports already available in that same terminal delivery update the target offset but do not require intermediate frames: the host paints at most once for the batch and directly displays its final target offset. If more reports arrive after that paint, the next read creates a new immediate batch.

This is input-frame coalescing, not synthetic inertia. It has no deadline, timer, animation, or deferred target playback. When terminal reports end, there is no pending application displacement or wheel repaint. It also prevents a high-rate trackpad from building a queue of full Dashboard redraws that plays after the hand stops.

Malformed controls, fragmented controls, paste atomicity, ordinary keys, and mouse-click decoding retain their current behavior.

## Shared Ranking Scroll Policy

Introduce a small, host-neutral state/policy unit rather than duplicating timing and acceleration logic in the standalone and Dashboard loops.

The policy owns the last direction, last report time, and acceleration index. Given the current offset, maximum offset, direction, and monotonic time, it returns the bounded next offset and updated state.

- First report in a sequence: step `1`.
- Same-direction report inside the continuity interval: advance through steps `2`, `4`, `8`, then `12`; remain capped at `12`.
- Opposite direction or elapsed interval beyond the continuity threshold: reset to step `1`.
- Clamp offsets to `[0, maximum_offset]`.
- A boundary-clamped report still updates no viewport position; hosts repaint only when the offset actually changes.

The continuity interval is a named policy constant, initially matching the existing short wheel burst threshold (`0.03` seconds), so tuning does not require modifying host logic.

## Host Integration

Both hosts identify whether the active/pointed chart is an overflowing historical Ranking, then use the shared policy:

- Dashboard identifies the pane from wheel coordinates. It continues to leave non-Ranking, non-overflowing, modal, and unrelated panes untouched.
- Standalone applies wheel movement to the displayed historical Ranking when its chart viewport overflows.
- Native and Custom historical Ranking use the same scrollability and viewport metadata contract. Fixed Ranking chrome remains fixed where the existing viewport behavior supports it.

Wheel handling changes only `chart_offset` and ephemeral scroll-policy state. It does not submit a query, collect/provider result, reset a scheduler, alter summaries or animation state, mutate configuration, or persist Dashboard history.

## Rendering and Performance

After a changed batch target, the host performs one synchronous presentation repaint. It uses the already accepted chart content and viewport metadata to slice the final visible rows; it performs no new projection/data acquisition because of scrolling.

Dashboard continues to compose a complete terminal frame so borders, headers, focus indicators, and pane geometry remain correct. A wheel-triggered frame must not invoke refresh/query/provider paths. No periodic wheel repaint, deferred motion, or catch-up loop is introduced. If a wheel event cannot change the offset, no repaint occurs.

Each terminal read batch causes at most one immediate redraw. The first report never waits for a timer; under high-rate input, stale intermediate frames are discarded and the renderer jumps directly to the latest target. This avoids the previous merged tail and prevents background redraw pressure after input stops.

## Tests

Add focused tests for:

1. **Input decoding:** one wheel report produces one signed unit event; a multi-report input remains individually available; `read_event()` does not drain reports for wheel coalescing.
2. **Scroll policy:** the exact step sequence `1, 2, 4, 8, 12`; cap behavior; reversal reset; timeout reset; boundary clamping; unchanged offset detection.
3. **Standalone:** native and Custom overflowing historical Ranking respond to a first wheel report by one rendered row, accelerate only with subsequent reports, and make no refresh/query call during wheel movement.
4. **Dashboard:** pointed native and Custom overflowing historical Ranking panes share the same semantics; non-target panes retain their offsets; a changed wheel offset triggers one presentation repaint without provider/scheduler work; a lack of later reports produces no further movement/repaint.
5. **Regression:** existing key, paste, click, Dashboard layout, TUI input, Custom chart, and Ranking rendering behavior remains intact.

## Acceptance Criteria

Manual verification on a long Ranking confirms that the first wheel notch/report visibly shifts one row with no merge delay; sustained movement becomes faster; reversing or pausing resumes at one row; and stopping input leaves the screen stationary. During and after scrolling, Dashboard data refreshes occur only on their normal lifecycle schedule or explicit user actions.
