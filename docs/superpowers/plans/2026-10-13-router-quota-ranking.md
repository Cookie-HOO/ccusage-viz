# Router Quota Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every normalized Trae quota pool as a 20-second, ranking-only Router Dataset metric with an optional one-line model list beneath each pool.

**Architecture:** Router separates high-frequency Trae quota refresh from hourly catalog refresh and serves a redacted, single-flight 20-second quota snapshot. The Go Dataset converts that snapshot into `quota_remaining_ratio` Monitor observations. ccusage-viz extends the generic V2 Monitor group entry with an optional localized description and uses its existing ranking-description presentation for custom Monitor rankings.

**Tech Stack:** Python 3.11, Starlette, httpx, Go, `ccuv.custom/v2`, Python dataclasses, pytest, Go `testing`.

**Spec:** `~/projects/py/ccusage-viz/docs/superpowers/specs/2026-10-13-router-quota-ranking-design.md`

## Global Constraints

- Do not expose raw entitlement pack identifiers, credentials, upstream URLs, prompts, or provider bodies.
- Router catalog/capability refresh remains startup plus hourly; only quota usage has a 20-second freshness policy.
- Expired concurrent quota reads share one refresh; no caller causes duplicate concurrent provider reads.
- The quota Dataset emits all pools: finite pools use the clamped remaining ratio; unlimited pools emit `100` and append exactly one `♾️` to the label.
- Ignore `live_limited` for quota ratio calculation.
- The quota metric is `value`, `summary: none`, `ranking` only, grouped by `quota_pool`, with a 20-second Monitor refresh interval.
- Pool model descriptions are optional, plain, one-line comma-and-space-separated identifiers in stable lexical order.
- Existing Router Runtime metric IDs and their 60-second window / 10-second refresh behavior remain unchanged.

---

## File Structure

```text
/Users/bytedance/Projects/my_ai/tools/custom/proxy/
  router_v3/trae_state.py             # Separate catalog and quota snapshots; redacted quota normalization and single-flight TTL refresh
  router_v3/app.py                    # Calls quota-aware state endpoint and keeps startup/catalog lifecycle wiring
  tests/test_router_v3_trae_state.py  # Provider-state freshness, redaction, pool/model association tests
  tests/test_router_v3.py             # Internal usage endpoint status/payload tests

/Users/bytedance/projects/go/ccuv-router-dataset/
  internal/router/client.go            # Typed Router quota snapshot client
  internal/router/client_test.go       # HTTP request/response and stale-status tests
  cmd/ccuv-router-dataset/main.go      # Descriptor, metric dispatch, quota observation conversion
  cmd/ccuv-router-dataset/main_test.go # Descriptor and Monitor response tests
  README.md                            # User-facing quota semantics and refresh cadence

/Users/bytedance/projects/py/ccusage-viz/
  src/ccusage_viz/custom_models.py             # Optional description on V2 Monitor group values
  src/ccusage_viz/custom_protocol.py           # Strict parse/validation of Monitor group descriptions
  src/ccusage_viz/custom_monitor_component.py  # Preserve descriptions in ranking entries and native ranking projection
  src/ccusage_viz/chart_models.py               # Optional scalar observed-ranking description
  src/ccusage_viz/render/ranking.py             # Render observed-ranking descriptions with existing ranking description behavior
  tests/test_custom_protocol.py                 # Description parse/validation coverage
  tests/test_custom_monitor_component.py        # Projection coverage
  tests/test_render.py                           # Rendered Monitor ranking description coverage
  docs/custom-command-protocol.md               # V2 Monitor group description contract
  docs/custom-command-protocol.zh-CN.md         # Chinese contract
```

### Task 1: Split and normalize Router Trae quota state

**Files:**
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/router_v3/trae_state.py`
- Create: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/tests/test_router_v3_trae_state.py`

**Interfaces:**
- Consumes: `GET <traex_proxy>/v1/models`, `GET <traex_proxy>/v1/usage`.
- Produces: `TraeProviderState.refresh_catalog(client)`, `TraeProviderState.refresh_usage(client)`, and `TraeProviderState.usage_payload(client)`.
- `usage_payload(client)` returns a redacted `dict[str, object]` with `provider`, `refreshed_at`, `stale`, `quota: {pools: [...]}`, and `pool_models: {pool_id: [model_id, ...]}`.

- [ ] **Step 1: Write failing normalization tests**

Create `tests/test_router_v3_trae_state.py` with an `httpx.MockTransport` fixture returning a catalog containing metered `openrouter-2o`, unmetered `GPT-5.5`, and usage containing finite `basic` plus unlimited `advanced` pools. Assert the normalized usage payload:

```python
self.assertNotIn("pack", payload["quota"])
self.assertEqual(payload["quota"]["pools"][0]["id"], "basic")
self.assertEqual(payload["pool_models"], {"basic": ["openrouter-2o"]})
self.assertFalse(payload["stale"])
```

Add tests that `live_limited=True` in a raw model row does not alter a pool value or pool-model association, and that a pool without a known association is retained with no `pool_models` entry.

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy
uv run python -m unittest tests.test_router_v3_trae_state -v
```

Expected: FAIL because `TraeProviderState` does not yet expose split refresh methods or redacted pool-model output.

- [ ] **Step 3: Implement independent catalog and usage refresh paths**

In `router_v3/trae_state.py`, replace the coupled `refresh()` implementation with:

```python
async def refresh_catalog(self, client: httpx.AsyncClient) -> None: ...
async def refresh_usage(self, client: httpx.AsyncClient) -> None: ...
```

Keep the existing normalized catalog behavior in `refresh_catalog`. In `refresh_usage`, fetch only `/v1/usage`; retain only quota pools, `models`, and `observed` fields that are required by Router state, then create a redacted public payload that omits raw `quota.pack`.

Build `pool_models` from the documented provider association: only raw usage model rows that carry a positive `quota_limit` belong to `basic`; sort model IDs lexically. Do not infer associations from matching numeric balances. Preserve all provider pools, including unlimited pools.

Persist `trae-usage.json` atomically after successful usage refresh. On an unsuccessful refresh, keep the prior successful payload and set `stale: true` without erasing it.

- [ ] **Step 4: Run the normalization tests and commit**

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
- Consumes: `TraeProviderState.usage_payload(client)`.
- Produces: `GET /internal/providers/trae/usage` returning the current normalized usage snapshot or a service-unavailable response before any successful quota snapshot.

- [ ] **Step 1: Write failing freshness and endpoint tests**

Use an injected monotonic/UTC clock and an async mock usage fetcher. Assert:

```python
await state.usage_payload(client)  # first request: one /v1/usage fetch
await state.usage_payload(client)  # within 20 seconds: still one fetch
clock.advance(20)
await asyncio.gather(*(state.usage_payload(client) for _ in range(3)))
# exactly two total /v1/usage fetches
```

Add an endpoint test that a successful expired refresh returns the updated payload, and an expired refresh failure returns the old snapshot with `stale: true`. Add a Dataset-facing condition test that no successful snapshot produces a non-200 unavailable result rather than a fabricated zero-pool response.

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
```

Expected: FAIL because current `/internal/providers/trae/usage` only returns the stored object and does not refresh on read.

- [ ] **Step 3: Implement 20-second single-flight usage reads**

Add these state fields in `TraeProviderState.__post_init__`:

```python
self.usage_max_age_seconds = 20.0
self._usage_refreshed_at: datetime | None = None
self._usage_refresh_task: asyncio.Task[None] | None = None
self._usage_refresh_lock = asyncio.Lock()
```

Implement `usage_payload(client)` to return the current usage object while it is non-stale and younger than 20 seconds. Otherwise create or await exactly one `refresh_usage(client)` task under `_usage_refresh_lock`. On a failure after a known-good snapshot, return that snapshot with `stale: true`; on a failure before a known-good snapshot, raise a typed state error that `app.py` maps to HTTP 503.

In `RouterService.startup()`, synchronously call both `refresh_catalog()` and `refresh_usage()` once. Keep `TraeProviderState.start()` as an hourly catalog-only background loop. Update `RouterService.trae_usage()` to await `usage_payload(self.client)` and return 503 for the no-snapshot state.

- [ ] **Step 4: Run focused Router tests and commit**

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

### Task 3: Add generic V2 Monitor entry descriptions in ccusage-viz

**Files:**
- Modify: `/Users/bytedance/projects/py/ccusage-viz/src/ccusage_viz/custom_models.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/src/ccusage_viz/custom_protocol.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/src/ccusage_viz/chart_models.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/src/ccusage_viz/custom_monitor_component.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/src/ccusage_viz/render/ranking.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/tests/test_custom_protocol.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/tests/test_custom_monitor_component.py`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/tests/test_render.py`

**Interfaces:**
- Consumes: optional Monitor group JSON `description: {"en": str, "zh-CN": str}`.
- Produces: `V2MetricValue.description: LocalizedText | None` and `ScalarRankingEntry.description: str | None` in a custom Monitor ranking model.

- [ ] **Step 1: Write failing protocol and projection tests**

Add a successful V2 Monitor response fixture containing:

```json
"groups": [{
  "id": "basic",
  "label": {"en": "basic", "zh-CN": "basic"},
  "value": "69.2",
  "description": {"en": "openrouter-1, openrouter-2o", "zh-CN": "openrouter-1, openrouter-2o"}
}]
```

Assert `parsed.observation.groups[0].description == LocalizedText(...)`. Add malformed-string and missing-locale description cases and assert `CustomProtocolError`.

Add a `CustomMonitorComponent.ranking_model(language="en")` test asserting the generated `ScalarRankingEntry.description` is the English source string. Add a renderer test asserting that string appears below the observed-ranking row when descriptions are enabled, and a regression asserting description-free Monitor output is unchanged.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd /Users/bytedance/projects/py/ccusage-viz
uv run pytest tests/test_custom_protocol.py tests/test_custom_monitor_component.py tests/test_render.py -q
```

Expected: FAIL because Monitor group parsing and scalar observed rankings discard descriptions.

- [ ] **Step 3: Implement strict parsing and ranking propagation**

Add `description: LocalizedText | None = None` to `V2MetricValue`. In `_parse_v2_monitor_observation`, accept only an absent value or a valid `_parse_localized(...)` description; reject malformed values.

Add `description: str | None = None` to `ScalarRankingEntry` after existing optional fields so current constructors remain compatible. Add the matching optional description to `CustomMonitorRankingEntry`. In `CustomMonitorComponent.ranking()`, carry `group.description`; in `ranking_model()`, localize it with `_localized` and pass it to `ScalarRankingEntry`.

Extend the observed branch in `render/ranking.py`: after writing an observed scalar row, append its optional description directly below that row. Reuse `_description_visible_text`, `_description_row_markup`, `_render_highlighted_description`, `wrap_width`, and the existing muted style from `ranking_presentation.py`; cap it at two physical lines exactly as historical Ranking does. Do not alter historical rendering, add a second custom Monitor renderer, or expose descriptions for list/timeline/bars.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
uv run pytest tests/test_custom_protocol.py tests/test_custom_monitor_component.py tests/test_render.py -q
```

Expected: PASS.

Commit:

```bash
git add src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py src/ccusage_viz/chart_models.py src/ccusage_viz/custom_monitor_component.py src/ccusage_viz/render/ranking.py tests/test_custom_protocol.py tests/test_custom_monitor_component.py tests/test_render.py
git commit -m "feat: render custom monitor ranking descriptions"
```

### Task 4: Document the V2 Monitor description extension

**Files:**
- Modify: `/Users/bytedance/projects/py/ccusage-viz/docs/custom-command-protocol.md`
- Modify: `/Users/bytedance/projects/py/ccusage-viz/docs/custom-command-protocol.zh-CN.md`
- Test: `/Users/bytedance/projects/py/ccusage-viz/tests/test_custom_protocol.py`

**Interfaces:**
- Consumes: the implemented optional V2 Monitor observation group description.
- Produces: protocol documentation that distinguishes Monitor group descriptions from historical Ranking `data.series[].description`.

- [ ] **Step 1: Add a documentation-facing protocol fixture test**

Add a protocol test proving a Monitor group description is accepted only as localized text and is optional. Name it `test_v2_monitor_group_description_is_optional_localized_text`.

- [ ] **Step 2: Run it to verify the implemented parser remains green**

Run:

```bash
uv run pytest tests/test_custom_protocol.py::test_v2_monitor_group_description_is_optional_localized_text -q
```

Expected: PASS.

- [ ] **Step 3: Update both protocol guides**

In the V2 Monitor response section of each guide, add the exact optional group field:

```json
"description": {"en": "optional plain text", "zh-CN": "可选纯文本"}
```

State that it is rendered below a Custom Monitor ranking entry when the host displays descriptions; omission preserves existing behavior; it is plain text and is not rendered in list/timeline/bars.

- [ ] **Step 4: Run documentation-adjacent protocol tests and commit**

Run:

```bash
uv run pytest tests/test_custom_protocol.py -q
```

Expected: PASS.

Commit:

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md tests/test_custom_protocol.py
git commit -m "docs: describe monitor entry descriptions"
```

### Task 5: Add the Router Dataset quota ranking metric

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/internal/router/client.go`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/internal/router/client_test.go`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main.go`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main_test.go`
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/README.md`

**Interfaces:**
- Consumes: Router `GET /internal/providers/trae/usage` normalized payload with `stale`, `quota.pools[]`, and `pool_models`.
- Produces: `quota_remaining_ratio` V2 Monitor observation groups with optional localized descriptions.

- [ ] **Step 1: Write failing typed client and conversion tests**

Add a test server response:

```json
{
  "provider":"traex_proxy",
  "stale":false,
  "quota":{"pools":[
    {"id":"basic","limit":300,"remaining":207.6,"unlimited":false},
    {"id":"advanced","limit":-1,"remaining":0,"unlimited":true}
  ]},
  "pool_models":{"basic":["openrouter-1","openrouter-2o"]}
}
```

Assert the client calls `/internal/providers/trae/usage`, decodes it, and returns a distinct stale error when `stale=true`.

Add command tests asserting the Probe descriptor includes a `provider_quota` group and `quota_remaining_ratio` with `aggregation: value`, `summary: none`, Monitor `refresh_interval_seconds: 20`, `group_by: ["quota_pool"]`, and only `ranking` under charts.

Add Monitor tests asserting:

```json
basic:    value "69.2", label "basic", description "openrouter-1, openrouter-2o"
advanced: value "100",  label "advanced ♾️", no description
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go test ./internal/router ./cmd/ccuv-router-dataset -count=1
```

Expected: FAIL because the client only implements telemetry snapshots and the descriptor has no quota metric.

- [ ] **Step 3: Add typed usage client and quota observation conversion**

In `internal/router/client.go`, add typed structures for the redacted snapshot and:

```go
func (c Client) QuotaUsage() (QuotaUsage, error)
```

Map Router HTTP 503 and `stale: true` to a typed error that the command maps to existing `source_unavailable`; do not emit stale data.

In `main.go`, dispatch `quota_remaining_ratio` separately from telemetry metrics. For every returned pool:

```go
if pool.Unlimited || pool.Limit < 0 {
    value = "100"
    label = pool.ID + " ♾️"
} else if pool.Limit > 0 {
    value = decimalString(clamp(pool.Remaining/pool.Limit*100, 0, 100))
    label = pool.ID
} else {
    return sourceUnavailable(...)
}
```

Sort pool output by ID before returning it; let ccusage-viz rank by numeric value. Join each `PoolModels[pool.ID]` with `", "` after lexical sorting. Do not use raw packs, raw model quota figures, `observed`, or `live_limited`.

Keep the existing telemetry path unchanged, including its 10-second refresh and 60-second business window.

- [ ] **Step 4: Run Go tests and commit**

Run:

```bash
go test ./... -count=1
```

Expected: PASS.

Commit:

```bash
git add internal/router/client.go internal/router/client_test.go cmd/ccuv-router-dataset/main.go cmd/ccuv-router-dataset/main_test.go
git commit -m "feat: add router quota ranking metric"
```

### Task 6: Document and validate the full Dataset contract

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/README.md`
- Modify: `/Users/bytedance/Projects/my_ai/tools/custom/proxy/docs/ROUTER_V3.md`
- Test: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main_test.go`

**Interfaces:**
- Consumes: final Router endpoint and final Dataset descriptor.
- Produces: safe user documentation for refresh frequency, ratio semantics, `♾️`, and model-list description behavior.

- [ ] **Step 1: Add a descriptor regression test for runtime metric cadence**

In `main_test.go`, assert the existing `requests` Monitor capability still contains:

```json
{"window_seconds": 60, "refresh_interval_seconds": 10}
```

and quota contains `refresh_interval_seconds: 20` plus only `ranking`.

- [ ] **Step 2: Run the regression test**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go test ./cmd/ccuv-router-dataset -run 'TestDescriptor' -count=1
```

Expected: PASS.

- [ ] **Step 3: Update Dataset and Router documentation**

In the Dataset README, document the new `Provider Quota` metric group, 20-second refresh, finite calculation, unlimited `100%` plus `♾️` convention, and model-list description. Explicitly say displayed models do not imply independent model balances and that `live_limited` is not reflected.

In `docs/ROUTER_V3.md`, document that `/internal/providers/trae/usage` is a redacted quota endpoint with a 20-second on-demand freshness cache, single-flight refresh, and stale metadata. Do not include actual pack values, internal auth paths, or credentials.

- [ ] **Step 4: Run repository checks and commit each repository’s documentation**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset && go test ./... -count=1
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy && uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
```

Expected: PASS.

Commit in Dataset:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
git add README.md cmd/ccuv-router-dataset/main_test.go
git commit -m "docs: explain router quota ranking"
```

Commit in Router:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy
git add docs/ROUTER_V3.md
git commit -m "docs: describe quota snapshot freshness"
```

### Task 7: End-to-end local validation

**Files:**
- Test: all modified repositories; no production source changes.

**Interfaces:**
- Consumes: local Router v3, Router Dataset executable, and ccusage-viz installed/local command registration.
- Produces: evidence that a quota Monitor response travels from Router state to a ranking description without raw pack exposure.

- [ ] **Step 1: Run all focused suites**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy && uv run python -m unittest tests.test_router_v3_trae_state tests.test_router_v3 -v
cd /Users/bytedance/projects/go/ccuv-router-dataset && go test ./... -count=1
cd /Users/bytedance/projects/py/ccusage-viz && uv run pytest tests/test_custom_protocol.py tests/test_custom_monitor_component.py tests/test_render.py -q
```

Expected: PASS.

- [ ] **Step 2: Probe the Dataset descriptor**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
go run ./cmd/ccuv-router-dataset ccuv <<'JSON'
{"protocol":"ccuv.custom/v2","request_id":"quota-probe","request_kind":"probe"}
JSON
```

Expected: JSON descriptor contains `quota_remaining_ratio`, its `provider_quota` group, 20-second ranking-only Monitor capability, and no raw pack value.

- [ ] **Step 3: Query a quota Monitor observation against running Router**

Run:

```bash
cd /Users/bytedance/projects/go/ccuv-router-dataset
CCUV_ROUTER_URL=http://127.0.0.1:4300 go run ./cmd/ccuv-router-dataset ccuv <<'JSON'
{"protocol":"ccuv.custom/v2","request_id":"quota-monitor","request_kind":"monitor","dataset_id":"router","metric_id":"quota_remaining_ratio","timezone":"Asia/Shanghai","range":{"end_at":"2026-10-13T12:00:00+08:00"},"query":{"filters":{},"group_by":"quota_pool"}}
JSON
```

Expected: every returned group has a numeric percentage; unlimited labels end with one `♾️`; model descriptions are one-line comma-separated values when known; output contains no raw entitlement pack identifier.

- [ ] **Step 4: Confirm no unintended working-tree changes**

Run:

```bash
cd /Users/bytedance/Projects/my_ai/tools/custom/proxy && git status --short
cd /Users/bytedance/projects/go/ccuv-router-dataset && git status --short
cd /Users/bytedance/projects/py/ccusage-viz && git status --short
```

Expected: only pre-existing user changes remain; report any new uncommitted implementation files before handoff.
