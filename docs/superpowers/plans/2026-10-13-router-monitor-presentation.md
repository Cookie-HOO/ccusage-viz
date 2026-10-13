# Router Monitor Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit useful localized Monitor descriptions and display text for the three final Router metrics, with P95 defaulting to a real-model ranking.

**Architecture:** Keep Router telemetry numeric values unchanged and add presentation metadata only in `ccuv-router-dataset` Monitor responses. Descriptor defaults control P95's initial view; small formatting helpers isolate QPM, latency, and quota presentation rules.

**Tech Stack:** Go, `ccuv.custom/v2`, Go `testing`.

**Spec:** `/Users/bytedance/projects/py/ccusage-viz/docs/superpowers/specs/2026-10-13-router-monitor-presentation-design.md`

## Global Constraints

- Do not modify ccusage-viz or Router APIs.
- Preserve numeric values as the authority for calculations and sorting.
- Keep exactly three metrics in two groups.
- P95 source values remain milliseconds; only Monitor `display` uses seconds.
- Runtime window remains 60 seconds with a 10-second refresh; quota remains 20 seconds.

---

### Task 1: Add presentation regression tests

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main_test.go`

**Interfaces:**
- Consumes: `descriptor()`, runtime group presentation helper, and `quotaObservation()`.
- Produces: assertions for P95 defaults and localized Monitor metadata.

- [ ] Write tests asserting `latency_p95_ms.defaults.monitor` equals `{"style":"ranking","group_by":"real_model"}`.
- [ ] Add table tests for QPM display/description and P95 millisecond-to-second display, including `850 -> 0.85 s`, `1000 -> 1.00 s`, and malformed input omitting display.
- [ ] Extend quota observation tests to assert finite localized remaining display and unlimited `♾️` display.
- [ ] Run `go test ./cmd/ccuv-router-dataset -count=1` and confirm the new assertions fail before implementation.

### Task 2: Implement source-owned Monitor presentation

**Files:**
- Modify: `/Users/bytedance/projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main.go`

**Interfaces:**
- Produces: `runtimeGroup(metricID string, group router.Group) map[string]any` and localized quota row display metadata.

- [ ] Add P95 Monitor defaults for ranking and `real_model` grouping.
- [ ] Add a decimal formatter that converts milliseconds to seconds with two-to-three decimal places and trailing-zero trimming above two decimals.
- [ ] Add localized `description` and `display` to runtime Monitor groups; omit display when parsing fails.
- [ ] Add finite and unlimited localized `display` to quota Monitor groups while retaining current descriptions.
- [ ] Run `gofmt` and `go test ./... -count=1`; confirm all tests pass.

### Task 3: Build and refresh local registration

**Files:**
- Rebuild: `/Users/bytedance/projects/go/ccuv-router-dataset/ccuv-router-dataset`

**Interfaces:**
- Produces: updated local Router Dataset executable and cached Probe descriptor.

- [ ] Build with `go build -o ./ccuv-router-dataset ./cmd/ccuv-router-dataset`.
- [ ] Refresh with `ccuv-local dataset add-local /Users/bytedance/projects/go/ccuv-router-dataset/ccuv-router-dataset ccuv`.
- [ ] Probe the descriptor and verify P95 defaults to ranking by `real_model`.
- [ ] Query live QPM, P95, and quota Monitor responses and verify their localized metadata and unchanged numeric values.
