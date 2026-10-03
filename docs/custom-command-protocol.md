# Custom command protocol guide

[简体中文](custom-command-protocol.zh-CN.md)

`ccuv custom` adapts a command that can return one additive historical metric. It
is for data such as reading, CI activity, spend amounts, build counts, or byte
totals. ccuv owns terminal presentation; the command owns the source-specific
query and aggregation.

This is a command protocol, not a plugin or persistence system. Version 1 does
not support file, HTTP, stdin, Python-plugin, or Monitor sources. It does not
cache completed command results, discover commands, combine query ranges, or
support non-additive metrics.

## Start a custom chart

Choose a chart kind and supply a stable dataset ID plus the command argv:

```bash
ccuv custom timeline --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom stack --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom calendar --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom ranking --dataset wechat-reading --command 'wechat-reading ccuv'
```

`--dataset` is required. It is the stable identity of the source and every
response must echo it exactly. `--command` is split into argv with
`shlex.split` and runs without a shell. To deliberately use shell behavior,
make the shell part of argv yourself:

```bash
ccuv custom timeline --dataset example --command "sh -lc 'collector | adapter'"
```

A custom chart begins with a 14-day, ungrouped total graph and a day-period
summary. Custom data cannot use `monitor`. The Dashboard pane always exposes
`p`/`P` to change the rolling graph range. After the first successful response,
it also exposes capability-gated query controls: `g` cycles declared
granularities, `b` cycles total and declared groupings, and `f` edits declared
filter options. Each such adjustment starts a new command query. Source editing
(`e`) and diagnostic Logs (`L`) are also available. Lowercase `l` cycles the
custom Timeline/Stack legend; uppercase `L` is reserved for Logs.

A standalone custom chart continuously refreshes by issuing `ccuv.custom/v1`
chart requests to its configured command. It does not run `ccusage` historical
acquisition or watch processing. A data-affecting replacement immediately
shows the candidate chart title and loading state, without stale facts or a
`querying` annotation. If that request fails, ccuv restores the previously
accepted chart with the custom-source error alongside it.

## Use custom panes in a Dashboard

Use ordinary ordered `--pane` fragments. The dataset may appear in more than
one pane only when all uses have the same command configuration.

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'empty' \
  --pane 'custom timeline --dataset wechat-reading --command "wechat-reading ccuv"' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

`dashboard --empty` suppresses default ccusage panes and their default data
dependencies. It uses the normal default Dashboard layout and fills it with
`empty` panes; `--grid` or an explicit layout sets their initial count and
placement. It does not add a clock. Existing `wide-clock` and `narrow-clock`
presets retain their clock pane.

`--pane 'empty'` is a real temporary pane: it takes part in layout, focus, mouse
and Tab navigation, insertion, deletion, and copied-command serialization, but
has no provider, scheduler, data, or summary. It displays:

```text
Empty pane
Double-click to select, then press r to choose a type
```

Double-clicking an empty pane enters its Dashboard management context. It shows
only Dashboard structure and position controls, not chart-specific settings.
`r` opens the shared replacement type chooser; `N` and `n` open the insert-before
and insert-after chooser. Selecting Custom then selects Timeline, Stack,
Calendar, or Ranking and opens Dataset ID and Command fields. The new custom
pane starts its initial query after replacement; the pane displays the resulting
source error if that query fails. Insertion can also create an Empty pane.
Deleting a pane with `x` compacts the remaining panes and does not create a
replacement placeholder.

## Process contract

Each physical query executes one command process:

1. ccuv starts the configured argv.
2. ccuv writes exactly one UTF-8 JSON request to stdin, then closes stdin.
3. The command writes exactly one UTF-8 JSON response to stdout, then exits.
4. stderr is bounded diagnostic output only, never protocol data.
5. ccuv validates the timeout, exit status, JSON, version, IDs, schema, and
   decimal values.

The protocol identifier is `ccuv.custom/v1`. ccuv generates `request_id` for
each physical execution. Equivalent in-flight Dashboard requests may coalesce,
so that ID identifies the one shared execution rather than a pane lifecycle.

The first normal chart request also discovers capabilities. There is no separate
`describe` request. Every successful chart result is self-describing: it carries
the full capability manifest, localized dataset metadata, and data. Summary
facts arrive through a separate request. The command must be stateless; a result
must not depend on a previous command process.

## Requests

A chart request has inclusive calendar dates. Version 1 has no timestamps, time
zones, hours, rolling windows, or sub-day fields.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "wechat-reading",
  "range": {"start_date": "2026-09-17", "end_date": "2026-09-30"},
  "query": {
    "filters": {"category": ["literature"]},
    "group_by": "book",
    "granularity": "day"
  }
}
```

`range` supplies graph coverage. `query` supplies source-side business filters,
grouping, and aggregation. ccuv does not send style, theme, density, legend,
sort order, Top N, Other, pane geometry, or layout.

A summary request contains the resolved, inclusive intervals for exactly one
user-facing scope. ccuv performs all calendar translation: commands must use
these intervals directly and must not reconstruct “this month” or comparisons.
Only present comparison intervals are requested.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "wechat-reading",
  "query": {"filters": {"category": ["literature"]}},
  "summary": {
    "scope": "month",
    "intervals": {
      "current": {"start_date": "2026-09-01", "end_date": "2026-09-30"},
      "sequential": {"start_date": "2026-08-01", "end_date": "2026-08-30"},
      "year_over_year": {"start_date": "2025-09-01", "end_date": "2025-09-30"}
    }
  }
}
```

The Dashboard displays one summary per dataset ID. It scans visible panes in
pane order and uses the first pane’s command and filter context for that ID at a
Header refresh boundary; duplicate-ID panes continue to query independently.
A same-ID pane command edit does not replace the accepted Header result until a
later Header-owned refresh. Header metrics remain independent from token totals.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "wechat-reading",
  "status": "ok",
  "summary": {
    "metric": {
      "id": "pages-read",
      "label": {"en": "Pages read", "zh-CN": "阅读页数"},
      "current": {
        "value": "68",
        "display": {"en": "68 pages", "zh-CN": "68 页"}
      },
      "sequential": {"status": "ready", "base_value": "56"},
      "year_over_year": {"status": "ready", "base_value": "50"}
    }
  }
}
```

## Successful responses and numbers

A successful chart response includes `protocol`, `request_id`, `request_kind`,
`dataset_id`, `status: "ok"`, `dataset`, `capabilities`, and `data`. A successful
summary response contains only `summary.metric`. Dataset titles/descriptions,
unit labels, dimension/filter labels and options, series labels, metric labels,
source display text, and returned messages must always include both `en` and
`zh-CN`. ccuv selects its active language.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "wechat-reading",
  "status": "ok",
  "dataset": {
    "title": {"en": "WeChat Reading", "zh-CN": "微信读书"},
    "description": {"en": "Daily pages read", "zh-CN": "每日阅读页数"},
    "unit": {"id": "page", "label": {"en": "pages", "zh-CN": "页"}, "placement": "suffix", "decimal_places": 0}
  },
  "capabilities": {},
  "data": {"series": [{"id": "book-001", "label": {"en": "One Hundred Years of Solitude", "zh-CN": "百年孤独"}, "points": [{"date": "2026-09-17", "value": "28"}]}]}
}
```

All metric values and comparison base values are decimal **strings** in ordinary
signed decimal notation. ccuv parses them as exact `Decimal` values. JSON
numbers, blank strings, scientific notation, `NaN`, and infinities are invalid. Each dataset chart
metric has one fixed unit and dimension and must be additive. Supported examples
include counts, amounts, and byte totals. Averages, rates, percentages, unique
users, min/max values, percentiles, balances, and snapshots are excluded.

The command filters the requested inclusive range, applies business rules,
aggregates by the requested dimension (or returns sole `total` when grouping is
null), and returns every candidate series. ccuv sorts candidates, calculates
Top N and Other, cumulative display forms, comparisons, and all presentation.
Do not pre-select Top N, substitute unsupported requests, or return formatted
numbers or percentages.

## Capabilities and charts

Every success returns the complete stable capability manifest. It declares the
supported query surface, not keyboard bindings. Version 1 exposes enumerated
multi-select filters only; no text/range/regex filters, pagination, search, or
hierarchies. An unsupported grouping, filter, granularity, or combination must
be rejected rather than weakened or silently changed.

Each chart declaration lists permitted granularities, grouping dimensions, and
filters. Timeline, Stack, and Ranking use total or grouped date series.
Calendar requires an ungrouped daily total. The protocol and projection
capability-validate period, grouping, granularity, filter IDs, and selected
filter option IDs. The Dashboard only shows `g`, `b`, and `f` after a successful
response declares the corresponding capability; it never weakens an unsupported
selection. Local Top N/Other changes remain display-only and do not start a
command query.

Summary values use the active filters but not grouping, Top N, or Other.
Summary responses return exactly one `metric`: its `current.value` and ready
comparison `base_value` fields are Decimal strings, while `current.display` is
the source-authoritative localized primary text. `ready` includes `base_value`;
`pending` and `unavailable` omit it. ccuv owns comparison direction, percentage,
colors, and localized surrounding copy. Week summaries request the previous full
week and omit year-over-year; year summaries omit sequential; explicit fixed
ranges omit both comparisons.

## Errors, source edits, and logs

A protocol error is a valid JSON response with `status: "error"`, a localized
message, and one of these stable codes:

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "wechat-reading",
  "status": "error",
  "error": {
    "code": "unsupported_query",
    "message": {"en": "Monthly grouping by author is not available.", "zh-CN": "暂不支持按作者进行月度聚合。"},
    "unsupported": {"field": "query.granularity", "value": "month"}
  }
}
```

- `unsupported_dataset`
- `unsupported_chart_kind`
- `unsupported_query`
- `invalid_request`
- `invalid_filter`
- `range_not_available`
- `source_unavailable`
- `internal_error`

ccuv keeps the last valid result and rendering after a failed source query,
then shows the error alongside that result. Its candidate source configuration
remains available for correction. Empty series is not an error: return
`status: "ok"`, an empty series list, and valid zero/pending/unavailable summary
values.

Malformed output, mismatched IDs, invalid decimals, missing localized text,
unknown protocol versions, timeouts, spawn failures, and nonzero exits without a
valid protocol error are source/protocol failures. stderr may appear in bounded
diagnostics but is never parsed into a result.

Only exact concurrent requests coalesce. Identity includes argv and execution
context, dataset ID, request kind, inclusive range, normalized filters (sorted
keys and choices), grouping, granularity, and summary period/as-of date. It
excludes chart kind, style, theme, density, legend, Top N, Other, layout, and
pane position. Version 1 has no overlapping-range merge, interval/range union,
completed-result cache, batching, or result slicing.

Custom Dashboard panes provide **Source** (`e`) to edit Dataset ID and argv
through the Tab-navigable form. Enter validates the draft and starts a query.
A data-affecting replacement immediately shows the candidate title and loading
state rather than the previous chart; a failed query restores the accepted
rendering with its error. `L` opens bounded per-pane **Logs** and `y` copies
them; `l` remains reserved for the built-in legend shortcut. Logs contain
successful query diagnostics and failures only; they never parse or display
protocol stdout as result data.
