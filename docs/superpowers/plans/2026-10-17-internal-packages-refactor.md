# Internal Packages Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split oversized production modules and their tests without changing public entry points or behavior.

**Architecture:** Extract cohesive owners and switch internal imports directly. CLI/TUI become internal packages with only their unchanged public entry points exposed by `__init__.py`; shared command parsing sits below both. Move pure functions before session state and event-loop code.

**Tech Stack:** Python 3.11–3.13, uv, Ruff 0.13.3, ty, pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-maintainability-package-refactor-design.md`

## Global Constraints

- No publication or version bump.
- Public entry-point paths and calling contracts do not change.
- All internal imports switch to the owning module; no old-path shims or re-exports.
- Preserve protocols, persistence, rendering, scheduling and branch order.
- Approximately 800 lines is a soft target; document coherent exceptions.
- Migrate all existing tests and parametrized cases without dropping assertions.

## Baseline

On `refactor/internal-packages`, baseline 2048 tests pass (14.72 seconds), Ruff lint passes, and ty reports 195 existing diagnostics. Collection and check logs are in `/tmp/ccuv-refactor-baseline-*`. Workspace was clean before the specification updates.

### Task 1: Protocol owners and tests

**Files:** replace `src/ccusage_viz/custom_protocol.py` with owner modules under `custom_protocol/`; split `tests/test_custom_protocol.py` under `tests/custom_protocol/`; update all production/test imports.

**Interfaces:** existing request/response classes, error type, canonical key function, parse and descriptor-wire functions retain their signatures and class identities.

- [ ] Parse the original AST and record every top-level definition and test case.
- [ ] Group primitives/errors, requests, response types/dispatch, Probe descriptors, and values into explicit modules; keep dependencies pointing toward primitives and existing custom models.
- [ ] Move complete definitions with decorators/docstrings and preserve statement ordering.
- [ ] Update import statements by each symbol's actual owner, including local imports; leave package initializer empty.
- [ ] Split tests by requests, Probe, responses, values; share only fixtures/builders.
- [ ] Run `uv run pytest tests/custom_protocol tests/test_custom_provider.py tests/test_custom_component.py tests/test_custom_monitor_component.py tests/test_datasets_models.py tests/test_datasets_service.py`.
- [ ] Check migrated test names/parametrizations against baseline and commit the validated unit.

### Task 2: Ranking presentation owners and tests

**Files:** replace `render/ranking_presentation.py` with `ranking_description.py`, `ranking_entries.py`, `ranking_columns.py`, `ranking_historical.py`; split `tests/test_render.py` into cohesive suites under `tests/render/`.

**Interfaces:** description copy/search/highlight functions, `RankingPresentationEntry`, column measurement, heading rendering, and historical rendering preserve signatures and output.

- [ ] Move description/link functions and entry/search functions without changing bodies.
- [ ] Move measurement/heading functions and historical rendering; update imports directly.
- [ ] Move existing render tests by chart kind and shared rendering concerns, retaining every assertion.
- [ ] Run `uv run pytest tests/render tests/test_custom_ranking_scroll.py tests/test_custom_ranking_dashboard_scroll.py tests/test_custom_ranking_projection.py`.
- [ ] Reconcile test collection and commit.

### Task 3: Preset codecs and tests

**Files:** replace `dashboard_presets.py` with `presets/values.py`, `presets/panes.py`, `presets/document.py`, `presets/materialize.py`; migrate `tests/test_dashboard_presets.py` and update callers.

**Interfaces:** record/document, primitive validators, Pane codec and launch materialization keep signatures, errors and serialized schema.

- [ ] Move paired wire/parse helpers into the same owner where they represent one entity.
- [ ] Put document types above primitive/Pane codecs without reverse imports.
- [ ] Switch all callers to direct imports.
- [ ] Move tests into `tests/presets/`; retain store integration coverage.
- [ ] Run `uv run pytest tests/presets tests/test_dashboard_preset_store.py tests/test_cli.py tests/test_tui_preset_manager.py` and commit.

### Task 4: Shared parsing and CLI package

**Files:** replace `cli.py` with `cli/__init__.py`, `cli/entrypoint.py`, `cli/routing.py`, `cli/configuration.py`; extract `command_parsing/parser.py`, `command_parsing/charts.py`, `command_parsing/panes.py`, `command_parsing/common.py`; migrate `tests/test_cli.py` and `tests/test_options.py` under `tests/cli/`.

**Interfaces:** only `cli.main` is exported at package entry; parser and configuration callers use their owners directly. `main(argv: list[str] | None = None) -> int` remains unchanged.

- [ ] Extract constants/common explicit-field handling below parser/chart conversion.
- [ ] Move parser grammar and chart/Pane conversion into neutral command parsing modules.
- [ ] Move routing/configuration/main and keep `cli/__init__.py` limited to `main`.
- [ ] Replace internal imports and patch targets; TUI imports Pane parsing from neutral owner.
- [ ] Move parser/routing/options/preset/entrypoint tests into matching suites, with uniquely identified pytest modules.
- [ ] Run all CLI/options/TUI integration suites and verify installed entry-point import and help/version behavior.
- [ ] Commit.

### Task 5: TUI pure concerns and tests

**Files:** replace `tui.py` with package owner modules described in the spec; migrate `tests/test_tui_dashboard.py`, `tests/test_tui_custom.py`, layout/header/repaint and ranking interaction tests into `tests/tui/`.

**Interfaces:** `tui.run_tui(options: DashboardLaunch, translator: Translator) -> int` unchanged; all internal helpers belong to explicit owner modules.

- [ ] Extract state types, geometry, header reconciliation and submission adapters first.
- [ ] Extract custom and built-in rendering, adjustments, chooser/catalog concerns; update every caller directly.
- [ ] Migrate unit tests to owner modules; move integration tests intact before organizing shared builders.
- [ ] Update architecture tests to inspect existing package files and preserve lifecycle/submit/frame ownership assertions rather than weakening them.
- [ ] Run `uv run pytest tests/tui tests/test_architecture.py` after each coherent extraction and commit only validated units.

### Task 6: TUI session and stateful handlers

**Files:** `tui/session.py`, `tui/queries.py`, `tui/help.py`, `tui/painting.py`, `tui/pointer.py`, `tui/history.py`, `tui/events.py`, `tui/datasets/modal.py`, `tui/runtime.py`; matching `tests/tui/` suites.

**Interfaces:** session owns exactly the previous closure state; collaborators operate on that state without copying or duplicating domain-component facts.

- [ ] Inventory closure variables and `nonlocal` assignments before conversion.
- [ ] Move state initializers to an explicit typed session object, retaining allocation and cleanup timing.
- [ ] Extract completion collection, scheduling, history, Help, frame composition, pointer and modal handlers in their existing invocation order.
- [ ] Keep event priority, consumed-event returns, polling deadlines, executor workers and finally cleanup unchanged.
- [ ] Re-run runtime integration tests for keyboard, mouse, queries, cancellation and presets after each move.
- [ ] Check dependency graph for cycles and oversized catch-all replacements; commit validated extraction.

### Task 7: Remaining size review, formatting and final checks

**Files:** oversized animate/Dataset/Monitor/provider files and matching tests as justified by cohesive boundaries; architecture test helpers; public architecture documentation when paths change.

- [ ] Review remaining modules over 800 lines and extract distinct responsibilities with corresponding test migration; record cohesive exceptions.
- [ ] Reconcile all baseline test function names and parametrized cases, not only counts.
- [ ] Run `uv run ruff format .` and commit formatting separately.
- [ ] Run `uv run ruff format --check .` and `uv run ruff check .` with no added suppressions.
- [ ] Run `uv run ty check src/ccusage_viz`; fix ownership/type errors without changing data semantics and distinguish baseline errors.
- [ ] Run `uv run pytest`; build fresh artifacts and smoke-test both installed aliases in an isolated uv environment.
- [ ] Record final file sizes, justified exceptions, test/check results and any blockers; finish with a clean committed workspace and no publication.
