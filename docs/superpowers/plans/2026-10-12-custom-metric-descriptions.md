# Custom Metric Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each V2 Custom Metric’s existing localized description in the tree-style Metric chooser and in Dashboard help for an accepted Custom Pane.

**Architecture:** Keep the protocol and `V2MetricDescriptor` unchanged: its existing `title` and `description` remain the sole metadata source. Replace the chooser’s primitive `(label, metric-index)` rows with typed presentation rows so headings, selectable Metric titles, and nonselectable description children can render and navigate independently. Dashboard help derives its current-Metric node only from a Custom component’s accepted config and accepted V2 descriptor, so pending switches cannot change the help text.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing terminal width/style utilities, ccusage-viz localization.

**Spec:** `docs/superpowers/specs/2026-10-12-custom-metric-description-design.md`

## Global Constraints

- Do not add or alter any Custom command protocol field; reuse `metrics[].description` exactly.
- Restrict new UI behavior to V2 Custom Metric chooser and accepted Custom Dashboard Panes.
- Use `Translator` and `LocalizedText`; never hard-code English or Chinese UI copy.
- Preserve Metric declaration order, Group declaration order, original `metrics[]` index selection, and existing `j`/`k`/arrow/Enter behavior.
- Help must use `accepted_config.metric_id` and `v2_descriptor`, never candidate or pending Metric metadata.
- Keep V1 Custom panes, native panes, and panes without a usable accepted descriptor free of the current-Metric help section.
- Preserve pre-existing unrelated modifications in `docs/superpowers/specs/2026-10-12-custom-dataset-refresh-ownership-design.md`.

---

## File Structure

- `src/ccusage_viz/tui.py`: owns chooser presentation rows, tree/description rendering, selectable-index navigation, and Dashboard help-tree composition.
- `src/ccusage_viz/locales/en.py`: adds English label for the current-Metric help section.
- `src/ccusage_viz/locales/zh.py`: adds Chinese equivalent label.
- `tests/test_tui_custom.py`: unit tests for chooser row order/localization/navigation-facing metadata and Dashboard help integration assertions.
- `docs/custom-command-protocol.md`: documents existing V2 Metric description as host-presentable explanatory metadata.
- `docs/custom-command-protocol.zh-CN.md`: Chinese equivalent protocol guidance.

### Task 1: Model and render tree-style Metric chooser rows

**Files:**
- Modify: `src/ccusage_viz/tui.py:603-640, 8779-8802, 9019-9042`
- Modify: `tests/test_tui_custom.py:996-1032`

**Interfaces:**
- Consumes: `V2ProbeDescriptor.metrics`, `V2ProbeDescriptor.metric_groups`, `V2MetricDescriptor.title`, `V2MetricDescriptor.description`, and `Translator`.
- Produces: a module-local immutable `MetricChooserRow` with `text: str`, `metric_index: int | None`, and presentation kind sufficient to distinguish `group`, selectable `metric`, and nonselectable `description` rows.
- Produces: `_dataset_metric_chooser_rows(descriptor, translator) -> tuple[MetricChooserRow, ...]`; callers derive navigation only from rows whose `metric_index is not None`.

- [ ] **Step 1: Write failing chooser-row tests**

Replace the tuple expectations with assertions against the new row fields. Add a grouped English fixture whose descriptions differ from titles and assert this exact display sequence and original metric indices:

```python
rows = tui_module._dataset_metric_chooser_rows(descriptor, load_translator("en"))
assert [(row.kind, row.text, row.metric_index) for row in rows] == [
    ("group", "GitHub tools", None),
    ("metric", "├─ stars", 0),
    ("description", "│  └─ Dataset", None),
    ("metric", "└─ updated", 1),
    ("description", "   └─ Dataset", None),
    ("metric", "legacy", 2),
    ("description", "  └─ Dataset", None),
]
```

Use the actual description text from the fixture instead of `Dataset` if the fixture changes it. Add a flat-descriptor test asserting no group row is synthesized, while every Metric still gets one description row. Add a Chinese assertion proving title and description use `zh_cn`.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `uv run pytest tests/test_tui_custom.py -k dataset_metric_chooser -v`

Expected: FAIL because rows are still two-tuples and descriptions/tree presentation do not exist.

- [ ] **Step 3: Add the typed row and row builder**

Near `_custom_metric_periods`, add:

```python
@dataclass(frozen=True, slots=True)
class MetricChooserRow:
    kind: Literal["group", "metric", "description"]
    text: str
    metric_index: int | None = None
```

Rewrite `_dataset_metric_chooser_rows` to emit Group rows only for nonempty declared Groups, Group member Metric rows in declaration order, a description child immediately after each Metric, and ungrouped Metrics after all Groups. Build the `├─`/`└─` and continuation prefixes from whether a Metric is the Group’s last member; use the same Unicode/ASCII branch characters already used by `help_lines`, respecting `options.host.ascii` only at rendering time if that is the existing chooser convention. Keep ungrouped Metric titles and their descriptions consistently indented as a two-level tree without creating a fake Group.

Use `_dataset_title(metric.title, translator)` and `_dataset_title(metric.description, translator)` for every visible localized value.

- [ ] **Step 4: Render row kinds without turning non-Metric rows into choices**

In the modal `metric` rendering branch, construct the chooser body from `MetricChooserRow` values: only `kind == "metric"` receives `›` when it is selected; Group headings use the existing terminal emphasis/highlight helper; description rows use the Dashboard theme’s weak/dim text helper. Pass the full row sequence to `_chooser_viewport`, with `metric_row_index` still locating the selected Metric’s row. Do not assign a selection glyph to group or description rows.

In `handle_dataset_modal`, derive `selectable` from `row.metric_index is not None`; retain the existing cyclic selection and Enter behavior. Update all old tuple unpacking to the row attributes.

- [ ] **Step 5: Run focused tests to verify they pass**

Run: `uv run pytest tests/test_tui_custom.py -k dataset_metric_chooser -v`

Expected: PASS, including legacy-flat ordering and newly added descriptions.

- [ ] **Step 6: Commit the chooser deliverable**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_custom.py
git commit -m "feat: show custom metric descriptions in chooser"
```

### Task 2: Show the accepted Metric explanation in Dashboard help

**Files:**
- Modify: `src/ccusage_viz/tui.py:7061-7470`
- Modify: `src/ccusage_viz/locales/en.py:457-506`
- Modify: `src/ccusage_viz/locales/zh.py:450-530`
- Modify: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `TuiCustomPane.component.accepted_config`, `TuiCustomPane.component.v2_descriptor`, and `V2ProbeDescriptor.metrics`.
- Produces: a module-local helper `_accepted_custom_metric_help_node(pane: TuiCustomPane, translator: Translator) -> tuple[str, tuple[tuple[str, tuple[object, ...]], ...]] | None` (or equivalent typed tree node) that returns only the committed Metric title plus description.
- Consumes: the existing nested `tree_node()` helper in `dashboard_tui`’s `help_lines`; the returned node must use its existing wrapping/tree rendering rather than manual line wrapping.

- [ ] **Step 1: Write failing tests for accepted-only help metadata**

Add a focused unit test around the extracted helper using a `TuiCustomPane` fixture with a V2 descriptor containing two differently named/described Metrics. Assert the helper is exactly:

```python
assert node == (
    translator.text("status.tui_help_current_metric"),
    (("Stars", (("Total GitHub stars", ()),)),),
)
```

Set `accepted_config.metric_id = "stars"` and a candidate/pending config for the other Metric; assert the result remains `Stars`. Add parameterized negative cases where the component has no descriptor, has no accepted config, has a V1/non-V2 descriptor, or has an accepted metric ID absent from the descriptor, and assert `None`.

Add an integration-level Dashboard help assertion using the existing terminal/input harness: select a V2 Custom Pane, enter Pane adjustment, press `h`, and assert the rendered overlay includes the localized section label, accepted title, and description. Assert an otherwise equivalent V1 Custom Pane overlay does not contain the section label.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `uv run pytest tests/test_tui_custom.py -k 'metric_help or accepted_custom_metric' -v`

Expected: FAIL because the helper, localizations, and help-tree node are absent.

- [ ] **Step 3: Add localized section labels**

Add these keys beside the existing help section labels:

```python
# en.py
"status.tui_help_current_metric": "CURRENT METRIC",

# zh.py
"status.tui_help_current_metric": "当前指标",
```

Do not add localized copies for protocol-owned title or description values; those always come from `LocalizedText`.

- [ ] **Step 4: Add accepted-Metric lookup and compose it into Pane help**

Add a small module-level helper close to other Custom-Pane helpers. It must return `None` unless all conditions are true: `pane.component.accepted_config` exists, `metric_id` is non-`None`, `pane.component.v2_descriptor` is a `V2ProbeDescriptor`, and that descriptor contains the ID. It must select title/description via `_dataset_title` and return a parent node whose Metric title has the description as its child.

Within the `mode == "pane"` branch of `help_lines`, invoke the helper only for `TuiCustomPane`, then splice the non-`None` node into `control_nodes` alongside existing Pane settings/structure sections. Let the existing `tree_node()` and `wrap_width()` paths produce tree branches and multiline descriptions. Do not read `candidate`, `request_config`, pending switch target, cached Probe outside `v2_descriptor`, or a response that has not been accepted.

- [ ] **Step 5: Run focused tests to verify they pass**

Run: `uv run pytest tests/test_tui_custom.py -k 'metric_help or accepted_custom_metric' -v`

Expected: PASS for accepted V2, pending-switch stability, localization, and all omission cases.

- [ ] **Step 6: Run the related Dashboard help regression suite**

Run: `uv run pytest tests/test_tui_custom.py tests/test_tui_dashboard.py -k 'help or metric_chooser or metric_switch' -v`

Expected: PASS; V1/native help layout and metric switching behavior remain unchanged.

- [ ] **Step 7: Commit the help deliverable**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_tui_custom.py
git commit -m "feat: explain active custom metric in help"
```

### Task 3: Document the existing Metric description behavior and run validation

**Files:**
- Modify: `docs/custom-command-protocol.md:12-26`
- Modify: `docs/custom-command-protocol.zh-CN.md:12-26`
- Test: `tests/test_tui_custom.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: the V2 Metric descriptor’s existing required bilingual `description` field.
- Produces: English and Chinese author guidance that descriptions are localized Metric explanations hosts may show in Metric selection and current-Pane help, not request fields or returned facts.

- [ ] **Step 1: Add the English protocol guidance**

After the V2 Metric introduction in `docs/custom-command-protocol.md`, add a concise paragraph stating that every Metric’s existing bilingual `description` explains that Metric; hosts may show it below the title during Metric selection and in help for the currently selected Pane. State that it does not alter request shape, metric ID, aggregation, or data semantics.

- [ ] **Step 2: Add the Chinese protocol guidance**

Add the equivalent paragraph at the corresponding V2 section in `docs/custom-command-protocol.zh-CN.md`, using the project’s established terms “指标”, “指标选择”, and “当前 Pane 帮助”. State the same non-request/non-data constraint.

- [ ] **Step 3: Run documentation and localization validation**

Run: `uv run pytest tests/test_i18n.py tests/test_tui_custom.py -k 'i18n or dataset_metric_chooser or metric_help or accepted_custom_metric' -v && git diff --check`

Expected: PASS and no whitespace errors.

- [ ] **Step 4: Run the full relevant test suite**

Run: `uv run pytest tests/test_tui_custom.py tests/test_tui_dashboard.py tests/test_i18n.py -q`

Expected: PASS.

- [ ] **Step 5: Commit documentation and final validation deliverable**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md
git commit -m "docs: explain custom metric descriptions"
```

## Self-Review

- **Spec coverage:** Task 1 covers chooser hierarchy, descriptions, order, nonselectable rows, localization, selection mapping, and width-aware existing viewport behavior. Task 2 covers accepted-only current-Metric help, V1/native/unavailable omission, pending switch stability, tree wrapping, and localized section labels. Task 3 covers both protocol guides and final regression checks.
- **Placeholder scan:** No TODO/TBD/future-work placeholders are present; every implementation and test step names concrete files, symbols, assertions, and commands.
- **Type consistency:** `MetricChooserRow` is produced by `_dataset_metric_chooser_rows` and consumed by both modal rendering and input navigation. `_accepted_custom_metric_help_node` takes `TuiCustomPane` and returns the same nested node shape consumed by `tree_node`.
