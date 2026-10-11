# Dashboard Pane Repaint Implementation Plan

> **For agentic workers:** Execute tasks in this session, test each independently before integration.

**Goal:** Isolate animation repaint computation and terminal output from static dashboard panes.

**Architecture:** Reuse composed pane contents on animation-only ticks. Diff styled display cells when emitting terminal changes, preserving full repaint fallback for unsupported control sequences.

**Tech Stack:** Python >=3.11, pytest, ruff, uv; no new dependencies.

**Spec:** docs/superpowers/specs/2026-10-11-dashboard-pane-repaint-design.md

## Global Constraints
- Preserve existing query intervals and uncommitted ranking scroll changes.
- No new dependencies; Python >=3.11.

### Task 1: Terminal display-cell differential output
Files: create `src/ccusage_viz/terminal_diff.py`; modify `src/ccusage_viz/terminal.py`; test `tests/test_terminal_diff.py` and `tests/test_terminal.py`.
Interface: `row_updates(previous: str, current: str, row: int) -> str` returns cursor-addressed changed spans or a safe whole-row replacement.
- [ ] Add regressions using `FramePainter(StringIO())`, paint old and new side-by-side rows, assert unchanged text is absent from output.
- [ ] Run `uv run pytest tests/test_terminal_diff.py -q` and confirm failure.
- [ ] Tokenize SGR/OSC8 sequences into display glyphs carrying style state; compare glyphs at cell offsets, expand changed spans to complete glyph boundaries, reset and close styles after each span. Return full row replacement for unsupported controls.
- [ ] Integrate `row_updates` into FramePainter's changed-row branch and update existing exact-output assertions to local spans.
- [ ] Run `uv run pytest tests/test_terminal.py tests/test_terminal_diff.py -q`.

### Task 2: Animation-only pane cache
Files: modify `src/ccusage_viz/tui.py`; test `tests/test_tui_dashboard.py`.
Interface: nested `paint(*, force: bool = False, animation_only: bool = False)` conservatively invalidates on all ordinary paints.
- [ ] Add a dashboard loop regression with a static pane and animation pane; count `_pane_render` calls across isolated animation ticks and ordinary interaction.
- [ ] Run regression and confirm static pane is currently rendered at every tick.
- [ ] Extract `_pane_animation_deadline(pane)`; cache `(geometry, content, overlays)` for normal pane rendering; reuse only on animation-only paints when deadline is absent/not due and geometry matches.
- [ ] In loop pass `animation_only=True` only when the animation deadline is the sole paint reason. Preserve editor, feedback, accepted data and copy-icon expiration invalidation.
- [ ] Run dashboard, layout, header, custom ranking and animation tests.

### Task 3: Verification
- [x] Run `uv run ruff check` and `uv run ruff format --check` on changed files.
- [x] Run `uv run pytest -q`.
- [x] Inspect `git diff` and report results without staging or overwriting unrelated changes.

## Execution results
- Implemented display-cell diff and animation-only composed-pane cache.
- Added `tests/test_dashboard_repaint.py` instead of enlarging the existing dashboard test file; covers individual animation deadlines, ordinary interaction, resize, attachments and overlay scheduling.
- New terminal regression tests failed before implementation. Dashboard tick regressions also fail against an isolated HEAD snapshot and pass with the fix.
- Focused terminal/dashboard/ranking/animation/layout suite: 204 passed.
- Final full suite: 1580 passed, 6 failed. All six failures reproduce on the original HEAD snapshot (text wrapping, two pre-existing dashboard tests, three header preset tests). A process timeout test failed transiently on the first run but passed in isolation and on the final full run.
- Ruff checks, formatting and diff whitespace checks pass. No unrelated working-tree changes staged or reverted.
