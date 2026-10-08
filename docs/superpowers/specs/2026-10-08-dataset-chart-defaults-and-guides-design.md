# Dataset Chart Defaults And Guides Design

## Goal

Allow each `ccuv.custom/v2` metric to suggest the complete initial state of
each supported chart without changing the protocol identifier. Invalid Dataset
suggestions must never reject a Probe, Dataset registration, or Pane; ccuv
falls back per field to the existing Dashboard or standalone defaults.

The change also makes the native Monitor default style `points`, gives Router
Metric fixtures sensible Monitor defaults, and adds separate English and
Simplified Chinese guides for Dataset developers and users.

## Scope

The existing `metrics[].defaults` mapping remains the extension point. Its
chart objects become sparse and can include these optional fields:

```json
{
  "period": "30d",
  "granularity": "week",
  "group_by": "book",
  "filters": {"category": ["literature", "history"]},
  "top": 12,
  "other": "hide",
  "style": "area",
  "theme": "nord",
  "window": "6h"
}
```

All identifiers use the existing public vocabulary. `top` stays `top`,
`other` stays `"show" | "hide"`, and style/theme values stay ccuv values.
Shortcuts such as `p`, `g`, and `b` are not protocol fields.

`window` is only useful for `monitor`. For a V2 Custom Monitor it means the
ccuv-local display horizon (`CustomMonitorComponent.display_window_seconds`),
not the source-owned query window. The fixed business query interval stays in
`capabilities.charts.monitor.window_seconds` and cannot be overridden by a
default. Historical charts ignore `window`.

## Resolution Rules

Each property resolves independently in this order:

```text
explicit CLI / explicit Dashboard pane option
> valid Dataset metric default
> existing host baseline (standalone or Dashboard)
```

The parser retains a sparse best-effort representation of Dataset defaults.
It accepts unknown fields and values of unexpected type as inert data rather
than treating the whole descriptor as malformed. The runtime merge point uses
the selected chart kind, the selected metric capability, and explicit-field
tracking to decide whether each suggested property can apply.

Invalid properties are ignored individually:

- invalid period or a period not declared by the historical capability;
- unsupported granularity or group dimension;
- unknown filter, unsupported filter for the chart, or unknown option;
- non-positive `top`, or `top` with no final valid grouping;
- unsupported `other` use for the chart;
- unknown theme;
- style unsupported by the chart or incompatible with the final grouping;
- invalid window duration, or a window on a non-Monitor chart.

For filters, ccuv retains valid options of a valid filter and silently drops
the rest. It omits a filter whose valid-option set becomes empty. Explicit
filter selection replaces the Dataset default for that filter collection.

The Dataset default is applied once after the first successful runtime Probe.
Subsequent TUI adjustments remain user-owned state. Probe and persisted static
descriptor parsing must never fail merely because a declared default is
unusable.

## Model And Integration

`CustomChartDefaults` becomes a sparse, immutable metadata type that represents
every supported field. Existing V1 handling continues to work with its current
subset of fields. V2 parsing and serialization preserve the extended mapping,
including Monitor defaults, so static manifests and local-registration Probe
snapshots round-trip accurately.

The default merger is the single policy point for historical charts. A small
V2 Custom Monitor counterpart resolves `group_by`, `top`, `filters`,
`presentation`, `other`, and `window` after the selected Metric has been
identified and its `V2MonitorCapability` is available. It must not turn a bad
default into a query failure.

CLI and dashboard-fragment parsing must record `theme`, `style`, `other`,
`filters`, `granularity`, and `window` as explicit when supplied, alongside
the currently tracked range/group/top fields. The two hosts retain their
different pre-merge baselines: standalone uses detailed density, and Dashboard
uses compact density.

Native Monitor defaults change from `bars` to `points` in both the CLI baseline
and the Dashboard pane baseline. This applies only when users do not choose a
style explicitly.

The production Router Dataset source is not present in this repository. Its
repository-local protocol fixtures and examples will declare `monitor` defaults
of `style: "ranking"` and `window: "6h"`; the actual Router Dataset must make
the identical Probe declaration in its own repository. Its existing
`window_seconds: 60` remains the source business window.

## Documentation

Add two bilingual document pairs:

- `docs/dataset-developer-guide(.zh-CN).md`: local command development,
  v2 Probe fields and their ccuv consumers, chart/summary/monitor queries,
  query/response process rules, local registration and test cycle, plus GitHub
  release publication.
- `docs/dataset-user-guide(.zh-CN).md`: local command registration, official
  catalog and arbitrary GitHub source installation flows where supported by the
  Dataset manager, list/refresh/enable/remove/update actions, Dashboard and
  standalone Dataset selection, Metric/chart selection, and expected runtime
  behavior.

The guides must distinguish implemented commands from future or unavailable
flows. README and README.zh-CN gain final "Further reading" table entries for
both guides.

## Verification

Tests cover sparse parsing and wire round-trips; per-field default application;
explicit CLI and pane override; invalid declarations falling back without
errors; filter partial acceptance; style compatibility after grouping; Monitor
display-window semantics; native standalone and Dashboard Monitor default style;
and Router fixture defaults. Documentation links and command examples are
reviewed against the actual CLI implementation.
