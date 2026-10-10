# Ranking Description Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Custom Dataset Ranking description visibility depend only on the selected density, with `d` and `D` cycling density forward and backward.

**Architecture:** Keep descriptions in Custom Ranking response projections, but calculate their visibility from `ChartPresentation.density` at the TUI boundary. Delete the transient override from standalone and Dashboard state, simplify renderer call paths, and keep legacy capability parsing only as ignored compatibility input.

**Tech Stack:** Python 3.11, pytest, terminal TUI, custom Dataset protocol documentation.

**Spec:** `docs/superpowers/specs/2026-10-09-ranking-description-density-design.md`

## Global Constraints

- `minimal`, `compact`, and `normal` hide Custom Ranking descriptions.
- `full` and `detailed` show returned Custom Ranking descriptions.
- `D` must only reverse density in standalone or Dashboard views; it is not a description control.
- Keep accepting legacy `descriptions_default` protocol input, but ignore it for rendering.
- Native Ranking and non-Ranking custom charts must retain current behavior.

---

### Task 1: Make Density The Sole Visibility Rule

**Files:**
- Modify: `src/ccusage_viz/tui.py:2393-2442`
- Modify: `tests/test_tui_custom.py:149-200`

**Interfaces:**
- Consumes: `CustomHistoricalComponent`, its accepted/candidate `CustomChartConfig`, and `ChartPresentation.density`.
- Produces: `_custom_descriptions_visible(component: CustomHistoricalComponent) -> bool` and `_custom_descriptions_available(component: CustomHistoricalComponent) -> bool`.

- [ ] **Step 1: Write the failing density matrix test**

Replace the override assertions with a parameterized test that configures the accepted Custom Ranking to each density and expects:

```python
@pytest.mark.parametrize(
    ("density", "visible"),
    (("minimal", False), ("compact", False), ("normal", False), ("full", True), ("detailed", True)),
)
def test_custom_ranking_description_visibility_follows_density(density: Density, visible: bool) -> None:
    component = described_ranking_component(density=density)
    assert _custom_descriptions_visible(component) is visible
```

Also assert `_custom_descriptions_available(component)` remains true for every density whenever the response has an entry description.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_tui_custom.py -k description_visibility -v`

Expected: FAIL because the existing helper takes an override and treats `normal` availability differently.

- [ ] **Step 3: Simplify TUI visibility helpers**

Change `_custom_descriptions_visible` to accept only `component`. It should return false unless the selected chart is a Custom Ranking with an accepted model that has at least one non-Other description, then return:

```python
return config.presentation.density in {"full", "detailed"}
```

Change `_custom_descriptions_available` to mean data availability only: Custom Ranking plus an accepted model containing at least one non-Other description. Do not gate availability on density.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/test_tui_custom.py -k description_visibility -v`

Expected: PASS.

- [ ] **Step 5: Commit the tested behavior**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "feat: tie ranking descriptions to density"
```

### Task 2: Remove The Description Toggle From TUI State And Commands

**Files:**
- Modify: `src/ccusage_viz/tui.py:412-430, 1802-1852, 1950-1968, 2510-2528, 4180-4243, 4424-4670, 4980-4995, 9140-9156`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: the density-only `_custom_descriptions_visible(component)` from Task 1.
- Produces: standalone and Dashboard Custom Ranking renders that pass no description override, and action lists containing no `D descriptions` entry.

- [ ] **Step 1: Write failing control and render-path tests**

Add one standalone and one Dashboard assertion that a described Custom Ranking's adjustment actions do not include `("D", "descriptions")`. Add a render assertion that `full` includes a returned description while `normal` does not, without passing a visibility argument.

```python
assert ("D", "descriptions") not in _custom_standalone_actions(component, translator)
assert "Release validation" not in normal_render.chart
assert "Release validation" in full_render.chart
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_tui_custom.py -k 'descriptions or standalone_actions or pane_adjustment' -v`

Expected: FAIL because `D` remains exposed and state/call sites still expect an override.

- [ ] **Step 3: Delete the secondary view state and key handling**

Remove `descriptions_visible` from the TUI pane and standalone runtime state. Remove every `D` action entry and both standalone/Dashboard `key == "D"` branches. Update custom render helpers and call sites so each invokes:

```python
descriptions_visible=_custom_descriptions_visible(component)
```

Do not change query configuration, refresh behavior, or Dashboard preset persistence.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/test_tui_custom.py -k 'descriptions or standalone_actions or pane_adjustment' -v`

Expected: PASS.

- [ ] **Step 5: Commit the interaction cleanup**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "refactor: remove ranking description toggle"
```

### Task 3: Preserve Protocol Compatibility Without A Presentation Default

**Files:**
- Modify: `src/ccusage_viz/custom_component.py:299-312`
- Modify: `src/ccusage_viz/configuration.py:175-190`
- Modify: `tests/test_custom_component.py`
- Modify: `tests/test_options.py`

**Interfaces:**
- Consumes: legacy `CustomChartCapability.descriptions_default` values from existing parsed descriptors.
- Produces: Custom configuration and component construction that do not use `descriptions_default` to choose description visibility.

- [ ] **Step 1: Write failing regression tests**

Create two otherwise identical described Custom Ranking capabilities, one with `descriptions_default="expanded"` and one with `"collapsed"`. For each, render at `full` and assert the description is visible; render at `normal` and assert it is hidden.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_custom_component.py tests/test_options.py -k descriptions_default -v`

Expected: FAIL if any configuration path still carries the capability default into presentation state.

- [ ] **Step 3: Remove capability-default consumption**

Delete only the code that copies `capability.descriptions_default` into custom configuration or component view state. Leave `CustomChartCapability.descriptions_default` and `custom_protocol.py` parsing intact so deployed Dataset descriptors remain valid.

- [ ] **Step 4: Run parser and compatibility tests**

Run: `pytest tests/test_custom_component.py tests/test_options.py tests/test_custom_protocol.py -k 'description or descriptions_default' -v`

Expected: PASS, including parser acceptance of both legacy values.

- [ ] **Step 5: Commit protocol compatibility cleanup**

```bash
git add src/ccusage_viz/custom_component.py src/ccusage_viz/configuration.py tests/test_custom_component.py tests/test_options.py
git commit -m "refactor: ignore ranking description defaults"
```

### Task 4: Update User And Dataset Documentation

**Files:**
- Modify: `docs/custom-command-protocol.md:90-100, 260-275`
- Modify: `docs/custom-command-protocol.zh-CN.md:40-50, 130-140`
- Modify: `docs/dataset-developer-guide.md:230-275`
- Modify: `docs/dataset-developer-guide.zh-CN.md:170-190`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: density-only rendering behavior and compatibility parsing from Tasks 1-3.
- Produces: no user-visible `D descriptions` help/copy; protocol documentation that treats the old capability field as accepted compatibility data rather than an active presentation control.

- [ ] **Step 1: Add a failing copy regression assertion**

Add or extend localization tests to assert no active TUI help/action text advertises a `D` description control. Keep unrelated localized uses of the word "description" intact.

- [ ] **Step 2: Run the focused localization test to verify it fails**

Run: `pytest tests/test_i18n.py -v`

Expected: FAIL while the old description-control help strings still exist.

- [ ] **Step 3: Update copy and bilingual documentation**

Remove the `D` control help strings. State that returned Ranking descriptions appear at `full` and `detailed`, and are hidden at `minimal`, `compact`, and `normal`. Describe `descriptions_default` as legacy-compatible and ignored for the view, or omit it from new Dataset examples while documenting its acceptance for compatibility.

- [ ] **Step 4: Run documentation and localization checks**

Run: `pytest tests/test_i18n.py -v && rg -n 'D.*descriptions|按 `D`|`D`.*说明|descriptions_default.*initial' docs src/ccusage_viz/locales`

Expected: pytest PASS; ripgrep finds only explicit legacy-compatibility wording and no active `D` interaction instructions.

- [ ] **Step 5: Commit the documentation**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md docs/dataset-developer-guide.md docs/dataset-developer-guide.zh-CN.md src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_i18n.py
git commit -m "docs: clarify ranking description density"
```

### Task 5: Run The Full Regression Suite

**Files:**
- Verify: `tests/test_tui_custom.py`
- Verify: `tests/test_custom_component.py`
- Verify: `tests/test_custom_protocol.py`
- Verify: `tests/test_render.py`
- Verify: `tests/test_i18n.py`

**Interfaces:**
- Consumes: the completed density-only implementation.
- Produces: verification that Custom Ranking rendering, searching, protocol compatibility, and localization all remain intact.

- [ ] **Step 1: Run the targeted regression suite**

Run:

```bash
pytest tests/test_tui_custom.py tests/test_custom_component.py tests/test_custom_protocol.py tests/test_render.py tests/test_options.py tests/test_i18n.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the project suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check && git diff --stat`

Expected: no whitespace errors and only scoped code, test, locale, and documentation changes.

- [ ] **Step 4: Commit any final test-only corrections**

```bash
git add -u
git commit -m "test: cover ranking description density"
```
