# Dataset V2 And Custom Monitor Design

## Goal

Upgrade ccuv custom Datasets from one additive historical metric to a Dataset
that exposes multiple Metrics. Metrics can support historical charts, Monitor,
or both. The first consumer is a local Router Dataset that exposes live TPM,
QPM, and average tokens per request without persisting Router telemetry.

The work also changes Router v3 to use configuration-driven, Agent-qualified
paths on one loopback listener. This gives each observed request a stable Agent
identity without separate public ports or protocol inference.

## Dataset V2

V2 uses a new `ccuv.custom/v2` protocol. V1 stays supported unchanged until a
separate removal decision. A V2 Dataset is a source integration. It exposes one
or more Metrics:

```text
Dataset -> Metric -> supported chart kind -> query
```

The CLI and Dashboard chooser follow that order. A chart configuration stores
the Dataset ID and Metric ID along with the existing chart configuration.

Metric metadata reuses the existing localized name, description, unit,
capability, filter, grouping, default, and environment concepts. Capabilities
move from Dataset scope to Metric scope so a Metric can support only the charts
and groupings that describe it.

Each Metric declares one aggregation semantic:

```text
sum   ccuv may safely aggregate returned facts.
value Dataset owns the final value for each complete query.
```

`sum` preserves V1 behavior: ccuv may combine date buckets, create Top N and
Other series, total series, summary values, and Monitor accumulation where the
chart supports it. Tokens, requests, bytes, duration, and money are examples.

`value` supports averages, ratios, percentages, percentiles, and other results
that cannot be reconstructed from previously returned scalar values. For a
data-affecting query change -- range, granularity, grouping, filters, chart
kind, or source -- ccuv sends a new request. It may retain and repaint only an
accepted result with exactly the same query identity. It never sums, averages,
or builds Total/Other from value responses.

For value Metrics, Datasets return final values for their requested range and
grouping. The Metric capability determines which charts are offered; V2 does
not infer chart support from the aggregation semantic.

## Custom Monitor

Custom Monitor has two separate time concepts:

```text
metric.monitor.window_seconds
    The Dataset-owned business window for one observation.

ccuv Monitor display window
    The amount of accepted observation history retained and shown by ccuv.
```

For example, a Router TPM Metric may declare `window_seconds: 60`. Every
observation ending at `end_at` means the Router's token total over
`[end_at - 60 seconds, end_at)`. Changing ccuv's display window does not alter
the Dataset query or the business meaning of TPM. The display window only
controls how much accepted observation history remains visible locally.

A Monitor request remains range-shaped like historical requests, but a custom
observation only needs an explicit timestamp endpoint in the initial V2 design:

```json
{
  "protocol": "ccuv.custom/v2",
  "request_kind": "monitor",
  "dataset_id": "router",
  "metric_id": "tokens",
  "range": {"end_at": "2026-10-07T14:00:10+08:00"},
  "query": {"group_by": "real_model", "filters": {}}
}
```

The Dataset applies its declared fixed metric window and returns one value per
group plus the source-owned total. A sum Metric returns a window total; a value
Metric returns its final window value. ccuv does not derive a new business
window from repeated responses.

Custom Monitor supports the existing bars, ranking, and list views. It keeps
ccuv's display-window control, but hides controls that would change the
Dataset-owned metric contract. `cumulative-bars` is not offered for a value
Metric. It is also not part of the first Custom Monitor implementation for sum
Metrics because a rolling-window total cannot honestly be converted into
non-overlapping historical increments without an additional bucket contract.

Every Monitor-capable Metric may optionally declare `refresh_interval_seconds`.
When absent, the Pane refreshes with ccuv's existing globally configurable
Dashboard sampling interval. When present, ccuv retains the global interval but
shows a non-blocking warning whenever the configured interval differs from the
Metric's declared interval. This avoids introducing Pane-local interval controls
or schedulers in V2.

At Pane startup, ccuv sends a runtime Probe regardless of the installed
descriptor cache. The cache remains useful for discovery and chooser metadata;
the runtime Probe validates the live Metric capability before the Pane starts.

If a Dataset cannot answer an observation endpoint or requested Monitor range,
it returns the ordinary localized `range_not_available` protocol error. ccuv
keeps accepted facts only for a refresh of the exact same query. A replacement
or incompatible-range request clears candidate numeric facts and renders the
localized Dataset error. It never substitutes zero or fabricates missing
intervals.

## WeRead Migration

WeRead becomes a V2 Dataset with one Metric that retains its current additive
historical behavior and the four historical chart capabilities. It does not
declare Monitor. Existing V1-style WeRead user workflows remain available
through the new Dataset/Metric selection, with the single Metric selected by
default where that is unambiguous.

## Router V3 Telemetry

Router v3 remains a foreground-only, loopback service. Public generation routes
are Agent-qualified and synthesized from `agents` in
`config/router_v3_config.yaml`:

```text
POST /agent/<agent>/v1/messages
POST /agent/<agent>/v1/responses
POST /agent/<agent>/v1/chat/completions
GET  /agent/<agent>/v1/models
GET  /agent/<agent>/health
GET  /health
```

There are no anonymous public `/v1/...` generation routes. All configured
Agents support all three protocols. Adding an Agent is a configuration change
and restart, not a Router code change.

Router creates an in-memory completed-request event only after a selected
request has a final result with usable usage data. Event fields include:

```text
completed_at
agent
public_model
real_model
input_tokens
output_tokens
total_tokens
```

The event buffer keeps only the fixed Metric window necessary for the first
Router Dataset, initially 60 seconds. It is not written to disk. Router restart
clears all telemetry.

A loopback-only read endpoint accepts a Metric, grouping dimension, and
observation endpoint and returns the Dataset-required aggregate for the fixed
window. It supports `tokens` (sum), `completed_requests` (sum), and
`average_tokens_per_request` (value), with `public_model`, `real_model`, and
`agent` groupings. Data missing from upstream usage is not invented as zero.

## Go Router Dataset

A new Go project under `~/Projects/go` implements the V2 command Dataset. It
contains one `router` Dataset with the three Metrics above, Runtime Probe, and
Monitor query handling. It reads Router's loopback telemetry endpoint and
adapts its response to ccuv's V2 protocol. It preserves all Router aggregation
semantics rather than recomputing request data itself.

The Dataset supplies a documented command suitable for `ccuv dataset add local`
or direct command development. It does not implement historical charts in its
first version.

## Verification

1. Unit and protocol tests cover V2 parsing, multiple Metric selection,
   sum/value projections, Monitor capability and error states, and V1
   compatibility where retained.
2. Existing WeRead custom chart tests verify timeline, stack, calendar, ranking,
   probe, registration, and Dataset-manager behavior.
3. Router v3 tests cover configuration-driven Agent routes, Agent attribution,
   bounded memory telemetry, grouping, and missing usage behavior.
4. The Go Dataset test suite validates Probe and the three Router Metric
   responses against Router endpoint fixtures.
5. Local integration uses only project-level or temporary Codex/Claude
   configuration directed at Agent-qualified Router v3 paths with
   `gpt-5.6-terra`. It does not edit global Codex or Claude Code configuration.
