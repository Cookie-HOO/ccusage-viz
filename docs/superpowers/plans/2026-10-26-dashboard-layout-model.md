# Dashboard Layout Model Redesign Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Keep each task independently tested and committed; do not add compatibility shims for the removed layout model.

**Goal:** Replace Dashboard grid/named-layout concepts with an explicit `columns` plus leading `spotlight` topology, exposed consistently through CLI, presets, state, geometry, and a transactional live-preview TUI editor.

**Architecture:** One pure topology builder maps ordered Panes to N full-width leading spotlight rows followed by a fixed-column ordinary grid. `DashboardHostConfig`, history state, preset v2, command copy, and TUI accepted state share the same declarations. A separate TUI draft previews topology without mutating accepted state; existing band-weight controls continue to resize accepted layouts directly.

**Tech Stack:** Python 3.11+, frozen dataclasses, argparse, terminal TUI, pytest, Ruff, ty

**Spec:** `docs/superpowers/specs/2026-10-26-dashboard-layout-model-design.md`

## Global constraints

- This is deliberately breaking: delete old flags, fields, names, parser functions, wire schema, tests, and docs rather than translating them.
- Do not accept or migrate preset v1.
- Do not retain `grid`, nullable `layout`, `auto`, `R×C`, `spotlight-wide`, or `spotlight-wide2` on public or internal layout boundaries.
- `wide`, `narrow`, `all`, clock variants, and `single` remain complete presets only.
- Layout changes are presentation-only and must not refresh queries or reconstruct Pane components.
- Preserve direct `{`/`}` column sizing and `J`/`K` row sizing.
- Preserve four default placeholders for `dashboard --empty`; `columns` changes placement, not Pane count.
- Do not overwrite unrelated working-tree changes.

## File structure

- `src/ccusage_viz/dashboard_layout.py`: pure topology, geometry, weights, navigation, and hit testing.
- `src/ccusage_viz/options.py`, `src/ccusage_viz/dashboard.py`: shared host declaration and built-in preset defaults.
- `src/ccusage_viz/command_parsing/`, `src/ccusage_viz/cli/configuration.py`: new CLI flags, explicit override semantics, final topology validation.
- `src/ccusage_viz/presets/`, `src/ccusage_viz/dashboard_state.py`, `src/ccusage_viz/command_copy.py`: v2 persistence, history declaration, and reproducible command serialization.
- `src/ccusage_viz/tui/`: accepted state, Pane lifecycle reconciliation, geometry, transactional topology editor, controls, and help.
- `src/ccusage_viz/locales/`, public docs: new terminology and removal of old layout surfaces.

---

### Task 1: Replace named/fixed layouts with the parameterized topology kernel

**Files:**
- Modify: `src/ccusage_viz/dashboard_layout.py`
- Rewrite focused expectations: `tests/test_dashboard_layout.py`
- Modify geometry/navigation expectations: `tests/tui/test_layout.py`

**Interfaces:**
- Produces: `layout_bands(*, columns, spotlight, pane_count) -> LayoutBands`
- Produces: `resolve_pane_layout(*, columns, spotlight, pane_count, width, height, ...) -> PaneLayout`
- Retains: `PaneSlot`, `PaneTopology`, `PaneRect`, weight normalization/adjustment, hit testing, and directional navigation.
- Removes: `NAMED_LAYOUTS`, `RenderedLayout`, `parse_grid`, `parse_layout`, `fixed_shape`, `layout_for_pane_count`, `_auto_shape`, and all configured/rendered layout strings.

- [ ] **Step 1: Rewrite pure topology tests first**

Replace parser/named-layout tests with parameterized topology tests covering:

```python
@pytest.mark.parametrize(
    ("pane_count", "columns", "spotlight", "rows", "slots"),
    [
        (1, 1, 0, 1, ((0, 0, 1),)),
        (5, 3, 0, 2, ((0, 0, 1), (0, 1, 1), (0, 2, 1), (1, 0, 1), (1, 1, 1))),
        (5, 3, 2, 3, ((0, 0, 3), (1, 0, 3), (2, 0, 1), (2, 1, 1), (2, 2, 1))),
        (3, 4, 3, 3, ((0, 0, 4), (1, 0, 4), (2, 0, 4))),
    ],
)
def test_parameterized_topology(...): ...
```

Also assert:

- incomplete last-row cells remain empty and preserve logical columns;
- one/all/zero spotlight boundaries;
- invalid columns, spotlight, and Pane counts fail;
- full-width spotlight geometry spans internal column gutters;
- weights, minimum dimensions, impossible axes, hit testing, and vertical navigation still work.

- [ ] **Step 2: Run the focused tests and verify the old API fails**

Run:

```bash
uv run pytest -o addopts='' tests/test_dashboard_layout.py tests/tui/test_layout.py -q
```

Expected: FAIL because production still accepts layout names and `R×C` strings.

- [ ] **Step 3: Implement one topology builder**

Change `PaneLayout` to hold resolved geometry without configured/rendered names. Validate `pane_count >= 1`, `columns >= 1`, and `0 <= spotlight <= pane_count`. Build spotlight slots with `column_span=columns`; build ordinary slots from offset `spotlight` with row `spotlight + ordinary_index // columns` and column `ordinary_index % columns`.

Make `layout_bands` and `resolve_pane_layout` consume integer declarations directly. Keep allocation and geometry code generic. Remove every old parser and topology branch rather than wrapping it.

- [ ] **Step 4: Run pure layout tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_dashboard_layout.py tests/tui/test_layout.py -q
```

Expected: PASS for the updated pure/geometry tests; TUI integration tests that still construct old session fields may remain for later tasks only if excluded into clearly identified cases.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/dashboard_layout.py tests/test_dashboard_layout.py tests/tui/test_layout.py
git commit -m "refactor: parameterize dashboard topology"
```

---

### Task 2: Replace CLI configuration and built-in preset layout declarations

**Files:**
- Modify: `src/ccusage_viz/options.py`
- Modify: `src/ccusage_viz/dashboard.py`
- Modify: `src/ccusage_viz/command_parsing/parser.py`
- Modify: `src/ccusage_viz/command_parsing/common.py`
- Modify: `src/ccusage_viz/chart_configuration.py`
- Modify: `src/ccusage_viz/cli/configuration.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/cli/test_parser.py`
- Test: `tests/cli/test_configuration.py`
- Test: `tests/cli/test_launch_options.py`
- Test: `tests/cli/test_panes.py`
- Test: `tests/cli/test_presets.py`
- Test as affected: `tests/test_application.py`

**Interfaces:**
- `DashboardHostConfig.columns: int = 2`
- `DashboardHostConfig.spotlight: int = 0`
- `DashboardPreset.columns`, `DashboardPreset.spotlight`
- CLI: `--columns C`, `--spotlight N`, repeated hidden/public weight flags as currently intended.

- [ ] **Step 1: Add failing parser and materialization tests**

Assert:

- new flags parse and enter explicit-option tracking;
- `--grid` and `--layout` are unknown arguments;
- positive columns and bounded spotlight validate against final Pane count;
- weight count validation uses resolved columns/rows;
- explicit topology overrides preset topology;
- inherited incompatible preset weights clear to `None`, while explicit bad weights fail;
- layout options still require a preset, `--pane`, or `--empty` when no default Dashboard is otherwise requested;
- `dashboard --empty` still creates four placeholders regardless of `columns`;
- `spotlight-wide` and `spotlight-wide2` are unknown presets;
- all six retained built-ins have exact topology and weight defaults from the spec.

- [ ] **Step 2: Run CLI tests to verify failures**

Run:

```bash
uv run pytest -o addopts='' tests/cli/test_parser.py tests/cli/test_configuration.py tests/cli/test_launch_options.py tests/cli/test_panes.py tests/cli/test_presets.py tests/test_application.py -q
```

Expected: FAIL on missing new fields/flags and retained old presets.

- [ ] **Step 3: Change declarations and built-ins**

Delete `grid` and `layout` from host and built-in preset dataclasses. Add `columns` and `spotlight`. Convert defaults exactly:

```text
wide 2/0, narrow 1/0, all 2/0,
wide-clock 2/1, narrow-clock 1/0, single 1/0
```

Retain the current Pane command fragments and presentation/cadence settings. Keep valid row weights for clock presets. Delete both spotlight-named preset records.

- [ ] **Step 4: Replace parser and launch assembly**

Delete old arguments/imports/combination errors. Add typed arguments with localization. Assemble final Pane fragments first, then resolve effective preset/explicit `columns` and `spotlight`, validate topology, derive row count, and validate weights.

Treat preset weights as inherited: retain an inherited axis only if its length matches the final axis. Treat CLI weights as explicit: reject non-positive values or wrong counts. Normalize retained explicit/inherited weights as before.

For `--empty`, preserve the current target of four initial Panes and fill after explicit `--pane` fragments; never infer Pane count from columns or spotlight.

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest -o addopts='' tests/cli/test_parser.py tests/cli/test_configuration.py tests/cli/test_launch_options.py tests/cli/test_panes.py tests/cli/test_presets.py tests/test_application.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/options.py src/ccusage_viz/dashboard.py src/ccusage_viz/command_parsing/parser.py src/ccusage_viz/command_parsing/common.py src/ccusage_viz/chart_configuration.py src/ccusage_viz/cli/configuration.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/cli tests/test_application.py
git commit -m "refactor: expose dashboard topology parameters"
```

---

### Task 3: Upgrade presets, immutable state, and command copying

**Files:**
- Modify: `src/ccusage_viz/dashboard_state.py`
- Modify: `src/ccusage_viz/presets/document.py`
- Modify: `src/ccusage_viz/presets/values.py`
- Modify: `src/ccusage_viz/presets/materialize.py` if field plumbing requires it
- Modify: `src/ccusage_viz/command_copy.py`
- Modify: `src/ccusage_viz/tui/history.py` for record construction/materialization and command formatting only
- Test: `tests/test_dashboard_state.py`
- Test: `tests/test_dashboard_preset_store.py`
- Test: `tests/test_tui_preset_manager.py`
- Test: `tests/tui/test_dashboard_command_views.py`
- Test: `tests/tui/test_dashboard_help_overlays.py` where preset materialization is asserted

**Interfaces:**
- Preset collection schema: `ccuv.dashboard-presets/v2`
- Host wire fields: `columns`, `spotlight`, `column_weights`, `row_weights`
- Full command formatting accepts runtime topology overrides as integers.

- [ ] **Step 1: Add failing state, wire, and command round-trip tests**

Assert:

- immutable state contains `columns`/`spotlight` and no old fields;
- v2 host wire round-trips topology and exact weights;
- v1 documents fail as unsupported schema;
- v2 host objects containing `grid`/`layout` fail strict-field validation;
- save/list/get/materialize preserve topology;
- full copied commands contain `--columns` and `--spotlight`, contain no old flags, and reparse identically;
- preset manager save/apply captures the current topology.

- [ ] **Step 2: Run persistence/command tests to verify failures**

Run:

```bash
uv run pytest -o addopts='' tests/test_dashboard_state.py tests/test_dashboard_preset_store.py tests/test_tui_preset_manager.py tests/tui/test_dashboard_command_views.py tests/tui/test_dashboard_help_overlays.py -q
```

Expected: FAIL on v1/old host fields and old command output.

- [ ] **Step 3: Change strict wire schema and state**

Set `PRESET_SCHEMA` to v2. Replace host wire keys and strict parser fields. Validate topology against Pane count before weight lengths. Change `DashboardState` and all record construction/materialization in this task to new integer fields.

Do not implement v1 parsing or migration. Preserve the store's existing corrupt/unsupported error boundaries and private atomic writes.

- [ ] **Step 4: Change command serialization**

Replace runtime `grid`/`layout` parameters with `columns`/`spotlight`. Always serialize enough topology state to reproduce the runtime Dashboard, followed by repeated weight flags when set. Update explicit-option/config maps that support command formatting.

- [ ] **Step 5: Run persistence and round-trip tests**

Run:

```bash
uv run pytest -o addopts='' tests/test_dashboard_state.py tests/test_dashboard_preset_store.py tests/test_tui_preset_manager.py tests/tui/test_dashboard_command_views.py tests/tui/test_dashboard_help_overlays.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/dashboard_state.py src/ccusage_viz/presets src/ccusage_viz/command_copy.py src/ccusage_viz/tui/history.py tests/test_dashboard_state.py tests/test_dashboard_preset_store.py tests/test_tui_preset_manager.py tests/tui/test_dashboard_command_views.py tests/tui/test_dashboard_help_overlays.py
git commit -m "refactor: persist dashboard topology v2"
```

---

### Task 4: Convert accepted TUI state, rendering, history, and Pane lifecycle

**Files:**
- Modify: `src/ccusage_viz/tui/session.py`
- Modify: `src/ccusage_viz/tui/painting.py`
- Modify: `src/ccusage_viz/tui/history.py`
- Modify: `src/ccusage_viz/tui/pane_events.py`
- Modify: `src/ccusage_viz/tui/datasets/modal.py`
- Modify as needed: `src/ccusage_viz/tui/layout.py`
- Test: `tests/tui/test_layout.py`
- Test: `tests/tui/test_dashboard_pane_lifecycle.py`
- Test: `tests/tui/test_dashboard_dataset_navigation.py`
- Test: `tests/tui/test_dashboard_structural_events.py`
- Test: `tests/test_dashboard_history.py`

**Interfaces:**
- Accepted session state: `columns`, `spotlight`, `column_weights`, `row_weights`
- A shared topology-reconciliation helper applies per-axis weight reset rules after Pane count/topology changes.

- [ ] **Step 1: Add failing accepted-state and lifecycle tests**

Cover:

- geometry reads accepted integer fields;
- state capture/apply and undo/redo restore topology and weights without query work;
- insertion reflows without changing columns/spotlight;
- deletion clamps spotlight to Pane count;
- reorder changes which Pane IDs occupy spotlight slots without changing topology values;
- changing Pane count resets only an axis whose band count changed;
- direct ordinary row/column resizing still records history;
- spotlight row resizing works, while spotlight column resizing is a no-op;
- dataset insertion follows the same reconciliation path.

- [ ] **Step 2: Run TUI state/lifecycle tests to verify failures**

Run:

```bash
uv run pytest -o addopts='' tests/tui/test_layout.py tests/tui/test_dashboard_pane_lifecycle.py tests/tui/test_dashboard_dataset_navigation.py tests/tui/test_dashboard_structural_events.py tests/test_dashboard_history.py -q
```

Expected: FAIL because session/lifecycle still mutate grid strings.

- [ ] **Step 3: Replace accepted state and geometry plumbing**

Initialize session integers from host config. Make `grid_geometry` and direct sizing call the new pure resolver. Replace every accepted-state capture/apply/full-command call with integer topology fields.

Introduce one narrow helper that compares old/new `LayoutBands`, clamps spotlight when Pane count shrinks, resets `column_weights` only when column count changes, and resets `row_weights` only when row count changes. Invoke it inside every Pane insert/delete boundary before history captures the final state. Reorder needs no band reconciliation.

Delete `_grid_for_pane_count` and old string mutation. Keep runtime rendering degradation and exact geometry behavior.

- [ ] **Step 4: Run TUI state/lifecycle tests**

Run:

```bash
uv run pytest -o addopts='' tests/tui/test_layout.py tests/tui/test_dashboard_pane_lifecycle.py tests/tui/test_dashboard_dataset_navigation.py tests/tui/test_dashboard_structural_events.py tests/test_dashboard_history.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/tui/session.py src/ccusage_viz/tui/painting.py src/ccusage_viz/tui/history.py src/ccusage_viz/tui/pane_events.py src/ccusage_viz/tui/datasets/modal.py src/ccusage_viz/tui/layout.py tests/tui/test_layout.py tests/tui/test_dashboard_pane_lifecycle.py tests/tui/test_dashboard_dataset_navigation.py tests/tui/test_dashboard_structural_events.py tests/test_dashboard_history.py
git commit -m "refactor: adopt dashboard topology state in tui"
```

---

### Task 5: Build the transactional live-preview topology editor

**Files:**
- Modify: `src/ccusage_viz/tui/session.py`
- Modify: `src/ccusage_viz/tui/adjustments.py`
- Modify: `src/ccusage_viz/tui/dashboard_events.py`
- Modify: `src/ccusage_viz/tui/events.py`
- Modify: `src/ccusage_viz/tui/input.py`
- Modify: `src/ccusage_viz/tui/help.py`
- Modify: `src/ccusage_viz/tui/painting.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/tui/test_layout.py`
- Test: `tests/tui/test_dashboard_structural_events.py`
- Test: `tests/tui/test_dashboard_rendering.py` if preview geometry needs an integration assertion
- Test: `tests/tui/test_dashboard_help_overlays.py`

**Interfaces:**
- Add a focused draft dataclass such as:

```python
@dataclass(slots=True)
class LayoutDraft:
    columns: int
    spotlight: int
    selected: Literal["spotlight", "columns"] = "spotlight"
```

- Preview geometry selects draft topology and axis-compatible accepted weights without changing accepted session fields.

- [ ] **Step 1: Replace chooser/text-entry tests with editor behavior tests**

Assert:

- `z` opens a draft copied from accepted values;
- Up/Down and `k`/`j` select fields; Tab cycles them;
- Left/Right and `-`/`+` adjust without wrapping;
- TUI boundaries are spotlight `0..pane_count` and columns `1..pane_count`;
- paint/geometry immediately uses draft values;
- preview uses equal weights only on axes whose draft band count differs;
- preview does not mutate accepted fields, history, presets, queries, or lifecycle generations;
- Enter records topology plus required weight resets as one mutation;
- unchanged Enter creates no history entry;
- Escape and adjustment timeout cancel exactly;
- undo/redo treats the commit as one operation;
- old chooser, `Z`, and `R×C` input no longer respond or render;
- help/footer text shows editor state and controls in both languages.

- [ ] **Step 2: Run editor tests to verify failures**

Run:

```bash
uv run pytest -o addopts='' tests/tui/test_layout.py tests/tui/test_dashboard_structural_events.py tests/tui/test_dashboard_rendering.py tests/tui/test_dashboard_help_overlays.py -q
```

Expected: FAIL because `z` still opens the old layout chooser and `Z` starts text input.

- [ ] **Step 3: Implement the draft and event reducer**

Delete `_LAYOUT_SHORTCUTS`, shortcut values/capacity helpers, `_choose_layout_shortcut`, `grid_draft`, and `grid_error`. Make `z` create the draft. Give active modal/editor handling precedence over global adjustment keys, consume all topology-edit keys, and route timeout/Escape through one cancellation helper.

On Enter, compute accepted and candidate bands, apply integer values and only necessary axis resets inside one `record_mutation` call, then close the draft. Do not trigger query refresh.

- [ ] **Step 4: Render live preview and controls**

Make geometry resolve through a small effective-topology/effective-weights helper. Accepted state remains untouched during preview. Render the two vertical fields and localized control hints in the existing adjustment/footer composition, with the selected field visibly marked. Remove `Z` and all custom-grid prompt/error rendering.

- [ ] **Step 5: Run editor and regression tests**

Run:

```bash
uv run pytest -o addopts='' tests/tui/test_layout.py tests/tui/test_dashboard_structural_events.py tests/tui/test_dashboard_rendering.py tests/tui/test_dashboard_help_overlays.py tests/test_dashboard_history.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/tui/session.py src/ccusage_viz/tui/adjustments.py src/ccusage_viz/tui/dashboard_events.py src/ccusage_viz/tui/events.py src/ccusage_viz/tui/input.py src/ccusage_viz/tui/help.py src/ccusage_viz/tui/painting.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/tui/test_layout.py tests/tui/test_dashboard_structural_events.py tests/tui/test_dashboard_rendering.py tests/tui/test_dashboard_help_overlays.py tests/test_dashboard_history.py
git commit -m "feat: add transactional dashboard layout editor"
```

---

### Task 6: Remove stale terminology, update public docs, and verify the repository

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Modify: `docs/design-philosophy.md`
- Modify: `docs/design-philosophy.zh-CN.md`
- Modify as applicable: `docs/architecture.md`, `docs/architecture.zh-CN.md`
- Modify generated/source counterpart if required: `docs/assets/readme/README.md`
- Modify affected protocol/dataset docs only where they describe Dashboard host layout: `docs/custom-command-protocol*.md`, `docs/dataset-user-guide*.md`
- Modify tests only when stale assertions remain from Tasks 1-5.

**Interfaces:**
- Public terminology: presets, spotlight Pane count, Panes per row/columns, row/column sizing.
- No public old flags, layout names, or fixed-grid input remain.

- [ ] **Step 1: Search source/tests for removed implementation concepts**

Run:

```bash
rg -n 'active_grid|active_layout|grid_draft|grid_error|NAMED_LAYOUTS|RenderedLayout|parse_grid|parse_layout|fixed_shape|layout_for_pane_count|spotlight-wide|spotlight-wide2|--grid|--layout' src tests
```

Expected: no matches. Generic rendering uses of the English word `layout` are allowed; removed identifiers and public names are not.

Also inspect remaining field-level matches deliberately:

```bash
rg -n '\bgrid\b|\.layout\b|"layout"' src/ccusage_viz tests
```

Classify every match; remove only stale Dashboard topology concepts, not unrelated UI/render layout language.

- [ ] **Step 2: Update bilingual user and architecture docs**

Document:

- retained preset list and distinction from topology;
- CLI examples with `--columns` and `--spotlight`;
- `z` editor controls and live-preview transaction;
- direct `{`/`}` and `J`/`K` sizing;
- preset v2 breaking change where versioning/user guides discuss saved state.

Remove examples and prose for named layouts, fixed `R×C`, `--grid`, `--layout`, and deleted presets. Do not rewrite historical superpowers specs/plans; they are implementation history, except this plan/spec.

- [ ] **Step 3: Run static checks**

Run:

```bash
uv run ruff format --check src/ccusage_viz tests
uv run ruff check src/ccusage_viz tests
uv run ty check src/ccusage_viz
```

Expected: PASS, or only an already documented unrelated baseline diagnostic.

- [ ] **Step 4: Run focused Dashboard suite**

Run:

```bash
uv run pytest -o addopts='' \
  tests/test_dashboard_layout.py \
  tests/test_dashboard_state.py \
  tests/test_dashboard_history.py \
  tests/test_dashboard_preset_store.py \
  tests/test_tui_preset_manager.py \
  tests/cli/test_parser.py \
  tests/cli/test_configuration.py \
  tests/cli/test_launch_options.py \
  tests/cli/test_panes.py \
  tests/cli/test_presets.py \
  tests/tui/test_layout.py \
  tests/tui/test_dashboard_command_views.py \
  tests/tui/test_dashboard_pane_lifecycle.py \
  tests/tui/test_dashboard_dataset_navigation.py \
  tests/tui/test_dashboard_structural_events.py \
  tests/tui/test_dashboard_rendering.py \
  tests/tui/test_dashboard_help_overlays.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification and build**

Run:

```bash
uv run pytest -o addopts='' -q
uv build
git diff --check
git status --short
```

Expected: full suite and package build pass; no whitespace errors; only intended plan/execution changes remain.

- [ ] **Step 6: Commit docs and any verification fixes**

```bash
git add README.md README.zh-CN.md docs src tests
git commit -m "docs: describe flexible dashboard topology"
```

If verification required no source/test fix, keep this as a documentation-only commit. Do not create an empty commit.

## Final acceptance checklist

- [ ] No old Dashboard layout identifier, flag, preset, parser, or wire field remains in source/tests/public docs.
- [ ] `columns` and `spotlight` determine every topology consistently across CLI, TUI, history, command copy, and preset v2.
- [ ] All leading spotlight Panes span full width; remaining Panes use fixed user-selected columns.
- [ ] Topology preview is non-mutating and query-free; Enter commits once and Escape/timeout cancels.
- [ ] Pane lifecycle preserves topology intent and resets only dimensionally invalid weights.
- [ ] Direct row/column sizing still works with expected spotlight no-op behavior.
- [ ] Built-ins, empty Dashboard behavior, bilingual help, copied commands, and docs agree.
- [ ] Ruff, ty, full pytest, and package build pass.