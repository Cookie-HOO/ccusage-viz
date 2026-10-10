# Dataset Historical Fixed Refresh Design

**Date:** 2026-10-10

## Goal

Allow Dataset authors to declare a fixed refresh interval for Timeline, Stack, Calendar, and Ranking charts, extending the existing Dataset-controlled Monitor interval model.

## Capability Field

Historical chart capabilities accept an optional positive integer:

```json
{
  "refresh_interval_seconds": 30
}
```

The field is valid only for Dataset historical chart capabilities (`timeline`, `stack`, `calendar`, `ranking`) in V1 and V2 descriptor/chart-response metadata. Absent means the host interval remains applicable.

## Scheduling

- A chart with declared `refresh_interval_seconds` uses that fixed interval in standalone watch and Dashboard.
- A chart without it uses its Dashboard global interval or standalone host interval.
- In a Dashboard, global `--interval` applies only to ccusage-native panes and Dataset panes lacking a declared fixed interval.
- Each Dashboard pane retains its own scheduler, so fixed and host-controlled panes coexist without changing one another.
- Status/control copy reflects the effective interval.

## Override Validation

A declared fixed interval is author-owned and cannot be overridden.

- If a Dataset chart declares `refresh_interval_seconds`, launching that chart with an explicit standalone `--interval` fails with a localized argument/conflict error.
- Dashboard global `--interval` is allowed even when fixed Dataset panes exist; it simply does not affect those panes.
- No pane-local runtime interval override is added.

## Propagation

Extend V1/V2 historical capability models, protocol parsing, persisted descriptor serialization, metric-to-V1 projection, runtime/probe capability adaptation, and scheduler construction. Existing Monitor semantics remain unchanged.

## Tests

- V1/V2 parser accepts a positive historical refresh interval and rejects zero, negative, non-integer, and non-historical placement.
- Serialization preserves a declared value and omits absent values.
- A fixed Dataset historical pane receives its declared scheduler interval while a sibling native/unfixed pane receives the host interval.
- Explicit standalone `--interval` with a fixed Dataset historical chart fails.
- Dashboard global interval remains valid with fixed panes and applies only to unrestricted panes.
