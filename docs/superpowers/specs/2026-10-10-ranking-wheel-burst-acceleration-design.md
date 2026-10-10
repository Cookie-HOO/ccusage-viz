# Ranking Wheel Burst Acceleration Design

**Date:** 2026-10-10

## Goal

Make continuous direct wheel scrolling traverse long historical Rankings faster without restoring inertia or input backlog replay.

## Behavior

- The base direct step remains `max(1, visible_rows // 8)` rendered rows.
- Same-direction wheel reports within 80ms advance a per-viewport burst multiplier: `1x`, `2x`, `3x`, then capped at `4x`.
- A direction change or a gap of 80ms or greater resets the next report to `1x`.
- The multiplier applies only to wheel reports. Up/down keys retain the base direct step.
- Stopping input never moves content again: there is no velocity, timer, scheduled frame, or queued displacement.
- Native and Custom historical Rankings share the policy in Dashboard and standalone hosts.
