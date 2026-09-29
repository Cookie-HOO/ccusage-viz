# Custom Command and Empty Dashboard Design

**Status:** approved direction, ready for implementation planning
**Date:** 2026-09-30

## Goal

Make ccuv a general-purpose terminal dashboard platform while preserving its existing ccusage experience. Users can add command-backed custom data to standalone charts and Dashboard panes, including datasets such as reading, CI activity, or cost.

The first release introduces command-backed custom historical charts and editable empty Dashboard panes. It does not introduce file-backed sources, Python plugins, persistence files, command discovery, result caching, range union queries, or non-additive metrics.

## User-facing commands

Standalone custom charts use the existing chart vocabulary under a new command:

```bash
ccuv custom timeline --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom stack --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom calendar --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom ranking --dataset wechat-reading --command 'wechat-reading ccuv'
```

Dashboard panes use the existing ordered `--pane` fragments:

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'empty' \
  --pane 'custom timeline --dataset wechat-reading --command "wechat-reading ccuv"' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

`--dataset` is required and is the stable identity of the data source. A Dashboard may use the same dataset in multiple panes only when each use has the same command configuration. The command must echo that dataset ID in each response.

`--command` is parsed into argv with `shlex.split` and executed without a shell. Users who explicitly need shell behavior may provide their own shell argv, for example `sh -lc 'collector | adapter'`.

## Empty Dashboard and temporary panes

`ccuv dashboard --empty` disables default ccusage pane assembly and its default data dependencies. It creates the normal default Dashboard layout, but fills it with `empty` panes. `--grid` or an explicit layout determines the number and placement of initial empty panes.

An empty pane is a real, temporary pane configuration:

```bash
--pane 'empty'
```

It participates in layout, focus, mouse handling, Tab navigation, insertion, deletion, and command serialization but has no provider, scheduler, chart data, or summary contribution. It renders exactly two localized lines:

```text
Empty pane
Double-click to choose a type
```

```text
空白子图
双击选择类型
```

A double-click replaces the empty pane in place. The type chooser is shared by empty-pane activation, replacement, insertion before, and insertion after:

```text
Empty
Timeline
Stack
Calendar
Ranking
Monitor
Animate
Custom
```

Selecting `Custom` opens a second chooser with Timeline, Stack, Calendar, and Ranking, then a Tab-navigable existing-style form for Dataset ID and Command. Confirmation validates the text fields, runs the initial default query, and replaces the temporary pane only after a successful response. Failure leaves the original empty pane in place and shows the error.

Insertion can create an `Empty` pane or any configured content pane. `x` preserves the existing Dashboard behavior: it deletes the current pane, including an empty pane, and remaining panes compact/reflow. It does not leave an automatic empty placeholder. Explicit `--pane 'empty'` preserves empty locations when a command is copied.

Clock presets remain unchanged: `wide-clock` and `narrow-clock` retain their first clock pane. Clock is not implicitly added by `--empty`.

## Custom command process contract

Each invocation is one request and one result:

1. ccuv starts the configured argv.
2. ccuv writes exactly one UTF-8 JSON request to stdin and closes stdin.
3. The command writes exactly one UTF-8 JSON response to stdout and exits.
4. stderr is diagnostic output and is not protocol data.
5. ccuv validates timeout, exit status, response JSON, protocol version, request ID, dataset ID, schema, and numeric values.

The first ordinary pane query is capability discovery. There is no separate `describe` call. Every successful response must carry the complete capability manifest, dataset presentation metadata, chart data, and pane summary.

The command is modeled as a stateless query adapter. Every successful response is self-describing; ccuv can cache the most recent valid result for display after a later failed refresh, but no response depends on an earlier command process.

## Common protocol envelope

The protocol version is `ccuv.custom/v1`. Each physical command execution has a generated `request_id`; when ccuv coalesces duplicate Dashboard requests, this is a shared physical execution ID rather than any individual pane lifecycle ID.

### Pane request

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "pane",
  "dataset_id": "wechat-reading",
  "range": {
    "start_date": "2026-09-17",
    "end_date": "2026-09-30"
  },
  "query": {
    "filters": {
      "category": ["literature"]
    },
    "group_by": "book",
    "granularity": "day"
  },
  "summary": {
    "period": "day",
    "as_of_date": "2026-09-30"
  }
}
```

All dates are inclusive ISO-8601 calendar dates (`YYYY-MM-DD`). There are no timestamps, time zones, hours, rolling windows, or sub-day fields in v1.

`range` controls the graph data. `query.filters`, `query.group_by`, and `query.granularity` control the command's business query and aggregation. `summary` controls the pane summary calculation and is separate from the graph range.

The request deliberately excludes chart style, theme, density, legend configuration, sorting presentation, Top N, Other, panel geometry, and layout because ccuv handles those locally.

`chart_kind` is deliberately omitted. The command returns neutral series-and-points data, so matching Timeline, Stack, and Ranking panes can reuse a physical command call. Calendar naturally requests the required ungrouped daily shape.

### Dashboard summary request

A Dashboard deduplicates global custom summaries by dataset ID. Each distinct custom dataset contributes at most one Dashboard header summary call per refresh cycle:

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-dashboard-summary-id",
  "request_kind": "dashboard_summary",
  "dataset_id": "wechat-reading",
  "summary": {
    "period": "day",
    "as_of_date": "2026-09-30"
  }
}
```

This request does not inherit any pane range, filters, grouping, Top N, Other, or graph granularity. Its summary period is controlled only by the Dashboard header summary setting. Dashboard metrics stay independent; ccuv never adds values across datasets with incompatible units.

## Successful pane response

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "pane",
  "dataset_id": "wechat-reading",
  "status": "ok",
  "dataset": {
    "title": {"en": "WeChat Reading", "zh-CN": "微信读书"},
    "description": {"en": "Daily pages read", "zh-CN": "每日阅读页数"},
    "unit": {
      "id": "page",
      "label": {"en": "pages", "zh-CN": "页"},
      "placement": "suffix",
      "decimal_places": 0
    }
  },
  "capabilities": {},
  "data": {
    "series": [
      {
        "id": "book-001",
        "label": {
          "en": "One Hundred Years of Solitude",
          "zh-CN": "百年孤独"
        },
        "points": [
          {"date": "2026-09-17", "value": "28"},
          {"date": "2026-09-18", "value": "15"}
        ]
      }
    ]
  },
  "summary": {}
}
```

All human-visible text in protocol results must provide both `en` and `zh-CN`: dataset metadata, units, dimension labels, filter labels/options, series labels, metric labels, and command-returned messages. Machine IDs, enum values, dates, error codes, and numeric values are not localized. ccuv selects the current application language.

All values are decimal strings, parsed as exact decimals by ccuv. Valid values are ordinary signed decimal notation only; NaN, Infinity, blank strings, and floating-point JSON numbers are invalid. The dataset chart metric has one fixed unit and dimension. v1 metrics must be additive; ccuv may sum them across series and time buckets.

## Capabilities

Every successful pane response contains a complete capabilities manifest. It declares the data source's stable supported query surface, not a hidden keyboard mapping. ccuv owns stable controls and only enables a control where the current chart capability permits it.

```json
{
  "capabilities": {
    "group_by": [
      {
        "id": "book",
        "label": {"en": "Book", "zh-CN": "书籍"}
      },
      {
        "id": "author",
        "label": {"en": "Author", "zh-CN": "作者"}
      }
    ],
    "filters": [
      {
        "id": "category",
        "label": {"en": "Category", "zh-CN": "分类"},
        "mode": "multi_select",
        "options": [
          {
            "id": "literature",
            "label": {"en": "Literature", "zh-CN": "文学"}
          }
        ]
      }
    ],
    "charts": {
      "timeline": {
        "granularities": ["day", "week", "month"],
        "group_by": ["book", "author"],
        "filters": ["category"]
      },
      "stack": {
        "granularities": ["day", "week", "month"],
        "group_by": ["book", "author"],
        "filters": ["category"]
      },
      "calendar": {
        "granularities": ["day"],
        "group_by": [],
        "filters": ["category"]
      },
      "ranking": {
        "granularities": ["day", "week", "month"],
        "group_by": ["book", "author"],
        "filters": ["category"]
      }
    }
  }
}
```

v1 filters are complete enumerated multi-select lists only. Free text, ranges, regular expressions, pagination, server-side option search, hierarchical filters, and an expression language are out of scope. A dimension may be both groupable and filterable. The command returns current complete filter options in every success response; ccuv removes invalid selections if a newer valid capability response no longer lists them and informs the user.

Capabilities must remain stable for one dataset's normal use. A command must reject a specific unsupported combination rather than silently dropping, replacing, or weakening a requested filter, grouping, or granularity.

## Data computation responsibilities

The command performs all data-source and business semantics:

- filter by the inclusive requested date range;
- apply business filters, account selection, permission rules, de-duplication, validity rules, and other domain logic;
- aggregate by the one requested `group_by` dimension, or return a single `total` series when it is null;
- aggregate by the requested day, week, or month granularity;
- return the complete candidate series set for that query shape.

ccuv performs all generic display semantics:

- sort complete series by their sum over the requested graph range;
- select Top N;
- add omitted series bucket-by-bucket into `Other` when enabled;
- build cumulative display values where a selected style requires them;
- render chart style, theme, density, legend, layout, and interaction;
- format values and comparison trends.

Therefore Top N, Other, sorting, styles, and layout do not go to the command. Grouping and business filtering do go to the command. A command must return complete candidates for a supported grouping so ccuv can calculate correct Top N and Other.

Only additive metrics are supported: page counts, amounts, build counts, byte totals, and similar sums. Averages, conversion rates, percentages, unique users, min/max, percentiles, balances, snapshots, and other non-additive measurements are excluded from v1.

## Chart support and existing ccuv behavior

Custom charts reuse existing ccuv chart kinds, styles, adjustment pages, localized terminology, keyboard semantics, geometry limits, and renderer restrictions.

| Chart | v1 data shape and controls | Constraints |
|---|---|---|
| Timeline | total or grouped date series; period, filters, grouping, granularities, Top N, Other, cumulative/view styles | uses present timeline style constraints; area is unavailable when grouping makes it incompatible |
| Stack | total or grouped date series; period, filters, grouping, granularities, Top N, Other, current stack styles | normalized remains a visual distribution mode; ungrouped total is permitted even if less informative |
| Calendar | ungrouped daily total series; period, filters, current calendar styles | no grouping, Top N, Other, or non-daily granularity |
| Ranking | complete grouped candidate series; ccuv sums range buckets and ranks locally; period, filters, grouping, Top N, Other | ungrouped total is protocol-valid but has limited visual value |

Common shortcuts keep their current semantics: `p` changes graph period, `b` chooses a declared grouping, `g` chooses a declared granularity, `f` edits declared filters, `+/-` changes local Top N, and `o` toggles local Other.

## Pane summary semantics

A pane summary comes in the normal pane response and is independent from graph grouping, Top N, and Other. It inherits the current filters.

For relative graph ranges such as the default 14 days, ccuv follows its current behavior: graph range and summary period are separate. Summary period is controlled by the current historical summary/aggregation setting, initially `day`.

- `day`: current date, compared to yesterday and the same weekday seven days earlier;
- `month`: month-to-date, compared to prior month-to-date and same elapsed period last year;
- `quarter`: quarter-to-date, compared to prior quarter-to-date and same elapsed period last year;
- `year`: year-to-date, compared to prior-year-to-date only; the second comparison is unavailable.

When an explicit fixed date range is selected, ccuv shows the selected-range total and comparisons are unavailable. This is independent of whether that range includes the current day.

The command receives the summary period and as-of date. It computes the business-correct current and baseline values with the same filters but without grouping, Top N, or Other. ccuv computes directions and percentage change using its existing rules: equal values are unchanged; a zero baseline yields `from_zero` with no synthetic infinite percentage; unavailable and pending comparisons are distinct states.

```json
{
  "summary": {
    "metric": {
      "id": "pages-read",
      "label": {"en": "Pages read", "zh-CN": "阅读页数"},
      "unit": {
        "id": "page",
        "label": {"en": "pages", "zh-CN": "页"},
        "placement": "suffix",
        "decimal_places": 0
      }
    },
    "value": "620",
    "sequential": {"status": "ready", "base_value": "552"},
    "year_over_year": {"status": "ready", "base_value": "460"}
  }
}
```

Comparison statuses are `ready`, `pending`, or `unavailable`. `ready` requires `base_value`; the other statuses omit it. ccuv maps these to its existing comparison state rendering.

## Dashboard summary response

A dashboard-summary response returns independent metrics. Each metric owns its unit and precision, so dataset header values need not share one unit:

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-dashboard-summary-id",
  "request_kind": "dashboard_summary",
  "dataset_id": "wechat-reading",
  "status": "ok",
  "metrics": [
    {
      "id": "pages-read",
      "label": {"en": "Pages read", "zh-CN": "阅读页数"},
      "unit": {
        "id": "page",
        "label": {"en": "pages", "zh-CN": "页"},
        "placement": "suffix",
        "decimal_places": 0
      },
      "value": "68",
      "sequential": {"status": "ready", "base_value": "56"},
      "year_over_year": {"status": "ready", "base_value": "50"}
    }
  ]
}
```

ccuv uses existing comparison calculation and presentation. It formats localized numbers, units, thousand separators, sign, precision, glyphs, compact/full density, and pending/unavailable/from-zero state. Commands never return preformatted number strings or percentage strings.

## Custom-pane adjustment surface

A custom pane exposes ordinary chart adjustments plus exactly two custom-specific adjustments. Ordinary chart controls retain the existing ccuv semantics and are capability-gated: period, grouping, filters, granularity, Top N, Other, style, theme, density, and legend. Controls that alter the command query (`p`, `b`, `g`, and `f`) run a new command request; local presentation controls, including Top N and Other, redraw from the accepted complete candidate set without starting a command.

The custom-specific adjustments are:

1. **Source** — edits Dataset ID and Command argv using the existing Tab-navigable editing structure. Enter validates argv and performs a query using the pane's current query configuration. ccuv atomically replaces source configuration, metadata, capabilities, result, and capability-gated controls only after a valid successful response. A failed edit preserves the previous source and most recently accepted rendering.
2. **Logs** — opens the existing-style bounded log/diagnostics view for the custom command: command lifecycle messages, latest protocol or execution failure, and bounded stderr output. It is diagnostic-only and never parsed as protocol result data.

`l` remains the existing legend shortcut. `L` opens the custom command Logs adjustment. The existing animation-pane log entry is also moved to `L`, establishing `L` as the shared Logs shortcut and eliminating its conflict with the chart Legend shortcut. Source and Logs are available for standalone `ccuv custom …` charts and Dashboard custom panes.

Changing a source does not change the pane chart kind. Changing Timeline to Stack, changing Custom to a built-in source, or changing to Monitor, Animate, or Empty uses the shared Replace pane flow.

## Errors and empty data

Unsupported requests must not silently degrade. A valid protocol error response is:

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "pane",
  "dataset_id": "wechat-reading",
  "status": "error",
  "error": {
    "code": "unsupported_query",
    "message": {
      "en": "Monthly grouping by author is not available.",
      "zh-CN": "暂不支持按作者进行月度聚合。"
    },
    "unsupported": {"field": "query.granularity", "value": "month"}
  }
}
```

Stable v1 error codes are:

- `unsupported_dataset`
- `unsupported_chart_kind`
- `unsupported_query`
- `invalid_request`
- `invalid_filter`
- `range_not_available`
- `source_unavailable`
- `internal_error`

On a valid error, ccuv keeps the last successful rendering and capabilities, displays the error, and restores the most recent valid view configuration rather than silently substituting another query.

No matching data is not an error. It is an `ok` result with empty series and valid zero/pending/unavailable summary values. Controls remain usable.

Malformed JSON, mismatched IDs, invalid decimals, missing required localized text, unknown protocol versions, timeout, spawn failure, and nonzero command exit without a valid protocol error are ccuv protocol/source failures. stderr is surfaced as bounded diagnostics but never parsed as result data.

## Request coalescing and lifecycle

Custom command queries integrate with the existing provider/query coordinator model.

ccuv guarantees only exact in-flight request coalescing. If multiple callers concurrently need the same canonical custom request, one command process executes and its response is delivered to all callers. A custom command physical identity contains:

- command argv and relevant execution context;
- dataset ID;
- request kind;
- inclusive range, when pane data is requested;
- normalized filters (keys and selected IDs sorted);
- grouping;
- granularity;
- pane summary period and as-of date, when pane data is requested;
- dashboard summary period and as-of date, for dashboard summaries.

Different styles, densities, themes, legends, Top N, Other, layout positions, and Chart kinds do not change physical identity. Timeline, Stack, and Ranking can share where their neutral query shape is identical. Calendar shares only where the required ungrouped daily request is identical.

No v1 guarantee exists for overlapping-range merge, interval union, post-completion caching, shared completed coverage, command batching, or result slicing. Pane and header lifecycles remain independent, as in existing Dashboard behavior.

## Architecture approach

Implement custom command data as another provider-backed source for the existing historical chart system, not as a separate chart language or a dynamic third-party plugin system.

The implementation should introduce a neutral custom command result model and a custom provider adapter that maps command requests/responses into reusable chart projection inputs. Existing chart definitions, hosts, rendering, localized controls, lifecycle cancellation/stale-result protection, query coordination, and exact in-flight merging remain shared.

`empty` is a temporary `PaneConfig` type. The reusable pane-selection flow produces a configured `PaneConfig` and is invoked by empty-pane activation, replacement, and insertion. The caller chooses whether to replace, insert before, or insert after only after that flow successfully completes.

## Out of scope and future direction

Not in v1:

- JSON/JSONL files, stdin sources, HTTP sources, or Python entry-point plugins;
- custom non-additive metric semantics;
- arbitrary user-defined keys or chart-specific controls;
- source/dataset discovery or global registered source aliases;
- filter search/paging and high-cardinality filter UX;
- persistent dashboard configuration files;
- command-server/JSON-RPC mode;
- custom monitor data sources;
- calendar grouping;
- smart range union, shared coverage cache, or completed-result cache;
- cross-dataset arithmetic in dashboard summaries.

Future file sources can adapt to the same normalized custom result model, with ccuv performing local filtering and aggregation only where the file schema guarantees sufficient complete facts.

## Acceptance criteria

1. `ccuv custom` can render Timeline, Stack, Calendar, and Ranking from a valid command source.
2. A command receives exactly one structured stdin request and produces one validated stdout response per physical invocation.
3. Default custom pane behavior is a 14-day graph window, ungrouped total, and day-period summary.
4. Every successful pane response includes complete capabilities and both English and Simplified Chinese presentation text.
5. Command-side query behavior and ccuv-side Top N/Other/sorting follow the responsibility boundary above.
6. Error, empty-data, zero-baseline, pending, unavailable, and malformed-response behavior are separately tested.
7. `dashboard --empty` starts without ccusage default panes or requests and fills its selected layout with temporary empty panes.
8. `--pane 'empty'` round-trips through copied Dashboard commands, including intermediate empty panes.
9. The shared type chooser is identical for empty activation, replacement, insertion before, and insertion after; insertion supports Empty.
10. A custom dataset contributes at most one Dashboard summary request per Dashboard refresh cycle.
11. Equivalent concurrent custom requests coalesce to one command execution; nonidentical or already-completed requests do not.
12. Existing ccusage dashboards, clock presets, pane deletion semantics, and non-custom chart behavior remain compatible.
