# Dashboard Custom Metric Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put accepted Custom metric information in its own Dashboard-help section and accurately expose same-Group metric switching and empty parameter states.

**Architecture:** Keep accepted metric lookup as the authority for static help content, and add small helpers that distinguish a V2 metric belonging to a declared group from all other Custom configurations. Reuse the existing `m`/`M` switching path and `TransientFeedback`; only the action-bar/help eligibility changes, while its three-second notice remains the feedback mechanism.

**Tech Stack:** Python 3.13, pytest, existing Dashboard TUI help-tree renderer, `V2ProbeDescriptor`, `TransientFeedback`, existing `Translator` localization dictionaries.

**Spec:** `docs/superpowers/specs/2026-10-12-dashboard-custom-metric-help-design.md`

## Global Constraints

- Do not change Custom protocol fields, request shapes, persistence, or switch normalization rules.
- Help metadata must use accepted V2 descriptor plus accepted config only; candidate and pending switch metadata must not replace it.
- Show `m` / `M` only for a V2 Custom metric with a non-`None` group ID that corresponds to a declared descriptor group.
- Retain the existing `m` / `M` declaration-order, capability-filtered, wraparound switching semantics.
- When a grouped metric has fewer than two current-kind candidates, retain the existing localized `status.custom_metric_no_alternative` transient message for three seconds.
- Do not modify the pre-existing unrelated changes in `docs/superpowers/specs/2026-10-12-custom-dataset-refresh-ownership-design.md`.

---

## File Structure

- `src/ccusage_viz/tui.py`: determines Custom metric group eligibility for action controls/help; arranges Dashboard help sections; supplies nonempty parameter-help fallback.
- `src/ccusage_viz/locales/en.py`: English empty-parameter fallback text.
- `src/ccusage_viz/locales/zh.py`: Chinese empty-parameter fallback text.
- `tests/test_tui_custom.py`: focused unit and Dashboard integration coverage for grouped switching help, ordering, and localized empty state.
- `tests/test_i18n.py`: localization completeness expectation if it enumerates all `status.*` TUI keys.

### Task 1: Make Custom `m` / `M` controls accurately group-aware

**Files:**
- Modify: `src/ccusage_viz/tui.py:2800-2913, 9876-9946`
- Modify: `tests/test_tui_custom.py:590-620, 990-1020`

**Interfaces:**
- Consumes: `TuiCustomPane.component.accepted_config`, `TuiCustomPane.component.v2_descriptor`, `V2ProbeDescriptor.metrics`, and `V2ProbeDescriptor.metric_groups`.
- Produces: `_custom_metric_group_switch_available(pane: TuiCustomPane) -> bool`, which returns true only when the accepted V2 Metric exists, has `group_id`, and that ID is declared in `metric_groups`.
- Produces: `_custom_pane_adjustment_bindings()` output where `("m/M", "metric")` is included only if the helper returns true.

- [ ] **Step 1: Write failing binding tests**

Add these tests adjacent to the existing Custom adjustment-binding tests. Use `_accepted_metric_help_pane()` and replace its descriptor/accepted config as needed:

```python
def test_custom_grouped_metric_exposes_metric_switch_binding() -> None:
    pane = _accepted_metric_help_pane()
    descriptor = pane.component.v2_descriptor
    assert isinstance(descriptor, V2ProbeDescriptor)
    pane.component.v2_descriptor = replace(
        descriptor,
        metrics=(replace(descriptor.metrics[0], group_id="github"), *descriptor.metrics[1:]),
        metric_groups=(V2MetricGroup("github", LocalizedText("GitHub", "GitHub")),),
    )

    assert ("m/M", "metric") in tui_module._custom_pane_adjustment_bindings(pane, "quick")
```

Add a parameterized test whose descriptor has no groups, whose accepted Metric has `group_id=None`, and whose metric references an undeclared group. It must assert `("m/M", "metric") not in ...`. Import the existing `V2MetricGroup` model if it is not already imported by the test module.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest tests/test_tui_custom.py -k 'grouped_metric_exposes or ungrouped_metric_omits' -v`

Expected: FAIL because the current quick binding unconditionally starts with `("m/M", "metric")` for Custom historical charts.

- [ ] **Step 3: Add the accepted group-membership helper**

Near `_accepted_custom_metric_help_node`, add:

```python
def _custom_metric_group_switch_available(pane: TuiCustomPane) -> bool:
    accepted = pane.component.accepted_config
    descriptor = pane.component.v2_descriptor
    if accepted is None or accepted.metric_id is None or not isinstance(descriptor, V2ProbeDescriptor):
        return False
    metric = next((item for item in descriptor.metrics if item.id == accepted.metric_id), None)
    return metric is not None and metric.group_id is not None and any(
        group.id == metric.group_id for group in descriptor.metric_groups
    )
```

In each quick branch of `_custom_pane_adjustment_bindings` which currently places `("m/M", "metric")` in the initial action list, start without it and insert it only when `_custom_metric_group_switch_available(pane)` is true. Leave `cycle_switch_metric()` and the event-handler failure notice unchanged: when a declared group has just one compatible metric, the binding remains visible and `cycle_switch_metric()` returns `None`, triggering the existing feedback.

- [ ] **Step 4: Run the binding tests to verify they pass**

Run: `uv run pytest tests/test_tui_custom.py -k 'grouped_metric_exposes or ungrouped_metric_omits' -v`

Expected: PASS.

- [ ] **Step 5: Commit the group-aware control deliverable**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "fix: limit custom metric switch controls to groups"
```

### Task 2: Separate current Metric from controls and prevent empty parameter branches

**Files:**
- Modify: `src/ccusage_viz/tui.py:7480-7580`
- Modify: `src/ccusage_viz/locales/en.py:455-490`
- Modify: `src/ccusage_viz/locales/zh.py:455-490`
- Modify: `tests/test_tui_custom.py:760-875`
- Modify: `tests/test_i18n.py:115-135`

**Interfaces:**
- Consumes: `_accepted_custom_metric_help_node(pane, translator)`, `_custom_pane_adjustment_bindings(pane, page)`, and the existing nested Dashboard `help_lines()` tree renderer.
- Produces: Pane help section tuple where `(status.tui_help_current_metric, ...)` is a top-level section between Modes and Controls.
- Produces: localized `status.tui_help_pane_settings_empty` fallback as the only child of Pane parameter adjustment if `parameter_children` is empty.

- [ ] **Step 1: Write failing overlay ordering and content tests**

Extend `test_dashboard_help_overlay_shows_committed_localized_v2_metric_and_omits_v1` to strip ANSI, find the first line containing each heading, and assert:

```python
assert current_metric_index < controls_index
assert "Pane 参数调整" in v2_help
```

Create a grouped descriptor in the V2 fixture and assert the rendered help contains the existing localized metric-help description, whose `m/M` text comes from `status.tui_help_parameter_metric`. For an ungrouped descriptor assert that this metric-switch text is absent.

Add a helper-level test that invokes `run_tui` with a `TuiCustomPane` in non-chart text view (where no chart or animation parameters are present), opens help, and asserts it contains `translator.text("status.tui_help_pane_settings_empty")` beneath the parameter heading.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `uv run pytest tests/test_tui_custom.py -k 'dashboard_help_overlay or pane_settings_empty' -v`

Expected: FAIL because current Metric is currently nested in Controls after Pane parameter adjustment, Custom parameter help is absent, and empty branches have no child text.

- [ ] **Step 3: Add localization keys and localization assertion**

Add beside `status.tui_help_pane_settings`:

```python
# src/ccusage_viz/locales/en.py
"status.tui_help_pane_settings_empty": "No parameters are available for this Pane",

# src/ccusage_viz/locales/zh.py
"status.tui_help_pane_settings_empty": "当前 Pane 没有可调整参数",
```

Add an exact expected-key/value assertion in `tests/test_i18n.py` following its current help-key assertions.

- [ ] **Step 4: Restructure Dashboard pane help**

In the `mode == "pane"` branch of `help_lines()`:

1. Build `current_metric_node` exactly as now using `_accepted_custom_metric_help_node`; do not use candidate state.
2. For `TuiCustomPane` in chart view, derive parameter help from `_custom_pane_adjustment_bindings(focused_pane, "quick")` and `("advanced")`, converting each binding with the project’s existing `AdjustmentAction` localization pathway or an equivalent `m/M` help action. This must render the metric action only when Task 1’s bindings expose it.
3. After all chart, Custom, and animation cases, if `parameter_children` is empty, append `(translator.text("status.tui_help_pane_settings_empty"), ())`.
4. Remove `current_metric_node` from `control_nodes`.
5. Construct `sections` as Modes, optional `("status.tui_help_current_metric", children)`, Controls, then existing policy/tip sections. Preserve the current metric node children exactly; only promote its heading to the outer section heading.

Do not add a synthetic Metric section when `_accepted_custom_metric_help_node` returns `None`.

- [ ] **Step 5: Run focused tests to verify they pass**

Run: `uv run pytest tests/test_tui_custom.py -k 'dashboard_help_overlay or pane_settings_empty' -v && uv run pytest tests/test_i18n.py -q`

Expected: PASS; Chinese V2 help has Current Metric before 操作, only grouped V2 help describes `m/M`, and the fallback is localized.

- [ ] **Step 6: Commit the help-layout deliverable**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_custom.py tests/test_i18n.py
git commit -m "feat: clarify custom pane parameters in dashboard help"
```

### Task 3: Verify singleton-group feedback lifetime and regressions

**Files:**
- Modify: `tests/test_tui_custom.py`
- Test: `src/ccusage_viz/tui.py:9922-9946, 9425-9462`

**Interfaces:**
- Consumes: the existing event loop’s `copy_feedback: TransientFeedback` and the `cycle_switch_metric()` no-candidate result.
- Produces: integration coverage proving the visible grouped `m` action invokes the existing no-alternative localized transient notice and that the event loop repaints after its standard three-second expiry.

- [ ] **Step 1: Write the failing singleton-group feedback integration test**

Create a V2 Custom historical pane with one accepted Metric in a declared group and no other compatible current-kind metric. Drive Dashboard events `m`, `m`, then a timeout beyond `copy_feedback.expires_at` using the existing `_dashboard_help_frames`-style `FramePainter` and `read_event` monkeypatches. Assert a captured intermediate Dashboard frame includes:

```python
translator.text("status.custom_metric_no_alternative")
```

Assert a later frame after the timeout excludes that exact message. Also assert the controls frame includes the `m/M` action before pressing the key.

- [ ] **Step 2: Run the focused test to verify it fails if the control eligibility or feedback path regresses**

Run: `uv run pytest tests/test_tui_custom.py -k singleton_group_metric_switch_feedback -v`

Expected: PASS after Tasks 1 and 2; if it fails, inspect the test harness timeout delivery and preserve the production event loop’s `copy_feedback.remaining()` scheduling rather than changing feedback duration.

- [ ] **Step 3: Run targeted behavioral regressions**

Run:

```bash
uv run pytest tests/test_tui_custom.py tests/test_custom_metric_switching.py tests/test_i18n.py -q
```

Expected: PASS. In particular, existing next/previous behavior, normalization, pending-switch accepted-help behavior, and V1 omission tests remain green.

- [ ] **Step 4: Check formatting and full relevant TUI suite**

Run:

```bash
git diff --check && uv run pytest tests/test_tui_custom.py tests/test_tui_input.py tests/test_tui_header.py tests/test_i18n.py -q
```

Expected: no whitespace errors and all tests pass.

- [ ] **Step 5: Commit validation coverage**

```bash
git add tests/test_tui_custom.py
git commit -m "test: cover grouped custom metric switch feedback"
```
