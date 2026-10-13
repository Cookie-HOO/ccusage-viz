# Grouped Custom Ranking Design

## Goal

Extend V2 Custom Historical Ranking with an optional outer partition so one chart can render multiple independent rankings. The motivating Router view partitions by logical model and ranks real models inside each partition.

This change also fixes flat Custom Ranking search so filtering rows does not renumber them, recalculate shares, or rescale bars.

## Scope

Included:

- V2 Custom Historical Ranking only;
- optional `partition_by` capability, defaults, query, CLI, Dashboard, and preset state;
- grouped response parsing, projection, comparison, rendering, search, scrolling, copying, and sticky group headings;
- Dashboard adjustment-page changes for spacing and filters;
- flat Custom Ranking search invariants.

Excluded:

- built-in Ranking;
- Custom Monitor;
- Timeline, Stack, and Calendar partitioning;
- V1 Custom protocol;
- collapsible groups;
- outer-group Top N, sorting, or rank-change presentation.

## Terminology

- **Partition**: the outer dimension controlled by `g/G`, such as logical model.
- **Group**: one returned outer partition instance, such as “Coding Model”.
- **Ranking dimension**: the inner dimension controlled by `b/B`, such as real model.
- **Series**: one ranked inner item.

The main heading expresses both selected dimensions with an arrow:

```text
Logical Model → Real Model · Ranking · 14d
```

Without a partition, the existing single-dimension title remains unchanged.

## Capabilities and Dimension Labels

A V2 metric may declare a partition dimension catalog alongside the existing grouping catalog:

```json
{
  "capabilities": {
    "group_by": [
      {
        "id": "real_model",
        "label": {"en": "Real Model", "zh-CN": "真实模型"}
      }
    ],
    "partition_by": [
      {
        "id": "logical_model",
        "label": {"en": "Logical Model", "zh-CN": "逻辑模型"}
      }
    ],
    "charts": {
      "ranking": {
        "partition_by": [null, "logical_model"],
        "group_by": ["real_model"],
        "show_percentage": true,
        "max_items": 100
      }
    }
  }
}
```

Rules:

- `charts.ranking.partition_by` is optional. Omission means the existing flat Ranking capability and old wire format.
- If `capabilities.partition_by` is declared, each non-null Ranking partition ID must reference it.
- If that catalog is omitted, partition IDs and labels fall back to `capabilities.group_by`.
- `group_by` continues to reference `capabilities.group_by`.
- The catalogs may contain the same ID, but an active non-null `partition_by` and `group_by` must differ.
- `partition_by` is Ranking-only.
- Inclusion of `null` in the chart capability permits switching back to flat Ranking. A list without `null` requires a partition.
- When a partition is active, `group_by` must be non-null.
- Invalid references or combinations reject the descriptor rather than silently degrading it.

## Defaults, CLI, and Persistence

Ranking defaults may suggest a partition:

```json
{
  "defaults": {
    "ranking": {
      "period": "14d",
      "partition_by": "logical_model",
      "group_by": "real_model",
      "top": 3
    }
  }
}
```

A non-null default `partition_by` equal to the default `group_by` is invalid and rejects the descriptor.

The CLI adds:

```text
--partition-by logical_model
```

Dashboard Pane configuration and presets persist `partition_by`. Old presets omit it and remain flat. Explicit CLI and Pane values continue to override Dataset defaults.

Metric switching normalizes the target as follows:

1. use a valid target Ranking default partition when available;
2. otherwise use `null` if supported, or the first required partition;
3. normalize `group_by` next;
4. skip a grouping equal to the selected partition;
5. reject the target combination when no valid non-null ranking dimension exists.

A metric that does not declare partition capability remains on the old flat path and does not receive a partition query field.

## Request Compatibility

An old Dataset that does not declare partition capability receives the unchanged query wire format.

Once a Dataset declares partition capability, requests explicitly include the selected value, including `null`:

```json
{
  "query": {
    "partition_by": "logical_model",
    "group_by": "real_model",
    "top": 3
  }
}
```

Explicit `null` lets a new Dataset distinguish a partition-aware client with partitioning disabled from an old client.

`top` retains its current source-coverage semantics:

- ccuv sends the selected Top N to the Dataset;
- the Dataset decides how many series to return per group;
- it may return fewer, exactly N, or more than N;
- ccuv never infers omitted source items.

## Response Union

### Flat response

A request without an active partition retains the existing response:

```json
{
  "data": {
    "series": []
  }
}
```

### Partitioned response

An active partition uses groups:

```json
{
  "data": {
    "groups": [
      {
        "id": "coding",
        "label": {
          "en": "Coding Model",
          "zh-CN": "代码模型"
        },
        "description": {
          "en": "Routes coding workloads",
          "zh-CN": "面向代码场景的逻辑路由"
        },
        "display": {
          "en": "12.4K requests",
          "zh-CN": "1.24 万次请求"
        },
        "comparison_display": {
          "en": "+1.8K requests",
          "zh-CN": "+1800 次请求"
        },
        "link": "https://example.com/router/coding",
        "series": [
          {
            "id": "seed-code",
            "label": {
              "en": "Seed Code",
              "zh-CN": "豆包代码模型"
            },
            "points": [
              {"date": "2026-10-13", "value": "7100"}
            ]
          }
        ]
      }
    ]
  }
}
```

Rules:

- `data.series` and `data.groups` are mutually exclusive.
- A null partition requires `series`; a non-null partition requires `groups`.
- Group IDs are unique in the response.
- Series IDs are unique within their group, but the same series ID may occur in different groups.
- A series identity is `(group.id, series.id)`.
- Empty groups are valid and render as zero with a localized no-data message.
- Group `label` is required.
- Group `description`, `display`, `comparison_display`, and HTTPS `link` are optional and have the same localization, safety, and display semantics as existing Ranking-entry metadata.
- Inner series retain the existing Ranking schema, including dated `points`, presentation metadata, and links.
- `max_items` limits the sum of raw series over all returned groups. Empty groups do not count as items.
- A violation in any group or series rejects the complete response. ccuv does not skip invalid subtrees because that would corrupt totals, shares, Top, and Other.

Errors identify the failing path where possible, for example:

```text
data.groups[2].series[4].points[0].value must be a decimal string
```

## Periods and Comparison

Inner series continue to return dated points. ccuv sums points in the selected interval.

For `period: "all"`, the existing rules remain:

- the request uses the anchored range and the `all` semantic marker;
- a Dataset may return one official aggregate point at `end_date` per series;
- no previous-period request or comparison columns are produced.

For ordinary periods:

- group comparison matches by `group.id`;
- inner comparison matches by `(group.id, series.id)`;
- the group current and previous values are sums of the series actually returned in each respective response;
- differing source coverage between periods is not interpreted as zero;
- a current group or series absent from the previous response is new;
- entities present only in the previous response are not rendered;
- moving a series between groups makes it new in the destination group;
- `Other` has no comparison or rank-change presentation;
- group totals may show value comparison but never outer rank change;
- inner series retain value and independent within-group rank comparison.

Optional current-response `comparison_display` replaces only the formatted group delta. Numeric comparison remains ccuv-owned.

## Projection and Numeric Semantics

For each returned series and group:

```text
item_total   = sum(series.points[*].value)
group_total  = sum(group.series[*].item_total)
global_total = sum(groups[*].group_total)
```

The returned points are the only numeric source of truth. A group does not carry a separate numeric total.

Group presentation:

- if `group.display` exists, it replaces the formatted group-total text;
- otherwise ccuv formats `group_total` using the metric unit;
- display text never affects calculations.

Ordering and Top:

- outer groups retain Dataset response order exactly;
- ccuv does not sort, rank, or apply Top to outer groups;
- each group independently sorts series using the metric's existing `sort_direction`;
- equal values use series ID as the stable tie-breaker;
- `top=N` independently keeps the first N sorted series in each group;
- `Other` is the arithmetic sum of actual returned series beyond N;
- `Other` is shown or hidden using the existing `other` setting;
- ccuv never derives Other by subtracting visible items from a separate total;
- if a Dataset returns no excess series, ccuv does not invent Other.

Signed Decimal values remain valid. ccuv does not clamp, take absolute values, or reinterpret negative entries or negative Other values.

Shares when `show_percentage` is true:

```text
group_share = group_total / global_total
item_share  = item_total / group_total
```

- group shares use all groups returned in the current response;
- item shares use all series returned in that group, before local Top and Other visibility;
- hiding Other, searching, and scrolling do not change either denominator;
- shares may be negative or exceed 100% when the source facts imply that;
- if `global_total` is zero, group shares are omitted;
- if a `group_total` is zero, that group's item shares are omitted;
- `show_percentage=false` hides both levels.

## Search Invariants

Search matches only inner Ranking-entry fields, preserving current Ranking scope:

- series label;
- series description;
- safe link visible text and URL.

Search does not match group label, description, display, comparison display, or link. A group with matching inner rows renders its normal group label and description. A group with no matches is hidden.

Search is visibility-only. The latest complete projected data determines:

- each series' original within-group rank;
- group and global totals;
- item and group shares;
- each group's bar maximum;
- comparison and activity facts.

The active search is applied only after those facts are built. Consequently, searching one row does not make it rank 1, 100%, or a full-width bar.

Every source refresh first rebuilds the complete Ranking and then reapplies the unchanged search text. Matching rows therefore update rank, value, share, comparison, and visibility with current source facts rather than remaining a frozen snapshot.

The same correction applies to the existing flat Custom Ranking viewport: flat search retains the current full Ranking rank, total, maximum, share, and comparison facts.

## Rendering

Each group is a secondary heading followed by an independent Ranking body:

```text
Coding Model                                  12.4K   +1.8K   48.6%
Routes coding workloads
  1  seed-code              ██████████████     7.1K   +900   57.3%
  2  claude-sonnet          ████████           3.8K   +420   30.6%
  3  gpt-codex              ███                1.1K   +140    8.9%
     Other                  █                    400           3.2%
```

Rules:

- group headings do not draw bars or rank numbers;
- their label, description, display, comparison, share, links, safety handling, density visibility, column hiding, wrapping, and formatting align with existing Ranking entries;
- group headings are visually secondary to the chart title;
- each group restarts inner numbering at 1;
- search retains original current-data numbers;
- each group computes its own bar maximum, so groups with very different scales remain readable;
- group total and share communicate cross-group scale;
- empty groups show the heading, zero total, and no-data message;
- spacing never inserts an item separator between a group heading and its first row;
- groups retain at least one visual break from one another.

## Viewport and Sticky Group Heading

The grouped Ranking remains physically line-scrollable. A group may span viewport boundaries.

When the original group heading has scrolled above the viewport and the top visible item belongs to that group, the viewport reserves its first line for a muted sticky heading containing only `group.label`.

- No sticky heading is shown while the original heading remains visible.
- It disappears when the next original group heading enters the viewport.
- It repeats no description, value, comparison, share, link, or copy action.
- Empty groups do not create sticky headings.
- It is omitted if the terminal cannot show both it and one content row.

Refresh and geometry changes restore position by stable identity where possible:

- flat Ranking: `series.id`;
- grouped Ranking: `(group.id, series.id)`.

If the anchor disappears, restoration falls back to the nearest matching row, then a nearby visible group rather than unconditionally returning to the first row.

## Copying

- Copying an inner series includes its group label so the item retains context.
- Copying a group includes group label, description, link, and its currently visible projected entries.
- Copy All follows Dataset group order and includes group headings.
- During search, Copy All copies only matching series while retaining their group headings.
- Top and Other visibility determine the copied projection.
- Other has no individual copy action.
- Sticky headings add no duplicate copy target.

## Dashboard Controls

### Quick

For grouped-capable Custom Ranking:

```text
p/P  period
g/G  partition
b/B  group
+/-  top
d/D  density
t/T  theme
s/S  style
```

`g/G` cycles the declared outer partitions. `b/B` cycles inner ranking dimensions. Both directions skip a value equal to the other active dimension. If no alternative exists, the current valid state is retained with the existing restricted-control feedback.

### Advanced

```text
s/S  spacing
f    filters
o    other
L    logs
```

Ranking spacing keeps the existing four mode names:

```text
compact → space → line → dashed
```

The existing `dashed` mode now renders its separators using the active theme's muted styling. No-color terminals render ordinary dashed text.

All Dashboard filter actions move to Advanced for consistency across Custom Historical charts, Custom Monitor, and built-in panes. Standalone charts have no Quick/Advanced split and retain their single filter entry.

## Data Flow

```text
Dataset response
  → strict union parsing and validation
  → per-series interval totals
  → group/global totals and prior-period matching
  → independent inner sorting
  → per-group Top and returned-excess Other
  → immutable full projection facts
  → search visibility filtering
  → grouped row layout and viewport geometry
  → sticky group heading and rendering
```

Numeric and ranking facts are established before search and rendering. Presentation metadata never changes sorting, totals, shares, comparison, Top, Other, or bar geometry.

## Verification

Tests cover:

- old descriptors and flat responses retaining the old wire format;
- declared partition capability sending explicit values and explicit `null`;
- separate and fallback partition dimension catalogs and localized arrow headings;
- defaults, CLI, presets, metric switching, and rejection of equal active dimensions;
- flat-versus-grouped response union validation;
- unique group IDs, within-group series IDs, duplicate IDs across groups, empty groups, metadata, safe links, dates, Decimal parsing, and global `max_items`;
- Dataset group order preservation;
- independent inner sorting, numbering, scales, Top, and arithmetic Other;
- totals and shares based only on returned source items and unaffected by Other visibility;
- signed values and zero-denominator omission;
- ordinary and `all` period behavior;
- group and inner comparison identities, new/moved/disappeared entities, and absent comparison for Other;
- search matching only inner fields, hiding empty match groups, retaining current full-data ranks/shares/scales, and updating after source refresh;
- the same search invariants for flat Custom Ranking;
- group headings without bars, density alignment, descriptions, narrow layouts, and no-data rendering;
- physical scrolling, sticky-heading boundaries, identity restoration, and scrollbar range;
- grouped copy, Copy All, search copy, and no duplicate sticky copy target;
- Quick/Advanced bindings, `g/G` and `b/B` conflict skipping, Dashboard-wide Advanced filters, Advanced `s/S` spacing, and muted dashed separators.
