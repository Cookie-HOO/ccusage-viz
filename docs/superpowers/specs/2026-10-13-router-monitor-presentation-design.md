# Router Monitor Presentation Design

## Goal

Optimize the three final Router Dataset metrics for ccusage-viz Monitor's source-owned `description` and `display` fields, without modifying ccusage-viz or Router APIs.

## Final Metric Set

- `requests` in `router_runtime`
- `latency_p95_ms` in `router_runtime`
- `quota_remaining_ratio` in `provider_quota`

`error_rate` and local-capacity metrics remain excluded.

## Defaults

`latency_p95_ms` defaults Monitor to:

```json
{"style":"ranking","group_by":"real_model"}
```

Explicit CLI or Dashboard settings continue to override these suggestions. Other runtime metrics retain their existing defaults. Quota retains `style: ranking` and `group_by: quota_pool`.

## Monitor Presentation Metadata

Monitor observation groups emit localized `description` and `display`. Numeric `value` remains authoritative for sorting, chart geometry, Top/Other behavior, and calculations.

### Router QPM

- Keep the numeric group value unchanged.
- `display`: `<value> req/min` in English and `<value> 请求/分钟` in Chinese.
- `description`: `Completed requests in the latest 60 seconds` / `最近 60 秒内完成的请求数`.

### Router P95 Latency

- Keep the numeric group value in milliseconds because the metric and Router telemetry contract remain `latency_p95_ms`.
- Convert only `display` to seconds by dividing the decimal millisecond value by 1000.
- Use up to three decimal places, remove trailing zeros, but retain at least two decimals: examples are `850 -> 0.85 s`, `1250 -> 1.25 s`, and `1000 -> 1.00 s`.
- Chinese and English use the same SI display text.
- `description`: `P95 request latency in the latest 60 seconds` / `最近 60 秒内请求延迟的 P95`.

### Provider Quota

- Finite pool `display`: `<ratio>% remaining` / `剩余 <ratio>%`.
- Unlimited pool `display`: `♾️` in both locales.
- Existing model-list `description` remains unchanged: lexically sorted model IDs joined by comma and space. Pools with no known models omit description.
- Historical Ranking continues to use the existing numeric value and model-list description. This change only requires source-owned display text for Monitor groups.

## Error Handling

If a runtime telemetry value cannot be parsed as a decimal for display formatting, the Dataset still returns the authoritative numeric `value` and omits `display`; it must not fail an otherwise valid observation. Quota values are produced internally and always receive display text.

## Verification

Dataset tests cover:

- exactly three metrics in two groups;
- P95 Monitor defaults to ranking grouped by `real_model`;
- QPM emits localized request-rate display and 60-second description;
- P95 preserves millisecond value while displaying seconds;
- finite quota displays localized remaining text;
- unlimited quota displays only `♾️`;
- quota model descriptions remain unchanged;
- malformed runtime values omit display without corrupting numeric source data.

The Dataset binary is rebuilt in place and the `ccuv-local` registration is refreshed after all Go tests pass.
