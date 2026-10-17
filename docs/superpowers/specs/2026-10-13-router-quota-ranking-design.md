# Router Quota Ranking Design

## Goal

Extend the local Router Dataset so ccusage-viz can show a single, source-owned
quota ranking. Each row represents one Trae entitlement quota pool; its optional
one-line description lists the models attached to that pool.

The view answers: "What quota pools are available, and which models use each
pool?" It is not a token ledger, per-model billing report, or Router health
metric.

## User Experience

The Router Dataset exposes a `Provider Quota` metric group containing one
metric:

```text
Quota Remaining
```

Its default entrypoint is Custom Monitor with `ranking` presentation. It also
supports the Custom historical `ranking` chart, restricted to `period: "all"`.
Both rankings have one row per quota pool, sorted by the normal descending
numeric ranking behavior.

Example:

```text
Quota Remaining
advanced ♾️                                  100.0%
basic                                        69.2%
  openrouter-1, openrouter-1o, openrouter-2o, openrouter-2o[1m], openrouter-3o, openrouter-3o[1m]
premium_slow ♾️                              100.0%
```

The entry description is a single comma-and-space-separated model list. It must
not use line breaks, a model count, or wording such as "shared by". The pool
label itself remains the primary identity.

## Metric Contract

```text
Dataset ID: router
Metric ID: quota_remaining_ratio
Metric group: provider_quota
Title: Quota Remaining / 剩余额度
Unit: percent
Aggregation: value
Summary: none
Monitor chart capability: ranking presentation only
Historical chart capability: ranking only; periods: [all]
Grouping: quota_pool only
Monitor refresh interval: 20 seconds
Monitor default style: ranking
```

`value` means the Dataset owns the exact current quota snapshot. ccusage-viz
must neither add snapshots over time nor permit cumulative-bar presentation.

A historical Ranking request is a current-state projection, not quota history.
The Dataset accepts only `period: "all"`, ignores the date range for provider
lookup, and returns one point for every pool at `range.end_date`. It must reject
all other periods with `unsupported_query` naming `range.period`. This lets a
user open a normal ranking view while preventing an arbitrary date range from
being misrepresented as historical quota data.

The metric description states that it is a provider quota snapshot and that a
model list identifies models attached to the pool; it must not claim models
have independent quota balances.

The Dataset continues to expose the existing Router Runtime metrics unchanged:
`requests`, `error_rate`, and `latency_p95_ms`. Their current 60-second business
window and 10-second Monitor refresh interval remain unchanged.

## Pool Inclusion And Values

All provider-reported quota pools appear; there is no filtering for finite
pools, consumed pools, or configured Router models.

For a finite pool with a positive limit, the Dataset computes:

```text
remaining_ratio = clamp((remaining / limit) * 100, 0, 100)
```

The Dataset emits the value with its normal percent precision.

For an unlimited pool (`unlimited: true` or a negative provider limit), the
Dataset emits a numeric value of `100` solely because the current Monitor
ranking contract requires a numeric value. Its label appends exactly one
infinity symbol:

```text
<pool> ♾️
```

The symbol is presentation text and is identical in both locales. A finite
pool at 100% is labelled only with its pool name. Thus the label, not the
number alone, distinguishes an unlimited pool from an unused finite pool.

A malformed finite pool with no usable positive limit, or a missing/invalid
quota snapshot, is not silently converted to zero. The Dataset returns its
existing source-unavailable error behavior.

`live_limited` is intentionally ignored. It is a process-local proxy signal
that a model recently received an upstream quota rejection; it does not alter
the entitlement pool balance shown by this metric.

## Model-to-Pool Description

The Router provider snapshot must expose an explicit pool-to-model association.
For the current Trae source, `traex_proxy` documents that all metered Claude and
`openrouter-*` models consume the shared `basic` pool. The Router derives the
association from this documented provider contract, not by comparing matching
numeric balance values.

A pool's description consists of its associated model identifiers in stable
lexicographic order, joined by `, `, localized identically because model IDs are
not translated. A pool with no known associated models omits its description;
it does not infer associations.

The description is presentation metadata. It does not make the ranking row a
per-model balance and it does not affect numeric grouping or ordering.

## Monitor Entry Description Protocol

The concurrent ccusage-viz Monitor-ranking description work defines an
additive `ccuv.custom/v2` Monitor observation group extension from:

```json
{"id":"basic","label":{"en":"basic","zh-CN":"basic"},"value":"69.2"}
```

to:

```json
{
  "id": "basic",
  "label": {"en": "basic", "zh-CN": "basic"},
  "value": "69.2",
  "description": {
    "en": "openrouter-1, openrouter-1o",
    "zh-CN": "openrouter-1, openrouter-1o"
  }
}
```

`description` is optional localized plain text. Existing Datasets that omit it
remain valid and visually unchanged. Empty text is treated as absent. The
protocol parser rejects malformed localized descriptions rather than dropping
them silently.

ccusage-viz owns parsing and rendering this optional Monitor entry description;
this quota work does not modify that repository. The Dataset emits the field
according to that existing contract. The normal ranking presentation rules
apply: no terminal escape interpretation, wrapping constrained by available
width, and no description on synthetic rows.

For historical `ranking`, the Dataset uses the existing `data.series[]`
structure: each pool has exactly one `points` entry at `range.end_date`, and
uses the existing optional series `description` field for the same model list.

## Boundaries

- Router remains responsible for redacting provider state. Raw entitlement pack
  identifiers and authentication-related fields must never enter the Dataset.
- `ccuv-router-dataset` adapts Router's normalized quota snapshot to the V2
  Monitor response. It does not call provider endpoints directly.
- ccusage-viz owns generic Monitor group-description parsing and ranking
  presentation through separate work. This feature only emits the established
  wire fields and does not change that repository.
- Provider-observed request/error/token counters are excluded. They have no
  stable period/reset semantics and are not needed for the quota user story.
- Existing Router Runtime metrics remain separate operational signals.

## Error Handling And Freshness

Router retains a normalized, redacted quota snapshot with a 20-second maximum
freshness age. `GET /internal/providers/trae/usage` returns that cached snapshot
while it is younger than 20 seconds. Once expired, concurrent callers share one
Router-to-`traex_proxy` refresh; the successful refresh replaces the snapshot
before the endpoint responds. The Dataset's quota Monitor declares a 20-second
refresh interval, so normal sampling can obtain one fresh provider snapshot per
observation rather than repeated identical ten-second samples.

Model catalog and capability discovery remain independent: startup refresh plus
hourly background refresh. The quota endpoint must not make catalog discovery
or capability probes run at the 20-second quota cadence.

When the quota snapshot is unavailable, or its refresh fails before any valid
snapshot exists, the Dataset reports `source_unavailable` rather than returning
fabricated zeroes. On refresh failure after a prior success, Router retains the
last good snapshot, marks it `stale: true`, and returns it. The Dataset must
reject that stale value as `source_unavailable` rather than presenting it as a
current quota observation. A valid latest snapshot retains its provider refresh
timestamp in Router state; the Dataset Monitor response uses its normal query
`end_at` for the observation time.

## Verification

Router tests cover:

- finite pools calculate a clamped remaining percentage;
- unlimited pools retain their unlimited state and do not expose raw pack data;
- documented Trae metered models map explicitly to `basic`;
- unassociated pools have no model description;
- `live_limited` does not affect the ratio;
- malformed/missing quota data remains unavailable rather than becoming zero;
- concurrent expired usage reads share exactly one refresh and the 20-second
  quota freshness age does not trigger model catalog refresh.

Dataset tests cover:

- the descriptor declares a `provider_quota` group and the ranking-only metric;
- all pools are returned, including unused finite and unlimited pools;
- unlimited pools emit `100` with a label ending in exactly one `♾️`;
- finite pools use the computed ratio;
- descriptions are single-line comma-separated model IDs;
- no raw pack identifier is returned;
- stale or unavailable provider data maps to the existing source-unavailable
  error;
- the quota metric declares a 20-second refresh while Router Runtime metrics
  retain their 10-second refresh.

Dataset tests also cover:

- Monitor defaults select `ranking`, declare a 20-second refresh, and permit no
  other Monitor presentation capability;
- historical ranking accepts only `period: "all"` and returns one pool series
  point at `range.end_date`;
- any other historical ranking period returns `unsupported_query` for
  `range.period`;
- historical ranking series use the same one-line model-list description.
