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

It supports only the Custom Monitor `ranking` presentation. The ranking has one
row per quota pool, sorted by the normal descending numeric ranking behavior.

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
Chart capability: ranking only
Grouping: quota_pool only
```

`value` means the Dataset owns the exact current quota snapshot. ccusage-viz
must neither add snapshots over time nor permit cumulative-bar presentation.

The metric description states that it is a provider quota snapshot and that a
model list identifies models attached to the pool; it must not claim models
have independent quota balances.

The Dataset continues to expose the existing Router Runtime metrics unchanged:
`requests`, `error_rate`, and `latency_p95_ms`.

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

The `ccuv.custom/v2` Monitor observation group is extended additively from:

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

ccusage-viz carries the optional description from the Monitor observation group
through the custom Monitor ranking projection. It renders it directly below the
corresponding ranking row using the existing muted ranking-description style.
The normal ranking presentation rules apply: no terminal escape interpretation,
wrapping constrained by available width, and no description on synthetic rows.
The description does not render in Monitor `list`, timeline, bars, or
cumulative-bars because the quota metric declares ranking only.

## Boundaries

- Router remains responsible for redacting provider state. Raw entitlement pack
  identifiers and authentication-related fields must never enter the Dataset.
- `ccuv-router-dataset` adapts Router's normalized quota snapshot to the V2
  Monitor response. It does not call provider endpoints directly.
- ccusage-viz owns generic Monitor group-description parsing and ranking
  presentation. It does not contain Trae-specific pool or model rules.
- Provider-observed request/error/token counters are excluded. They have no
  stable period/reset semantics and are not needed for the quota user story.
- Existing Router Runtime metrics remain separate operational signals.

## Error Handling And Freshness

The Router quota snapshot includes freshness state. When it is unavailable or
stale beyond the accepted Dataset policy, the Dataset reports `source_unavailable`
rather than returning fabricated zeroes. A valid latest snapshot must retain its
provider timestamp in Router state; the Dataset's Monitor observation endpoint
uses its normal query `end_at` for the observation time.

## Verification

Router tests cover:

- finite pools calculate a clamped remaining percentage;
- unlimited pools retain their unlimited state and do not expose raw pack data;
- documented Trae metered models map explicitly to `basic`;
- unassociated pools have no model description;
- `live_limited` does not affect the ratio;
- malformed/missing quota data remains unavailable rather than becoming zero.

Dataset tests cover:

- the descriptor declares a `provider_quota` group and the ranking-only metric;
- all pools are returned, including unused finite and unlimited pools;
- unlimited pools emit `100` with a label ending in exactly one `♾️`;
- finite pools use the computed ratio;
- descriptions are single-line comma-separated model IDs;
- no raw pack identifier is returned;
- unavailable provider data maps to the existing source-unavailable error.

ccusage-viz tests cover:

- valid and omitted Monitor group descriptions;
- malformed group descriptions fail protocol parsing;
- descriptions survive Custom Monitor ranking projection;
- ranking renders the description beneath the matching row;
- non-ranking Custom Monitor views do not render descriptions;
- existing description-free Monitor rendering remains unchanged.
