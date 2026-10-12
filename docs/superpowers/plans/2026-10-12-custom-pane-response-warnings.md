# Custom Pane Response Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display custom Dataset warnings from successful historical chart responses in the owning Dashboard pane beneath the chart and above its controls.

**Architecture:** `CustomHistoricalComponent` retains the warnings from its accepted primary response, making their lifecycle identical to accepted chart facts. The custom Dashboard pane render path turns that state into `PaneRender.notices`, which the existing pane-local layout already places below the chart and before local controls.

**Tech Stack:** Python 3, dataclasses, pytest, existing terminal `PaneRender` layout.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-pane-response-warnings-design.md`

## Global Constraints

- Do not change Dataset protocol parsing or GitHub Tools warning generation.
- Only custom historical chart responses are in scope; probe, summary, and monitor warnings retain current behavior.
- Retain existing custom-log recording and its Dataset/code deduplication as diagnostic history.
- Never render a response warning in the Dashboard-global footer or a sibling pane.
- Select warning text using the active UI language and preserve wire order.

---

## File Structure

- Modify `src/ccusage_viz/custom_component.py`: retain accepted primary-response warnings in `CustomHistoricalComponent`.
- Modify `src/ccusage_viz/tui.py`: append component warnings as local `PaneRender.notices` for chart-body rendering only.
- Modify `tests/test_custom_component.py`: prove primary warning acceptance, replacement, clearing, and comparison isolation.
- Modify `tests/test_tui_custom.py`: prove a successful warning-bearing custom chart produces pane-local notices.

### Task 1: Retain accepted historical-response warnings

**Files:**
- Modify: `src/ccusage_viz/custom_component.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- Consumes: `CustomChartResponse.warnings: tuple[CustomProtocolWarning, ...]`.
- Produces: `CustomHistoricalComponent.accepted_warnings: tuple[CustomProtocolWarning, ...]`.
- Invariant: only a successfully accepted `purpose="primary"` completion updates `accepted_warnings`; an accepted warning-free primary response sets it to `()`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_primary_response_retains_its_protocol_warnings() -> None:
    component = CustomHistoricalComponent(config())
    warning = CustomProtocolWarning("coverage", LocalizedText("using 2d", "使用 2 天"))

    assert component.accept_response(response(warnings=(warning,)))
    assert component.accepted_warnings == (warning,)


def test_warning_free_primary_replacement_clears_accepted_warnings() -> None:
    component = CustomHistoricalComponent(config())
    assert component.accept_response(response(warnings=(warning,)))
    component.configure(replacement_config(), data_affecting=True)

    assert component.accept_response(response())
    assert component.accepted_warnings == ()
```

Add a comparison-response assertion that accepting `purpose="comparison"` does not replace the primary warning tuple.

- [ ] **Step 2: Run the new tests to verify failure**

Run: `uv run pytest tests/test_custom_component.py -k 'warning' -v`

Expected: FAIL because `accepted_warnings` does not exist.

- [ ] **Step 3: Add the accepted-warning state**

Add `accepted_warnings` to `CustomHistoricalComponent.__slots__`, initialize it to `()`, and update it in the primary branch of `apply_result` immediately when assigning `accepted_response`:

```python
self.accepted_response = completion.response
self.accepted_warnings = completion.response.warnings
```

Do not update this value in the comparison branch or in failure paths, so retained accepted facts retain their own warning semantics.

- [ ] **Step 4: Run the component suite**

Run: `uv run pytest tests/test_custom_component.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_component.py tests/test_custom_component.py
git commit -m "feat: retain custom chart response warnings"
```

### Task 2: Render accepted warnings as pane-local notices

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `CustomHistoricalComponent.accepted_warnings` from Task 1 and `Translator.language`.
- Produces: `PaneRender(chart, notices=...)` whose notices contain the active-language warning messages in response order.
- Invariant: notices are added only for the custom historical `chart` body, after a component has a model; command/data/error/pending views remain unchanged.

- [ ] **Step 1: Write a failing pane-render test**

Construct an accepted `CustomHistoricalComponent` with chart facts and two `CustomProtocolWarning` values, then call `_pane_render` for a `TuiCustomPane` at Dashboard size. Assert the rendered `chart` still contains the ranking facts and:

```python
assert rendered.notices == ("using 2d", "second notice")
```

Create the translator with English. Add a Chinese assertion using the same component that verifies `("使用 2 天", "第二条提示")`. Assert the warning text is not appended into `rendered.chart`, which ensures the layout treats it as pane-local notices rather than Dashboard-global content.

- [ ] **Step 2: Run the new test to verify failure**

Run: `uv run pytest tests/test_tui_custom.py -k 'response_warning' -v`

Expected: FAIL because custom chart rendering does not add accepted warnings to `PaneRender.notices`.

- [ ] **Step 3: Add a focused warning-to-notice helper and invoke it**

Near the other custom pane rendering helpers, add:

```python
def _custom_response_warning_notices(
    component: CustomHistoricalComponent, translator: Translator
) -> tuple[str, ...]:
    return tuple(
        warning.message.zh_cn if translator.language == "zh" else warning.message.en
        for warning in component.accepted_warnings
    )
```

In the successful custom historical chart branch of `_pane_render`, merge the helper result with existing local notices:

```python
return PaneRender(rendered.chart, (*rendered.notices, *_custom_response_warning_notices(component, translator)))
```

Preserve the existing error branch by merging the response warning notices with `format_error(...)`; this keeps currently accepted data warnings visible when a refresh fails after accepted data exists.

- [ ] **Step 4: Run focused rendering and regression suites**

Run: `uv run pytest tests/test_tui_custom.py tests/test_custom_component.py -q`

Expected: PASS.

- [ ] **Step 5: Run formatting/lint and complete test suite**

Run: `uv run ruff check src/ccusage_viz/custom_component.py src/ccusage_viz/tui.py tests/test_custom_component.py tests/test_tui_custom.py && uv run pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "feat: show dataset warnings in custom panes"
```

## Self-Review

- **Spec coverage:** Task 1 binds warnings to accepted primary historical facts, clears them on a warning-free replacement, and excludes comparison/stale/failure mutation. Task 2 localizes and renders every warning in wire order through existing pane notices, preserving logs and avoiding global/sibling display.
- **Placeholder scan:** no unresolved placeholders or deferred implementation steps.
- **Type consistency:** `accepted_warnings` is a tuple of `CustomProtocolWarning`; the Task 2 helper consumes that tuple and returns `tuple[str, ...]`, exactly matching `PaneRender.notices`.
