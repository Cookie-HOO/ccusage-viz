# Monitor Time-of-Day Token Distribution

**Status:** Approved design

## Purpose

Add a Monitor presentation that answers a different question from the existing realtime TPM timeline:

> During a selected local calendar day, when did token consumption occur and which groups contributed to each peak?

The new presentation aggregates observed token deltas into local-clock hour or half-hour buckets. It is a Monitor-only view: date-level historical providers do not supply enough timestamp detail to reconstruct it.

## Product model

Monitor styles retain their own semantics and therefore expose only controls that affect their rendered result. Controls are not defined by a broad pair of "realtime" and "distribution" categories.

| Style | Heading range | `w` control | `g` control |
|---|---|---|---|
| Existing time-series styles (`points`, `line`, `step`, TPM bars, etc.) | Rolling recent duration | Existing rolling durations (`5m` through `24h`) | Hidden |
| Existing `ranking` and `list` styles | Current observation | Hidden | Hidden |
| New cumulative-token bar style | `Today` or `Yesterday` | Local calendar day: `Today` ↔ `Yesterday` | `Hourly` ↔ `30 min` |

`ranking` and `list` already compute their values from the newest valid observation interval. Their configured `window_seconds` does not affect their values, ordering, title, or layout, so `w` must be removed from their adjustment controls.

## New style

The initial style is a cumulative bar view. Its title follows the existing Monitor naming convention:

```text
Model Token cumulative bars Today
```

Localized product copy may use the established Chinese terminology, e.g.:

```text
模型 Token 累计柱 今天
```

The title is parameterized by the selected dimension and local-day window:

```text
Total / Model / Agent / Project Token cumulative bars Today / Yesterday
```

A concise metadata line includes the selected resolution and coverage boundary, for example:

```text
Hourly · observed from 09:18
```

The view is a separate style selected through the existing `s` style control. It does not replace realtime TPM styles or change sampling behavior.

## Time windows and granularity

### Window (`w`)

The new style uses local calendar-day windows:

- **Today** is the default and covers local midnight through the accepted observation time.
- **Yesterday** covers the prior local calendar day from midnight through midnight.

This directly supports the long-running-monitor case. Shortly after local midnight, Today correctly contains only the newly started day; `w` gives immediate access to the just-completed day rather than forcing a rolling 12-hour or 24-hour chart with a different semantic axis.

The new style does not offer rolling 12-hour or 24-hour windows. Those would require a continuous datetime axis, can cross two calendar days, and answer a separate "recent hourly totals" question rather than time-of-day distribution.

### Granularity (`g`)

`g` cycles:

```text
Hourly ↔ 30 min
```

Buckets align to local clock boundaries, never the Monitor start time:

- Hourly: `09:00–10:00`.
- Half-hour: `09:00–09:30`, `09:30–10:00`.

An hourly view has up to 24 buckets; a half-hour view has up to 48. Labels are selectively thinned at narrow terminal widths, while bucket boundaries remain exact in inspection/data output.

## Aggregation and grouping

Each bucket contains observed **token increments**, not TPM. A sampling interval crossing one or more bucket boundaries is proportionally allocated by its overlap with each bucket, using the Monitor observer's existing cumulative-counter difference, reset protection, and gap handling.

The view fully supports the currently available `by` dimensions:

| `by` | Rendering |
|---|---|
| Total | One cumulative-token bar per bucket |
| Model | One stacked bar per bucket, segmented by model |
| Agent | One stacked bar per bucket, segmented by agent |
| Project | One stacked bar per bucket, segmented by project |

For grouped views, `Top N + Other` remains a late projection over the selected day. The same group retains its color across buckets and styles; color does not change when its rank changes. A single bucket's total height remains the total token consumption for that time period.

No history provider is queried to fill gaps, and the feature never infers intraday consumption from date-level records.

## Coverage semantics

The chart must distinguish unavailable observation time from observed zero consumption. It does **not** use the existing Monitor-start vertical line.

| Bucket state | Rendering | Meaning |
|---|---|---|
| Unobserved | Continuous dark, hatched region | The Monitor had no trustworthy observation for this part of the day; it is not a zero value. |
| Partial | Observed token bar with a hatch overlay | A bucket contains trustworthy observations but does not cover its entire period. This includes the start bucket and the current unfinished Today bucket. |
| Full | Solid token bar | The complete bucket has observed coverage. |
| Observed zero | Valid zero-baseline token mark | The period was observed and had zero tokens; it remains distinct from unobserved space. |

The title metadata preserves the exact Monitor start time (`observed from HH:MM`). The hatched region expresses a coverage range, avoiding the false precision and visual competition of a line that crosses a bar at an arbitrary minute.

Coverage must also handle observation gaps. A bucket is full only when the observer reports full trustworthy coverage; missing/invalid portions remain visibly partial or unobserved rather than being represented as zero.

## Retention

The existing high-resolution raw observation intervals remain short-lived (about one hour). They are not retained for the new feature's full history.

Minute-level rollups retain aggregate token deltas, component values, and coverage information for **50 hours**. These are not raw provider responses, raw counter snapshots, or per-refresh sample records.

```text
~1 hour   raw observation intervals
50 hours  minute-level aggregate rollups
```

The 50-hour minute rollups support any Today/Yesterday selection at the end of a long day, including two adjacent local days and an extra DST fall-back hour. They also retain the minute precision needed to mark partial half-hour buckets accurately. The existing realtime TPM styles continue to expose no window longer than 24 hours.

## Controls

Control rows are style-aware.

### Existing time-series styles

```text
w window · i interval · b grouping · +/- Top N · d density · t/T theme · s style
```

`w` retains its existing rolling-window choices.

### Existing ranking and list styles

```text
i interval · b grouping · +/- Top N · d density · t/T theme · s style
```

`w` is absent because it has no effect there.

### New cumulative-token bar style

```text
w day · g granularity · i interval · b grouping · +/- Top N · d density · t/T theme · s style
```

- `w`: Today ↔ Yesterday.
- `g`: Hourly ↔ 30 min.
- `i`: monitor sampling interval; it affects future observation cadence but does not rewrite already aggregated buckets.
- `b`, `+/-`: existing grouping and Top N behavior.
- `d`, `t/T`, `s`: existing density, theme, and style behavior.

Advanced controls remain available only where applicable: filters and legend controls in grouped views, plus project aggregation and project-label context for project grouping.

## Data inspection and export

The Monitor data table and JSON data view will include a distribution-oriented row per bucket and series:

- `started_at` and `ended_at` in local-time-aware ISO form;
- selected day window and granularity;
- group/series identity and project display context where applicable;
- `value` and `unit: tokens`;
- coverage state: `full`, `partial`, or `unobserved`.

The table/JSON must preserve an unobserved status rather than emitting a misleading zero value.

## Implementation boundaries

The feature belongs at the Monitor projection boundary:

1. Extend Monitor configuration with the new presentation style, calendar-day selection, and time-of-day granularity.
2. Add a calendar-aligned bucket projection over existing observation intervals and minute rollups, preserving value and coverage separately.
3. Add a semantic model/rendering path for cumulative stacked bars and coverage decorations.
4. Make Monitor adjustment controls style-aware, including removal of ineffective `w` from existing ranking/list styles.
5. Extend Monitor data views and localization metadata.

Historical `UsageRecord` parsing, historical chart granularity, and provider capability are intentionally out of scope.

## Verification

Tests must cover:

1. Local hour and half-hour aligned aggregation and proportional interval splitting.
2. Today and Yesterday selection, including a shortly-after-midnight Today and accessible complete Yesterday.
3. Monitor start in the middle of a bucket: preceding buckets unobserved and the first bucket partial.
4. Current unfinished Today bucket as partial.
5. Observed zero distinct from unobserved coverage.
6. Explicit observation gaps, counter resets, and invalid intervals without fabricated token values.
7. Total and grouped Model/Agent/Project buckets, late Top N + Other, and stable group identity.
8. 50-hour minute-rollup retention, including a 25-hour DST fall-back local day.
9. No change to the maximum 24-hour selectable realtime TPM window.
10. Ranking/list adjustment controls omit `w`, while time-series and cumulative-bar styles expose only their meaningful `w` choices.
11. Data-table/JSON coverage fields and local-time bucket boundaries.
