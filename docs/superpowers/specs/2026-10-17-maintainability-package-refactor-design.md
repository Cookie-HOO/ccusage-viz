# Maintainability refactor: internal CLI/TUI packages and matching tests

## Status and scope

The user has approved a behavior-preserving, responsibility-based refactor with internal `cli/` and `tui/` packages and matching test organization. This specification records the design for review before implementation. The 0.3.0 publication work is paused: do not bump versions, push, merge, tag, or publish as part of this refactor.

Baseline: commit `cb262ddf`. The tracked working tree was clean before writing this specification.

Goals:

- Replace oversized production modules with cohesive modules, with a soft target of approximately 800 lines per file.
- Split corresponding tests by the same responsibilities, preserving every existing test case and assertion intent.
- Format Python code and pass Ruff formatting and lint checks.
- Preserve behavior, data ownership, scheduling, and lifecycle semantics; this is not a product or algorithm redesign.

Non-goals: new features, new protocol or persistence versions, dependency upgrades, generic plugin/event frameworks, arbitrary line-count splitting, and publication.

## Invariants

Preserve CLI commands, defaults, help/error text, exit codes, language behavior, Dataset V1/V2 wire payloads, validation order, exception behavior, canonical request identity, preset serialization, terminal output, keyboard/mouse semantics, query counts, deadline ordering, cancellation, shutdown, and source-owned data semantics.

Keep `ccusage_viz.cli.main`, both installed script entry points, `ccusage_viz.__main__`, and `ccusage_viz.tui.run_tui` working. Keep existing explicitly imported compatibility functions and protocol classes available through thin explicit re-exports where needed. Do not duplicate class definitions across modules.

Private helper imports and test monkeypatch targets may move to their actual owner. Do not implement dynamic module forwarding, `sys.modules` replacement, global namespace injection, or a dependency registry solely to preserve old private patch paths. Retain integration coverage of the public entry points.

## Module design

### CLI internal package

Replace `src/ccusage_viz/cli.py` with `src/ccusage_viz/cli/`:

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Explicit compatibility exports; no execution or service startup on import |
| `entrypoint.py` | Main orchestration, language setup, short-circuit rendering, and exit/error handling |
| `parser.py` | Localized argument parser and parameter groups |
| `routing.py` | Command recognition, defaults, short-circuit decisions and diagnostic suggestions |
| `charts.py` | Namespace-to-chart conversion and existing chart validation |
| `panes.py` | Pane fragment parsing entry point |
| `configuration.py` | Namespace-to-launch composition and explicit fields |

`parse_pane_fragment` currently calls `build_parser` and chart converters. Merely moving it into a neutral module while importing `cli` back would not remove the dependency cycle. Extract the shared chart/pane syntax and conversion primitives to a neutral `command_parsing/` package as needed (`syntax.py`, `charts.py`, `panes.py`); the CLI modules above delegate to those owners rather than duplicating implementations. Shared parsing must not import CLI entrypoint/routing orchestration, application startup, or TUI. Do not create redundant wrappers for symbols with no compatibility need.

TUI built-in preset construction uses the neutral Pane parser, not the CLI facade. The complete parser must preserve the existing argument grammar, validation ordering, explicit-field handling, and error translation.

### TUI internal package

Replace `src/ccusage_viz/tui.py` with `src/ccusage_viz/tui/`:

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Public `run_tui` and required explicit compatibility exports |
| `models.py` | Pane/Outcome/Overlay/search state types and small result types |
| `layout.py` | Grid, rectangles, hit geometry, frame composition |
| `header.py` | Header presentation and source/summary reconciliation |
| `pane_lifecycle.py` | Pane construction, replacement, shutdown, submission adapters |
| `rendering.py` | Built-in/animation Pane rendering and render dispatch |
| `custom_rendering.py` | Custom historical/Monitor rendering, diagnostics and copy payloads |
| `adjustments.py` | Built-in/animation adjustment bindings and presentation |
| `custom_adjustments.py` | Dataset capability-gated adjustment logic |
| `datasets/chooser.py` | Dataset/Metric rows, local command and installed-source selection |
| `datasets/catalog.py` | Official catalog browsing and GitHub install UI |
| `datasets/modal.py` | Non-blocking Dataset modal transitions and completion |
| `session.py` | Session initialization and session-owned state |
| `queries.py` | Submission, refresh, completion acceptance and summary scheduling |
| `help.py` | Contextual Help and controls composition |
| `painting.py` | Frame assembly, cache use, overlay placement and repaint decisions |
| `pointer.py` | Ranking scroll, hover, drag and copy hit handling |
| `history.py` | Capture/apply Dashboard state, undo/redo and preset integration |
| `events.py` | Event dispatch with existing priority and consumption rules |
| `runtime.py` | Public startup, polling loop and cleanup |

These are responsibility boundaries, not a requirement to create empty files. Split a module further only when it actually contains separate cohesive responsibilities. Keep the existing `tui_input.py` and `tui_preset_manager.py` where they are unless their migration is needed for dependency direction; there is no need to rename every TUI-related file.

Dependencies flow from runtime orchestration through handlers to state/geometry/presentation and existing domain components. Internal modules must not import the `tui` facade. State modules must not import event handlers or runtime.

The current `run_tui` is 5,616 lines. Extract independent top-level functions first. Then move its closure-owned state to an explicit internal session object without changing initial values, object aliasing, update ordering, or cleanup scope. Handlers operate on that state with typed, narrowly scoped collaborators where required. Do not turn the session into a new 5,000-line class, a multiple-inheritance mixin host, or an untyped callback/global dictionary.

Particular care is required for the 580-line completion collector, 500-line Help composer, painting, and modal handlers. Split along existing branches, preserving branch order and return/continue semantics. Retain the same executor ownership and number of workers, terminal context manager, and try/finally cleanup boundary.

### Other oversized production modules

- `custom_protocol.py`: retain explicit facade exports; extract request/response types, request canonicalization, Probe/Metric parsing and wire conversion, response dispatch, value validation. Primitive validation/errors sit below request and response code; no import back into the facade.
- `render/ranking_presentation.py`: extract description/link/search handling, entry types, column measurement/heading, and historical rendering. Preserve identical visible and ANSI output and source-owned comparison facts.
- `dashboard_presets.py`: extract primitive validation/codec, chart/Pane codec, and materialization. Pair decoding and encoding of the same entity where that keeps the schema cohesive; do not split mechanically into unrelated serializer/deserializer copies.
- Review the other production modules over approximately 800 lines (`animate.py`, Dataset manager/models, custom Monitor component, processing Monitor, ccusage provider) for real responsibility boundaries. Extract helper concerns and matching tests where cohesive; document a single-responsibility exception instead of cutting arbitrarily.
- Locale dictionaries and generated lockfiles are not split just to meet a line limit.

## Test organization

Use matching subdirectories such as `tests/cli/`, `tests/tui/`, `tests/custom_protocol/`, `tests/render/`, and `tests/presets/`. Ensure unique pytest module identities using package markers in directories with repeated basenames; do not change global pytest import mode merely to make collection pass.

Move existing test cases intact before adding new coverage. Group tests around actual production responsibilities, not their old file positions. Keep end-to-end CLI/TUI tests separate from internal unit tests. Cross-module integration suites need not map one-to-one to a production file.

Share only genuine fixtures/builders through local `conftest.py` or explicitly named helper modules. Do not import one test module from another or move all old helpers into a new oversized catch-all file.

Record test collection before and after migration, including parametrized cases. Reconcile renamed node IDs; equal counts alone are insufficient. No test or assertion may be dropped to make the refactor pass. Additional regression tests may increase collection counts.

Update architecture tests that currently read `tui.py` directly to inspect the new owning modules/package. Preserve their substantive checks: lifecycle ownership, no duplicated component business state, legal submit sites, frame composition, and dependency boundaries. Add checks for no facade back-imports and no TUI dependency on CLI orchestration. Ensure source-scanning helpers actually inspect files rather than silently passing on a missing old path.

## Sequence and validation

1. Record clean baseline, create an isolated local refactor branch, and capture test collection and test/lint/type results. Do not reset or discard any newly appearing user changes.
2. Perform the approved structural extraction in small units, each paired with test migration and targeted regression checks. Prefer foundational codec/rendering work before CLI and TUI stateful extraction.
3. Commit independently validated units. Avoid unrelated cleanup, renamed concepts, or algorithm simplification in movement commits.
4. Following the user's requested order, run the final repository-wide `uv run ruff format .` after the splits and commit formatting separately. New modules can be formatted while developing, but do not interleave broad unrelated formatting with movement commits.
5. Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check src/ccusage_viz`, and the full `uv run pytest` suite. No rule suppression or test removal solely to obtain green results.
6. Build into a fresh output directory and install the wheel into an isolated environment. Smoke-test both command aliases, version/help, representative parser success/error paths, and import-only behavior without starting providers.
7. Report module/test size changes, exceptions to the soft 800-line target, test results, and remaining blockers. Finish with committed work and a clean working tree. Discuss publication separately.

If baseline lint/type/test failures exist, record them before extraction so they cannot be confused with refactor regressions. Fix demonstrably behavior-preserving issues in separate commits; surface failures requiring a product behavior decision rather than concealing them.

## Acceptance criteria

- CLI and TUI are proper internal packages with explicit entry points and acyclic ownership boundaries.
- Original public behavior and wire/persistence contracts remain covered and unchanged.
- Oversized code and its tests are split by matching responsibility, with justified size exceptions recorded.
- Ruff format and lint, type checking, full regression suite, build, and isolated entrypoint smoke checks pass.
- The workspace is clean after commits; no 0.3.0 publication operation has been performed.
