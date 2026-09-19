# External Sources Design

**Status:** superseded protocol draft; never implemented

**Date:** 2026-09-14

**Superseded:** 2026-09-19 by the future Source contract in [`../../source-plugin-guide.md`](../../source-plugin-guide.md)

> This document is retained only as design history. It is not an approved implementation contract. The replacement contract discards this draft's timestamp/range resolutions, Monitor interval increments, optional dimensions, source-side selector ownership, shell/script CLI surface, and additive same-Source row/refresh semantics. A future Source instead returns natural-day cumulative Token facts with mandatory `agent`, `model`, and `project` values; a newer same-Source snapshot replaces the earlier value for the complete identity key.

## Purpose

`ccusage-viz` currently obtains all data through `ccusage`. This design adds optional local external sources so that usage unavailable from `ccusage`—such as proxy-recorded Terra usage or a DeepSeek Harness exporter—can be included in the same charts and diagnostics.

External sources are local programs. They own their storage, filtering, and aggregation. `ccusage-viz` owns invocation, protocol validation, source-aware inspection, chart compatibility checks, and final display aggregation.

The first version does **not** solve duplicate accounting or reconciliation. Every external token record is assumed to be new usage not already represented by `ccusage` or another configured source.

## Scope

### Included

- Repeatable `--source-shell` and `--source-script` inputs.
- Explicit environment authorization before external code can execute.
- A versioned NDJSON protocol with metadata and three data resolutions.
- Unified scheduling of `ccusage` queries and external sources.
- External-source support in historical charts, Watch, Monitor, and a source-inspection `data` command.
- Provenance-aware `data --format table|json` output.
- Strict source-protocol validation with actionable diagnostics.

### Excluded from v1

- Deduplicating records within or across sources.
- Reconciling external records with partially reported `ccusage` records.
- Automatic comparison to cloud logs.
- Config files, persistent source registration, or a source marketplace.
- Remote execution, HTTP fetching, or network credentials managed by `ccusage-viz`.

## User-facing CLI

### Source configuration

```bash
CCUV_ENABLE_EXTERNAL_SOURCES=1 \
ccuv timeline \
  --source-script /path/to/exporter \
  --source-name proxy \
  --source-shell 'billing-export --active' \
  --source-name billing
```

| Option | Meaning |
|---|---|
| `--source-script PATH` | Run an executable local file directly, without a shell. `ccuv` appends standard filter arguments. |
| `--source-shell COMMAND` | Run a local command with `/bin/sh -c`. Query filters are injected through environment variables. |
| `--source-name NAME` | Optional local diagnostic name for the immediately preceding source. It is not sent to that source and does not replace protocol `sourceId`. |
| `--no-ccusage` | Do not require or run `ccusage`; at least one external source is then required. |
| `--max-parallel N` | Maximum concurrent query subprocesses in total: all `ccusage` queries plus all external sources. Default `4`; valid range `1`–`8`. |
| `--redact-sources-on-copy` | When Watch/Monitor copies the command with `y`, omit all source options and associated source names. The redaction option itself is omitted too. |

Sources may be mixed and repeated. Their configuration order is retained for diagnostics and deterministic reporting.

`--source-script` is intended for a directly executable script or CLI. A source that needs an interpreter, activation, pipes, or shell composition uses `--source-shell` explicitly.

### Authorization gate

Any command that includes `--source-shell` or `--source-script` requires:

```bash
export CCUV_ENABLE_EXTERNAL_SOURCES=1
```

Without this exact value, `ccuv` stops before starting any query and explains that the variable explicitly authorizes execution of local external sources. This applies to every Watch refresh and Monitor sample within the authorized process.

The gate intentionally does not make source execution safe; it makes it explicit. `--source-shell` can execute arbitrary local shell code.

### Default source behavior

`ccusage` remains enabled by default. With no external source options, existing behavior is unchanged. `--no-ccusage` is valid only when at least one external source is configured.

## Query inputs

Sources receive parsed, absolute query filters only. Display controls such as command name, `--by`, Top, Other, theme, style, and summary visibility are never sent.

### Historical commands, `data`, and Watch

Sources receive:

- `since`, `until`: inclusive natural-date bounds;
- `timezone`;
- repeatable user-entered `agent`, `model`, and `project` selectors.

For scripts:

```bash
/path/to/exporter \
  --since 2026-09-01 \
  --until 2026-09-14 \
  --timezone Asia/Shanghai \
  --agent claude \
  --model terra \
  --project my-app
```

For shell sources:

```text
CCUV_SINCE=2026-09-01
CCUV_UNTIL=2026-09-14
CCUV_TIMEZONE=Asia/Shanghai
CCUV_AGENTS_JSON='["claude"]'
CCUV_MODELS_JSON='["terra"]'
CCUV_PROJECTS_JSON='["my-app"]'
```

All environment values are strings. The three multi-value values contain JSON arrays. Unspecified selector dimensions are passed as `[]`.

Sources inherit the parent environment, with these `CCUV_*` query variables overwritten by `ccuv`.

### Monitor

Monitor sources receive only an exact half-open interval, not date bounds:

```text
[sinceAt, untilAt)
```

For scripts:

```bash
/path/to/exporter \
  --since-at 2026-09-14T10:00:00+08:00 \
  --until-at 2026-09-14T10:15:00+08:00 \
  --timezone Asia/Shanghai
```

For shell sources:

```text
CCUV_SINCE_AT=2026-09-14T10:00:00+08:00
CCUV_UNTIL_AT=2026-09-14T10:15:00+08:00
CCUV_TIMEZONE=Asia/Shanghai
```

The first successful external Monitor interval begins at Monitor startup. After each successful source query, the interval endpoint becomes the next interval start. A failed, paused, or timed-out sample does not advance the start; the next success asks for the missed interval. This prevents gaps without requiring the source to preserve Monitor state.

`ccusage` itself continues with its existing cumulative-snapshot behavior. Internally, `ccuv` converts the `ccusage` snapshot difference and each external source’s interval total into the same per-sample increment before feeding Monitor.

## External source protocol v1

Each source writes UTF-8 NDJSON to stdout. Empty lines are ignored. The source must write no prose, markdown, arrays, or other non-object lines.

### Metadata line

The first non-empty line is required to be this metadata object:

```json
{"type":"ccuv-source-metadata","version":1,"sourceId":"proxy","dataResolution":"timestamp"}
```

Required metadata fields:

| Field | Rule |
|---|---|
| `type` | Exact string `ccuv-source-metadata`. |
| `version` | Integer `1`. |
| `sourceId` | Unique among configured external sources; matches `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. |
| `dataResolution` | One of `timestamp`, `date`, or `range`. |

`dataResolution: "date"` additionally requires a metadata `timezone` equal to the request timezone.

No unknown metadata fields are accepted in v1.

### Token rows

Every following non-empty line is one independent, non-overlapping token share. Rows are added; `ccuv` does not infer containment, deduplicate, or reconcile overlapping data.

Example timestamp row:

```json
{
  "timestamp":"2026-09-14T10:03:21+08:00",
  "agent":"proxy",
  "model":"terra",
  "project":"my-app",
  "inputTokens":1200,
  "outputTokens":800,
  "cacheReadTokens":300,
  "cacheCreationTokens":100,
  "totalTokens":2400
}
```

| Field | Rule |
|---|---|
| `timestamp` | Required only for `timestamp` resolution. RFC 3339 with an explicit offset or timezone. It denotes a real token attribution time, not an arbitrary point for an interval aggregate. |
| `date` | Required only for `date` resolution. `YYYY-MM-DD`, already bucketed in metadata timezone. |
| `agent` | Optional safe ID with the same syntax as `sourceId`. |
| `model` | Optional non-empty text without control characters. It remains intentionally less constrained than a source or agent ID. |
| `project` | Optional source-owned project identifier. Existing display safety and agent-scoped project identity rules apply. |
| `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheCreationTokens` | Optional non-negative integer token counts. |
| `totalTokens` | Required non-negative integer token count. |

Known component values may not exceed `totalTokens`. The remainder is retained as residual `Other`; absent components are not treated as known zero token categories.

No unknown token-row fields are accepted in v1.

A metadata-only response is valid and means a successful zero-usage result for the requested filters.

### Data resolution

| Resolution | Meaning | Row time field |
|---|---|---|
| `timestamp` | Each token row has an exact attributable time. | `timestamp` |
| `date` | Each row is already a natural-day aggregate in the declared timezone. | `date` |
| `range` | Each row aggregates the entire query range passed to the source. | none |

For `timestamp` and `date`, rows outside the requested range are protocol errors. `range` cannot be independently range-verified; the source is authoritative for its received filters.

## Filtering and attribution responsibilities

`ccuv` passes the user’s original selectors to every source. The source is responsible for honoring them and may return fully aggregated data that no longer carries original dimensions.

- Missing `agent`, `model`, or `project` data is accepted. It means that granularity is unavailable, not that the row should be discarded.
- If a row includes a dimension which conflicts with a user’s explicit selector in that dimension, `ccuv` fails the query. It never silently drops the row.
- If a source omits the dimension, `ccuv` does not claim to re-check the source’s filtering.

Fallback attribution for grouped views:

| Missing field | Grouped view fallback |
|---|---|
| `agent` | `External · <sourceId>` |
| `model` | `External · <sourceId>` in model grouping |
| `project` | A source-scoped synthetic project displayed as `External · <sourceId>` |

A provided real project retains the internal `(agent, project)` identity and existing privacy-safe display rules.

## Chart compatibility

| Resolution | Timeline / Calendar / Stack | Ranking | Ranking daily summary | Monitor | `data` |
|---|---:|---:|---:|---:|---:|
| `timestamp` | supported | supported | supported | supported | supported |
| `date` | supported | supported | supported | rejected | supported |
| `range` | rejected | supported | not computable | supported | supported |

A resolution incompatibility fails the chart query with a source-specific explanation and repair options. `ccuv` never spreads a range total over days or invents hourly attribution.

For Ranking with a `range` source and summary enabled, the ranking remains valid. The summary region displays a localized explanation that daily comparison statistics are unavailable because the source only supplied range totals. The normal summary toggle controls this explanation: when summary is off, it is hidden; when on, it returns.

For Monitor, a `timestamp` or `range` source returns the exact passed interval’s increment. A `date` source is rejected because it cannot reliably partition a whole-day total into an exact sample interval.

## Execution, limits, and failure behavior

All `ccusage` subprocesses and external sources are unified query tasks.

- `--max-parallel` controls total simultaneous tasks, default `4`, valid `1`–`8`.
- `--timeout` applies independently to each task, not an aggregate wall-clock budget.
- Each task may emit at most 16 MiB of stdout per execution.
- A timeout or output-limit breach terminates that task and its process group.
- Any start failure, timeout, output limit breach, non-zero exit, invalid UTF-8, protocol violation, duplicate `sourceId`, or query failure cancels remaining tasks and fails the current query.
- In Watch and Monitor, the previous successful chart remains visible while a refresh/sample failure is reported.

Before metadata is available, diagnostics use optional `--source-name` or a stable `source #N`. After metadata is parsed, diagnostics use `sourceId`.

External source stderr is not echoed by `ccuv`, because arbitrary local commands can emit credentials, paths, or private service details. Errors point to the source name/ID, line and field where applicable, and offer an actionable repair direction.

Example diagnostics:

```text
External source "proxy", line 17: timestamp is required for dataResolution "timestamp".
Add an RFC 3339 timestamp with an explicit timezone.
```

```text
External source "billing" cannot serve Timeline: dataResolution "range" provides only a whole-range total.
Use Ranking, provide date/timestamp rows, or remove this source.
```

```text
External source "proxy" exceeded the 16 MiB output limit.
Filter or aggregate source data using the supplied query conditions, then run again.
```

## `data` command

`data` is a single-run query-inspection command for validating sources and comparing their contribution to `ccusage`.

```bash
CCUV_ENABLE_EXTERNAL_SOURCES=1 \
ccuv data --format table --source-script /path/to/exporter --period 14d
```

It accepts ordinary historical date/timezone/selectors and source options. It does not support `--watch` or Monitor-specific parameters.

By default, it queries `ccusage` and all configured external sources. `--no-ccusage` makes it source-only. With neither ccusage nor any source, it fails as an empty query plan.

### `data --format table`

The default human-readable output emits one row per unmerged source/query result, with source label, resolution, record count, total, known token components, and residual Other. It does not hide range aggregates or impose chart compatibility restrictions.

Examples of source labels:

```text
ccusage · unified daily
ccusage · Claude daily projects
ccusage · Codex sessions
external · proxy
```

### `data --format json`

JSON is a stable public diagnostic format. It writes exactly one versioned JSON document to stdout and no progress/prose/ANSI text. It groups accepted, normalized records by provenance:

```json
{
  "version": 1,
  "query": {
    "since": "2026-09-01",
    "until": "2026-09-14",
    "timezone": "Asia/Shanghai"
  },
  "sources": [
    {
      "kind": "ccusage",
      "id": "unified-daily",
      "resolution": "date",
      "records": []
    },
    {
      "kind": "external",
      "id": "proxy",
      "metadata": {"dataResolution": "timestamp"},
      "records": []
    }
  ]
}
```

It does not emit source commands, script paths, environment values, or stderr. On any error it writes diagnostics to stderr, exits non-zero, and emits no partial JSON.

`data` works without a TTY. JSON is suitable for files, pipes, and integration tests; table output becomes plain text when stdout is not interactive.

## Copy behavior

The `y` action normally copies a complete, replayable original command, including source options and relative date options such as `--period 14d`. It does not substitute dynamic internal dates or Monitor interval endpoints with shell `date` expressions.

When `--redact-sources-on-copy` was present at startup, copied output excludes every `--source-shell`, `--source-script`, and associated `--source-name`, plus the redaction flag itself. Other query semantics remain intact.

## Documentation requirements

README and command help must document:

- the `CCUV_ENABLE_EXTERNAL_SOURCES=1` authorization gate and shell risk;
- `--source-shell`, `--source-script`, `--source-name`, `--no-ccusage`, `--max-parallel`, and copy redaction;
- query filter injection for scripts and shell sources;
- metadata and NDJSON v1 schema, including strict fields and per-row additivity;
- filtering responsibility boundary and optional dimension semantics;
- resolution compatibility and Ranking summary behavior;
- global query limits and safe diagnostic behavior;
- `data` usage and its stable JSON contract.

## Acceptance criteria

Implementation tests must cover at least:

- authorization failure before any query starts;
- script argv and shell environment injection;
- source ordering and optional source-name binding;
- strict metadata/row schema validation and actionable line diagnostics;
- each data resolution and chart compatibility result;
- date timezone matching and timestamp date/interval bounds;
- component-token conservation and residual Other;
- missing vs conflicting attribution dimensions;
- source ID uniqueness and metadata-only success;
- shared concurrency behavior with ccusage, per-task timeout, stdout limit, cancellation, and Watch/Monitor retained output;
- Monitor incremental external intervals and failure-gap retry;
- `data` table provenance and stable JSON stdout/error behavior;
- complete versus redacted copied commands;
- English/Chinese localization key and placeholder parity.
