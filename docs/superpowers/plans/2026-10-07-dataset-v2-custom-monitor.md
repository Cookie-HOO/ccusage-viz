# Dataset V2 Custom Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add V2 multi-Metric Datasets and source-owned Monitor observations, then integrate Router v3 live TPM, QPM, and average-token metrics through a Go command Dataset.

**Architecture:** Retain V1 unchanged. V2 adds Metric-owned aggregation and chart capabilities beneath a Dataset. Built-in Monitor continues creating observations from counters, while Custom Monitor consumes source-owned fixed-business-window observations. Router v3 retains bounded event metadata in memory; the Go Dataset owns Router-to-ccuv protocol adaptation.

**Tech Stack:** Python 3.12, pytest, Starlette/httpx, Go standard library.

**Spec:** `docs/superpowers/specs/2026-10-07-dataset-v2-custom-monitor-design.md`

## Global Constraints

- V1 custom Datasets remain compatible.
- V2 aggregation is only `sum` or `value`; ccuv never derives a new value fact.
- Custom Monitor keeps ccuv display history but cannot change Metric business `window_seconds`.
- Custom Monitor supports bars/ranking/list only; no cumulative-bars in V2.
- Declared Metric refresh interval warns on mismatch with Dashboard global sampling; no Pane-local timing UI.
- Router exposes only config-defined `/agent/<id>/...` generation paths and no persisted telemetry.
- Never alter global Codex or Claude Code configuration.

---

### Task 1: Commit Existing Baselines

**Files:** Existing tracked ccuv changes; Router v3 files under `~/Projects/my_ai/tools/custom/proxy`; V2 spec.

**Produces:** Clean, independently testable ccuv baseline commits and a Router v3 baseline commit before new work.

- [ ] Inspect all changed ccuv files with `git diff --name-only` and run `pytest -q tests/test_dataset_manager.py tests/test_tui_dashboard.py tests/test_query_planner.py tests/test_historical_component.py`.
- [ ] Classify the existing ccuv work by behavior, stage source/tests/docs for each coherent feature, and commit each. Do not stage `.dsh-bin/`, `.pnpm*/`, `node_modules/`, `tmp.txt`, or generated lockfiles.
- [ ] In Router `router_v3/config.py`, validate adapter base URL port reservations before executable lookup. Preserve a test where `:8317` reports a reserved-port error even without Node on PATH.
- [ ] Run Router baseline: `PATH=/Users/bytedance/.nvm/versions/node/v18.20.8/bin:$PATH .venv/bin/python -m unittest tests.test_router_v3_config tests.test_router_v3_supervisor tests.test_router_v3_codex tests.test_router_v3 -v`.
- [ ] Commit Router v3 source/config/docs/tests/.env example, excluding `.superpowers/`, logs, caches and screenshots, with `feat: add isolated router v3`.

### Task 2: Parse V2 Multi-Metric Dataset Descriptors

**Files:** `src/ccusage_viz/custom_models.py`, `src/ccusage_viz/custom_protocol.py`, `src/ccusage_viz/datasets/models.py`, `tests/test_custom_protocol.py`, `tests/test_datasets_models.py`.

**Produces:** V2 Probe descriptor with `metrics[]`, Metric-owned capabilities, and protocol-version dispatch.

- [ ] Add failing parser cases for two Metrics: `tokens` with `aggregation: sum`, Monitor window 60/refresh 10; and `average_tokens_per_request` with `aggregation: value`, Monitor window 60. Reject duplicate IDs, invalid aggregation, missing aggregation, and non-positive windows.
- [ ] Confirm red tests: `pytest -q tests/test_custom_protocol.py tests/test_datasets_models.py`.
- [ ] Add parallel V2 immutable models; do not weaken V1 invariants. Use `Aggregation = Literal["sum", "value"]` and Monitor capability fields `window_seconds`, optional `refresh_interval_seconds`, `group_by`.
- [ ] Parse Metric-owned chart/default/filter/group metadata and route V1/V2 by protocol version.
- [ ] Rerun parser tests; commit `feat: add dataset v2 metric descriptors`.

### Task 3: Implement Dataset -> Metric -> Chart Selection

**Files:** `src/ccusage_viz/options.py`, `src/ccusage_viz/cli.py`, `src/ccusage_viz/configuration.py`, `src/ccusage_viz/tui.py`, `tests/test_cli.py`, `tests/test_options.py`, `tests/test_tui_custom.py`.

**Produces:** Metric-aware custom config, `--metric`, and chooser flow.

- [ ] Add failing tests for `ccuv chart monitor --dataset router --metric tokens`; require Metric for multi-Metric V2 datasets, auto-select sole Metric, and reject unsupported Metric/chart pairs before query submission.
- [ ] Add `metric_id` to custom chart serialization, Dashboard state and CLI. Preserve V1's single implicit Metric behavior.
- [ ] Update chooser: Dataset, then Metric, then only the selected Metric's supported charts.
- [ ] Run `pytest -q tests/test_cli.py tests/test_options.py tests/test_tui_custom.py tests/test_tui_dashboard.py`; commit `feat: select dataset metrics before charts`.

### Task 4: Generalize Monitor To Direct Observations

**Files:** `src/ccusage_viz/processing/monitor.py`, `src/ccusage_viz/monitor_component.py`, new `src/ccusage_viz/custom_monitor_component.py`, `src/ccusage_viz/chart_models.py`, Monitor test files.

**Produces:** Shared Monitor projection accepting built-in counter deltas and direct custom observations.

- [ ] Add failing tests with direct source observations from a fixed 60-second Metric business window. Changing ccuv display history prunes visible observations but does not change supplied values. `value` never creates totals/Other by summing observations or groups.
- [ ] Define immutable observation: endpoint timestamp, source total/groups, aggregation, unit/presentation metadata, coverage state. Convert existing built-in deltas to the same shape without behavior change.
- [ ] Keep custom observations out of distribution/cumulative projection; support bars/ranking/list through common code.
- [ ] Run `pytest -q tests/test_monitor.py tests/test_monitor_component.py tests/test_monitor_distribution.py tests/test_render.py`; commit `refactor: support source-owned monitor observations`.

### Task 5: Run V2 Custom Monitor And Value Queries

**Files:** `src/ccusage_viz/acquisition.py`, `src/ccusage_viz/providers/custom_command.py`, `src/ccusage_viz/custom_component.py`, `src/ccusage_viz/tui.py`, `src/ccusage_viz/render/custom.py`, related custom tests.

**Produces:** Runtime Probe, Monitor request with `metric_id` and `end_at`, range error state, interval warning, and source-owned `value` projection.

- [ ] Add failing lifecycle tests: runtime Probe per custom Monitor Pane; global Dashboard sampling when no Metric interval; warning if declared interval differs; `range_not_available` gives localized error and no zero; no cumulative-bars for a `value` Metric.
- [ ] Add V2 Monitor wire parser/request. At Pane startup runtime-Probe even when descriptor cache exists; display Metric business window independently from ccuv display history.
- [ ] For V2 `value` historical data, fetch a fresh Dataset result for every changed range/granularity/group/filter/chart. Do not reuse V1 rollup, range total, Top N, Other, comparison or summary sum pipelines.
- [ ] Run `pytest -q tests/test_custom_provider.py tests/test_custom_component.py tests/test_tui_custom.py tests/test_tui_dashboard.py tests/test_monitor.py tests/test_monitor_component.py`; commit `feat: run custom monitor metrics`.

### Task 6: Migrate WeRead And Update Documentation

**Files:** Dataset models/service/manager, custom protocol docs in both languages, README/usage in both languages, locale files, Dataset/i18n tests.

**Produces:** V2 single-Metric WeRead without Monitor and complete user help.

- [ ] Add failing tests: V2 WeRead reading-duration Metric is `sum`, preserves timeline/stack/calendar/ranking and never offers Monitor. Add English/Chinese copy fixtures for selection order, aggregation meaning, fixed Monitor business window, interval mismatch and range-unavailable states.
- [ ] Map WeRead's existing descriptor into one V2 Metric. Preserve current title, unit, filters, groupings, defaults and historical response behavior.
- [ ] Update protocol guide, README, usage and locales. State V1 stays compatible; V2 has multi-Metric Dataset sources.
- [ ] Run `pytest -q tests/test_datasets_service.py tests/test_dataset_manager.py tests/test_i18n.py tests/test_tui_custom.py`; commit `feat: migrate datasets to v2 metrics`.

### Task 7: Nice To Have - WeRead Note Count Metric

**Files:** WeRead source/descriptor and focused tests discovered in Task 6; docs only if implemented.

**Produces:** Optional `note_count` `sum` Metric in the existing WeRead Dataset.

- [ ] Inspect the real WeRead data adapter/API. Continue only if it provides a stable note count attributable to requested date ranges; never infer it from display-only metadata.
- [ ] If unsupported, skip coding and record in final status: source lacks a reliable range-attributed note count. Reading-duration behavior remains unchanged.
- [ ] If supported, add failing tests and a second V2 Metric: `id: note_count`, `aggregation: sum`, unit `note`, zero decimal places. Declare only chart kinds, granularities and groupings that the source truthfully supports.
- [ ] Run focused WeRead tests and commit `feat: add weread note count metric` only when verification passes.

### Task 8: Add Configuration-Driven Router Agent Paths

**Files:** `config/router_v3_config.yaml`, `router_v3/config.py`, `router_v3/app.py`, Router docs/tests.

**Produces:** Validated `agents: [cc, codex, dsh]` and dynamic public routes.

- [ ] Add failing tests: invalid/duplicate Agent rejected; `/agent/codex/v1/responses` reaches routing core with agent context; anonymous `/v1/responses` is 404; every configured Agent exposes all three protocols, models and health.
- [ ] Parse Agent IDs into `RouterConfig`; dynamically build Agent route paths using existing protocol mapping. Pass identity to handlers explicitly, never infer from protocol/port.
- [ ] Retain only unqualified `GET /health` for Router-wide health.
- [ ] Run `PATH=/Users/bytedance/.nvm/versions/node/v18.20.8/bin:$PATH .venv/bin/python -m unittest tests.test_router_v3_config tests.test_router_v3 -v`; commit `feat: add agent-qualified router routes`.

### Task 9: Add Bounded Router Telemetry Endpoint

**Files:** new `router_v3/telemetry.py`, `router_v3/app.py`, new `tests/test_router_v3_telemetry.py`.

**Produces:** Loopback aggregate endpoint for `tokens` sum, `completed_requests` sum, `average_tokens_per_request` value, grouped by public model/real model/Agent.

- [ ] Add controlled-clock tests for 60-second event pruning, per-group totals, source-owned average, and missing final usage omitted rather than zero-filled.
- [ ] Implement immutable completed events in a bounded deque: completion time, Agent, public request model, winning native model, input/output/total tokens. Do not retain prompt/response content or credentials.
- [ ] Record only final successful requests with usable usage. Add aggregate endpoint validating Metric, grouping and endpoint time, returning fixed-window facts.
- [ ] Run `PATH=/Users/bytedance/.nvm/versions/node/v18.20.8/bin:$PATH .venv/bin/python -m unittest tests.test_router_v3_telemetry tests.test_router_v3 tests.test_router_v3_config -v`; commit `feat: expose router live usage telemetry`.

### Task 10: Implement Go Router Dataset

**Files:** new `~/Projects/go/ccuv-router-dataset` module: `go.mod`, command main, protocol module, Router client and tests, README.

**Produces:** Strict stdin/stdout V2 Dataset command.

- [ ] Use `httptest.Server` to write Probe/Monitor fixture tests. Probe declares tokens sum, requests sum, average value; all use fixed window 60, refresh 10, and public_model/real_model/agent groupings. Router unavailable-range maps to localized V2 `range_not_available`.
- [ ] Implement one JSON request -> one JSON response; protocol output only on stdout and diagnostics on stderr. Support runtime Probe and Monitor; preserve Router aggregates rather than recomputing event data.
- [ ] Run `gofmt -w cmd internal && go test ./...` in the new module, then commit `feat: add router ccuv dataset`.

### Task 11: Verify Without Global Client Changes

**Files:** temporary/project-local configuration only; release notes with reproducible non-sensitive commands.

**Produces:** Live Dashboard verification and WeRead regression result.

- [ ] Start Router v3 and check `/health`, `/agent/codex/v1/models`, `/agent/cc/v1/models`.
- [ ] Register the Go command into a temporary ccuv Dataset state root only: `CCUV_DATASET_HOME=$(mktemp -d) ccuv dataset add local router --command "$HOME/Projects/go/ccuv-router-dataset/ccuv-router-dataset"`.
- [ ] Use temporary/project-local Codex and Claude settings pointed to `/agent/codex` and `/agent/cc`, with `gpt-5.6-terra`. Do not change global settings.
- [ ] Open three panes: tokens by real model, completed requests by public model, average tokens/request by Agent. Confirm traffic changes values, mismatch notice appears only when applicable, average Metric has no cumulative-bars, unavailable range is an error rather than zero.
- [ ] Run WeRead Timeline/Stack/Calendar/Ranking and confirm Monitor is absent. Finish with `pytest -q`.
