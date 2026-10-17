# Router Quota Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose every Trae quota pool as a current-state Router Dataset quota ranking, with pool model lists and a 20-second Monitor refresh.

**Architecture:** Router separates the high-frequency redacted Trae quota snapshot from hourly catalog discovery, and serves it with a 20-second single-flight freshness cache. `ccuv-router-dataset` adapts that snapshot into the established V2 Monitor-ranking-description contract and into a historical Ranking current-state projection that only accepts `period: "all"`. ccusage-viz is out of scope: its Monitor ranking description support is implemented independently.

**Tech Stack:** Python 3.11, Starlette, httpx, Go, `ccuv.custom/v2`, Python unittest, Go `testing`.

**Spec:** `~/projects/py/ccusage-viz/docs/superpowers/specs/2026-10-13-router-quota-ranking-design.md`

## Global Constraints

- Do not expose raw entitlement pack identifiers, credentials, upstream URLs, prompts, or provider bodies.
- Catalog/capability discovery remains startup plus hourly; quota usage alone gets a 20-second freshness policy.
- Concurrent expired quota reads share one provider refresh.
- Emit every quota pool: finite pools use clamped remaining percentage; unlimited pools use `100` and label suffix `♾️`.
- Ignore `live_limited` for quota ratio calculation.
- `quota_remaining_ratio` is a `value` metric with `summary: none`; Monitor defaults to ranking at 20 seconds and historical ranking accepts only `period: "all"`.
- Pool model descriptions are optional, plain, one-line, lexically sorted, comma-and-space-separated identifiers.
- Runtime metrics retain their 60-second business window and 10-second Monitor refresh.
- Do not modify `ccusage-viz`; consume its independently implemented Monitor group `description` wire contract.

---

## File Structure

```text
/Users/bytedance/Projects/my_ai/tools/custom/proxy/
  router_v3/trae_state.py             # Separate catalog/quota state, redaction, pool-model association, single-flight quota reads
  router_v3/app.py                    # Startup lifecycle and quota endpoint status mapping
  tests/test_router_v3_trae_state.py  # State normalization, freshness, and concurrency tests
  tests/test_router_v3.py             # Internal usage endpoint tests

/Users/bytedance/projects/go/ccuv-router-dataset/
  internal/router/client.go            # Typed Router quota snapshot client
  internal/router/client_test.go       # Usage endpoint/stale response tests
  cmd/ccuv-router-dataset/main.go      # Descriptor, Monitor observation, and all-time Ranking projection
  cmd/ccuv-router-dataset/main_test.go # Metric descriptor and response tests
  README.md                            # Quota semantics and refresh behavior
```

### Task 1: Split and normalize Router Trae quota state

**Files:**
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/router_v3/trae_state.py`
- Create: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/tests/test_router_v3_trae_state.py`

**Interfaces:**
- Consumes: `GET <traex_proxy>/v1/models` and `GET <traex_proxy>/v1/usage`.
- Produces: `TraeProviderState.refresh_catalog(client)`, `TraeProviderState.refresh_usage(client)`, and a redacted usage shape:

```python
{
    "provider": "traex_proxy", "refreshed_at": str, "stale": bool,
    "quota": {"pools": list[dict[str, object]]},
    "pool_models": dict[str, list[str]],
}
```

- [ ] **Step 1: Write failing normalized-quota tests**

Create `tests/test_router_v3_trae_state.py` with an `httpx.MockTransport` returning catalog rows `openrouter-2o` and `GPT-5.5`, plus usage containing finite `basic` and unlimited `advanced`. Assert:

```python
self.assertNotIn("pack", payload["quota"])
self.assertEqual(payload["quota"]["pools"][0]["id"], "basic")
self.assertEqual(payload["pool_models"], {"basic": ["openrouter-2o"]})
self.assertFalse(payload["stale"])
```

Add a case where a raw model row has `live_limited=True` and assert it does not alter pool membership or values. Add a pool with no documented model association and assert it remains in `pools` with no invented `pool_models` item.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy
uv run python -m unittest tests.test_router_v3_trae_state -v
```

Expected: FAIL because the current state refresh couples catalog/usage and exposes raw usage directly.

- [ ] **Step 3: Implement separate catalog and quota normalization**

Replace the coupled `refresh()` path in `router_v3/trae_state.py` with:

```python
async def refresh_catalog(self, client: httpx.AsyncClient) -> None: ...
async def refresh_usage(self, client: httpx.AsyncClient) -> None: ...
```

Keep catalog normalization in `refresh_catalog`. In `refresh_usage`, fetch only `/v1/usage`, retain all quota pools, remove `quota.pack`, and atomically write the redacted `trae-usage.json`.

Build `pool_models` from the documented Trae contract: raw model rows with a positive `quota_limit` map to `basic`; sort model IDs lexically. Do not infer a pool association from equal numeric balances. Preserve the most recent successful usage payload and set only its `stale` flag when refresh fails.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
uv run python -m unittest tests.test_router_v3_trae_state -v
```

Expected: PASS.

Commit:

```bash
git add router_v3/trae_state.py tests/test_router_v3_trae_state.py
git commit -m "feat: normalize router quota state"
```

### Task 2: Add Router 20-second single-flight quota freshness

**Files:**
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/router_v3/trae_state.py`
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/router_v3/app.py`
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/tests/test_router_v3_trae_state.py`
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/tests/test_router_v3.py`

**Interfaces:**
- Consumes: `await TraeProviderState.usage_payload(client)`.
- Produces: `GET /internal/providers/trae/usage`, which returns a fresh/redacted snapshot, a stale marked prior snapshot, or HTTP 503 when no valid snapshot exists.

- [ ] **Step 1: Write failing freshness and endpoint tests**

Inject a controllable UTC clock and assert:

```python
await state.usage_payload(client)  # one /v1/usage request
await state.usage_payload(client)  # still one request within 20 seconds
clock.advance(20)
await asyncio.gather(*(state.usage_payload(client) for _ in range(3)))
# exactly two total /v1/usage requests
```

Add endpoint tests that an expired successful refresh returns current data, an expired failure returns the last known snapshot with `stale: true`, and a startup failure before a successful quota snapshot returns HTTP 503 rather than a synthetic empty/zero quota response.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
```

Expected: FAIL because the endpoint merely returns the existing state and refreshes only through the hourly loop.

- [ ] **Step 3: Implement 20-second usage refresh and keep catalog hourly**

In `TraeProviderState.__post_init__`, add:

```python
self.usage_max_age_seconds = 20.0
self._usage_refreshed_at: datetime | None = None
self._usage_refresh_task: asyncio.Task[None] | None = None
self._usage_refresh_lock = asyncio.Lock()
```

Implement `usage_payload(client)` to return a non-stale snapshot younger than 20 seconds. Otherwise, create or await exactly one `refresh_usage(client)` task under `_usage_refresh_lock`. On refresh failure after a known-good state, return it with `stale: true`; before any known-good state, raise a typed unavailable error.

In `RouterService.startup()`, synchronously call `refresh_catalog()` and `refresh_usage()`. Make the background state task refresh catalog only at the existing hourly cadence. Update `RouterService.trae_usage()` to await `usage_payload(self.client)` and map the typed no-snapshot error to HTTP 503.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
```

Expected: PASS.

Commit:

```bash
git add router_v3/trae_state.py router_v3/app.py tests/test_router_v3_trae_state.py tests/test_router_v3.py
git commit -m "feat: refresh router quota snapshots on demand"
```

### Task 3: Add typed Router quota client in the Dataset

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/internal/router/client.go`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/internal/router/client_test.go`

**Interfaces:**
- Consumes: `GET /internal/providers/trae/usage` payload from Task 2.
- Produces:

```go
type QuotaPool struct { ID string; Limit, Remaining float64; Unlimited bool }
type QuotaUsage struct { Stale bool; Pools []QuotaPool; PoolModels map[string][]string }
func (c Client) QuotaUsage() (QuotaUsage, error)
```

- [ ] **Step 1: Write failing client tests**

Add an HTTP test response:

```json
{"provider":"traex_proxy","stale":false,"quota":{"pools":[{"id":"basic","limit":300,"remaining":207.6,"unlimited":false},{"id":"advanced","limit":-1,"remaining":0,"unlimited":true}]},"pool_models":{"basic":["openrouter-1","openrouter-2o"]}}
```

Assert the request path is `/internal/providers/trae/usage`, finite/unlimited fields decode correctly, and `PoolModels["basic"]` contains both models. Add a stale payload test and an HTTP 503 test, each expecting a typed source-unavailable error.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go test ./internal/router -count=1
```

Expected: FAIL because `Client` supports only telemetry snapshots.

- [ ] **Step 3: Implement typed quota usage retrieval**

Add the exported structs and `QuotaUsage()` method. Use the existing `BaseURL` and optional HTTP client conventions. Return a dedicated error type for HTTP 503 and `stale: true`; do not return stale payload data to the caller.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
go test ./internal/router -count=1
```

Expected: PASS.

Commit:

```bash
git add internal/router/client.go internal/router/client_test.go
git commit -m "feat: read router quota snapshots"
```

### Task 4: Add quota Monitor and all-time historical Ranking

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main.go`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main_test.go`

**Interfaces:**
- Consumes: `router.Client.QuotaUsage()`.
- Produces: `quota_remaining_ratio` responses for `request_kind: "monitor"` and `request_kind: "chart"`.

- [ ] **Step 1: Write failing descriptor and Monitor tests**

Assert the probe descriptor declares an ordered `metric_groups` item:

```json
{"id":"provider_quota","title":{"en":"Provider Quota","zh-CN":"Provider 额度"}}
```

and a `quota_remaining_ratio` metric with:

```json
{
  "group_id":"provider_quota",
  "aggregation":"value",
  "summary":"none",
  "capabilities":{"group_by":[{"id":"quota_pool"}],"charts":{"monitor":{"window_seconds":20,"refresh_interval_seconds":20,"group_by":["quota_pool"]},"ranking":{"granularities":["day"],"group_by":["quota_pool"],"periods":["all"]}}},
  "defaults":{"monitor":{"style":"ranking"},"ranking":{"period":"all","group_by":"quota_pool"}}
}
```

For a finite `basic` pool with remaining `207.6` of `300`, assert Monitor group:

```json
{"id":"basic","label":{"en":"basic","zh-CN":"basic"},"value":"69.2","description":{"en":"openrouter-1, openrouter-2o","zh-CN":"openrouter-1, openrouter-2o"}}
```

For unlimited `advanced`, assert `value: "100"`, label `advanced ♾️`, and no description.

- [ ] **Step 2: Add failing historical Ranking tests**

Send a V2 chart request with `metric_id: "quota_remaining_ratio"`, `period: "all"`, `group_by: "quota_pool"`, and `end_date: "2026-10-13"`. Assert `data.series` contains one item per pool, each with exactly:

```json
{"date":"2026-10-13","value":"69.2"}
```

and the same optional one-line model description used by Monitor.

Send the same request with `period: "30d"` and assert an `unsupported_query` response whose `unsupported` object is:

```json
{"field":"range.period","value":"30d"}
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go test ./cmd/ccuv-router-dataset -count=1
```

Expected: FAIL because the command accepts Monitor only and has no quota metric.

- [ ] **Step 4: Implement descriptor and shared quota rows**

Refactor `descriptor()` to declare `metric_groups`, retain all three existing Runtime metrics unchanged, and add `quota_remaining_ratio` with Monitor and Ranking capabilities described in Step 1.

Create a helper:

```go
func quotaRows(usage router.QuotaUsage) ([]quotaRow, error)
```

where `quotaRow` contains ID, localized label, decimal value, and optional localized description. Sort pools and associated model IDs lexically. For each pool:

```go
if pool.Unlimited || pool.Limit < 0 {
    value, label = "100", pool.ID+" ♾️"
} else if pool.Limit > 0 {
    value = decimalString(clamp(pool.Remaining/pool.Limit*100, 0, 100))
    label = pool.ID
} else {
    return nil, errSourceUnavailable
}
```

Use `strings.Join(models, ", ")` for the one-line description. Do not read raw packs, `observed`, raw per-model quota values, or `live_limited`.

- [ ] **Step 5: Implement Monitor and historical Ranking dispatch**

Keep the existing telemetry dispatch for `requests`, `error_rate`, and `latency_p95_ms` unchanged.

For quota Monitor requests, require `query.group_by == "quota_pool"`; call `QuotaUsage()`, build quota rows, and return the established Monitor observation with `end_at` from the request and `total: "0"` because pool percentages are non-additive.

For quota chart requests, require `query.group_by == "quota_pool"`, `query.granularity == "day"`, and `range.period == "all"`. Return `data.series`, one series per quota row, with one point at `range.end_date` and the optional `description`. Reject every other period with `unsupported_query` for `range.period`. Reject all chart requests for the three Runtime metrics with the existing unsupported-query behavior.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
go test ./cmd/ccuv-router-dataset -count=1
go test ./... -count=1
```

Expected: PASS.

Commit:

```bash
git add cmd/ccuv-router-dataset/main.go cmd/ccuv-router-dataset/main_test.go
git commit -m "feat: add router quota rankings"
```

### Task 5: Document and validate both repositories

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/README.md`
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/docs/ROUTER_V3.md`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main_test.go`

**Interfaces:**
- Consumes: final Router usage endpoint and Dataset descriptor.
- Produces: safe documentation of ratio semantics, `♾️`, model descriptions, 20-second refresh, and all-time ranking behavior.

- [ ] **Step 1: Add a cadence regression test**

Assert the existing `requests` descriptor continues to contain `window_seconds: 60` and `refresh_interval_seconds: 10`, while quota Monitor has `window_seconds: 20`, `refresh_interval_seconds: 20`, and default style `ranking`.

- [ ] **Step 2: Run the regression test**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go test ./cmd/ccuv-router-dataset -run TestDescriptor -count=1
```

Expected: PASS.

- [ ] **Step 3: Update documentation**

In the Dataset README, document:

- Provider Quota and `quota_remaining_ratio`;
- all pools are displayed;
- finite-pool formula and unlimited `100% + ♾️` convention;
- model descriptions are pool associations, not independent balances;
- `live_limited` is ignored;
- Monitor refresh is 20 seconds and default style is ranking;
- historical Ranking accepts only `all` and projects the current snapshot, not history.

In Router documentation, state that `/internal/providers/trae/usage` is redacted, has 20-second on-demand single-flight freshness, marks last-known-good data stale after failed refresh, and never exposes pack/auth fields.

- [ ] **Step 4: Run final suites and commit documentation**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy && uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
cd /Users/bytedance/projects/go/ccuv-router-dataset && go test ./... -count=1
```

Expected: PASS.

Commit Dataset documentation:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
git add README.md cmd/ccuv-router-dataset/main_test.go
git commit -m "docs: explain router quota rankings"
```

Commit Router documentation:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy
git add docs/ROUTER_V3.md
git commit -m "docs: describe quota snapshot freshness"
```

### Task 6: End-to-end local validation

**Files:**
- Test only; no source changes.

- [ ] **Step 1: Run focused repository tests**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy && uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
cd /Users/bytedance/projects/go/ccuv-router-dataset && go test ./... -count=1
```

Expected: PASS.

- [ ] **Step 2: Probe the descriptor**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go run ./cmd/ccuv-router-dataset ccuv <<'JSON'
{"protocol":"ccuv.custom/v2","request_id":"quota-probe","request_kind":"probe"}
JSON
```

Expected: the output contains `quota_remaining_ratio`, `provider_quota`, a Monitor default ranking at 20 seconds, and historical Ranking limited to `periods: ["all"]`; it contains no raw pack identifier.

- [ ] **Step 3: Query Monitor and all-time Ranking against running Router**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
CCUV_ROUTER_URL=http://127.0.0.1:4300 go run ./cmd/ccuv-router-dataset ccuv <<'JSON'
{"protocol":"ccuv.custom/v2","request_id":"quota-monitor","request_kind":"monitor","dataset_id":"router","metric_id":"quota_remaining_ratio","timezone":"Asia/Shanghai","range":{"end_at":"2026-10-13T12:00:00+08:00"},"query":{"filters":{},"group_by":"quota_pool"}}
JSON
CCUV_ROUTER_URL=http://127.0.0.1:4300 go run ./cmd/ccuv-router-dataset ccuv <<'JSON'
{"protocol":"ccuv.custom/v2","request_id":"quota-ranking","request_kind":"chart","dataset_id":"router","metric_id":"quota_remaining_ratio","timezone":"Asia/Shanghai","range":{"start_date":"1971-01-01","end_date":"2026-10-13","period":"all"},"query":{"filters":{},"group_by":"quota_pool","granularity":"day","top":null}}
JSON
```

Expected: Monitor groups and Ranking series contain every pool; unlimited labels end in one `♾️`; known model descriptions are one-line comma-separated strings; Ranking points use `2026-10-13`; no output contains a raw entitlement pack.

- [ ] **Step 4: Confirm no unintended working-tree changes**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy && git status --short
cd /Users/bytedance/projects/go/ccuv-router-dataset && git status --short
cd /Users/bytedance/projects/py/ccusage-viz && git status --short
```

Expected: only pre-existing user changes and the independently owned ccusage-viz work remain; report any new unexpected uncommitted files.
