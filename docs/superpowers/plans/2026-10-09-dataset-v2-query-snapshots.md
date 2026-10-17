# Dataset V2 Query Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every successful V2 historical chart and Monitor response an atomic descriptor, runtime-control, and fact snapshot.

**Architecture:** Remove V2 static filter catalogs from Probe descriptors and chart capabilities. Parse one complete `V2ProbeDescriptor` plus a `V2Runtime` filter catalog from each successful chart/Monitor response, then make accepted historical and Monitor component state the only source for post-query controls. Update the WeRead and Router command Datasets to produce those snapshots.

**Tech Stack:** Python 3.11, pytest, ruff, Go, Go test.

**Spec:** `docs/superpowers/specs/2026-10-09-dataset-v2-query-snapshots-design.md`

## Global Constraints

- Keep the protocol identifier `ccuv.custom/v2`; it is unpublished and needs no compatibility mode.
- Leave V1 protocol behavior unchanged.
- Require `descriptor` and `runtime.filters` on every successful V2 chart and Monitor response.
- Do not introduce `stat` in this change.
- Preserve unrelated local changes in all three repositories.

---

### Task 1: Define The Python Snapshot Protocol

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/custom_protocol.py`
- Test: `tests/test_custom_protocol.py`

**Interfaces:**
- Produces immutable `V2Runtime(filters: tuple[CustomFilter, ...])`.
- Changes `V2ChartResponse` to `(metric_id, descriptor, runtime, data)`.
- Changes `V2MonitorResponse` to `(metric_id, descriptor, runtime, observation)`.

- [ ] Write parser tests for a chart response containing `descriptor`, empty `runtime.filters`, and valid data.
- [ ] Write parser tests for a Monitor response containing a descriptor, dynamic filter options, and an observation.
- [ ] Write parser tests rejecting omitted `runtime`, omitted `runtime.filters`, duplicate runtime filter IDs/options, an absent selected Metric, and a selected Metric without the requested chart kind.
- [ ] Remove V2 `filters` from `V2MetricCapabilities`, `V2HistoricalChartCapability`, and `V2MonitorCapability`; update V2 descriptor serialization to omit those fields.
- [ ] Parse `descriptor` with `parse_v2_probe_descriptor`, parse `runtime.filters` with the existing localized filter parser, and validate the requested Metric/chart before constructing responses.
- [ ] Run `./.venv/bin/pytest tests/test_custom_protocol.py` and `./.venv/bin/ruff check src tests`.

### Task 2: Make ccuv Components Response-Owned

**Files:**
- Modify: `src/ccusage_viz/custom_component.py`
- Modify: `src/ccusage_viz/custom_monitor_component.py`
- Modify: `src/ccusage_viz/configuration.py`
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/custom_monitor.py`
- Test: `tests/test_tui_custom.py`
- Test: `tests/test_custom_monitor_component.py`
- Test: `tests/test_custom_monitor.py`

**Interfaces:**
- `CustomHistoricalComponent.accept_response()` retains response descriptor/runtime and derives its current capability from the selected descriptor Metric.
- `CustomMonitorComponent.accept()` replaces presentation/capability metadata using the accepted response descriptor and exposes accepted runtime filters.
- `f` reads only accepted `V2Runtime.filters`; a Probe cannot show the editor.

- [ ] Add component tests that an accepted V2 chart response replaces Probe-equivalent capability metadata and exposes dynamic filter options.
- [ ] Add Monitor acceptance tests that response descriptor metadata replaces startup metadata, and that dynamic filters are retained only after a successful observation.
- [ ] Refactor historical component projection setup to use response descriptor Metric unit/title/capabilities rather than the removed chart-response partial capability shape.
- [ ] Refactor Monitor component acceptance to resolve the request Metric from `response.descriptor`, normalize style against that Metric aggregation, and retain `response.runtime`.
- [ ] Change Dashboard and standalone `f` routes to pass accepted runtime filters directly into the existing custom filter editor; remove Probe/static capability filter branches.
- [ ] Retain Probe only for initial Metric/chart selection and loading state; apply defaults after Probe as today, then replace static metadata on first response.
- [ ] Run the focused Python component and TUI tests.

### Task 3: Update WeRead Dataset Snapshots

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/protocol/v2/protocol.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/dataset/dataset.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/readingtime/metric.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/metrics/totalnotes/metric.go`
- Test: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/protocol/v2/protocol_test.go`
- Test: `/Users/bytedance/Projects/go/ccuv-dataset-weread/internal/dataset/dataset_test.go`

**Interfaces:**
- Probe descriptor has no filter catalog or chart filter fields.
- Every chart success payload includes `descriptor`, `runtime: {"filters": []}`, and `data`.

- [ ] Update Go descriptor structs so V2 metric and chart capabilities omit static filter fields.
- [ ] Make dataset chart handlers attach the same complete descriptor used by Probe to each success response.
- [ ] Add `runtime` with an explicit empty dynamic filter list to each current WeRead chart response.
- [ ] Update Go fixture expectations and protocol tests to assert the new response shape and absence of Probe filter fields.
- [ ] Run `go test ./...` in the WeRead repository.

### Task 4: Update Router Dataset Monitor Snapshots

**Files:**
- Modify: `/Users/bytedance/Projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-router-dataset/cmd/ccuv-router-dataset/main_test.go`
- Modify: `/Users/bytedance/Projects/go/ccuv-router-dataset/README.md`

**Interfaces:**
- Router Monitor success response includes the complete `descriptor`, `runtime: {"filters": []}`, and `observation`.

- [ ] Remove `filters` from Router Probe descriptor Metric and Monitor chart capability maps.
- [ ] Attach `descriptor()` and a required explicit empty runtime filter catalog to every successful Monitor response.
- [ ] Expand handler tests to verify Probe and Monitor snapshot response shapes, including descriptor and runtime fields.
- [ ] Update the Router README response contract description.
- [ ] Run `go test ./...` in the Router Dataset repository.

### Task 5: Document And Verify The Protocol Upgrade

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`
- Modify: `docs/dataset-user-guide.md`
- Modify: `docs/dataset-user-guide.zh-CN.md`
- Test: `tests/test_custom_protocol.py`

**Interfaces:**
- Documents describe response-owned complete descriptor and `runtime.filters` without a compatibility fallback.

- [ ] Replace static-filter Probe examples with response `runtime.filters` examples in both languages.
- [ ] Document the accepted snapshot lifecycle, the required `descriptor` and `runtime` fields, and `f` availability after a successful response.
- [ ] Run `env -u NO_COLOR TERM=xterm-256color .venv/bin/pytest`, `.venv/bin/ruff check src tests`, and `git diff --check` in ccuv.
- [ ] Run `go test ./...` in both Dataset repositories.
- [ ] Commit ccuv and separately commit each Dataset repository with protocol-specific messages.
