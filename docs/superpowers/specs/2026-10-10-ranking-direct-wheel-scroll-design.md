# Ranking Direct Wheel Scroll Design

**Date:** 2026-10-10

## Decision

Replace the prior kinetic-scroll design with direct, non-inertial wheel scrolling.

## Behavior

- Native and Custom historical Ranking views scroll when the pointer is inside their Dashboard pane rectangle, including the border; focus is not required.
- Standalone native and Custom historical Rankings use their sole chart viewport.
- Each SGR wheel report is a signed unit. It changes the rendered-row viewport immediately by `max(1, visible_rows // 8)` rows in that direction and clamps at the viewport bounds.
- There is no velocity, target offset, timer, animation frame, tail repaint, or state that can move content after the final wheel report.
- A terminal read turn may consume all already-buffered wheel reports and accumulate their bounded direct moves, but renders at most once using the final offset. It does not retain reports for later playback.
- The moving viewport is ephemeral. It never queries data sources, invokes a scheduler, changes selection/focus, or persists configuration.

## Rendering

Ranking chrome above the first numbered entry stays fixed. Only rendered Ranking rows are sliced. Native and Custom historical Rankings share the same viewport metadata: integer offset, total scrollable rows, visible rows, and maximum offset.

## Tests

Test individual wheel decoding, direct screen-relative step sizes, clamping, no movement without a report, pointer targeting independent of focus, native/Custom Dashboard and standalone coverage, one paint per input turn, and no query/scheduler calls caused by scrolling.
