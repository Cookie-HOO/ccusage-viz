# Custom V2 Metric Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users cycle Dataset-declared, related V2 Metrics in a Custom pane while keeping historical switching transactional and Monitor sampling independent per visited Metric.

**Architecture:** Extend V2 Dataset descriptors with optional ordered `metric_groups` resources and Metric `group_id` references, then use the accepted descriptor to derive same-Group candidates for an active chart kind. Historical panes create a pending target request without committing the selected Metric until it succeeds. Custom Monitor owns a small per-Metric runtime registry, allowing visited Metrics to continue sampling independently while only the selected runtime is rendered.

**Tech Stack:** Python 3.12+, dataclasses, pytest, existing Custom V2 protocol/provider, Dashboard TUI lifecycle scheduler, English and Simplified-Chinese locale dictionaries.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-metric-switching-design.md`

## Global Constraints

- Reuse V2 `metric_id`; do not add a protocol version, request field, Ranking-only view, or preset field.
- `metric_groups` is an optional ordered Dataset-level resource list; each Group has a unique stable ID and localized title. A Metric may optionally reference one Group through `group_id`.
- `m/M` must be present in Custom-pane help regardless of candidate count.
- Candidates must have the active chart capability and reference the current Metric's declared Group; Metric declaration order is the cycle order.
- Static rejection checks only chart kind, declared periods, declared group-by values, and declared granularities; no preflight command or Probe.
- Historical switches commit only after successful target data; failed target requests leave old selected facts and persisted `metric_id` untouched, and old historical data must not refresh after successful commit.
- Monitor keeps independent visited-Metric sampling and history alive in the background; never mix observations, baselines, or failures across Metrics.
- Never modify or commit the pre-existing unrelated changes in `src/ccusage_viz/render/custom_ranking_viewport.py` and `tests/test_custom_ranking_scroll.py`.

---

## File Structure

- `src/ccusage_viz/custom_models.py`: typed `V2MetricGroup` resource and optional Metric `group_id` descriptor field.
- `src/ccusage_viz/custom_protocol.py`: V2 descriptor parsing and local registration wire serialization.
- `src/ccusage_viz/custom_metric_switching.py` (new): pure candidate selection and static compatibility helpers, shared by Dashboard and tests.
- `src/ccusage_viz/custom_component.py`: transactional historical target-switch state and successful commit behavior.
- `src/ccusage_viz/custom_monitor_component.py`: isolated runtime snapshots / operations per visited Monitor Metric.
- `src/ccusage_viz/tui.py`: Dataset Metric chooser grouping, key handling, notices, target request wiring, and scheduling each visited Monitor runtime.
- `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`: localized control and notice strings.
- `docs/custom-command-protocol.md`, `docs/custom-command-protocol.zh-CN.md`, `docs/dataset-developer-guide.md`, `docs/dataset-developer-guide.zh-CN.md`: public schema and authoring guidance.
- `tests/test_custom_protocol.py`: descriptor schema tests.
- `tests/test_custom_metric_switching.py` (new): pure eligibility and static validation tests.
- `tests/test_custom_component.py`: transactional historical component tests.
- `tests/test_custom_monitor_component.py`: independent Monitor Metric runtime tests.
- `tests/test_tui_custom.py`, `tests/test_tui_dashboard.py`: Dashboard key, request, help, notice, and scheduling integration tests.

## Interfaces

```python
# src/ccusage_viz/custom_metric_switching.py
@dataclass(frozen=True, slots=True)
class MetricSwitchRejection:
    field: Literal["kind", "range.period", "query.group_by", "query.granularity"]
    value: str | None

def switch_candidates(
    descriptor: V2ProbeDescriptor, *, current_metric_id: str, kind: str
) -> tuple[V2MetricDescriptor, ...]: ...

def cycle_switch_metric(
    descriptor: V2ProbeDescriptor, *, current_metric_id: str, kind: str, step: int
) -> V2MetricDescriptor | None: ...

def validate_metric_switch(
    config: CustomChartConfig, target: V2MetricDescriptor
) -> MetricSwitchRejection | None: ...
```

`cycle_switch_metric` returns `None` where there is no alternate candidate. `validate_metric_switch` is purely in-memory and does not inspect runtime filters or issue requests.

### Task 1: Add Metric Group resources to the V2 descriptor contract

**Files:**
- Modify: `src/ccusage_viz/custom_models.py:V2MetricDescriptor`
- Modify: `src/ccusage_viz/custom_protocol.py:_parse_v2_metric`, `v2_probe_descriptor_to_wire`
- Modify: `tests/test_custom_protocol.py`

**Interfaces:**
- Produces: `V2ProbeDescriptor.metric_groups: tuple[V2MetricGroup, ...]` and `V2MetricDescriptor.group_id: str | None`.
- Produces: descriptor parsing and registration wire round-trip support.

- [ ] **Step 1: Write failing protocol tests**

```python
def test_v2_metric_groups_and_references_round_trip() -> None:
    value = v2_probe_descriptor()
    value["metric_groups"] = [{"id": "router-throughput", "title": text("Throughput", "吞吐量")}]
    value["metrics"][0]["group_id"] = "router-throughput"
    descriptor = parse_v2_probe_descriptor(value)

    assert descriptor.metric_groups[0].id == "router-throughput"
    assert descriptor.metrics[0].group_id == "router-throughput"
    assert v2_probe_descriptor_to_wire(descriptor)["metric_groups"][0]["id"] == "router-throughput"


def test_v2_metric_rejects_unknown_group_id() -> None:
    descriptor = v2_probe_descriptor()
    descriptor["metrics"][0]["group_id"] = "missing"

    with pytest.raises(CustomProtocolError, match="group_id"):
        parse_v2_probe_descriptor(descriptor)
```

- [ ] **Step 2: Run the protocol tests to verify they fail**

Run: `pytest tests/test_custom_protocol.py -k 'metric_group or group_id' -v`

Expected: FAIL because the descriptor has no Metric Group parser support.

- [ ] **Step 3: Implement the minimal typed parser and serializer support**

```python
@dataclass(frozen=True, slots=True)
class V2MetricGroup:
    id: str
    title: LocalizedText


class V2MetricDescriptor:
    # existing fields
    summary: Literal["comparisons", "total", "none"] = "comparisons"
    group_id: str | None = None
```

In `parse_v2_probe_descriptor`, parse optional `metric_groups` before Metrics, validate Group IDs are unique, and require localized titles. In `_parse_v2_metric`, read optional `group_id` using existing stable-ID validation. After all Metrics are parsed, reject any non-null `group_id` not declared in `metric_groups`. Pass optional fields by keyword to preserve existing positional constructors. In `v2_probe_descriptor_to_wire`, emit `metric_groups` only when nonempty and `group_id` only when non-`None`.

- [ ] **Step 4: Run focused protocol tests**

Run: `pytest tests/test_custom_protocol.py -k 'metric_group or group_id or v2_probe' -v`

Expected: PASS.

- [ ] **Step 5: Commit the contract change**

```bash
git add src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py tests/test_custom_protocol.py
git commit -m "feat: declare groups for custom metrics"
```

### Task 2: Implement pure candidate and static compatibility logic

**Files:**
- Create: `src/ccusage_viz/custom_metric_switching.py`
- Create: `tests/test_custom_metric_switching.py`

**Interfaces:**
- Consumes: `V2ProbeDescriptor`, `V2MetricDescriptor`, `V2HistoricalChartCapability`, `V2MonitorCapability`, `CustomChartConfig`.
- Produces: `switch_candidates`, `cycle_switch_metric`, `validate_metric_switch`, and `MetricSwitchRejection` exactly as declared above.

- [ ] **Step 1: Write failing candidate-order tests**

```python
def test_cycles_only_same_group_metrics_that_support_the_active_kind() -> None:
    descriptor = descriptor_with_metrics(
        metric("stars", group_id="github", charts={"ranking"}),
        metric("updated_days", group_id="github", charts={"ranking"}),
        metric("issues", group_id="github", charts={"timeline"}),
        metric("builds", group_id="ci", charts={"ranking"}),
        metric("forks", group_id=None, charts={"ranking"}),
        groups=(group("github"), group("ci")),
    )

    assert [item.id for item in switch_candidates(descriptor, current_metric_id="stars", kind="ranking")] == ["stars", "updated_days"]
    assert cycle_switch_metric(descriptor, current_metric_id="stars", kind="ranking", step=1).id == "updated_days"
    assert cycle_switch_metric(descriptor, current_metric_id="stars", kind="ranking", step=-1).id == "updated_days"


def test_returns_none_when_group_has_no_alternate_metric() -> None:
    descriptor = descriptor_with_metrics(metric("stars", group_id="github", charts={"ranking"}), groups=(group("github"),))
    assert cycle_switch_metric(descriptor, current_metric_id="stars", kind="ranking", step=1) is None
```

- [ ] **Step 2: Write failing static-validation tests**

```python
def test_rejects_only_declared_period_group_and_granularity_mismatches() -> None:
    target = metric_with_ranking(periods=("30d",), group_by=("repo",), granularities=("week",))
    config = custom_config("ranking", period="14d", group_by=None, granularity="day")

    assert validate_metric_switch(config, target) == MetricSwitchRejection("range.period", "14d")


def test_does_not_validate_runtime_filters_or_cross_field_rules() -> None:
    target = metric_with_ranking(periods=(), group_by=(None,), granularities=("day",))
    config = custom_config("ranking", period="14d", group_by=None, granularity="day", filters=(("unknown", ("x",)),))
    assert validate_metric_switch(config, target) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_custom_metric_switching.py -v`

Expected: FAIL because the module is absent.

- [ ] **Step 4: Implement only deterministic descriptor-based helpers**

Implement candidate filtering from the current descriptor Metric's non-null group and active chart key. Preserve descriptor declaration order. For `step`, normalize to `+1` / `-1`, locate current ID, wrap with modulo, and return `None` if the candidate tuple has fewer than two items.

`validate_metric_switch` must obtain `target.capabilities.charts[config.kind]`. For historical capabilities, reject a selected period only when `periods` is nonempty and missing it; reject selected `group_by` only when `group_by` is declared and missing it; reject selected granularity only when `granularities` is declared and missing it. For Monitor, validate chart capability only; group validation uses its declared `group_by`. Do not examine `runtime.filters`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_custom_metric_switching.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the pure switching layer**

```bash
git add src/ccusage_viz/custom_metric_switching.py tests/test_custom_metric_switching.py
git commit -m "feat: resolve related custom metric switches"
```

### Task 3: Make historical Metric switching transactional

**Files:**
- Modify: `src/ccusage_viz/custom_component.py:CustomHistoricalComponent`
- Modify: `tests/test_custom_component.py`

**Interfaces:**
- Produces: `CustomHistoricalComponent.begin_metric_switch(config: CustomChartConfig) -> None` and `cancel_metric_switch(error: BaseException, *, generation: int) -> bool`.
- Invariant: `candidate` remains the committed config until a target primary response is accepted; an internal pending target config is requestable by the scheduler.

- [ ] **Step 1: Write failing component tests for commit and failure behavior**

```python
def test_historical_metric_switch_commits_only_after_target_response() -> None:
    component = accepted_historical_component(metric_id="stars")
    target = replace(component.candidate, metric_id="updated_days")

    component.begin_metric_switch(target)

    assert component.candidate.metric_id == "stars"
    assert component.request_config.metric_id == "updated_days"
    assert component.accept_response(target_response("updated_days"))
    assert component.candidate.metric_id == "updated_days"
    assert component.model is not None


def test_historical_metric_switch_failure_retains_old_facts_and_metric() -> None:
    component = accepted_historical_component(metric_id="stars")
    old_model = component.model
    component.begin_metric_switch(replace(component.candidate, metric_id="updated_days"))

    assert component.cancel_metric_switch(RuntimeError("unavailable"), generation=component.generation)
    assert component.candidate.metric_id == "stars"
    assert component.model is old_model
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_custom_component.py -k 'metric_switch_commits or metric_switch_failure' -v`

Expected: FAIL because no transactional switch API exists.

- [ ] **Step 3: Implement pending-target state without changing ordinary adjustments**

Add private slots for `switch_target_config: CustomChartConfig | None` and enough prior query state to restore the old generation on failure. Add a read-only `request_config` that yields target while a switch is pending, otherwise `candidate`. `begin_metric_switch` increments the generation and marks the target pending but does not clear `accepted_config`, `accepted_response`, model, presentation, capability, or persisted candidate.

Update request-producing methods (`comparison_request_config`, `accept_response`, and the provider-result conversion path) to use `request_config` for target request identity. On successful primary target acceptance, first atomically assign `candidate = switch_target_config`, then clear switch state and proceed through the existing successful primary replacement path, thereby discarding old historical facts and caches. On failure, clear switch state and retain the old accepted state. Ensure ordinary non-switch `configure(..., data_affecting=True)` retains its current replacement behavior.

- [ ] **Step 4: Run historical component coverage**

Run: `pytest tests/test_custom_component.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the historical transactional behavior**

```bash
git add src/ccusage_viz/custom_component.py tests/test_custom_component.py
git commit -m "feat: commit custom metric switches after historical success"
```

### Task 4: Refactor Custom Monitor into independent visited-Metric runtimes

**Files:**
- Modify: `src/ccusage_viz/custom_monitor_component.py:CustomMonitorComponent`
- Modify: `tests/test_custom_monitor_component.py`

**Interfaces:**
- Produces: `CustomMonitorComponent.switch_metric(config: CustomChartConfig) -> None` and `metric_components: Mapping[str, CustomMonitorMetricState]` (internal state type may remain module-private).
- Each `CustomMonitorMetricState` owns `config`, `generation`, accepted response/config/time, history, error, runtime, descriptor-derived presentation and capability.
- The existing public properties (`candidate`, `history`, `accepted_response`, `monitor_capability`, render methods) project the selected Metric state so render callers remain simple.

- [ ] **Step 1: Write failing retained-sampling tests**

```python
def test_monitor_keeps_visited_metric_history_while_another_metric_is_selected() -> None:
    component = component_with_accepted_metric("stars", total="10")
    component.switch_metric(config(metric_id="updated_days"))
    component.accept(completion_for("updated_days", total="2"), accepted_at=NOW)
    component.accept(completion_for("stars", total="11"), accepted_at=NOW_PLUS_MINUTE)

    component.switch_metric(config(metric_id="stars"))

    assert [item.observation.total for item in component.history] == [Decimal("10"), Decimal("11")]
    assert component.accepted_response.observation.total == Decimal("11")


def test_monitor_failure_for_hidden_metric_does_not_affect_selected_metric() -> None:
    component = component_with_two_visited_metrics(selected="updated_days")
    component.fail(RuntimeError("stars unavailable"), generation=generation_for(component, "stars"), metric_id="stars")

    assert component.candidate.metric_id == "updated_days"
    assert component.error is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_custom_monitor_component.py -k 'keeps_visited or hidden_metric' -v`

Expected: FAIL because one component has one history / generation.

- [ ] **Step 3: Introduce a private per-Metric state object and preserve existing render API**

Move the currently singular fields that represent a source sampling stream (`candidate`, accepted fields, generation, history, error, runtime, descriptor/presentation/capability) into a private dataclass keyed by `metric_id`. Keep pane-wide `display_window_seconds`, timezone, distribution window, and render revision shared.

`switch_metric` selects or creates a state without clearing an existing state. `accept` and `fail` must route by explicit completion Metric ID / state generation. The selected state's properties remain exposed through the existing component API, so `render_custom_monitor` continues to render only the selected Metric. Add a method returning each visited state that needs a periodic submission; do not create state for unvisited candidates.

- [ ] **Step 4: Run Monitor component tests**

Run: `pytest tests/test_custom_monitor_component.py -v`

Expected: PASS, including existing tests after adapting direct-field setup helpers to select a state explicitly.

- [ ] **Step 5: Commit isolated Monitor state**

```bash
git add src/ccusage_viz/custom_monitor_component.py tests/test_custom_monitor_component.py
git commit -m "feat: retain sampling for switched custom monitor metrics"
```

### Task 5: Wire `m/M`, localized feedback, historical requests, and Monitor background scheduling

**Files:**
- Modify: `src/ccusage_viz/tui.py:TuiCustomPane`, `_custom_pane_adjustment_bindings`, Dashboard key dispatch, `refresh`, `collect`, periodic loop
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Modify: `tests/test_tui_custom.py`
- Modify: `tests/test_tui_dashboard.py`

**Interfaces:**
- Consumes: Task 2 helper APIs, Task 3 `request_config` / switch APIs, Task 4 visited-Metric state API.
- Produces: `m/M` behavior in Custom panes and background scheduling for every visited Custom Monitor Metric.

- [ ] **Step 1: Write failing Dataset Metric chooser grouping tests**

```python
def test_metric_chooser_remains_flat_when_dataset_declares_no_metric_groups() -> None:
    descriptor = descriptor_without_metric_groups("stars", "updated_days")

    assert metric_chooser_rows(descriptor, language="en") == (
        MetricChooserMetricRow("stars", "Stars", indent=0),
        MetricChooserMetricRow("updated_days", "Days since update", indent=0),
    )


def test_metric_chooser_renders_declared_nonempty_groups_then_ungrouped_metrics() -> None:
    descriptor = descriptor_with_metric_groups(
        groups=(group("github", "GitHub tools"), group("empty", "Empty")),
        metrics=(
            metric("stars", group_id="github"),
            metric("updated_days", group_id="github"),
            metric("legacy", group_id=None),
        ),
    )

    assert metric_chooser_rows(descriptor, language="en") == (
        MetricChooserGroupRow("GitHub tools"),
        MetricChooserMetricRow("stars", "Stars", indent=1),
        MetricChooserMetricRow("updated_days", "Days since update", indent=1),
        MetricChooserMetricRow("legacy", "Legacy metric", indent=0),
    )
```

- [ ] **Step 2: Run chooser tests to verify they fail**

Run: `pytest tests/test_tui_custom.py -k metric_chooser -v`

Expected: FAIL because chooser rows are currently a direct flat rendering of `descriptor.metrics`.

- [ ] **Step 3: Add a selectable-row chooser projection and render it**

Add a small pure helper close to `_choose_dataset_pane_config`, such as `metric_chooser_rows(descriptor: V2ProbeDescriptor, translator: Translator) -> tuple[MetricChooserRow, ...]`. It must preserve a stable mapping from every selectable metric row to its original `metrics[]` index. When `descriptor.metric_groups` is empty, return only flat metric rows exactly matching current rendering. Otherwise: collect each group's members in `metrics[]` order, emit only nonempty Group title rows in `metric_groups[]` order, indent their metric rows by one display level, then emit `group_id is None` metrics as flat rows with no generated heading. Never make Group rows selectable; `j/k` skips Group rows, while Enter resolves the selected Metric row.

- [ ] **Step 4: Run chooser tests to verify they pass**

Run: `pytest tests/test_tui_custom.py -k metric_chooser -v`

Expected: PASS.

- [ ] **Step 5: Write failing TUI switching and Monitor scheduling tests**

```python
def test_custom_history_m_switches_to_next_same_group_metric_only_after_success(dashboard) -> None:
    pane = custom_ranking_pane_with_grouped_metrics(dashboard, current="stars")
    dashboard.press("m")

    assert sent_metric_ids(dashboard) == ["updated_days"]
    assert pane.component.candidate.metric_id == "stars"
    dashboard.complete_custom_chart(metric_id="updated_days")
    assert pane.component.candidate.metric_id == "updated_days"


def test_custom_metric_switch_static_rejection_keeps_chart_and_shows_expiring_notice(dashboard) -> None:
    pane = custom_ranking_pane_with_incompatible_target(dashboard)
    old_model = pane.component.model
    dashboard.press("m")

    assert pane.component.model is old_model
    assert sent_metric_ids(dashboard) == []
    assert dashboard.feedback_contains("period")
    assert dashboard.feedback_expires_in_seconds == 3


def test_single_related_metric_shows_three_second_notice_and_help_still_lists_m(dashboard) -> None:
    dashboard.focus(custom_pane_with_one_group_member())
    dashboard.press("m")

    assert dashboard.feedback_expires_in_seconds == 3
    assert "m/M" in dashboard.help_text()


def test_monitor_samples_hidden_visited_metric_on_periodic_refresh(dashboard) -> None:
    pane = custom_monitor_with_two_grouped_metrics(dashboard)
    dashboard.switch_metric("updated_days")
    dashboard.advance_to_periodic_refresh()

    assert set(sent_metric_ids(dashboard)) >= {"stars", "updated_days"}
    assert rendered_metric_id(pane) == "updated_days"
```

- [ ] **Step 6: Run the focused switching tests to verify they fail**

Run: `pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'metric_switch or hidden_visited_metric or one_group_member' -v`

Expected: FAIL because no key dispatch or multiple Monitor scheduling exists.

- [ ] **Step 7: Add localizations and always-visible Custom control**

Add English and Chinese strings for:

```python
"adjustment.metric": "related metric"
"status.custom_metric_no_alternative": "No related Metric is available to switch to"
"status.custom_metric_switch_rejected": "Related Metric does not support {field}: {value}"
"status.custom_metric_switched": "Switched to {metric}"
"status.tui_help_parameter_metric": "switch to the next or previous related Metric"
```

Use project capitalization/style equivalents in Chinese. Add `("m/M", "metric")` to Custom quick adjustment bindings independently of candidate count and expose it through help translation.

- [ ] **Step 8: Implement key dispatch with static checks and 3-second feedback**

In the existing Custom-pane key branch, resolve the active descriptor from the accepted component snapshot. Call `cycle_switch_metric(..., step=1 if key == "m" else -1)`. Show `copy_feedback.show(...)` with the existing three-second feedback mechanism when there is no destination or `validate_metric_switch` rejects the target. Do not request a Probe.

For historical panes, call `begin_metric_switch(replace(base, metric_id=target.id))` and submit a normal configuration request built from `component.request_config`; only present the success feedback after completion commits.

For Monitor panes, call `switch_metric` and immediately start target sampling if first visited; retain existing state. Update summary selection only when selected Metric changes, without applying Metric defaults.

- [ ] **Step 9: Make dashboard submission identity Metric-aware for Monitor**

Refactor `TuiCustomPane` to own per-Metric monitor lifecycle/scheduler entries (or a keyed operation registry) rather than one lifecycle submission that can represent only the selected Metric. `start_custom_submission` must accept the state/config it is executing, and `collect` must route completion and failure back to that Metric state. On each periodic tick, iterate `component.visited_metric_configs()` and request refresh for each; do not schedule never-visited Metrics. Continue rendering only the selected state. Cancel all keyed operations when the pane is retired.

Keep historical panes on their existing single lifecycle path; historical old Metrics must never receive periodic requests after a successful target commit.

- [ ] **Step 10: Run focused TUI tests**

Run: `pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'metric_switch or hidden_visited_metric or one_group_member' -v`

Expected: PASS.

- [ ] **Step 11: Run the full Custom TUI regression set**

Run: `pytest tests/test_tui_custom.py tests/test_tui_dashboard.py tests/test_custom_monitor_component.py tests/test_custom_component.py -v`

Expected: PASS.

- [ ] **Step 12: Commit the Dashboard feature**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_custom.py tests/test_tui_dashboard.py
git commit -m "feat: switch related metrics in custom panes"
```

### Task 6: Document the additive V2 field and authoring semantics

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`

**Interfaces:**
- Documents the implemented Dataset-level `metric_groups` and Metric `group_id` schema and host behavior. No executable interface changes.

- [ ] **Step 1: Add the protocol contract in English and Chinese**

Near the V2 Metric introduction, state that Dataset-level `metric_groups` is optional and that a Metric may reference one resource through `group_id`. Explain that a Group joins independently declared Metrics into an in-chart quick-switch ring, does not add a request parameter or change `metric_id`, and that Metrics must independently declare the chart kinds they support. Describe that datasets omitting `metric_groups` retain the flat selector and no `m/M` relation.

Include this JSON example in each language’s appropriate prose:

```json
"metrics": [
  {"id": "github-tools", "title": {"en": "GitHub tools", "zh-CN": "GitHub 工具"}}
],
"metrics": [
  {"id": "stars", "group_id": "github-tools", "...": "..."},
  {"id": "updated_days_ago", "group_id": "github-tools", "...": "..."}
]
```

- [ ] **Step 2: Document Dataset author decision rules**

In the developer guides, explain that authors should use separate Metrics when values have independent units, aggregation, chart capabilities, sorting, descriptions, or summaries. Create a Group resource and use its `group_id` only when Metrics form a coherent user-switchable view. Explain selector ordering: Groups and titles follow `metric_groups` declaration order, members follow `metrics` declaration order and are indented, ungrouped Metrics remain flat after groups, and empty Groups are hidden. Explain that hosts retain the active query state and may reject a switch if the next Metric’s declared chart capability does not accept it; source runtime validation remains authoritative.

- [ ] **Step 3: Document historical versus Monitor retention**

State precisely: historical Custom chart changes commit only after successful target data, then discard the prior Metric state; Custom Monitor keeps already visited Metrics sampling in the background and restores their independent history when users switch back. Never promise prefetching unvisited Metrics.

- [ ] **Step 4: Verify documentation links and working tree**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended documentation files plus the known unrelated working-tree files are modified.

- [ ] **Step 5: Commit docs**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md docs/dataset-developer-guide.md docs/dataset-developer-guide.zh-CN.md
git commit -m "docs: explain custom metric groups"
```

### Task 7: Final full regression and preset persistence verification

**Files:**
- Modify if necessary: `tests/test_dashboard_presets.py`
- Modify if necessary: `tests/test_dashboard_preset_store.py`

**Interfaces:**
- Verifies successful historical commit is the only case that changes persisted `CustomChartConfig.metric_id`.

- [ ] **Step 1: Write persistence tests**

```python
def test_preset_keeps_old_metric_when_historical_switch_target_fails(dashboard) -> None:
    pane = accepted_custom_history_pane(metric_id="stars")
    dashboard.switch_then_fail(metric_id="updated_days")

    assert saved_preset(dashboard).panes[0].metric_id == "stars"


def test_preset_saves_target_metric_after_historical_switch_succeeds(dashboard) -> None:
    pane = accepted_custom_history_pane(metric_id="stars")
    dashboard.switch_then_succeed(metric_id="updated_days")

    assert saved_preset(dashboard).panes[0].metric_id == "updated_days"
```

- [ ] **Step 2: Run the persistence tests to verify they pass**

Run: `pytest tests/test_dashboard_presets.py tests/test_dashboard_preset_store.py -k metric -v`

Expected: PASS.

- [ ] **Step 3: Run the project test suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 4: Run style/type checks configured by the repository**

Run: `ruff check src tests && ty check src`

Expected: PASS. If `ty` is not configured in `pyproject.toml`, run only the configured checker and record that fact in the implementation summary.

- [ ] **Step 5: Commit any final test-only changes**

```bash
git add tests/test_dashboard_presets.py tests/test_dashboard_preset_store.py
git commit -m "test: cover custom metric switch persistence"
```
