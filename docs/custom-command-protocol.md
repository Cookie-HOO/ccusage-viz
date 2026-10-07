# Custom command protocol guide

[简体中文](custom-command-protocol.zh-CN.md)

`ccuv chart <kind> --dataset ID` adapts a command that can return one additive
historical metric. It is for data such as reading, CI activity, spend amounts,
build counts, or byte totals. ccuv owns terminal presentation; the command owns
the source-specific query and aggregation.

This is a command protocol, not a plugin or persistence system. Version 1 does
not support file, HTTP, stdin, Python-plugin, or Monitor sources. It does not
cache completed command results, discover commands, combine query ranges, or
support non-additive metrics.

## Version 2 metrics

`ccuv.custom/v2` changes the Dataset boundary from one metric per Dataset to
one Dataset with one or more declared metrics. Select a Dataset, then a metric,
then a chart kind. A command may set `default_metric_id`; ccuv uses it only when
`--metric` is omitted. Without a declared default, omission is allowed only when
the Dataset has exactly one metric.

Each metric declares `aggregation: "sum"` or `aggregation: "value"`.
`sum` permits ccuv to aggregate returned facts for historical projections.
`value` is source-owned: ccuv displays only the exact query result and asks the
Dataset again whenever range, grouping, granularity, filters, or chart changes.

V2 metrics may declare `monitor`. A Monitor metric declares its fixed business
`window_seconds` and may declare `refresh_interval_seconds`. ccuv's Monitor
display history remains local and does not alter the metric's business window.
The existing Dashboard sampling interval remains authoritative; a differing
declared refresh interval is shown as a warning. Custom Monitor supports bars,
ranking, and list views. It does not offer `cumulative-bars`, because a fixed
rolling observation is not a non-overlapping cumulative increment.

Custom Monitor requests contain a timezone-aware `range.end_at`. The Dataset
calculates its declared fixed window ending there and returns its source-owned
total and groups. If the source cannot answer that window, it returns
`range_not_available`; ccuv shows that error and never replaces it with zero.

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "pane:router:2",
  "request_kind": "monitor",
  "dataset_id": "router",
  "metric_id": "tokens",
  "timezone": "Asia/Shanghai",
  "range": {"end_at": "2026-10-08T10:00:00+08:00"},
  "query": {"filters": {}, "group_by": "real_model"}
}
```

## Start a custom chart

Choose a chart kind and one source mode. A Dataset declares its stable ID through
its metadata-only probe; ccuv does not ask a local command user to invent one.

```bash
# Registered Dataset: chart kind + Dataset ID, resolved from ccuv's Dataset store.
ccuv chart timeline --dataset weread

# Arbitrary developer command: chart kind + temporary Dataset ID + command argv.
ccuv chart timeline --dataset example --command 'example-reader ccuv'
ccuv chart stack --dataset example --command 'example-reader ccuv'
ccuv chart calendar --dataset example --command 'example-reader ccuv'
ccuv chart ranking --dataset example --command 'example-reader ccuv'
```

`--dataset` is required. It is the stable identity of the source and every
response must echo it exactly. Without `--command`, `--dataset ID` resolves and
validates the locally installed Dataset; it never requires the user to supply its
executable path.
`--command` is split into argv with `shlex.split` and runs without a shell. To
deliberately use shell behavior, make the shell part of argv yourself:

```bash
ccuv chart timeline --dataset example --command "sh -lc 'collector | adapter'"
```

A custom chart begins with a 14-day, ungrouped total graph and a day-period
summary. Custom data cannot use `monitor`. The Dashboard pane always exposes
`p`/`P` to cycle the shared rolling graph range (`7d → 14d → 30d → 90d → 180d → 365d → 1w → 1mo → 1y`). `1w`, `1mo`, and `1y` mean This week, This month, and This year. After the first successful response,
it also exposes capability-gated query controls: `g` cycles declared
granularities, `b` cycles total and declared groupings, and `f` edits declared
filter options. Each such adjustment starts a new command query. Source editing
(`e`) and diagnostic Logs (`L`) are also available. Lowercase `l` cycles the
custom Timeline/Stack legend; uppercase `L` is reserved for Logs.

A standalone custom chart continuously refreshes by issuing `ccuv.custom/v1`
chart requests to its configured command. It does not run `ccusage` historical
acquisition or watch processing. A data-affecting replacement immediately
shows the candidate chart title and loading state, without stale facts or a
`querying` annotation. A same-query refresh failure may retain its accepted
chart with the custom-source error alongside it. A failed replacement query
never renders numeric facts from a different selection: ccuv keeps only the
candidate title/range and the error.

## Use custom panes in a Dashboard

Use ordinary ordered `--pane` fragments. The Dataset may appear in more than
one pane only when all uses have the same source configuration. Installed Dataset
panes require only chart kind and Dataset ID; arbitrary commands remain available
for developer integrations.

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'empty' \
  --pane 'chart timeline --dataset weread' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

Dashboard presets remain the built-in token-consumption templates; adding a
Dataset pane does not create or modify a Dataset preset.

`dashboard --empty` suppresses default ccusage panes and their default data
dependencies. It uses the normal default Dashboard layout and fills it with
`empty` panes; `--grid` or an explicit layout sets their initial count and
placement. It does not add a clock. Existing `wide-clock` and `narrow-clock`
presets retain their clock pane.

After a custom Dashboard pane is selected, `v` and `V` cycle forward and backward
through chart, compact command, full command, data table, and JSON views. The
data views serialize ccuv's current locally projected chart data: they honor the
active range, filters, grouping, granularity, Top/Other selection, and unit
precision. JSON keeps canonical series IDs and Decimal values as strings beside
localized display labels; it does not expose an opaque raw process response.

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
and insert-after chooser. Selecting Datasets lets a user choose an installed
Dataset and then Timeline, Stack, Calendar, or Ranking—no command path is shown.
Selecting Local command uses the advanced Dataset ID and Command fields. The new
custom pane starts its initial query after replacement; the pane displays the
resulting source error if that query fails. Insertion can also create an Empty pane.
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

Every successful chart result remains self-describing: it carries the effective
capability manifest, localized dataset metadata, and data. Summary facts arrive
through a separate request. The command must be stateless; a result must not
depend on a previous command process.

A `probe` is a metadata-only request for Dataset registration and explicit
refresh. It has no timezone, range, query, or summary fields. It must not read
business data, verify credentials, mutate state, or create a business-data
gateway. It returns the stable descriptor, including declared environment
variables and chart defaults; a later chart response remains authoritative for
that individual query.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "probe-request-id",
  "request_kind": "probe"
}
```

## Requests

A chart request has inclusive calendar dates and a required IANA `timezone`.
ccuv resolves its global `--timezone` (or the local system IANA timezone by
default) before every request. The timezone is request context, not a capability:
it tells a Dataset how ccuv interpreted the date boundaries. Version 1 has no
timestamps, hours, or sub-day fields. `range.period` is additive metadata within
`ccuv.custom/v1` for the selected rolling preset; it does not replace the
absolute date boundaries or change the protocol version.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "weread",
  "timezone": "Asia/Shanghai",
  "range": {"start_date": "2026-09-17", "end_date": "2026-09-30", "period": "14d"},
  "query": {
    "filters": {"category": ["literature"]},
    "group_by": "book",
    "granularity": "day"
  }
}
```

`range.start_date` and `range.end_date` are inclusive, resolved, and authoritative graph coverage. `range.period` is the canonical rolling-period spelling (`1w`, `1mo`, and `1y` carry natural week-to-date, month-to-date, and year-to-date intent); it is `null` for a fixed `--since`/`--until` range. A Dataset may use it for source-specific semantics but must not replace the supplied dates. `query` supplies source-side business filters, grouping, and aggregation. ccuv does not send style, theme, density, legend,
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
  "dataset_id": "weread",
  "timezone": "Asia/Shanghai",
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
pane order and uses the first pane’s command for that ID; duplicate-ID panes
continue to query independently. Header summaries always use empty filters and
ignore Pane grouping, granularity, graph range, and presentation settings. When
that first pane’s command changes, ccuv immediately suppresses the previously
accepted Header metric and starts a replacement Header-owned refresh. Header
metrics remain independent from token totals.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "weread",
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
summary response contains `summary.metric`. Either successful response may also
include a non-blocking `warnings` array. Each warning has an open-ended stable
`code` and a localized `message`; ccuv shows it while retaining the successful
chart or summary. Dataset titles/descriptions,
unit labels, dimension/filter labels and options, series labels, metric labels,
source display text, and returned messages must always include both `en` and
`zh-CN`. ccuv selects its active language.

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "weread",
  "status": "ok",
  "warnings": [
    {
      "code": "timezone_not_supported",
      "message": {
        "en": "WeRead uses Asia/Shanghai; the requested timezone was not applied.",
        "zh-CN": "微信读书使用 Asia/Shanghai；未应用请求的时区。"
      }
    }
  ],
  "dataset": {
    "title": {"en": "WeRead", "zh-CN": "微信读书"},
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

For example, the WeRead Dataset currently uses `Asia/Shanghai` for source-date
semantics. It accepts every valid request timezone; when the requested timezone
is not `Asia/Shanghai`, it successfully returns Shanghai-based data with a
`timezone_not_supported` warning instead of turning the successful query into an
error. Datasets declare their own units and precision. WeRead reports reading
minutes to two decimals: it aggregates raw seconds before converting and
rounding summaries, so the sum of individually rounded days can differ from a
total by `0.01` minute.

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
Calendar requires an ungrouped daily total. A Dataset owns source-specific
combination rules—such as an otherwise declared grouping that is available only
for particular `range.period` values—and returns its correlated
`unsupported_query` response when the selected combination is unavailable.
ccuv sends the selected query unchanged: it does not maintain a Dataset-specific
compatibility matrix, substitute Total data, or select another period. The
protocol and projection capability-validate period syntax, grouping,
granularity, filter IDs, and selected filter option IDs. The Dashboard only shows
`g`, `b`, and `f` after a successful response declares the corresponding
capability. Local Top N/Other changes remain display-only and do not start a
command query.

A Dataset may represent an official period aggregate in a Ranking response with
one point per entity at the request `end_date`. That point is a coordinate for
Ranking projection, not daily attribution; its value is the source aggregate.
Such a Dataset must declare the grouping only for Ranking, not for Timeline,
Stack, or Calendar unless it also supplies the respective source-backed data.

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
  "dataset_id": "weread",
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

`unsupported` is optional, but a Dataset should include it for every user-correctable
selection failure. Its exact `field` and requested `value` identify the rejected
control. In particular, use `{"field": "range.period", "value": "<period>"}`
when the selected rolling period is unavailable. ccuv then clears an older chart:
leaving it visible would imply that the period switch did not apply. For every
other field, ccuv retains a prior accepted chart when one exists and shows the
warning beside it. Other replacement failures clear prior numeric facts when
the request-affecting identity differs; the titled candidate error surface then
shows the current selection without a chart from another query.

Dataset error messages are localized, actionable UI copy. Both variants should
identify the rejected choice and name supported alternatives where applicable.
They must not prescribe ccuv shortcuts or controls: a Dataset can run under
multiple hosts, and the host renders the controls available in its current
surface. Do not silently substitute a different period or query.

ccuv compares a failed request's data-affecting identity—source, chart kind,
inclusive range plus `range.period`, filters, grouping, and granularity—with the
accepted query. A same-query refresh may retain valid facts, while a failed
replacement clears them and retains only localized Dataset metadata for the
candidate title/range. This is Dataset-neutral and never depends on specific
period names, Dataset IDs, or source endpoints. Empty series is not an error:
return `status: "ok"`, an empty series list, and valid zero/pending/unavailable
summary values.

Malformed output, mismatched IDs, invalid decimals, missing localized text,
unknown protocol versions, timeouts, spawn failures, and nonzero exits without a
valid protocol error are source/protocol failures. stderr may appear in bounded
diagnostics but is never parsed into a result.

Only exact concurrent requests coalesce. Identity includes argv and execution
context, dataset ID, request kind, timezone, inclusive range **and its
`range.period` semantic**, normalized filters (sorted keys and choices), grouping,
granularity, and summary period/as-of date. Thus, equal resolved dates with
different selected period semantics never share an execution. Identity excludes
chart kind, style, theme, density, legend, Top N, Other, layout, and pane
position. Version 1 has no overlapping-range merge, interval/range union,
completed-result cache, batching, or result slicing.

Custom Dashboard panes provide **Source** (`e`). Installed Dataset panes edit
only chart type and Dataset ID, then revalidate the local installation; arbitrary
command panes edit Dataset ID and argv through the Tab-navigable form. Enter
validates the draft and starts a query. A data-affecting replacement immediately
shows the candidate title and loading state rather than the previous chart. A
same-query refresh failure may retain accepted facts with its error; a failed
replacement keeps only the candidate title/range and error. `L` opens bounded
per-pane **Logs** and `y` copies them; `l` remains reserved for the built-in
legend shortcut. Logs contain successful query diagnostics and failures only;
they never parse or display protocol stdout as result data.
