# Custom command protocol guide

[简体中文](custom-command-protocol.zh-CN.md)

`ccuv chart <kind> --dataset ID` adapts an executable Dataset command to ccuv.
The current V2 protocol supports multiple additive or source-owned Metrics,
historical charts, and source-owned Monitor observations; the legacy V1
protocol supports one additive historical metric. ccuv owns terminal
presentation, while the command owns source-specific querying and aggregation.

This is a command protocol, not a plugin or persistence system. ccuv starts the
executable with one JSON request on stdin and reads one JSON response from
stdout. It does not load Python plugins, cache completed command results, or
combine query ranges. Version 1 does not support Monitor or non-additive
metrics; Version 2 does.

## Version 2 metrics

`ccuv.custom/v2` changes the Dataset boundary from one metric per Dataset to
one Dataset with one or more declared metrics. Select a Dataset, then a metric,
then a chart kind. A command may set `default_metric_id`; ccuv uses it only when
`--metric` is omitted. Without a declared default, omission is allowed only when
the Dataset has exactly one metric.

Each metric declares `aggregation: "sum"` or `aggregation: "value"`.

Every Metric's existing required bilingual `description` is localized explanatory metadata for that Metric. Hosts may show it beneath the Metric title during Metric selection and in help for the currently selected Pane. It does not alter request shape, metric ID, aggregation, or data semantics.

### V2 Metric Groups

A V2 descriptor may declare an ordered top-level `metric_groups` array. Each
Group has a stable Dataset-local `id` and a required bilingual `title`. A Metric
may optionally reference one declared Group through `group_id`:

```json
{
  "metric_groups": [
    {"id": "github-tools", "title": {"en": "GitHub tools", "zh-CN": "GitHub 工具"}}
  ],
  "metrics": [
    {"id": "stars", "group_id": "github-tools", "...": "..."},
    {"id": "updated_days_ago", "group_id": "github-tools", "...": "..."}
  ]
}
```

Group IDs must be unique, and every `group_id` must reference a declared Group.
Groups may be empty. A Dataset that omits `metric_groups` is fully compatible
with earlier V2 behavior: its Metric chooser is flat and it has no related-
Metric quick-switch relation. When Groups are declared, hosts render nonempty
Groups in declaration order and their members in Metric declaration order;
Metrics without `group_id` remain ordinary flat entries after the Groups.

A Group defines a coherent quick-switch boundary, not shared Metric semantics.
Each Metric still independently owns its unit, aggregation, capabilities,
defaults, summary, data, display, and source validation. Hosts may use `m/M`
to cycle same-Group Metrics that support the active chart kind; this only sends
a normal request with the target `metric_id` and adds no request field.
`sum` permits ccuv to aggregate returned dated facts for Timeline, Stack, and
Calendar projections. `value` is source-owned: ccuv displays only the exact
query result and asks the Dataset again whenever a data-affecting range,
grouping, filter, or chart choice changes. V2 Ranking is scalar for either
aggregation mode: the Dataset computes each entry's complete-range `value`,
while ccuv may still sort returned entries and derive Top, Other, shares, and
comparisons across them. Non-Ranking historical charts also requery for
granularity changes; V2 Ranking has no granularity.

Local Dataset registration caches its successful Probe for discovery, environment
state, and the nonblocking chooser. Re-running `ccuv dataset add-local COMMAND`
replaces an existing local registration with the same Dataset ID and refreshes
that cache. A Custom Monitor Pane still performs a new runtime Probe before it
starts sampling; cached metadata is never its final capability authority.

Every successful V2 `chart` and `monitor` response is a complete accepted
snapshot: it includes the full Probe-shaped `descriptor`, a `runtime` object,
and its `data` or `observation`. After the initial Probe chooses the Dataset and
Metric, ccuv reads static controls from the latest accepted response descriptor.
`runtime.filters` is required (and may be empty); it is the only filter catalog
that ccuv offers through `f`. Probe descriptors and static chart capabilities do
not declare filters or option values. Every runtime filter has `mode:
"multi_select"` or `"single_select"`; omitted mode means `"multi_select"`.
Both modes use the existing query array of option IDs, but ccuv sends at most
one ID for a `single_select` filter. The Dataset remains authoritative for
whether an empty selection is valid or required.

Dataset authors should prefer `single_select` for mutually exclusive source
modes and clear ranges, such as `Within 7 days`, `Within 30 days`, and `Any
time`; combining those ranges is ambiguous and hard to present. Use
`multi_select` only when users genuinely combine independent discrete values,
such as languages, categories, tags, authors, or shelf labels.

V2 metrics may declare `summary: "comparisons" | "total" | "none"`.
`comparisons` is the default and permits the ordinary current/sequential/year-over-year
summary. `total` permits only one total value. `none` suppresses Dataset summary
acquisition. A historical chart capability may declare its supported `periods`.
When present, ccuv limits `p/P` to that ordered list. A V2 Ranking may include
positive-integer `Ns`, `Nm`, and `Nh` periods (seconds, minutes, and hours).
The Dataset owns the exact spellings and declaration order: ccuv neither sorts
nor normalizes them, so `90s` remains `90s`. Omission keeps ccuv's legacy period
fallback and does not add built-in subday periods. Existing `d`, `w`, `mo`, `q`,
`y`, and `all` meanings are unchanged; in particular, `1d` is a calendar-date
period, not the last 24 hours. `all` is Ranking-only: ccuv sends `period: "all"`
with an anchored range from `1971-01-01` through today. The marker, not the
anchor date, means all source data. Datasets must reject unsupported periods
with their existing `unsupported_query` response for `range.period`.

Each chart's `group_by` is also an ordered set of permitted query values. Use
JSON `null` to permit the ungrouped total; dimension IDs remain strings, so a
dimension named `total` is unambiguous. When either declared list prevents a
requested change, ccuv keeps the current query and shows a short notice rather
than sending an unsupported request. Omit `periods` to let ccuv use its normal
period cycle and let the Dataset dynamically interpret each request.

### Grouped V2 Ranking

A V2 Metric may give Ranking an optional outer partition. The Metric can declare
a separate ordered partition-dimension catalog; if it omits that catalog,
partition IDs and labels fall back to the existing `capabilities.group_by`
catalog. `group_by` IDs always use the grouping catalog.

```json
"capabilities": {
  "group_by": [
    {"id": "real_model", "label": {"en": "Real Model", "zh-CN": "真实模型"}}
  ],
  "partition_by": [
    {"id": "logical_model", "label": {"en": "Logical Model", "zh-CN": "逻辑模型"}}
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
```

`capabilities.charts.ranking.partition_by` is Ranking-only. Omitting it keeps
the old flat capability and wire format. A declared list containing `null`
allows flat Ranking; a list without `null` requires a partition. An active
partition requires a non-null grouping, and the active `partition_by` and
`group_by` IDs must differ. Every non-null partition ID must occur in the
explicit partition catalog, or in the grouping catalog when the partition
catalog is omitted. Invalid references or combinations reject the descriptor;
ccuv does not silently downgrade them.

### V2 chart defaults

Each Metric may use `defaults` to suggest its initial state for a chart. This is
a best-effort presentation and query suggestion, not a validity requirement:
ccuv ignores an invalid field and keeps its standalone or Dashboard default.
An explicit CLI or Dashboard Pane option overrides the Dataset field.

```json
"defaults": {
  "timeline": {
    "period": "30d",
    "granularity": "week",
    "group_by": "book",
    "top": 8,
    "other": "hide",
    "style": "line-points",
    "theme": "nord"
  },
  "ranking": {
    "period": "14d",
    "partition_by": "logical_model",
    "group_by": "real_model",
    "top": 3
  },
  "monitor": {"style": "ranking", "window": "6h"}
}
```

All fields are optional. `period` and `group_by` must be supported by the
selected chart capability; non-Ranking `granularity` must also be supported.
A legacy Ranking `granularity` default is accepted but ignored. `top` needs a
valid final grouping; style must be compatible with that grouping. `partition_by` is valid only
for Ranking and must follow the declared partition capability. A non-null
partition default requires a non-null, different `group_by`; invalid default
combinations reject the descriptor. `other` is `"show"` or `"hide"`. `theme`
and `style` use ccuv's ordinary CLI values. Filters have no static default:
their IDs and options are response-owned `runtime.filters`.

Explicit CLI and Dashboard Pane settings override Dataset defaults. Dashboard
presets persist `partition_by`; older presets omit it and remain flat. When a
Metric switch needs normalization, ccuv chooses the target's valid partition
default, otherwise `null` when allowed or the first required partition, then
chooses a non-conflicting grouping.

`defaults.top` is only the first-screen Top N suggestion. For a historical
Ranking, `capabilities.charts.ranking.max_items` may declare a positive
source-owned upper bound on raw ranking items. It is not a display default.
ccuv includes the selected Top as optional `query.top`, which expresses both
the visible Top N and the requested raw ranking coverage; Datasets may return
more entries when needed for an honest `Other` row. A `null` query value means
no requested Top bound. ccuv retains user selections above `max_items`, but
reports the source limit rather than issuing a request that cannot add entries.

For compatibility with older Dataset descriptors, a Ranking capability may
still declare `descriptions_default: "expanded" | "collapsed"`; ccuv accepts
but ignores the field. Entry-description visibility is controlled only by
Ranking density: `full` and `detailed` show descriptions, while `minimal`,
`compact`, and `normal` hide them.

A Ranking capability may declare `comparison: "full" | "rank" | "none"`;
the default is `"full"`. `"rank"` still asks for the prior equal-duration
range and displays rank movement, but hides the absolute-growth column.
`"none"` suppresses the prior-range request and all Ranking comparison columns.

A Ranking capability may also declare `sort_direction: "ascending" |
"descending"`; omission defaults to `"descending"`. It is Dataset-owned Metric
semantics, not a host preference: ccuv applies it before Ranking order, Top N,
Other, and rank-comparison derivation. It does not change numeric values,
units, Dataset `display`, or comparison facts. There is no CLI, Dashboard, or
keyboard override; switching Metrics applies the target Metric's declared
direction. Use `"ascending"` for a fact such as days since last update when
smaller values should appear first, and `"descending"` for Stars, growth,
ratings, or counts when larger values should appear first.

#### Grouped request compatibility

An undeclared partition capability leaves `query.partition_by` absent. Once the
Ranking capability declares `partition_by`, every request includes the selected
value: either a dimension ID or explicit JSON `null`. The explicit null tells a
partition-aware Dataset that a capable client selected flat mode.

```json
{
  "chart_kind": "ranking",
  "query": {
    "filters": {},
    "partition_by": "logical_model",
    "group_by": "real_model",
    "top": 3
  }
}
```

Every V2 historical request explicitly includes top-level `chart_kind`, including
non-Ranking requests. V2 Ranking requests omit `query.granularity`. A legacy
Ranking capability or default may still contain granularity metadata; ccuv
accepts but ignores it and never uses it for validation, matching, refresh, or
request identity.

`query.top` keeps its source-coverage meaning. The Dataset decides how many raw
series to return in each group and may return fewer than, exactly, or more than
N; ccuv never treats omitted source entries as zero or infers an omitted
remainder.

#### Flat and grouped response shapes

A flat request, including a declared explicit-null partition, requires the
existing `data.series` container. A non-null partition requires `data.groups`.
`series` and `groups` are mutually exclusive. In both containers, V2 Ranking
entries are scalar:

```json
{
  "data": {
    "series": [
      {
        "id": "seed-code",
        "label": {"en": "Seed Code", "zh-CN": "豆包代码模型"},
        "value": "7100"
      }
    ]
  }
}
```

A partitioned response nests the same scalar entries:

```json
{
  "data": {
    "groups": [
    {
      "id": "coding",
      "label": {"en": "Coding Model", "zh-CN": "代码模型"},
      "description": {
        "en": "Routes coding workloads",
        "zh-CN": "面向代码场景的逻辑路由"
      },
      "display": {"en": "12.4K requests", "zh-CN": "1.24 万次请求"},
      "comparison_display": {
        "en": "+1.8K requests",
        "zh-CN": "+1800 次请求"
      },
      "link": "https://example.com/router/coding",
      "series": [
        {
          "id": "seed-code",
          "label": {"en": "Seed Code", "zh-CN": "豆包代码模型"},
          "value": "7100"
        }
      ]
    }
  ]
  }
}
```

Group IDs must be unique. Series IDs must be unique within a group, but may
repeat in different groups; stable inner identity is `(group.id, series.id)`.
Groups retain Dataset response order and may be empty. `label` is required.
Optional `description`, `display`, `comparison_display`, and absolute HTTPS
`link` have the same localization, safety, and presentation rules as Ranking
series metadata. Inner series use the V2 Ranking scalar-entry schema and metadata. Each entry
must contain exactly one decimal-string `value` and must not contain `points`,
a date, or a timestamp. The Dataset computes the authoritative value for the
requested range—whether it is a sum, percentile, growth value, or another
existing source algorithm—and ccuv never reconstructs it from time-series
points. `max_items` bounds the sum of all returned inner series, not the number
of groups. Any invalid group or series rejects the whole response.

ccuv sums returned scalar entries to form each group total, then sums group
totals to form the global total. There is no separate numeric group-total field:
optional `group.display` changes only its formatted text. For `period: "all"`,
the anchored dates and `all` marker retain their existing meaning, and ccuv
makes no prior-period request.

Outer groups are never sorted, ranked, or limited by Top. Inside every group,
ccuv independently applies the Metric's sort direction, uses series ID as the
equal-value tie-breaker, restarts numbering at 1, and applies Top N. `Other` is
the arithmetic sum of actual returned series beyond N and is shown or hidden by
the existing setting; it is never inferred from a separate total. Signed
Decimal values, including negative entries and negative Other, are not clamped
or reinterpreted.

With `show_percentage: true`, a group's share is its returned total divided by
the global returned total, while an item's share is its total divided by its
returned group total. These denominators are established before Top/Other
visibility, search, or scrolling. A zero global total omits group shares; a zero
group total omits that group's item shares. Source facts may legitimately yield
negative shares or shares above 100%.

Search matches inner series labels, descriptions, safe link text, and link URLs;
it does not match group metadata. Groups without matching inner rows are hidden.
Search changes visibility only: original within-group ranks, totals, shares, bar
scales, and comparisons still come from the complete latest response. A refresh
rebuilds those facts before reapplying the unchanged search. Copy All follows
Dataset group order, includes group headings, honors Top/Other, and during search
copies only matching inner series under their headings.

For ordinary comparison periods, flat entries match by item ID. Grouped results
first match group ID, then match entries by the stable `(group.id, series.id)`
pair. Current and previous totals each use only the scalar entries actually
returned in that response; differing response coverage is not filled with zero.
A missing prior group or series is new, and moving a series to another group
makes it new there. Group totals may show value comparison but not outer rank
movement; inner rows retain their independent within-group comparison. `Other`
has no comparison.

For a Custom Monitor, `window` is ccuv's local display horizon (`5m` through
`24h`), not the source business window. The fixed request interval remains
`capabilities.charts.monitor.window_seconds`.

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

Each observation group may include optional localized `description` and
`display` fields, matching Custom Ranking series metadata. In Monitor `ranking`,
`description` appears below the row only at `full` or `detailed` density;
Monitor `list` never shows it. `display` replaces the row's numeric value text
in `ranking` and `list`. The numeric `value` remains authoritative for sorting,
bar lengths, Top/Other projection, and time-based charts. Bars and timeline
views use neither field. Empty localized fields are treated as absent; malformed
supplied localized fields reject the response.

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

# A declared V2 partition: independently rank real models within each logical model.
ccuv chart ranking --dataset router --partition-by logical_model --group-by real_model
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

A legacy V1 chart begins with a 14-day, ungrouped total graph and a day-period
summary. A V2 Metric may instead declare compatible startup defaults and may
support `monitor`. A historical Dataset pane exposes `p`/`P` to cycle the
Metric's declared periods, or the shared fallback range when none are declared
(`7d → 14d → 30d → 90d → 180d → 365d → 1w → 1mo → 1y`). `1w`, `1mo`, and `1y` mean This week, This month, and This year. After the first successful response,
it also exposes capability-gated query controls. For ordinary historical
charts, `g` cycles granularities and `b` cycles total and declared groupings.
For a grouped-capable Ranking, Quick `g/G` cycles declared outer partitions and
`b/B` cycles inner grouping dimensions; both directions skip the other active
dimension, and an unavailable alternative keeps the valid query with a short
notice. Quick `s/S` changes style. Advanced `s/S` changes Ranking spacing, `o`
changes Other, and `f` edits filters; filters are Advanced for all Dashboard
chart panes. Focused Dataset charts use the same Quick/Advanced Pane controls as Dashboard.
Data-affecting partition, grouping, and filter adjustments start a new command
query; spacing is presentation-only. Source editing
(`e`) and diagnostic Logs (`L`) are also available. Lowercase `l` cycles the
custom Timeline/Stack legend; uppercase `L` is reserved for Logs.

A focused Dataset chart continuously refreshes by issuing the selected
Dataset protocol's chart or monitor requests to its configured command. It does
not run `ccusage` historical acquisition or watch processing. A data-affecting replacement immediately
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
ccuv dashboard --empty --columns 2 --spotlight 0 \
  --pane 'empty' \
  --pane 'chart timeline --dataset weread' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

Dashboard presets begin with built-in token-consumption templates, and the
Dashboard preset manager can also save complete user configurations. In browse
mode, press `Ctrl-S` to save and `P` to manage saved presets. Presets retain installed
Dataset identities, local-command Dataset argv, and command-driven overlays.
They are trusted user-local automation: loading a preset can execute its commands,
so only load presets you trust. Presets never contain environment variables,
credentials, results, or runtime/UI state.

User names match `^[a-z][a-z0-9-]*$`. They can shadow built-ins: user-first
resolution loads the saved record, while deleting the user override exposes the
same-named built-in again. The manager asks before overwriting an existing user
preset or deleting one. A name is launchable as `ccuv dashboard <name>`; that
closed form accepts only `--demo`, `--lang`, `--empty`, and `--ccusage-bin` as
additional options. A missing installed Dataset does not make a preset unavailable;
only unreadable, malformed, or unsupported preset storage is unavailable and
protected from writes.

`dashboard --empty` suppresses default ccusage panes and their default data
dependencies. It uses the normal default Dashboard layout and fills it with
`empty` panes; `--grid` or an explicit layout sets their initial count and
placement. It does not add a clock. Existing `wide-clock` and `narrow-clock`
presets retain their clock pane. For a named preset, `ccuv dashboard <name>
--empty` preserves that preset's layout, weights, display and cadence settings,
timezone, demo and safe process configuration, replacing only its panes in memory;
it never changes the stored preset. A demo-enabled preset remains demo-enabled.

After a custom Dashboard pane is selected, `v` and `V` cycle forward and backward
through chart, compact command, full command, data table, and JSON views. The
data views serialize ccuv's current locally projected chart data: they honor the
active range, filters, grouping, applicable non-Ranking granularity, Top/Other
selection, and unit precision. JSON keeps canonical series IDs and Decimal values as strings beside
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
and insert-after chooser. Selecting Datasets lets a user choose an installed Dataset, Metric, and one of
its declared historical or Monitor chart kinds—no command path is shown.
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

The wire identifier is `ccuv.custom/v1` for legacy requests and
`ccuv.custom/v2` for V2 Probe, chart, summary, and Monitor requests. ccuv
generates `request_id` for each physical execution. Equivalent in-flight
Dashboard requests may coalesce, so that ID identifies the one shared execution
rather than a pane lifecycle.

Every successful chart result remains self-describing: it carries the effective
capability manifest, localized dataset metadata, and data. Summary facts arrive
through a separate request. The command must be stateless; a result must not
depend on a previous command process.

For a non-fixed Ranking at `full` or `detailed` density, unless its Ranking
capability declares `comparison: "none"`, ccuv first requests the selected range
and then requests the contiguous prior range with the same duration. V1 keeps
its dated-series response contract. V2 returns scalar entries for both ranges;
ccuv matches flat item IDs, or grouped `(group.id, series.id)` pairs, and derives
displayed absolute growth and rank movement locally. A missing prior item is
new, never zero. No delta, previous-total, or previous-rank fields belong in the
protocol. A failed or unavailable prior-range response leaves the current
Ranking visible without comparison markers. `comparison: "rank"` uses that
response only for rank movement. Fixed date-range and `all` Rankings do not
request a prior range. For a subday range anchored at `T`, current is
`[T-duration, T)` and prior is `[T-2*duration, T-duration)`: both derive from the
same captured aware instant, so they cannot have a gap or overlap.

For a Ranking query only, a `data.series` item may include optional bilingual
`description`, `display`, `comparison_display`, and `link` fields. The first
three use the same
`{ "en": "...", "zh-CN": "..." }` shape as a label. `description` renders as a
muted, indented explanation below the Ranking item at `full` and `detailed`
density, wrapping to at most two terminal rows. `display` is the Dataset-owned formatted total shown in
the Ranking value column. `comparison_display` is the Dataset-owned formatted
absolute-change text shown in the prior-period comparison column when ccuv has
calculated a non-zero comparison. In V1, numeric `points[].value` facts remain the source for those calculations.
In V2 Ranking, the scalar `value` is authoritative for ranking, shares,
comparisons, colours, and rank movement. When either
display field is omitted, ccuv formats that value from the declared unit. A description may contain `[label](https://URL)` links,
`**bold text**`, and `*italic text*`; ccuv renders only `label` as a clickable
terminal hyperlink. Star emphasis is also allowed inside a link label. Underscore
emphasis and other Markdown,
HTML, malformed links, unsupported URL schemes, and terminal control sequences
remain plain safe text. Ranking search matches both labels and link URLs; a
URL-only match appends a clickable highlighted `↗` marker. Timeline, Stack, and
Calendar responses must not include these fields; ccuv rejects them there. The
locally composed `Other` row never receives any of these fields. `link` is one
absolute `https://` URL for the concrete Ranking project. ccuv renders it as a
clickable `↗` in the project's action group (`Project | ⊞ ↗`) and
includes the URL after the project label and description in the copied content.
Missing links show no icon. Timeline, Stack, and Calendar responses must not
include it, and unsafe or malformed URLs are rejected.

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

V2 historical chart requests additionally carry an explicit top-level
`chart_kind`. Timeline, Stack, and Calendar continue to use the inclusive dated
range and dated points above. V2 Ranking also uses that date form for day and
longer periods, but returns scalar values, never points. Only V2 Ranking may use
a declared positive-integer `Ns`, `Nm`, or `Nh` period; every such spelling,
including `24h` or `48h`, uses aware timestamps and an exact half-open range:

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "chart_kind": "ranking",
  "dataset_id": "router",
  "metric_id": "requests",
  "timezone": "Asia/Shanghai",
  "range": {
    "start_at": "2026-10-14T22:59:45+08:00",
    "end_at": "2026-10-14T23:00:00+08:00",
    "period": "15s"
  },
  "query": {"filters": {}, "group_by": "route", "top": 10}
}
```

Both timestamps must be timezone-aware, `start_at` must precede `end_at`, and
the Dataset must query exactly `[start_at, end_at)` without recomputing “now.”
A request contains one complete range form and never mixes date and timestamp
fields. Each refresh captures a new aware end instant; presentation-only changes
retain the accepted range. A timestamp-form Ranking has no date-based summary
request or summary display. Existing summaries for inclusive date-form Ranking
ranges (`d`, `w`, `mo`, `q`, or `y`) are unchanged.

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

A successful V1 chart response includes `protocol`, `request_id`, `request_kind`,
`dataset_id`, `status: "ok"`, `dataset`, `capabilities`, and `data`. A successful
V2 chart or Monitor response instead includes `descriptor`, `runtime`, and its
`data` or `observation`. A successful summary response contains `summary.metric`.
Either successful response may also
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
numbers, blank strings, scientific notation, `NaN`, and infinities are invalid.
A V1 Dataset has one fixed unit and additive metric; supported examples include
counts, amounts, and byte totals. V2 additionally supports source-owned
`aggregation: "value"` Metrics whose exact non-additive facts are returned by
the Dataset, as described above.

For example, the WeRead Dataset currently uses `Asia/Shanghai` for source-date
semantics. It accepts every valid request timezone; when the requested timezone
is not `Asia/Shanghai`, it successfully returns Shanghai-based data with a
`timezone_not_supported` warning instead of turning the successful query into an
error. Datasets declare their own units and precision. WeRead reports reading
minutes to two decimals: it aggregates raw seconds before converting and
rounding summaries, so the sum of individually rounded days can differ from a
total by `0.01` minute.

For V1 and additive V2 date-series responses, the command filters the requested
inclusive range, applies business rules, aggregates by the requested dimension,
and returns the requested candidate facts. V2 Ranking instead returns
source-owned scalar entries and may use `query.top` as the requested raw
coverage; partitioned Ranking applies that coverage across all Groups as defined
above. ccuv performs the local projection allowed by the selected protocol and
Metric. Never silently substitute an unsupported query.

## Capabilities and charts

Every success returns the complete stable capability manifest. It declares the
supported query surface, not keyboard bindings. Version 1 exposes enumerated
multi-select filters only; no text/range/regex filters, pagination, search, or
hierarchies. An unsupported grouping, filter, granularity, or combination must
be rejected rather than weakened or silently changed.

Each non-Ranking chart declaration lists permitted granularities; chart
declarations also list their grouping dimensions and filters. V2 Ranking may
carry legacy granularity metadata, but ccuv ignores it. Timeline and Stack use total or grouped date series, and Calendar requires an
ungrouped daily total. V1 Ranking remains dated. V2 Ranking instead returns one
authoritative scalar `value` per flat or grouped entry and never returns
`points`. A Dataset owns source-specific
combination rules—such as an otherwise declared grouping that is available only
for particular `range.period` values—and returns its correlated
`unsupported_query` response when the selected combination is unavailable.
ccuv sends the selected query unchanged: it does not maintain a Dataset-specific
compatibility matrix, substitute Total data, or select another period. The
protocol and projection capability-validate period syntax, grouping,
applicable non-Ranking granularity, filter IDs, and selected filter option IDs. The Dashboard only shows
`g`, `b`, and `f` after a successful response declares the corresponding
capability. In V1, local Top N/Other changes remain display-only. V2 Ranking
may requery when Top changes because `query.top` also expresses requested
source coverage; Other is still derived only from entries actually returned.

A V1 Dataset may represent an official period aggregate in a Ranking response
with one point per entity at the request `end_date`; this legacy coordinate is
not daily attribution. A V2 Dataset must return that authoritative aggregate as
the entry's scalar `value` instead, with no point or fabricated date. In either
version, declare the grouping only for Ranking unless the Dataset also supplies
the respective source-backed Timeline, Stack, or Calendar data.

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

ccuv compares a failed request's data-affecting identity with the accepted
query. For V1 and non-Ranking dated charts this includes source, chart kind,
inclusive range plus `range.period`, filters, grouping, and granularity. For V2
Ranking it includes source, explicit chart kind, Dataset and Metric IDs,
timezone, the exact date or timestamp range plus period spelling, normalized
filters, grouping, partition, Top/source coverage, and other existing
source-affecting fields—but never Ranking granularity. A same-query refresh may retain valid facts, while a failed
replacement clears them and retains only localized Dataset metadata for the
candidate title/range. This is Dataset-neutral and never depends on specific
period names, Dataset IDs, or source endpoints. Empty series is not an error:
return `status: "ok"`, an empty series list, and valid zero/pending/unavailable
summary values.

Malformed output, mismatched IDs, invalid decimals, missing localized text,
unknown protocol versions, timeouts, spawn failures, and nonzero exits without a
valid protocol error are source/protocol failures. stderr may appear in bounded
diagnostics but is never parsed into a result.

Only exact concurrent requests coalesce. V1 identity includes argv and execution
context, dataset ID, request kind, timezone, inclusive range **and its
`range.period` semantic**, normalized filters (sorted keys and choices), grouping,
granularity, and summary period/as-of date; its existing chart-kind and
presentation exclusions are unchanged. V2 historical identity also includes the
explicit `chart_kind`, Metric ID, partition and source-affecting Top coverage.
For V2 Ranking it excludes granularity and includes exact timestamp boundaries
when present. Timestamp identity is normalized by UTC instant, so equivalent
offsets coalesce, while different second-level ranges never collapse to one date
key. Equal resolved boundaries with different declared period spellings remain
distinct. A refresh creates a new subday anchor and therefore a new identity;
comparison requests use their exact prior range. Style, theme, density, legend,
Other, layout, and pane position remain presentation-only. Version 1 has no
overlapping-range merge, interval/range union, completed-result cache, batching,
or result slicing.

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
