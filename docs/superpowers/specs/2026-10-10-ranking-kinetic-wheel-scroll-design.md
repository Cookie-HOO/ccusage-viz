# Ranking Kinetic Wheel Scroll Design

**Date:** 2026-10-10

## Goal

Make large native and Custom historical Ranking views scroll naturally with the mouse wheel while preserving the responsiveness expected from a terminal dashboard:

- A wheel report is accepted whenever its pointer lies within an overflowing Ranking pane; focus is not required.
- Native and Custom historical Rankings share the same scrolling behavior in Dashboard and standalone hosts.
- Stopping wheel input has a perceptible but very short inertia tail.
- Scroll speed scales with the visible size of the pane.
- High-rate wheel reports do not create a queued backlog that continues playing after input stops.
- Scrolling is presentation-only: it never triggers a query, provider refresh, scheduler work, or persisted configuration change.

## Chosen Approach

Use the common velocity-based kinetic scrolling model:

1. Wheel reports inject a signed impulse into one scalar velocity.
2. The active frame loop advances the viewport from that velocity using monotonic elapsed time.
3. Velocity decays exponentially after input ends.
4. Velocity is capped and forcibly stopped after a short hard inertia deadline.

This differs deliberately from target-offset interpolation and spring-to-target approaches. Those approaches retain a growing target distance under high-rate input, so they can visibly catch up after the user stops. The chosen model has no target offset and no pending displacement queue: only the current velocity survives from one event or frame to the next.

## Scope

Applies to overflowing historical Ranking content in:

- standalone native Ranking;
- standalone Custom historical Ranking;
- native Ranking panes in Dashboard; and
- Custom historical Ranking panes in Dashboard.

It excludes monitor rankings, non-Ranking charts, keyboard viewport behavior, mouse click behavior, overscroll bounce, and persistence of scroll positions.

## Pointer Targeting and Ownership

For every wheel report, Dashboard identifies the pane from the report coordinates. A pane is eligible when all of the following are true:

- the coordinate is within its pane rectangle, including its border;
- the pane currently renders an overflowing historical Ranking;
- no modal interaction owns input; and
- the Ranking has a positive maximum viewport offset.

The pointed pane may differ from the focused pane. Wheel input does not change focus.

The host records one session-local kinetic scroll owner. A wheel report directed at an eligible pane stops any inertia owned by another pane before applying its impulse. Once started, the selected pane may finish its already-bounded inertia even if the pointer leaves it. A new wheel report in another pane transfers ownership immediately.

Standalone Ranking uses its displayed Ranking viewport as the sole eligible target.

## Shared Viewport and State Contract

Native and Custom historical Ranking rendering must expose the same ephemeral viewport metadata:

```python
@dataclass
class RankingViewport:
    offset: float         # logical rendered-line offset; retained as a fraction internally
    total_rows: int
    visible_rows: int

    @property
    def maximum_offset(self) -> int: ...
```

The renderer derives its first displayed line from a stable integer projection of `offset` (floor), then slices the accepted rendered rows. Fixed Ranking chrome remains fixed according to the existing viewport rendering contract.

Each scrollable viewport owns this session-only kinetic state:

```python
@dataclass
class RankingKineticState:
    velocity_screens_per_second: float = 0.0
    last_input_at: float | None = None
    last_tick_at: float | None = None
```

A state carries neither target position nor an event list. It is reset when a pane’s accepted content is replaced, when its geometry makes it non-scrollable, when it reaches an outward boundary, or when another pane becomes the kinetic owner.

## Wheel Input and Speed Scaling

The input decoder emits individual signed wheel reports with their terminal coordinates. Each report is consumed without a per-event repaint requirement. Hosts may drain already-available wheel reports in one input turn, apply their effects in order to the current state, and paint only the final presentation state once.

The velocity unit is **screens per second**, not rows per second. One screen equals `visible_rows` rendered Ranking lines. This makes the same physical input traverse roughly the same percentage of a large and small pane, while retaining line-level precision in a short pane.

For a wheel direction `d` (`-1` or `+1`):

```text
velocity = clamp(
    velocity + d × impulse_screens_per_second,
    -maximum_screens_per_second,
    +maximum_screens_per_second,
)
```

Initial named tuning constants:

| Constant | Initial value | Meaning |
|---|---:|---|
| `WHEEL_IMPULSE_SCREENS_PER_SECOND` | `0.32` | velocity injected by one standard report |
| `WHEEL_MAX_SCREENS_PER_SECOND` | `2.25` | cap for fast continuous input |
| `WHEEL_DAMPING_PER_SECOND` | `22.0` | exponential deceleration rate |
| `WHEEL_STOP_SCREENS_PER_SECOND` | `0.03` | velocity below this is zeroed |
| `WHEEL_MAX_INERTIA_SECONDS` | `0.110` | absolute post-input inertia deadline |
| `WHEEL_MAX_FRAME_DELTA_SECONDS` | `0.050` | cap on an interrupted frame’s integration interval |

Same-direction reports build velocity to the cap. Reverse-direction reports are applied to the existing signed velocity, so they brake the old direction first and then generate reverse motion; no previously queued forward movement can play out.

## Frame Integration and Inertia

A frame is scheduled only while the kinetic owner has non-zero velocity. On each frame, using monotonic time:

```text
dt = min(now - last_tick_at, WHEEL_MAX_FRAME_DELTA_SECONDS)
rows_per_second = velocity_screens_per_second × visible_rows
offset = clamp(offset + rows_per_second × dt, 0, maximum_offset)
velocity *= exp(-WHEEL_DAMPING_PER_SECOND × dt)
```

After integration, the host sets velocity to zero when any condition holds:

- `abs(velocity) < WHEEL_STOP_SCREENS_PER_SECOND`;
- `now - last_input_at >= WHEEL_MAX_INERTIA_SECONDS`;
- the viewport reached its top boundary while velocity is upward; or
- the viewport reached its bottom boundary while velocity is downward.

This provides a deliberate, small continuation after the final report, but it cannot outlive 110 ms. At rest, no frame timer or periodic repaint remains active.

If a report arrives after a long idle period, the state is treated as stopped before applying its new impulse. A fresh report therefore cannot revive stale velocity.

## Input Coalescing and Rendering Pressure

Input and rendering are separated deliberately:

- Wheel reports update only the scalar velocity and last-input timestamp.
- They do not enqueue row deltas, target offsets, or animation jobs.
- During one readable-input turn, the host may consume all immediately available wheel reports, retaining their ordered velocity effects but discarding intermediate visual states.
- That turn renders at most one frame, after integrating the current velocity to the current time.
- A subsequent animation frame is generated only while kinetic velocity remains active, and only until the hard inertia limit.

At a boundary, reports that cannot produce visible movement do not request a repaint. Likewise, a frame repaints only when the projected visible row offset changes; fractional progress alone need not redraw the full terminal frame.

This bounds both work and perceived tail latency under a high-rate trackpad or terminal mouse-report burst.

## Host Integration

Add a host-neutral kinetic policy module responsible for:

- applying a signed wheel impulse;
- advancing a viewport for a monotonic timestamp;
- clamping and boundary stopping; and
- reporting whether the projected display offset or active state changed.

Dashboard uses pointer hit-testing to select the target pane, invokes the policy, and requests an immediate presentation paint only when needed. Its existing complete-frame compositor remains responsible for borders, headers, focus marks, and geometry.

Standalone native and Custom hosts use the same policy and input event path. They retain Ranking viewport metadata after rendering so a wheel report or kinetic frame can reslice the accepted content without recomputing its data model.

All scroll state is UI-session-local. It is not copied into chart configuration, Dashboard preset history, undo/redo state, or data export.

## Data and Scheduler Isolation

Wheel reports and kinetic frames may:

- update an ephemeral Ranking viewport offset and kinetic state; and
- issue a presentation repaint based on already accepted chart content.

They must not:

- submit a native or Custom query;
- invoke a provider, Custom command, query coordinator, or summary query;
- alter Dashboard refresh/sampling schedules;
- reset component business state or accepted results;
- change focus, pane configuration, or persisted Dashboard state; or
- create background repaint activity after velocity stops.

## Error and Change Handling

When a Ranking becomes empty, non-historical, non-overflowing, or replaced due to a query/configuration change, its viewport is clamped and its kinetic state stops. Geometry changes preserve the fractional offset only insofar as the resulting projected offset remains valid; it is then clamped to the new maximum. No overscroll or elastic rebound is rendered.

Malformed and fragmented terminal controls retain the existing decoder behavior. Wheel report handling must remain bounded by existing input-buffer safety limits.

## Tests

Add deterministic, monotonic-time tests for:

1. **Policy integration:** one impulse sets velocity; frames advance a line offset proportionally to visible rows; exponential decay occurs; velocity stops below threshold and at the hard deadline.
2. **Speed scaling:** equal velocity over equal time moves approximately the same fraction of a 10-row and 30-row viewport.
3. **Bounds:** top/bottom clamp clears outward velocity; an inward report leaves the boundary immediately; no repaint is requested without a projected line change.
4. **Direction changes:** reverse reports brake and reverse velocity without replaying movement from the old direction.
5. **No backlog:** a burst is coalesced into bounded velocity and one input-turn paint; no target/delta queue remains; motion has stopped by 110 ms after final input.
6. **Pointer semantics:** Dashboard wheels the pointed eligible native or Custom Ranking regardless of focus; non-Ranking, non-overflowing, and modal-covered panes are ignored; a new pane stops the prior owner’s inertia.
7. **Host coverage:** standalone native, standalone Custom, Dashboard native, and Dashboard Custom all share the policy and preserve no-query/no-scheduler behavior on wheel or kinetic frames.
8. **Regression:** keyboard input, clicks, paste atomicity, malformed sequences, normal Dashboard composition, and existing Ranking rendering remain intact.

## Acceptance Criteria

With a long Ranking, a wheel action over any part of its pane moves its viewport even if another pane has focus. Fast continuous input reaches a bounded speed that feels proportionate to pane height. Releasing the wheel or trackpad produces a visible but restrained continuation and settles completely within 110 ms. The terminal never spends seconds catching up after input ends, and scrolling creates no data refreshes or configuration mutations.
