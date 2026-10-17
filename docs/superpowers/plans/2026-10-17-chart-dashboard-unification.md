# Chart Dashboard Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every `ccuv chart` invocation through a focused one-Pane Dashboard and remove standalone chart runtimes.

**Architecture:** Add a pure adapter that converts `StandaloneLaunch` to `DashboardLaunch` with a 1×1 focused host. Keep `run_tui` and all pre-existing Dashboard construction paths unchanged; `application.run` alone chooses the adapter for chart launches. Delete standalone-only runtime modules after their behavior is covered by Dashboard-path tests.

**Tech Stack:** Python 3.11+, pytest, argparse, terminal Dashboard runtime.

**Spec:** `docs/superpowers/specs/2026-10-17-chart-dashboard-unification-design.md`

## Global Constraints

- Existing `ccuv dashboard ...` behavior is unchanged.
- Generated chart hosts use `grid="1x1"`, `header_style="hidden"`, and `header_summary="none"`.
- Historical `--interval` maps only to `refresh_interval`; Monitor maps it only to `sampling_interval`.
- `animate`, including `--gallery`, remains an independent runtime.
- `--no-watch` is removed rather than emulated.

---

### Task 1: Create the focused chart-to-Dashboard adapter

**Files:**
- Modify: `src/ccusage_viz/configuration.py`
- Test: `tests/test_configuration.py` or existing configuration-focused test module

**Interfaces:**
- Consumes: `StandaloneLaunch`.
- Produces: `DashboardLaunch` with exactly one `ChartPaneConfig` or `CustomChartPaneConfig` matching the input chart.

- [ ] **Step 1: Write failing adapter tests**

Test builtin historical, Monitor, and Custom chart inputs. Assert the input chart becomes the only Pane, host grid is 1×1, header style is hidden, header summary is none, and cadence maps by chart kind.

- [ ] **Step 2: Run adapter tests and verify failure**

Run: `uv run pytest tests/test_configuration.py -v`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement the pure adapter**

Add `focused_dashboard_from_chart(launch: StandaloneLaunch) -> DashboardLaunch`. Copy process and explicit fields, construct the focused host from the standalone host, preserve the chart as a builtin or custom Pane, and only map the appropriate cadence field.

- [ ] **Step 4: Run adapter tests and verify pass**

Run: `uv run pytest tests/test_configuration.py -v`

Expected: PASS.

- [ ] **Step 5: Commit adapter and tests**

```bash
git add src/ccusage_viz/configuration.py tests/test_configuration.py
git commit -m "refactor: adapt charts to focused dashboards"
```

### Task 2: Route chart launches through Dashboard and remove standalone dispatch

**Files:**
- Modify: `src/ccusage_viz/application.py`
- Modify: `src/ccusage_viz/cli.py`
- Test: `tests/test_application.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: a parsed `StandaloneLaunch` from `chart KIND ...`.
- Produces: `run_tui(focused_dashboard_from_chart(options), translator)`.

- [ ] **Step 1: Write failing dispatch tests**

Mock `run_tui` and verify builtin historical, Monitor, and Custom chart launches reach it with a focused Dashboard. Verify an `AnimationLaunch` still invokes `run_animation`. Assert parsing `chart timeline --no-watch` fails.

- [ ] **Step 2: Run dispatch tests and verify failure**

Run: `uv run pytest tests/test_application.py tests/test_cli.py -v`

Expected: FAIL because chart launches retain standalone dispatch and `--no-watch` is still accepted.

- [ ] **Step 3: Implement dispatch and CLI removal**

Make `application.run` adapt all non-animation, non-Dashboard chart launches and invoke `run_tui`. Remove the hidden `--no-watch` parser argument and unused standalone-specific imports.

- [ ] **Step 4: Run focused tests and verify pass**

Run: `uv run pytest tests/test_application.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 5: Commit dispatch changes**

```bash
git add src/ccusage_viz/application.py src/ccusage_viz/cli.py tests/test_application.py tests/test_cli.py
git commit -m "refactor: run charts through dashboard"
```

### Task 3: Remove standalone runtimes and their tests

**Files:**
- Delete: `src/ccusage_viz/watch.py`
- Delete: `src/ccusage_viz/monitor.py`
- Delete: `src/ccusage_viz/custom_monitor.py`
- Delete: `src/ccusage_viz/standalone_help.py` if no remaining import uses it
- Modify: imports and tests referring to deleted runtime APIs
- Test: full suite

**Interfaces:**
- Preserves: Dashboard components, rendering helpers, and normal `dashboard` behavior.
- Removes: standalone execution loops only.

- [ ] **Step 1: Locate all imports and test references**

Run:

```bash
rg -n "ccusage_viz\.(watch|monitor|custom_monitor|standalone_help)|run_watch|run_monitor|run_custom_monitor|run_custom_standalone" src tests
```

- [ ] **Step 2: Delete runtime-only files and migrate/remove their direct tests**

Delete only modules whose remaining exports are not used by Dashboard. Keep reusable components and rendering helpers. Replace obsolete standalone assertions with focused Dashboard adapter/dispatch assertions rather than duplicating Dashboard behavior tests.

- [ ] **Step 3: Run affected tests**

Run: `uv run pytest tests/test_application.py tests/test_cli.py tests/test_tui_dashboard.py tests/test_tui_custom.py -v`

Expected: PASS.

- [ ] **Step 4: Run full quality gate**

Run:

```bash
uv run pytest
uv run ruff check .
uv build
```

Expected: all pass.

- [ ] **Step 5: Commit runtime consolidation**

```bash
git add -A
git commit -m "refactor: remove standalone chart runtimes"
```

### Task 4: Document the unified chart runtime

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Modify: `docs/architecture.md`
- Modify: `docs/architecture.zh-CN.md`

**Interfaces:**
- Documents: `chart` as a focused single-Pane Dashboard shortcut, `dashboard single` as interactive starting point, and `animate --gallery` as independent.

- [ ] **Step 1: Update English and Chinese documentation together**

Remove descriptions that call `chart` a standalone runtime. State that it starts a one-Pane Dashboard with hidden header/summary, and that Dashboard behavior takes over after launch. Keep `animate --gallery` documented as provider-free and independent.

- [ ] **Step 2: Verify references**

Run:

```bash
rg -n "standalone (chart|runtime)|--no-watch" README.md README.zh-CN.md docs src
```

Expected: no public claims of a standalone chart runtime and no CLI `--no-watch` reference.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md README.zh-CN.md docs/usage.md docs/usage.zh-CN.md docs/architecture.md docs/architecture.zh-CN.md
git commit -m "docs: describe focused chart dashboards"
```
