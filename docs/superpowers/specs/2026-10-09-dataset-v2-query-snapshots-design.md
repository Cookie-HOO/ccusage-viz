# Dataset V2 Query Snapshots Design

## Goal

Replace Dataset V2's Probe-owned static filter catalog with a response-owned
query snapshot for all V2 historical charts and Monitor. V2 is unpublished, so
the protocol changes in place without a compatibility mode or V3 fork.

## Snapshot Contract

Every successful V2 `chart` and `monitor` response returns three independent
parts which ccuv accepts atomically:

```text
descriptor  the complete static Dataset descriptor for this response
runtime     query-context controls that may change on the next request
facts       chart data or one Monitor observation
```

`descriptor` uses the same complete V2 descriptor shape as a Probe response:
revision, version, Dataset identity, all Metrics, units, aggregation semantics,
grouping dimensions, supported chart kinds, periods, defaults, and environment
declarations. It is the static authority for an accepted query snapshot. ccuv
does not compare a revision to an earlier Probe or retain a second static
authority.

The response root still echoes its requested `metric_id`. The descriptor must
contain that Metric and the selected Metric must declare the requested chart
kind. A response failing either constraint is invalid and is not accepted.

The initial Probe remains a side-effect-free discovery and startup selection
directory. Its descriptor lets ccuv choose a Metric and chart to query. A
successful query replaces the UI's accepted static descriptor with the query
snapshot descriptor.

## Static And Dynamic Controls

Static chart controls remain in the response descriptor. Historical chart
periods and group-by dimensions therefore remain static declarations: `p/P`
and `b/B` use the selected Metric's accepted descriptor. Monitor keeps its
source-owned `window_seconds`, refresh suggestion, and grouping declaration in
that same descriptor.

Probe and response descriptors no longer include filter declarations or option
catalogs. Remove `V2MetricCapabilities.filters` and each chart capability's
`filters` field. A Dataset no longer promises at Probe time that a certain
filter or option exists.

Each successful V2 chart or Monitor response includes a `runtime` object. Its
first member is `filters`, the complete filter catalog that is valid to edit in
the accepted response's query context:

```json
"runtime": {
  "filters": [
    {
      "id": "book",
      "label": {"en": "Book", "zh-CN": "图书"},
      "mode": "multi_select",
      "options": [
        {
          "id": "book-a",
          "label": {"en": "The Three-Body Problem", "zh-CN": "三体"}
        }
      ]
    }
  ]
}
```

`runtime` is required on successful V2 chart and Monitor responses. `filters`
is required and may be an empty list. Filter IDs and option IDs must be unique;
all UI text remains bilingual. The envelope intentionally leaves room for later
runtime controls without changing the root response shape.

ccuv exposes `f` only after accepting a response with non-empty
`runtime.filters`. The filter editor uses exactly that accepted catalog. The
next query sends its selected IDs in `query.filters`. A successful replacement
atomically replaces the data/observation, descriptor, and runtime catalog. A
failed replacement retains the last accepted snapshot and catalog; the
Dataset must reject expired IDs or invalid combinations with `invalid_filter`
or `unsupported_query` rather than ccuv inventing a fallback.

## Response Shapes

A historical response has this top-level shape:

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "request-1",
  "request_kind": "chart",
  "dataset_id": "weread",
  "metric_id": "reading-time",
  "status": "ok",
  "descriptor": {"...": "complete V2 descriptor"},
  "runtime": {"filters": []},
  "data": {"series": []}
}
```

A Monitor response uses the same snapshot fields and replaces `data` with
`observation`.

Probe and summary response contracts do not change in this work. Summary facts
continue to rely on the active pane's accepted query descriptor for metric
metadata; no new runtime controls are introduced for summary requests.

## Hosts And Components

`CustomHistoricalComponent` retains the accepted V2 chart descriptor and
runtime. It obtains the selected chart capability from the accepted descriptor,
not from the earlier Probe or a chart response's former partial capabilities.
The Dashboard and standalone filter editor consume its accepted runtime
filters.

`CustomMonitorComponent` replaces Probe-only presentation metadata when an
observation snapshot is accepted. It obtains its Metric, Monitor capability,
unit, aggregation, title, and runtime filters from that response descriptor.
Before the first Monitor response, Probe metadata may provide a loading title
and make the initial request possible, but cannot expose `f`.

When a returned descriptor removes the selected chart capability or Metric,
the response is rejected as a protocol error. Existing accepted facts remain
visible only while they describe the unchanged accepted query identity.

## Documentation And Tests

The bilingual custom protocol and Dataset developer/user guides describe the
new required snapshot fields and clarify that filters are dynamic response
runtime controls. Old static `capabilities.filters` examples and descriptions
are removed.

Tests cover parser validation, serializers used by fixture helpers, descriptor
replacement, dynamic filter editor availability, invalid snapshot rejection,
and chart/Monitor response acceptance. Existing V2 fixtures are migrated to
the new response requirements; V1 remains unchanged.
