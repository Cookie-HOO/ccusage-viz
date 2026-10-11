# Dataset Developer Guide

[简体中文](dataset-developer-guide.zh-CN.md) · [Protocol reference](custom-command-protocol.md) · [User guide](dataset-user-guide.md)

This is a build-from-zero guide for an executable `ccuv.custom/v2` Dataset. By
the end, you will have a runnable local Dataset, register it with ccuv, run a
historical chart and a Monitor chart, and know what to package for GitHub.

## What A Dataset Can Do

A Dataset lets ccuv visualize a source that `ccusage` does not own. It can
declare one or more independently selectable Metrics, their units, bilingual
labels, source-specific dimensions and filters, and the chart kinds each Metric
supports. Depending on its capabilities, a Dataset can provide:

- additive historical facts for Timeline, Calendar, Stack, and Ranking;
- source-owned non-additive historical values when ccuv must not aggregate;
- source-owned fixed-window Monitor observations such as events per minute;
- current/comparison summaries, or an explicit decision to provide none;
- compatible first-screen defaults for period, grouping, Top/Other,
  style, theme, and Monitor's local display horizon.

It does **not** become a ccuv collector or change built-in token calculations.
ccuv owns terminal rendering, interaction, local Top/Other projection where
allowed, scheduling, and Dashboard layout. Your Dataset owns source access,
source semantics, source aggregation, and its protocol responses.

## What You Are Building

A Dataset is a **stateless executable adapter**. On every invocation, ccuv:

1. starts your exact command without a shell;
2. writes one UTF-8 JSON request to standard input and closes it;
3. reads one UTF-8 JSON response from standard output;
4. waits for the process to exit.

Your program must output protocol JSON only to stdout. Write logs and errors to
stderr. Do not retain ccuv session state between invocations: the next request
may run in a fresh process.

This is currently the **only** Dataset integration form. A Dataset must be a
local executable command or an executable installed from a verified Dataset
archive. ccuv does not load Python modules, shared libraries, or plugins; it
does not speak HTTP, WebSocket, gRPC, or a persistent stdin session; it does not
watch a Dataset-owned file format; and it does not accept a Dataset response via
a file, socket, or callback. Your executable may internally call an API, read a
database, inspect files, or contact a local service, but its boundary with ccuv
remains exactly one JSON request on stdin and one JSON response on stdout per
process execution.

Use V2 for any new Dataset. It supports several Metrics in one Dataset, and a
Metric can support historical charts, Monitor, or both. V1 remains supported
only for existing single-metric historical commands.

## Quick Start: A Runnable Go Dataset

Go is the recommended implementation language for a distributable Dataset. A
pure Go program compiles into one executable file: users do not need Go, Python,
or a virtual environment. It is also straightforward to cross-compile one
archive per ccuv platform.

Create an empty module and save this complete program as
`cmd/example-activity/main.go`. It intentionally uses hard-coded facts so you
can validate the contract before replacing `dailyFacts()` and `handleMonitor()`
with your API, database, file, or local-service adapter.

```go
package main

import (
    "encoding/json"
    "fmt"
    "os"
    "time"
)

const protocol = "ccuv.custom/v2"
const datasetID = "example-activity"

type Request struct {
    Protocol    string         `json:"protocol"`
    RequestID   string         `json:"request_id"`
    RequestKind string         `json:"request_kind"`
    MetricID    string         `json:"metric_id"`
    Range       map[string]any `json:"range"`
}

func text(en, zh string) map[string]string {
    return map[string]string{"en": en, "zh-CN": zh}
}

func unit() map[string]any {
    return map[string]any{
        "id": "event", "label": text("events", "事件"),
        "placement": "suffix", "decimal_places": 0,
    }
}

func ok(req Request, payload map[string]any) map[string]any {
    response := map[string]any{
        "protocol": protocol, "request_id": req.RequestID,
        "request_kind": req.RequestKind, "dataset_id": datasetID, "status": "ok",
    }
    for key, value := range payload { response[key] = value }
    return response
}

func descriptor() map[string]any {
    project := map[string]any{"id": "project", "label": text("Project", "项目")}
    category := map[string]any{
        "id": "category", "label": text("Category", "类别"), "mode": "multi_select",
        "options": []any{map[string]any{"id": "work", "label": text("Work", "工作")}},
    }
    historical := map[string]any{
        "granularities": []string{"day"}, "group_by": []any{nil, "project"},
        "periods": []string{"7d", "14d", "30d"},
    }
    return map[string]any{
        "revision": "example-activity-1", "version": "0.1.0", "default_metric_id": "events",
        "dataset": map[string]any{"title": text("Example activity", "示例活动"), "description": text("Minimal V2 Dataset", "最小 V2 Dataset")},
        "metrics": []any{map[string]any{
            "id": "events", "title": text("Events", "事件"), "description": text("Daily activity", "每日活动"),
            "unit": unit(), "aggregation": "sum", "summary": "total",
            "capabilities": map[string]any{
                "group_by": []any{project},
                "charts": map[string]any{
                    "timeline": historical, "ranking": historical,
                    "monitor": map[string]any{"window_seconds": 60, "refresh_interval_seconds": 10, "group_by": []string{"project"}},
                },
            },
            "defaults": map[string]any{
                "timeline": map[string]any{"period": "14d", "group_by": "project", "top": 5, "style": "line-points", "theme": "nord"},
                "monitor": map[string]any{"style": "ranking", "window": "6h"},
            },
        }},
        "environment": []any{},
    }
}

func fail(req Request, code, field, value string) map[string]any {
    return map[string]any{
        "protocol": protocol, "request_id": req.RequestID, "request_kind": req.RequestKind,
        "dataset_id": datasetID, "status": "error",
        "error": map[string]any{"code": code, "message": text("Unsupported query", "不支持的查询"), "unsupported": map[string]string{"field": field, "value": value}},
    }
}

func handleChart(req Request) map[string]any {
    start, err := time.Parse("2006-01-02", req.Range["start_date"].(string)); if err != nil { return fail(req, "invalid_request", "range.start_date", "") }
    end, err := time.Parse("2006-01-02", req.Range["end_date"].(string)); if err != nil { return fail(req, "invalid_request", "range.end_date", "") }
    points := []any{}
    for day := start; !day.After(end); day = day.AddDate(0, 0, 1) {
        points = append(points, map[string]string{"date": day.Format("2006-01-02"), "value": fmt.Sprintf("%d", 1+day.Day()%5)})
    }
    return ok(req, map[string]any{
        "metric_id": "events",
        "descriptor": descriptor(), "runtime": map[string]any{"filters": []any{},},
        "data": map[string]any{"series": []any{map[string]any{"id": "example", "label": text("Example", "示例"), "points": points}}},
    })
}

func main() {
    var req Request
    if err := json.NewDecoder(os.Stdin).Decode(&req); err != nil || req.Protocol != protocol { os.Exit(1) }
    var response map[string]any
    switch req.RequestKind {
    case "probe": response = ok(req, map[string]any{"descriptor": descriptor()})
    case "chart": response = handleChart(req)
    case "monitor":
        response = ok(req, map[string]any{"metric_id": "events", "descriptor": descriptor(), "runtime": map[string]any{"filters": []any{}}, "observation": map[string]any{"end_at": req.Range["end_at"], "total": "42", "groups": []any{map[string]any{"id": "example", "label": text("Example", "示例"), "value": "42"}}}})
    case "summary":
        response = ok(req, map[string]any{"metric_id": "events", "summary": map[string]any{"metric": map[string]any{"id": "events", "label": text("Events", "事件"), "current": map[string]any{"value": "42", "display": text("42 events", "42 个事件")}, "sequential": map[string]string{"status": "unavailable"}, "year_over_year": map[string]string{"status": "unavailable"}}}})
    default: response = fail(req, "invalid_request", "request_kind", req.RequestKind)
    }
    if err := json.NewEncoder(os.Stdout).Encode(response); err != nil { os.Exit(1) }
}
```

Build it, call Probe directly, then register the resulting single binary:

```bash
go mod init example.com/example-activity
go build -o bin/example-activity ./cmd/example-activity
printf '%s\n' '{"protocol":"ccuv.custom/v2","request_id":"dev-probe","request_kind":"probe"}' | ./bin/example-activity
ccuv dataset add-local "$PWD/bin/example-activity"
ccuv dataset list
ccuv chart timeline --dataset example-activity --metric events
ccuv chart monitor --dataset example-activity --metric events
```

The direct Probe call is the fastest debugging loop. A valid Probe response
prints one JSON object and exits with status zero. `add-local` runs the same
Probe and prints the Dataset ID after registration.

## Implement The Contract Deliberately

### Required envelope

Every successful response contains exactly the request's `protocol`,
`request_id`, and `request_kind`, plus your stable `dataset_id` and
`status: "ok"`. Chart, Monitor, and summary responses must also echo the
requested `metric_id`. IDs must match exactly: ccuv rejects a response intended
for a different request or Dataset.

Text is always bilingual:

```json
{"en":"Events","zh-CN":"事件"}
```

All measurements are decimal **strings**, such as `"42"` or `"1.25"`.
Do not send JSON numeric values, scientific notation, `NaN`, or infinity.

### Probe: what to declare

Probe is metadata only. It must not query billable business data, test a secret,
or mutate the source. ccuv uses it before registration, in Dataset selection,
and again before a live custom Monitor starts.

| Field | You declare | ccuv does with it |
| --- | --- | --- |
| `revision`, `version` | Dataset metadata revision and SemVer-like version | Shows it in Dataset UI and persists the safe Probe snapshot. |
| `dataset` | Dataset title and description | Labels Dataset manager and chooser. |
| `metric_groups` | Optional ordered Groups with stable IDs and bilingual titles | Organizes related Metrics in the chooser and defines the `m/M` quick-switch boundary. |
| `metrics` | One or more independent measurements; each may reference one Group with `group_id` | Lets users choose a Metric and prevents unsupported chart choices. |
| `unit` | Stable unit ID, bilingual label, prefix/suffix, precision | Formats chart, table, and summary values. |
| `aggregation` | `sum` for additive facts; `value` for source-owned values | Controls whether ccuv can locally project Top/Other and history. |
| `capabilities` | Dimensions and supported chart kinds | Gates static controls and validates requests ccuv sends. Historical Ranking may declare `max_items` when its source has a fixed raw-row limit. |
| `runtime.filters` | Query-context filter dimensions, options, and `multi_select` / `single_select` mode | Returned only with each successful chart/Monitor response; enables the `f` filter editor for that accepted snapshot. |
| `defaults` | Optional initial chart suggestions | Applies only compatible fields; a bad suggestion is ignored. |
| `summary` | `comparisons`, `total`, or `none` | Determines whether/how ccuv issues summary requests. |
| `environment` | Required/optional variable names and setup instructions | Shows setup status only; ccuv never saves values. |

Use a Metric Group only for Metrics that form one coherent user-facing switch
set, such as GitHub project cumulative Stars and days since the last update.
Keep them separate Metrics when their units, aggregation, Ranking order,
displays, descriptions, summaries, or capabilities differ; the Group does not
make any of those properties shared. Declare the Group once in `metric_groups`,
then give each member the same `group_id`. Both fields are optional: omitting
all Groups preserves the flat legacy chooser, while a Metric without `group_id`
remains a flat entry and is not eligible for `m/M`. Group titles are visible to
users, so provide both languages. Empty Groups are valid but hidden by ccuv.

Choose Filter modes for user meaning rather than transport convenience. Prefer
`single_select` for mutually exclusive modes and understandable ranges, such as
`Within 7 days`, `Within 30 days`, and `Any time`: combining several ranges is
ambiguous and hard to present. Use `multi_select` only where users genuinely
combine independent discrete values, such as languages, categories, tags,
authors, or shelf labels. Omit `mode` only when you intend the compatible
`multi_select` default. A `single_select` Filter may be empty in ccuv; validate
any required selection in the Dataset query and return an actionable localized
error rather than guessing a value.

For historical charts, a Metric capability has `granularities`, `group_by`,
and optionally ordered `periods`. A Ranking may also declare positive
`max_items` when the source can never provide more raw ranking entries, plus
legacy `descriptions_default: "expanded" | "collapsed"`, which ccuv accepts
but ignores. Entry descriptions are visible at `full` and `detailed` density,
and hidden at `minimal`, `compact`, and `normal`. Use
`comparison: "full" | "rank" | "none"` to control Ranking comparison facts:
`rank` keeps the prior-range request and rank movement but hides absolute
growth; `none` suppresses both the request and all comparison columns. The
default is `full`.
`null` in `group_by` to permit an ungrouped total. For Monitor, declare fixed
positive `window_seconds`; this is the business semantics of every observation.
`refresh_interval_seconds` is advisory and ccuv warns when its actual sampling
cadence differs.

### Chart request and response

ccuv sends historical data requests like this:

```json
{
  "protocol":"ccuv.custom/v2",
  "request_id":"pane:1",
  "request_kind":"chart",
  "dataset_id":"example-activity",
  "metric_id":"events",
  "timezone":"Asia/Shanghai",
  "range":{"start_date":"2026-10-01","end_date":"2026-10-08","period":"7d"},
  "query":{"filters":{"category":["work"]},"group_by":"project","granularity":"day","top":10}
}
```

Treat `start_date` and `end_date` as inclusive and authoritative. `period` is
extra rolling-range context and is `null` for fixed bounds. Apply only the
accepted response's runtime filters and static groupings/granularities. `query.top` is optional and unifies
the user's visible Top N with the requested ranking coverage. A Dataset may
return additional raw rows when it needs them to form an honest `Other` row;
`null` means no requested Top bound. Return a `chart` success with the complete
Probe-shaped `descriptor`, `runtime: {"filters": [...]}`, and dated `data.series` points. Every point uses ISO
`YYYY-MM-DD`; return an empty series list when the requested valid range has no
facts. A Ranking series may additionally provide an optional bilingual
`description` with the same shape as `label`; ccuv renders it as at most two
muted, indented rows at `full` and `detailed` density. Its supported markup is
`[label](https://URL)`, `**bold text**`, and `*italic text*`; links render as
clickable labels and may contain star emphasis. Underscore emphasis, all other
Markdown, and unsafe terminal content stays plain text. A Ranking
series may also provide optional localized `display`, which is the exact total
string shown in its value column, and `comparison_display`, which is the exact
absolute-change string shown in its prior-period comparison column. ccuv
continues to calculate ordering, shares, comparison availability, colours, and
rank movement from the decimal points. At `full` and `detailed`, a non-fixed
Ranking also receives a second ordinary chart request for the contiguous,
equal-duration prior range. Keep series IDs stable between those responses:
ccuv uses them to calculate absolute growth and rank movement locally. Do not
return delta or previous-value fields. A concrete Ranking series may also provide
an optional `link` as one absolute `https://` URL. ccuv renders its clickable
`↗` in the whole-project action group (`Project | ⊞ ↗`) and appends the URL when the project is
copied. Do not return `description`, `display`, or `link` for Timeline, Stack,
or Calendar. Do not invent zeros unless zero is a
true source fact.

### Summary request and response

ccuv sends a summary only when the Metric declares `comparisons` or `total`.
It resolves all calendar intervals itself:

```json
{
  "request_kind":"summary",
  "summary":{"scope":"month","intervals":{"current":{"start_date":"2026-10-01","end_date":"2026-10-08"}}}
}
```

Use the supplied intervals directly. Do not reinterpret “month” in your source
timezone. A `comparisons` response may mark an unavailable comparison as
`{"status":"unavailable"}`; a `total` Metric returns the same metric object
but ccuv displays only the current total. Use `summary: "none"` if a summary is
meaningless or too expensive.

### Monitor request and response

Monitor is different from historical charts. ccuv sends an aware `end_at`, not
a user-selectable duration:

```json
{
  "request_kind":"monitor",
  "metric_id":"events",
  "range":{"end_at":"2026-10-08T10:00:00+08:00"},
  "query":{"filters":{},"group_by":"project"}
}
```

Calculate the fixed source window ending at that point, using your declared
`window_seconds`, and return the complete Probe-shaped `descriptor`,
`runtime: {"filters": [...]}`, and one source-owned `observation` with an aware
`end_at`, decimal-string `total`, and optional groups. If the source cannot
answer that exact window, send `status: "error"` with `code:
"range_not_available"`; never silently substitute zero. Dataset `defaults`
`window` changes only ccuv's local display horizon, never this source window.

### Errors and warnings

For a valid request you cannot support, return a protocol error rather than
crashing. Error codes are `unsupported_dataset`, `unsupported_chart_kind`,
`unsupported_query`, `invalid_request`, `invalid_filter`,
`range_not_available`, `source_unavailable`, and `internal_error`. Each error
has a bilingual message. For an unsupported selection, add:

```json
"unsupported":{"field":"query.group_by","value":"project"}
```

You may include successful nonblocking `warnings`, each with a stable code and
bilingual message, for example a source timezone that could not be honored.

## Development Workflow

1. Define source semantics first: what the Metric measures, whether it is
   additive (`sum`) or source-owned (`value`), its natural date boundary, and
   the exact Monitor business window if applicable.
2. Implement Probe from static configuration. Test it by piping the Probe JSON
   above into your executable and inspect stdout with `jq`.
3. Implement one chart kind and test a fixed range with an explicit request.
   Add `ranking` only after grouping and decimal totals are correct.
4. Register locally with `ccuv dataset add-local ...`; rerun that command after
   changing Probe metadata. The Dataset ID must stay the same to replace the
   registration.
5. Run `ccuv dataset`, select the Dataset, press Enter for its details, and
   verify its Metric, source command, required environment names, and status.
6. Exercise standalone charts and a Dashboard Pane. Test explicit CLI options
   and unsupported capability requests.
7. Add protocol fixture tests in your own repository: Probe, every request
   kind, invalid metric/filter/grouping, no-data range, source-unavailable, and
   every declared environment/setup state.

## Packaging, Runtime Dependencies, And Publishing

### Recommended: pure Go, one binary

Prefer a pure Go Dataset and build with `CGO_ENABLED=0`. Go modules are compiled
into the program, so the result is one executable with no Go installation or
language runtime required on the user machine. Build a binary for every release
platform; Go cross-compilation is especially convenient:

```bash
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-darwin-arm64/bin/example-activity ./cmd/example-activity
CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-darwin-amd64/bin/example-activity ./cmd/example-activity
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-linux-amd64/bin/example-activity ./cmd/example-activity
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-windows-amd64/bin/example-activity.exe ./cmd/example-activity
```

Do not use this promise casually: `cgo`, a C-backed database driver, system
shared libraries, or a browser driver can make the binary depend on its target
environment. Prefer standard-library networking and pure Go dependencies where
possible.

### If you need another executable

First ask whether the dependency can become a library dependency or be replaced
with a direct API call. That keeps the Dataset a true single binary and is the
preferred design.

When another executable is genuinely required, package a version-matched
companion binary inside the same platform archive and let the Dataset locate it
relative to its own executable. For example:

```text
manifest.json
bin/my-dataset
lib/vendor-client
```

Keep both binaries in one release version, and make the Dataset return
`source_unavailable` with a bilingual error when its companion is missing or
cannot run. Do not rely solely on discovering a dependency from `PATH`: it is
acceptable as an explicitly documented fallback, but makes deployment
non-reproducible.

If a companion cannot be redistributed because of licensing, size, or a vendor
installation requirement, require an explicit environment variable such as
`MY_DATASET_CLIENT_BIN=/opt/vendor/client`. Declare that variable in Probe's
`environment`, then validate it during chart/Monitor work and return
`source_unavailable` with actionable bilingual text when it is absent.

### If the Dataset is Python or another dynamic language

Python, Node, Ruby, and similar implementations are fully valid for **local
development** and private deployment. Register the runtime explicitly:

```bash
ccuv dataset add-local /absolute/path/to/.venv/bin/python /absolute/path/to/dataset.py
```

For public distribution, do not assume users share your runtime, virtual
environment, or installed packages. Prefer rewriting the adapter as pure Go. If
the existing dynamic-language code must remain, build a separate native
executable for every platform with an appropriate packager, such as PyInstaller
or Nuitka for Python, then test each artifact exactly as a user would. This is
valid but does not have Go's simple cross-compilation workflow.

### GitHub release

Local development needs no archive. To distribute a managed Dataset, publish a
GitHub Release with one `.tar.gz` per OS/architecture. Each archive contains:

```text
manifest.json
bin/my-dataset
```

`manifest.json` declares `schema: "ccuv.dataset/v1"`, `protocol:
"ccuv.custom/v2"`, `entrypoint: "bin/my-dataset"`, the target `platform`, and
either metadata fields or a static Probe descriptor. The executable must have
the executable bit set. Name release assets so ccuv can identify the platform,
for example `example-activity-darwin-arm64.tar.gz`, and publish a checksum file
(`checksums.txt`, `sha256sums`, or `sha256sums.txt`) containing each SHA-256.

After release, use `ccuv dataset` -> `+` -> **Install from GitHub** and enter
`OWNER/REPOSITORY`. ccuv downloads only a compatible archive, verifies its
checksum, validates the manifest, and registers it. An official Dataset is a
separate status: its repository must be included in ccuv's signed official
catalog. A public GitHub release remains installable even when it is not
official.

## Final Checklist

- [ ] One request in, one JSON response out; logs only on stderr.
- [ ] Probe is metadata-only and has bilingual text everywhere.
- [ ] Dataset ID, Metric IDs, unit IDs, filter IDs, and option IDs are stable.
- [ ] Every response echoes request/protocol identity exactly.
- [ ] Every numeric measurement is a decimal string.
- [ ] Capabilities describe only configurations your adapter can answer.
- [ ] Unsupported valid requests return a structured protocol error.
- [ ] Monitor uses the declared fixed source window and returns
  `range_not_available` when it cannot.
- [ ] Local registration, standalone chart, Dashboard Pane, and release install
  have all been tested.
