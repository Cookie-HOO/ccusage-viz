# Metric Switch Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an `m/M`-initiated related-Metric switch retain current query state first, then recover only Dataset-reported incompatible fields to the target Metric defaults and retry transactionally.

**Architecture:** Remove pre-request static compatibility rejection from the switch path. Maintain a pending switch object on historical and Monitor components with its target config and normalized-field categories. When the Dataset returns a structured `unsupported_query`, map the reported field to exactly one target-Metric default mutation, issue another target request, and commit only after success. All ordinary user adjustments keep their existing strict failure behavior.

**Tech Stack:** Python 3.12+, dataclasses, pytest, Custom V2 protocol error model, historical/Monitor components, Dashboard TUI lifecycle.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-metric-switching-design.md`

## Global Constraints

- Only `m/M` related-Metric switches normalize; manual period, group, granularity, filters, and Top changes do not.
- First target request preserves all current state; do not use static `periods`, `group_by`, or `granularities` to block it.
- Normalize only Dataset `unsupported_query` fields: `range.period`, `query.group_by`, `query.granularity`, `query.filters` / `query.filters.*`, and `query.top`.
- Any filter-related field resets the **entire** filter state to target defaults, or empty filters when target has no filter default.
- Each normalized category is allowed once. Unknown, repeated, unchanged, or default-less categories stop with the old Metric still selected.
- Transactional semantics remain: commit target config and persist it only after a successful response; old historical facts or Monitor samples remain visible until then.
- Do not alter V1 Dataset behavior, source replacement, or ordinary user adjustment error semantics.

---

## File Structure

- `src/ccusage_viz/custom_metric_switching.py`: remove static switch rejection API; add pure unsupported-field category and default-normalization helper.
- `src/ccusage_viz/custom_component.py`: retain pending historical switch normalization state and retry config.
- `src/ccusage_viz/custom_monitor_component.py`: retain pending Monitor switch normalization state and retry config.
- `src/ccusage_viz/tui.py`: route structured target failures to retry only while a switch is pending; add normalized-switch feedback.
- `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`: normalized-switch feedback labels.
- `tests/test_custom_metric_switching.py`: normalization helper tests.
- `tests/test_custom_component.py`: historical pending switch retries and terminal failures.
- `tests/test_custom_monitor_component.py`: Monitor pending switch retries and terminal failures.
- `tests/test_tui_custom.py`, `tests/test_tui_dashboard.py`: key path sends preserved state, retries target with normalized state, and only commits after success.

### Task 1: Model supported normalization categories and target defaults

**Files:**
- Modify: `src/ccusage_viz/custom_metric_switching.py`
- Modify: `tests/test_custom_metric_switching.py`

**Interfaces:**

```python
SwitchNormalization = Literal["period", "group_by", "granularity", "filters", "top"]

def normalization_category(field: str) -> SwitchNormalization | None: ...

def normalize_switch_config(
    config: CustomChartConfig,
    target: V2MetricDescriptor,
    category: SwitchNormalization,
) -> CustomChartConfig | None: ...
```

`None` means the target has no changing default for that category. `filters` uses `defaults.<kind>.filters` or `()`.

- [ ] **Step 1: Write failing pure helper tests**

```python
def test_normalizes_target_period_and_filter_fields_from_metric_defaults() -> None:
    target = metric_with_defaults(ranking={"period": "all", "filters": (("kind", ("tool",)),)})
    current = config(period="7d", filters=(("language", ("python",)),))

    assert normalization_category("range.period") == "period"
    assert normalize_switch_config(current, target, "period").date_range.period == "all"
    assert normalization_category("query.filters.language") == "filters"
    assert normalize_switch_config(current, target, "filters").filters == (("kind", ("tool",)),)


def test_unknown_or_unchanged_default_does_not_normalize() -> None:
    target = metric_with_defaults(ranking={"period": "7d"})
    current = config(period="7d")

    assert normalization_category("query.combination") is None
    assert normalize_switch_config(current, target, "period") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_metric_switching.py -k normalization -v`

Expected: FAIL because no normalization helper exists.

- [ ] **Step 3: Implement pure category/default helpers**

Map exact documented fields; map every `query.filters` prefix to `filters`. Resolve the target chart default by `config.kind`. Use `replace()` for only that field. For a missing period/group/granularity/top default, return `None`; for filters use `()` when missing. Return `None` if the replacement equals current config. Delete `MetricSwitchRejection` and `validate_metric_switch`, along with their obsolete static-rejection tests.

- [ ] **Step 4: Run helper tests**

Run: `uv run pytest tests/test_custom_metric_switching.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_metric_switching.py tests/test_custom_metric_switching.py
git commit -m "feat: normalize related metric switch defaults"
```

### Task 2: Preserve and retry pending historical switches

**Files:**
- Modify: `src/ccusage_viz/custom_component.py`
- Modify: `tests/test_custom_component.py`

**Interfaces:**
- Extend the pending target state with `normalized_categories: frozenset[SwitchNormalization]`.
- Produce: `retry_metric_switch(field: str, target: V2MetricDescriptor) -> bool` that updates `request_config`, increments generation, and leaves committed facts untouched.

- [ ] **Step 1: Write failing historical retry tests**

```python
def test_historical_switch_retries_unsupported_period_with_target_default() -> None:
    component = accepted_component(metric_id="star_growth", period="7d")
    component.begin_metric_switch(config(metric_id="last_updated", period="7d"))

    assert component.retry_metric_switch("range.period", target_metric(default_period="all"))
    assert component.candidate.metric_id == "star_growth"
    assert component.request_config.metric_id == "last_updated"
    assert component.request_config.date_range.period == "all"


def test_historical_switch_does_not_retry_same_category_twice() -> None:
    component = pending_switch_component()
    assert component.retry_metric_switch("range.period", target_metric(default_period="all"))
    assert not component.retry_metric_switch("range.period", target_metric(default_period="all"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_component.py -k 'retry_metric_switch' -v`

Expected: FAIL because no retry API exists.

- [ ] **Step 3: Implement retry state and generation safety**

Store the category set with the pending target. `retry_metric_switch` succeeds only while a target is pending, its category is recognized and unvisited, and the pure helper yields a changed config. Replace pending target config, add the category, increment generation, clear only pending/comparison request bookkeeping, and leave accepted historical facts, presentation, config, and persisted Metric unchanged. A final success commits normalized target config through the existing transaction. Any terminal failure follows existing pending-switch rollback.

- [ ] **Step 4: Run full historical component tests**

Run: `uv run pytest tests/test_custom_component.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_component.py tests/test_custom_component.py
git commit -m "feat: retry normalized historical metric switches"
```

### Task 3: Preserve and retry pending Monitor switches

**Files:**
- Modify: `src/ccusage_viz/custom_monitor_component.py`
- Modify: `tests/test_custom_monitor_component.py`

**Interfaces:**
- Produce the same `retry_metric_switch(field: str, target: V2MetricDescriptor) -> bool` semantics as Task 2.

- [ ] **Step 1: Write failing Monitor retry tests**

```python
def test_monitor_switch_retries_filter_error_by_resetting_all_filters() -> None:
    component = accepted_monitor(metric_id="star_growth", filters=(("language", ("python",)),))
    component.begin_metric_switch(config(metric_id="last_updated", filters=(("language", ("python",)),)))

    assert component.retry_metric_switch("query.filters.language", target_metric(default_filters=()))
    assert component.candidate.metric_id == "star_growth"
    assert component.request_config.filters == ()


def test_monitor_switch_keeps_old_history_when_normalization_cannot_continue() -> None:
    component = pending_monitor_switch_with_history()
    old_history = component.history

    assert not component.retry_metric_switch("query.unknown", target_metric())
    assert component.history is old_history
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_monitor_component.py -k 'retry_metric_switch' -v`

Expected: FAIL because Monitor has no retry state.

- [ ] **Step 3: Implement Monitor retry state**

Mirror Task 2 using the pending target config, while retaining old Monitor observations and baseline until final target success. A retry gets a new generation but must not clear old history. Existing first accepted target observation commits and clears old sampling state exactly once.

- [ ] **Step 4: Run full Monitor tests**

Run: `uv run pytest tests/test_custom_monitor_component.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_monitor_component.py tests/test_custom_monitor_component.py
git commit -m "feat: retry normalized custom monitor switches"
```

### Task 4: Route target `unsupported_query` failures to retries in the TUI

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Modify: `tests/test_tui_custom.py`
- Modify: `tests/test_tui_dashboard.py`

**Interfaces:**
- TUI consumes typed Dataset failures with `code == "unsupported_query"` and a structured unsupported `field`.
- TUI calls component retry only for pending `m/M` target switches, then schedules the same pane's normal configuration request.

- [ ] **Step 1: Write failing integration tests**

```python
def test_m_switch_retries_target_period_from_dataset_unsupported_field(dashboard) -> None:
    pane = accepted_grouped_ranking(dashboard, metric="star_growth", period="7d")
    dashboard.press("m")
    dashboard.complete_custom_error(code="unsupported_query", field="range.period", value="7d")

    assert sent_metric_ids(dashboard) == ["last_updated", "last_updated"]
    assert sent_periods(dashboard) == ["7d", "all"]
    assert pane.component.candidate.metric_id == "star_growth"

    dashboard.complete_custom_chart(metric_id="last_updated", period="all")
    assert pane.component.candidate.metric_id == "last_updated"


def test_m_switch_filter_unsupported_resets_entire_filter_state(dashboard) -> None:
    pane = accepted_grouped_ranking(dashboard, filters=(("language", ("python",)),))
    dashboard.press("m")
    dashboard.complete_custom_error(code="unsupported_query", field="query.filters.language")

    assert sent_filters(dashboard)[-1] == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'switch.*unsupported or normalization' -v`

Expected: FAIL because TUI currently rolls back every target error.

- [ ] **Step 3: Remove static rejection from the `m/M` branch**

Keep only same-Group/current-kind candidate lookup. Do not call `validate_metric_switch`. Begin a target switch with the preserved current config and submit it immediately.

- [ ] **Step 4: Recognize structured target errors and schedule retries**

At the Custom completion error path, inspect the typed failure. If and only if the component has a pending Metric switch and the error is `unsupported_query` with a field, locate the target Metric in its pending/current V2 descriptor, call `retry_metric_switch`, and invoke existing `refresh(... CONFIGURATION, data_affecting=False)`. Do not log or show a terminal error for an accepted retry. If retry returns false, retain normal terminal failure behavior and leave old Metric selected.

Add localized success feedback that names every normalized category committed (`period`, `group`, `granularity`, `filters`, `top`). Show it only after target success.

- [ ] **Step 5: Run focused TUI tests**

Run: `uv run pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'switch.*unsupported or normalization or metric_switch' -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_custom.py tests/test_tui_dashboard.py
git commit -m "feat: retry normalized related metric switches"
```

### Task 5: Document Dataset error fields and normalization behavior

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`

- [ ] **Step 1: Document structured unsupported fields**

Explain that Dataset authors return one precise `unsupported.field` at a time. List the supported switch-normalization fields and state that any `query.filters` prefix resets the entire host filter state to the target Metric defaults or empty selection.

- [ ] **Step 2: Explain scope and safety**

State that normalization is only for in-pane related-Metric `m/M` switching, preserves state first, retries each category once, and commits only after target success. Ordinary user controls remain strict and must receive normal Dataset errors.

- [ ] **Step 3: Commit**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md docs/dataset-developer-guide.md docs/dataset-developer-guide.zh-CN.md
git commit -m "docs: explain metric switch normalization"
```

### Task 6: Final verification

- [ ] **Step 1: Run relevant tests**

Run: `uv run pytest tests/test_custom_metric_switching.py tests/test_custom_component.py tests/test_custom_monitor_component.py tests/test_tui_custom.py tests/test_tui_dashboard.py -q`

Expected: PASS, except document unrelated pre-existing Dashboard test failures separately rather than altering this feature.

- [ ] **Step 2: Run lint and inspect state**

Run: `uv run ruff check src tests && git diff --check && git status --short`

Expected: PASS with a clean intended working tree.
