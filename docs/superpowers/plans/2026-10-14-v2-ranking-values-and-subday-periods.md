# V2 Ranking Values and Subday Periods Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace V2 Ranking dated points with scalar values, remove its granularity semantics, enable Dataset-declared seconds/minutes/hours, and minimally migrate all three registered plugins.

**Architecture:** Introduce distinct scalar Ranking facts and projections alongside unchanged dated historical series. Represent Custom Ranking timestamp ranges explicitly, route them through existing timestamp acquisition machinery without date truncation, and retain the existing flat/partition wire containers and presentation behavior. Update plugin wire adapters only, preserving their current business computations.

**Tech Stack:** Python, uv, pytest, existing project lint tooling; Go and go test for plugins; existing JSON protocol and local Dataset registrations.

**Spec:** `docs/superpowers/specs/2026-10-14-v2-ranking-values-and-subday-periods-design.md`

## Global Constraints

- Protocol remains `ccuv.custom/v2`; V2 Ranking is intentionally breaking. Do not accept old Ranking points as the scalar value source.
- V1, Monitor, and dated Timeline/Stack/Calendar retain their contracts.
- Ranking items have scalar Decimal values and no date/timestamp/hidden time buckets.
- Ranking legacy granularity/granularities fields are ignored without parsing or validation; new requests omit them.
- Only V2 Custom Ranking supports arbitrary positive integer `s/m/h` periods; no opaque IDs or host-defined subday presets.
- Existing `d/w/mo/q/y/all` meanings and existing all ordering restrictions remain unchanged.
- Timestamp ranges are aware, nonempty, half-open, and calculated by elapsed duration in UTC.
- Preserve all partition controls, validation, Top/Other, comparison, search, scrolling, copying, and metadata behavior.
- Plugins receive protocol-only migration: no new metrics, periods, source calls, aggregation algorithms, filter or grouping behavior.
- No remote push/release/catalog publication. Rebuild only registered local executables; refresh snapshots via DatasetService.
- Preserve uncommitted and concurrent changes in all four repositories. Stage precise paths/hunks, never use git add . or reset.
- Each task has a red/green cycle and an independently reviewed diff. Do not change fixtures to hide value changes.

## File Map and Dependencies

Core additions:

- `src/ccusage_viz/core/custom_ranking_time.py`: TimestampRange and scoped Custom Ranking period/range operations.
- `src/ccusage_viz/processing/custom_ranking.py`: scalar Ranking projections, independent Top/Other and comparisons.
- `tests/test_custom_ranking_time.py`: deterministic range/period/DST tests.
- `tests/test_custom_ranking_projection.py`: scalar flat/partition tests.

Core modifications:

- `custom_models.py`, `custom_protocol.py`: distinct V2 Ranking facts, range serialization, ignored gran, explicit chart kind.
- `processing/custom_historical.py`, `custom_component.py`, `render/custom.py`: dispatch scalar Ranking without dated-axis dependency.
- `options.py`, `configuration.py`, `chart_configuration.py`, `dashboard_presets.py`, `custom_metric_switching.py`: kind-scoped period resolution, gran removal, persistence.
- `acquisition.py`, `providers/custom_command.py`, `query/models.py`, `query/runtime.py`, `tui.py`, `watch.py`: precision-safe requests, deduplication, refresh, copied commands and status.
- `locales/en.py`, `locales/zh.py`: only required Ranking period/range copy.
- `processing/projection.py`, `chart_models.py`, `historical_component.py`: audit native Ranking, modify only where a real violation is found.

Plugin roots:

- WeRead: `/Users/bytedance/Projects/go/ccuv-dataset-weread`
- Router: `/Users/bytedance/Projects/go/ccuv-router-dataset`
- GitHub: `/Users/bytedance/Projects/github-projects`

Execution order: Tasks 1–5 core; Tasks 6–8 plugin migrations can run independently after Task 1 contract is fixed; Task 9 integration after all previous tasks.

### Task 1: Distinct V2 Ranking facts and explicit wire discrimination

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`, `src/ccusage_viz/custom_protocol.py`
- Test: `tests/test_custom_protocol.py`

**Interfaces:**
- Produces `CustomRankingEntry(id: str, label: LocalizedText, value: Decimal, description: LocalizedText | None = None, display: LocalizedText | None = None, comparison_display: LocalizedText | None = None, link: str | None = None)`.
- Produces `V2RankingGroup` with existing group metadata and `series: tuple[CustomRankingEntry, ...]`.
- Produces `V2RankingData(series: tuple[CustomRankingEntry, ...] = (), groups: tuple[V2RankingGroup, ...] | None = None)`; groups/series mutually exclusive.
- `V2ChartResponse.data` accepts `CustomData | V2RankingData`; legacy `CustomSeries` and `CustomRankingGroup` retain V1 behavior.
- V2 response adaptation must retain scalar data without converting to dated CustomData. Existing capabilities/presentation adaptation may remain.

- [ ] **Step 1: Add failing parsing tests using current V2 descriptor/response fixtures.** Introduce a `ranking_response` fixture helper in this test file that starts from its existing V2 success fixture, explicitly selects Ranking, and replaces only the data section. Add assertions equivalent to:

```python
assert parsed.data.series[0].value == Decimal("185.2")
assert not hasattr(parsed.data.series[0], "points")
assert not hasattr(parsed.data.series[0], "date")
assert parsed.data.groups[0].series[0].value == Decimal("185.2")
```

Test points-only and value+points rejection, invalid decimal values, duplicate group IDs, group-local duplicate item IDs, repeated item IDs across distinct groups, max_items across all partitions, wrong groups/series shape, preserved descriptions/display/links. Delete Ranking granularities from fixtures; also set it to an object and defaults granularity to an integer to prove neither is parsed.

- [ ] **Step 2: Run red tests.** `uv run pytest tests/test_custom_protocol.py -q`; confirm failures are new scalar contract/gran cases rather than unrelated fixtures.
- [ ] **Step 3: Implement immutable scalar models and V2-only parsers.** Add `_parse_v2_ranking_entry`, `_parse_v2_ranking_group`, `_parse_v2_ranking_data`; reuse decimal, localized text, HTTPS, unique-ID validation. Route by explicit V2 request chart kind. `_parse_series` and old parsers remain dated for V1/non-Ranking. Serialize `chart_kind` on V2 chart requests independently of partition_declared. Do not make scalar response inference depend on presence of description or group_by.
- [ ] **Step 4: Ignore Ranking granularities/default granularity; omit Ranking query granularity.** Keep internal transitional default only until Task 3 removes its effects. Preserve non-Ranking and V1 validation. Ensure descriptor-to-wire omits Ranking gran fields and new cached Probe round-trips scalar capability changes.
- [ ] **Step 5: Run green protocol and Monitor tests.** `uv run pytest tests/test_custom_protocol.py tests/test_custom_monitor.py tests/test_custom_monitor_component.py -q`. Temporarily broken old V2 Ranking points fixtures outside this task are tracked for Tasks 2/9, not accepted via fallback.
- [ ] **Step 6: Review and commit precise files.** `git diff --check`; `git add src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py tests/test_custom_protocol.py`; `git commit -m "feat: define scalar v2 ranking wire contract"`.

### Task 2: Scalar Ranking projection with partition preservation

**Files:**
- Create: `src/ccusage_viz/processing/custom_ranking.py`, `tests/test_custom_ranking_projection.py`
- Modify: `src/ccusage_viz/processing/custom_historical.py`, `src/ccusage_viz/custom_component.py`, `src/ccusage_viz/render/custom.py`
- Test: `tests/test_custom_component.py`, `tests/test_custom_ranking_scroll.py`, `tests/test_custom_ranking_dashboard_scroll.py`, `tests/test_tui_custom.py`

**Interfaces:**
- Consumes Task 1 scalar entry/data/group types.
- Produces `CustomRankingProjection`, `CustomProjectedRankingEntry`, `CustomProjectedScalarRankingGroup`; entries expose scalar `value`, existing metadata and comparison facts, with a read-only `total` alias where shared rendering needs it. No `days`, bucket `values`, or granularity.
- Produces `process_custom_ranking(response, config, *, comparison_response=None, comparison_config=None) -> CustomRankingProjection`.
- Components expose `CustomChartProjection | CustomRankingProjection` and dispatch by chart kind/protocol data, preserving V1 dated processing.

- [ ] **Step 1: Add scalar flat and partition red tests.** Use entries with A=100, B=200, C=50; descending Top 1 must expose B and Other=150 when enabled. Add two groups with identical inner IDs but different values; totals, maxima, Top and comparisons must be independent. Equivalent assertions:

```python
assert projection.series[0].id == "b"
assert projection.series[0].value == Decimal("200")
assert projection.series[1].is_other
assert projection.series[1].value == Decimal("150")
assert not hasattr(projection, "days")
assert not hasattr(projection.series[0], "values")
```

Test ascending order, stable tie behavior, signed values, missing previous item/group, preservation of group order and max_items behavior. Keep current Other policy even for aggregation=value.
- [ ] **Step 2: Run red.** `uv run pytest tests/test_custom_ranking_projection.py -q`.
- [ ] **Step 3: Implement scalar projection.** Sort entry.value with existing direction/tie rules; calculate old cross-entry totals/percentages without time-axis operations. Extract metadata helpers only if useful; do not rewrite dated Timeline/Stack code. For groups, preserve Dataset order and scope previous entries by group ID. Reuse existing Top/Other policy but sum scalar discarded values, never fabricate buckets.
- [ ] **Step 4: Dispatch in component/rendering and migrate Ranking-only fixtures.** Preserve titles, comparison columns, search unfiltered rank/scale/share, sticky headings, copying all/grouped Other, animation behavior, and logs. Shared rendering may consume scalar total and metadata; timeline rendering remains typed to dated projections. Remove Ranking references to `_period_axis`, `_bucket_values`, and `_validate_dates` from the V2 path.
- [ ] **Step 5: Run green including existing partition regression.** `uv run pytest tests/test_custom_ranking_projection.py tests/test_custom_component.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_tui_custom.py -q`. Review every fixture value against the old sum of points.
- [ ] **Step 6: Commit scoped changes.** `git diff --check`; stage created/modified files and only relevant tests; `git commit -m "refactor: project v2 rankings without temporal buckets"`.

### Task 3: Remove Ranking granularity effects and audit built-in Ranking

**Files:**
- Modify: `src/ccusage_viz/custom_component.py`, `src/ccusage_viz/configuration.py`, `src/ccusage_viz/custom_metric_switching.py`, `src/ccusage_viz/options.py`, `src/ccusage_viz/chart_configuration.py`, `src/ccusage_viz/dashboard_presets.py`, `src/ccusage_viz/custom_protocol.py`, `src/ccusage_viz/tui.py`
- Audit: `src/ccusage_viz/chart_models.py`, `src/ccusage_viz/processing/projection.py`, `src/ccusage_viz/historical_component.py`
- Test: `tests/test_custom_component.py`, `tests/test_custom_metric_switching.py`, `tests/test_options.py`, `tests/test_dashboard_presets.py`, `tests/test_tui_custom.py`

**Interfaces:**
- Ranking data-query identity contains range/group/partition/filter/source/Metric, not granularity.
- Shared CustomChartConfig may retain its non-Ranking granularity slot, but V2 Ranking treats it as absent semantically. No dedicated Ranking model/projection gets a granularity field.
- Older persisted Ranking granularity values are ignored on load; new Ranking serialization omits them. Other charts preserve required field validation.

- [ ] **Step 1: Red tests for ignored internal and persisted gran.** For equivalent V2 Ranking configs differing only in legacy gran value:

```python
assert not custom_replacement_required(current, replace(current, granularity="legacy"))
assert not custom_summary_replacement_required(current, replace(current, granularity="legacy"))
assert canonical_custom_request_key(request_a) == canonical_custom_request_key(request_b)
```

Test omission of gran in emitted queries/presets/copied Ranking commands; old preset gran set to an object does not block load. Non-Ranking still rejects invalid persisted gran. Metric switch unsupported query.granularity cannot normalize/retry a Ranking query based on ignored state. Verify `g/G` still cycles partition rather than granularity.
- [ ] **Step 2: Run red.** `uv run pytest tests/test_custom_component.py tests/test_custom_metric_switching.py tests/test_options.py tests/test_dashboard_presets.py -q`.
- [ ] **Step 3: Implement kind-scoped defaults/identity/serialization.** Narrow changes to V2 Ranking; use a single predicate for this scope rather than duplicated guesses. Remove relevant normalization and status category exposure. Preserve partition as query-affecting and its persisted fields. Existing dated V1 Ranking behavior stays intact.
- [ ] **Step 4: Audit native Ranking.** Assert native RankingConfig has no granularity and RankingEntry has no date/timestamp. Confirm build_ranking consumes time-bearing source records only to calculate range totals and comparisons. No rewrite is needed when invariants already hold; retain native range/summary fields.
- [ ] **Step 5: Run green.** `uv run pytest tests/test_custom_component.py tests/test_custom_metric_switching.py tests/test_options.py tests/test_dashboard_presets.py tests/test_tui_custom.py tests/test_processing.py -q`; if `test_processing.py` layout differs at execution, use the actual existing tests of build_ranking located by `rg -l 'build_ranking' tests`.
- [ ] **Step 6: Commit scoped gran removal.** Review diff for accidental g/G partition removal; commit with `refactor: remove v2 ranking granularity semantics`.

### Task 4: Scoped Custom Ranking timestamp range and period operations

**Files:**
- Create: `src/ccusage_viz/core/custom_ranking_time.py`, `tests/test_custom_ranking_time.py`
- Modify: `src/ccusage_viz/options.py`, `src/ccusage_viz/configuration.py`, `src/ccusage_viz/chart_configuration.py`, `src/ccusage_viz/custom_protocol.py`, `src/ccusage_viz/dashboard_presets.py`
- Test: `tests/test_core_time.py`, `tests/test_options.py`, `tests/test_dashboard_presets.py`, `tests/test_custom_protocol.py`

**Interfaces:**
- Produces frozen `TimestampRange(start_at: datetime, end_at: datetime, relative_until: bool = False, period: str | None = None, fixed_bounds: bool = False)`; positive duration validated using UTC instants.
- Produces `parse_subday_period(value: str) -> timedelta`, accepting positive integer s/m/h only.
- Produces `resolve_custom_ranking_range(period: str, *, now: datetime, timezone: str) -> DateRange | TimestampRange`, delegating old units to existing date resolution.
- Produces `refresh_custom_ranking_range(value: DateRange | TimestampRange, *, now: datetime, timezone: str) -> DateRange | TimestampRange` and `previous_custom_ranking_range(value: TimestampRange) -> TimestampRange`.
- CustomChartConfig.date_range becomes `DateRange | TimestampRange`; TimestampRange is valid only for V2 Ranking. Retain field name for minimal configuration churn, but consumers must narrow the union.
- V2ChartRequest adds optional aware start_at/end_at and mutually exclusive optional start_date/end_date; request post-init enforces exactly one complete valid shape and timestamp Ranking scope.

- [ ] **Step 1: Write deterministic duration and DST red tests.**

```python
@pytest.mark.parametrize("period,seconds", [("15s",15),("90s",90),("10m",600),("45m",2700),("1h",3600),("6h",21600)])
def test_subday_period_duration(period, seconds):
    assert parse_subday_period(period) == timedelta(seconds=seconds)

def test_hour_uses_elapsed_time_at_dst_transition():
    now = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1)
    interval = resolve_custom_ranking_range("1h", now=now, timezone="America/New_York")
    assert interval.end_at.astimezone(UTC) - interval.start_at.astimezone(UTC) == timedelta(hours=1)
```

Reject 0s/-1m/fractional hours, naive/incomplete/mixed bounds. Test crossing midnight, huge out-of-datetime-range duration yields controlled ValueError, same UTC instant endpoints reject even with different offsets, unchanged 1d natural-day behavior, and all existing rules.
- [ ] **Step 2: Run red.** `uv run pytest tests/test_custom_ranking_time.py -q`.
- [ ] **Step 3: Implement UTC-based elapsed arithmetic.** Compute end_utc once, subtract duration in UTC, convert back to request timezone for wire/display. Do not subtract directly in ZoneInfo wall time across DST. Previous interval derives from accepted interval only, not datetime.now().
- [ ] **Step 4: Integrate kind-scoped period parsing/defaults/cycling.** Permit s/m/h only in V2 Ranking periods and defaults. Live Dataset declarations remain authoritative, preserve exact declaration strings and order, and retain no-declaration generic fallback. Non-Ranking and native CLI reject the same new strings. Preserve fixed startup anchor semantics for existing date paths.
- [ ] **Step 5: Add timestamp wire and preset tests.** Serialization emits only start_at/end_at for TimestampRange, no dates/gran. UTC-normalized boundaries enter canonical_custom_request_key. Restore relative presets with fresh injected clock, fixed timestamp ranges with their original boundaries; old date presets still round-trip. Do not add new CLI timestamp-bound options.
- [ ] **Step 6: Run green and commit.** `uv run pytest tests/test_custom_ranking_time.py tests/test_core_time.py tests/test_options.py tests/test_dashboard_presets.py tests/test_custom_protocol.py -q`; commit `feat: resolve dataset-declared subday ranking periods`.

### Task 5: Precision-safe acquisition, lifecycle, summaries and UI

**Files:**
- Modify: `src/ccusage_viz/acquisition.py`, `src/ccusage_viz/providers/custom_command.py`, `src/ccusage_viz/custom_component.py`, `src/ccusage_viz/query/models.py`, `src/ccusage_viz/query/runtime.py`, `src/ccusage_viz/tui.py`, `src/ccusage_viz/watch.py`, `src/ccusage_viz/render/custom.py`, `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_provider.py`, `tests/test_custom_component.py`, `tests/test_tui_custom.py`, `tests/test_tui_dashboard.py`, existing acquisition/query runtime tests found by `rg -l 'custom_historical_query_intent|canonical_custom_request_key' tests`

**Interfaces:**
- Consumes TimestampRange and scalar projections from Tasks 2/4.
- `custom_historical_query_intent` dispatches timestamp Ranking as `DataResolution.TIMESTAMP` with `DataScope(())` and `missing_intervals=()`; actual bounds belong to payload and immutable fingerprint options, not DateInterval.
- Query execution_options include sorted UTC start_at/end_at keys for timestamp intent fingerprint; physical command request identity derives from canonical_custom_request_key.
- `CustomHistoricalComponent` primary/comparison config and completion matching preserve exact range and one shared anchor.

- [ ] **Step 1: Add acquisition/dedup red tests.** Two different second-level ranges on the same date must start separate physical requests; equal UTC instants expressed with different offsets share identity. Duplicate subscribers for the same range share execution. Top/theme/style behavior retains existing identity rules.
- [ ] **Step 2: Add lifecycle tests.** For accepted `[T-10m,T)`, comparison must be `[T-20m,T-10m)` even if clock advances before comparison submission. Period edits and refresh capture new T; presentation-only changes preserve accepted T. A completion for an older range cannot overwrite newer accepted configuration.
- [ ] **Step 3: Implement timestamp acquisition without bogus date coverage.** Follow existing Monitor timestamp request handling. Audit provider execution for access to request.start_date and scope.intervals; narrow by actual range shape. Add canonical UTC bounds to logical intent fingerprint rather than relying on payload, since QueryIntent fingerprint currently excludes payload. Do not overhaul date coverage globally.
- [ ] **Step 4: Suppress date-only summaries for subday queries.** In component and Dashboard summary routing, do not construct DateInterval from TimestampRange or retain stale previous date summary. Switching back to a date period restores existing summary behavior. Use fake summary providers to assert zero summary submissions for subday Ranking even if capability says comparisons.
- [ ] **Step 5: Wire refresh and display.** Update relevant tui/watch paths to dispatch DateRange or TimestampRange helpers with request timezone. Display exact accepted bounds and preserved period text; copied commands use period, no gran. Prevent timeline/calendar/stack renderers from consuming TimestampRange. Preserve partition headings, Top/Other and density controls.
- [ ] **Step 6: Run green.** Run affected acquisition/runtime tests plus `uv run pytest tests/test_custom_provider.py tests/test_custom_component.py tests/test_tui_custom.py tests/test_tui_dashboard.py tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py -q`.
- [ ] **Step 7: Commit precise lifecycle/UI changes.** `git diff --check`; commit `feat: query and refresh precise custom ranking ranges`.

### Task 6: Minimal WeRead wire adapter migration

**Files (WeRead root):**
- Modify: `internal/protocol/v2/protocol.go`, `internal/protocol/v2/protocol_test.go`
- Modify: `internal/metrics/readingtime/metric.go`, `internal/metrics/readingtime/metric_test.go`
- Modify: `internal/metrics/totalnotes/metric.go`, `internal/metrics/totalnotes/metric_test.go`
- Test/update: `internal/dataset/dataset_test.go`, command/package verification tests containing Ranking requests
- Docs: existing protocol sections only

**Interfaces:**
- Consumes V2 explicit chart_kind and scalar Ranking contract.
- Retains existing dated Series for non-Ranking. Add `RankingEntry` with value and existing metadata, used only in Ranking response data.
- Request carries ChartKind; Ranking validation ignores gran and other charts still require the same supported gran as before.

- [ ] **Step 1: Record clean/dirty status and baseline tests.** `git status --short`; `go test ./...`. Preserve any newly arrived changes.
- [ ] **Step 2: Red tests for unchanged numeric results.** Existing book/category reading rank output must have scalar value equal to the old single point value, no points/date. total_notes book/note_type same. Test Ranking query missing gran and carrying arbitrary legacy gran succeeds; Timeline/Calendar/Stack output points and unsupported gran validation remain unchanged.
- [ ] **Step 3: Implement protocol-only adapter.** Existing reading rank branch produces `Value: formatMinutes(record.Seconds)`; existing totalnotes aggregate emits its current formatted count. Do not alter Source calls, supported periods, top/max_items, or category aggregation. Remove only Ranking granularities declarations. Explicit chart_kind selects branch, not group presence; validate non-Ranking exactly as before.
- [ ] **Step 4: Run green.** `go test ./...`; compare fixture values before/after, including display strings and summary behavior.
- [ ] **Step 5: Commit only adapter/tests/docs paths.** Commit `feat: adapt weread rankings to scalar v2 results`. Binary rebuild is Task 9.

### Task 7: Minimal Router quota Ranking migration

**Files (Router root):**
- Modify: `cmd/ccuv-router-dataset/main.go`, `cmd/ccuv-router-dataset/main_test.go`
- Test unchanged business client: `internal/router/client_test.go`
- Docs: `README.md` Ranking protocol examples only

**Interfaces:**
- Consumes V2 scalar Ranking contract for existing quota all; requests/P95 remain Monitor-only.
- Existing quota rows map `row.Value` directly to item.value with display/description preserved.

- [ ] **Step 1: Inspect overlapping uncommitted changes and save baseline diff outside repo if needed.** `git diff -- cmd/ccuv-router-dataset/main.go cmd/ccuv-router-dataset/main_test.go README.md`; `go test ./...`. Never overwrite existing changes or stage their unrelated hunks.
- [ ] **Step 2: Add red quota response assertions.** Existing fake quota response fixture must keep same item IDs, value strings, display, descriptions and ordering. Assert absent points, accepted missing/arbitrary gran, descriptor Ranking lacks granularities, unsupported non-all period still fails.
- [ ] **Step 3: Replace points wrapper with scalar value.** Use `"value": row.Value` in existing item assembly; remove Ranking-only gran validation and capability field; accept explicit chart_kind. Do not change `internal/router/client.go`, telemetry API, quota arithmetic, stale behavior, or Monitor.
- [ ] **Step 4: Run green.** `go test ./...`; Monitor snapshots and requests/P95 capability remain byte/semantic equivalent where relevant.
- [ ] **Step 5: Review scoped hunks and commit only this task's changes.** Use interactive/path-specific staging; commit `feat: adapt router quota ranking to scalar v2 results` only if unrelated hunks can be safely excluded. Otherwise leave a documented task diff without claiming a clean standalone commit.

### Task 8: Minimal GitHub Ranking migration

**Files (GitHub root):**
- Modify: `internal/protocol/protocol.go`, `internal/protocol/protocol_test.go`
- Docs: existing README Dataset examples only
- Do not modify: catalog database, discovery/enrichment/sync scripts, source data, existing command changes unrelated to protocol

**Interfaces:**
- Consumes V2 scalar Ranking item contract.
- Existing three item construction sites for creator/source results, projects and grouped totals return existing numeric value strings directly.

- [ ] **Step 1: Inspect baseline and run tests.** `git status --short`; `git diff -- internal/protocol/protocol.go internal/protocol/protocol_test.go`; `go test ./...`.
- [ ] **Step 2: Add red tests covering all existing metrics.** stars_total, stars_growth, heat_score, updated_days_ago, source_discovery retain old values, rounding/display, grouping and periods. Assert no points, descriptor has no Ranking granularities, arbitrary query.granularity is ignored, and explicit non-Ranking chart_kind is rejected without touching ranking logic.
- [ ] **Step 3: Migrate output wrappers.** Replace dated point wrappers with `"value": fmt.Sprint(existingValue)` at existing constructors. Keep end_date usage for actual growth/source calculations; deleting item date does not delete range semantics. Remove unused date parameters only when they were used exclusively to label a point; retain them when computations depend on them.
- [ ] **Step 4: Run green.** `go test ./...`; verify tests use temporary fixture database rather than modifying live catalog.db. Do not add subday periods.
- [ ] **Step 5: Commit protocol/tests and narrowly scoped docs.** `git diff --check`; commit `feat: adapt github rankings to scalar v2 results` with unrelated dirty files untouched.

### Task 9: Full regression, docs, binaries and registration refresh

**Files:**
- Modify: `docs/dataset-developer-guide.md`, `docs/dataset-developer-guide.zh-CN.md`, affected usage/README protocol sections and `examples/` V2 Ranking fixtures
- Modify: remaining tests with V2 Ranking points fixtures; keep V1/non-Ranking fixtures unchanged
- Build local ignored/generated binaries at the three registered source paths; do not publish archives

**Interfaces:**
- Consumes migrated core and plugins.
- Registration refresh uses existing `DatasetService.refresh_all()` or current CLI/UI equivalent, not hand-edited JSON.

- [ ] **Step 1: Find stale V2 Ranking contract examples.** `rg -n 'granularities|granularity|points|chart_kind' docs examples tests`; update only contexts explicitly describing V2 Ranking, including grouped partition examples. Explain date-inclusive versus timestamp-half-open, standard s/m/h periods, and ignored legacy gran fields. Keep date series examples for other historical charts.
- [ ] **Step 2: Add fake-command end-to-end case.** Probe declares Ranking periods `["15s","90s","10m","1h","1d","all"]` and optional partition. Fake command checks exact timestamp bounds/no gran/explicit chart kind, returns scalar flat/grouped facts. Exercise chooser, p/P, refresh, comparison, persistence and grouped render/copy without relying on any plugin having subday source support.
- [ ] **Step 3: Run core full suite and lint.** `uv run pytest -q`; inspect pyproject.toml for existing configured lint commands, run `uv run ruff check src tests` and existing formatting checks without auto-reformatting unrelated code. Existing failures caused by concurrent tasks are recorded with baseline evidence, not silently ignored.
- [ ] **Step 4: Run all plugin suites.** In each plugin root run `go test ./...`. Confirm same declared metric/period/group/default behavior except removal of Ranking gran fields and deliberate protocol revision metadata changes.
- [ ] **Step 5: Build registered native executables after tests pass.**

```bash
(cd /Users/bytedance/Projects/go/ccuv-dataset-weread && go build -o ccuv-dataset-weread ./cmd/ccuv-dataset-weread)
(cd /Users/bytedance/Projects/go/ccuv-router-dataset && go build -o ccuv-router-dataset ./cmd/ccuv-router-dataset)
(cd /Users/bytedance/Projects/github-projects && go build -o bin/ccuv-github-tools-dataset ./cmd/ccuv-github-tools-dataset)
```

Read current registrations before overwrite and confirm they still point to these paths; abort/update plan if a concurrent agent changed them. Preserve original binary until replacement build succeeds by building to a neighboring temporary file then atomically moving it to the registered path.

- [ ] **Step 6: Probe binaries with new CCUV parser.** Feed each a V2 probe JSON; GitHub must use its existing registered --database argument, but Probe must not run catalog mutation or enrichment. Verify capabilities match old ones except Ranking gran/revision fields. Use fake source servers/fixtures for chart queries; do not invent zeros to replace failed live requests.
- [ ] **Step 7: Refresh registration snapshots via service.** Read DatasetService constructor and current registration API, run its existing refresh flow under current user context. It only probes registered executables; assert all three statuses ready or distinguish existing missing required environment from protocol errors. Check snapshots omit Ranking granularities, preserve command args, enabled state and other capabilities. Do not manually edit JSON to force availability.
- [ ] **Step 8: Final review and scoped commit.** `git diff --check`; inspect git status/log for all four roots; commit remaining core docs/test migrations. Do not commit generated binaries unless already tracked and part of this repository's established practice. Record tests, local binary/registration changes, and pre-existing dirty work in handoff.

## Self-Review Checklist

- [ ] Scalar migration covers both data.series and data.groups[].series, not just flat rankings.
- [ ] V1 dated fixtures and Timeline/Stack/Calendar remain distinct.
- [ ] Ranking gran is absent semantically in parsing, defaults, requests, identity, normalization and preset serialization; partition g/G is retained.
- [ ] Timestamp intervals do not pass through DateInterval, date-axis construction or date-only summaries.
- [ ] Logical and physical fingerprints retain exact UTC boundaries; payload-only identity is insufficient.
- [ ] Clock arithmetic uses UTC elapsed duration across DST and comparison shares the primary anchor.
- [ ] No plugin adds subday periods or changes business values/source calls.
- [ ] Full partition behaviors, native Ranking invariants, plugin test coverage and registration migration have tasks.
- [ ] Remote publication is not included; unrelated concurrent changes remain untouched.

## Execution Handoff

Recommended: core tasks sequentially with review gates, plugin Tasks 6–8 delegated independently after the wire contract is stable, then Task 9 sequential integration. For plugin repositories with dirty overlapping files, use exact edits and review hunks; isolated worktrees would miss the existing unpublished business changes and are not a safe substitute without explicit synchronization.
