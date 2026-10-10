# Dataset Ranking Comparison Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide Custom Dataset Ranking comparison columns until a prior-period Dataset response is accepted, while treating entries absent from an available comparison response as new.

**Architecture:** The Custom historical projection distinguishes response-level comparison availability from the individual series' previous facts. Custom Ranking passes that availability to the shared historical Ranking renderer, whose native default remains unchanged.

**Tech Stack:** Python, `Decimal`, pytest, existing dict-based i18n, terminal renderer.

**Spec:** `docs/superpowers/specs/2026-10-10-dataset-ranking-comparison-availability-design.md`

## Global Constraints

- Apply only to Custom Dataset historical Ranking.
- Do not add sorting controls, messages, toasts, protocol fields, or new requests.
- A partial comparison response enables columns; an omitted prior series is new, not zero.
- Preserve existing `all` period, width, density, and `comparison: full|rank|none` rules.

---

### Task 1: Preserve Comparison Availability In Projection

**Files:**
- Modify: `src/ccusage_viz/processing/custom_historical.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- Produces: `CustomChartProjection.comparison_available: bool`.
- Produces: missing prior series preserve `previous_total=None` and `comparison_ready=False`.

- [ ] Add failing tests for a Ranking with no comparison response and a partial comparison response.
- [ ] Run: `pytest tests/test_custom_component.py -k ranking_derives_decimal_comparison_facts -v`
- [ ] Add `comparison_available = comparison_response is not None` to projection construction.
- [ ] Only assign `previous_total`, `previous_rank`, and `comparison_ready` when a prior id exists.
- [ ] Re-run the targeted test and verify it passes.

### Task 2: Gate Custom Renderer Columns And Label New Entries

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_component.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `render_historical_ranking(..., comparison_available: bool = True)`.
- Consumes: `CustomChartProjection.comparison_available` from Custom Ranking rendering.
- Produces: absent comparison response hides comparison headers; available partial response renders localized new-entry cells.

- [ ] Add failing tests that a detailed/wide Custom Ranking without comparison facts hides `vs prior` and `Rank Delta`.
- [ ] Add failing tests that a partial response retains visible columns, labels the missing entry `New` / `New in ranking`, and leaves `Other` unlabelled.
- [ ] Run: `pytest tests/test_custom_component.py tests/test_render.py -k 'ranking and (comparison or prior)' -v`
- [ ] Add the optional availability argument with a default of `True` to retain native behavior.
- [ ] Gate existing comparison-column geometry with that argument and render localized new-entry labels for non-Other entries without per-entry prior facts.
- [ ] Pass the projection availability only from `render_custom_ranking()`.
- [ ] Re-run the focused tests and verify they pass.

### Task 3: Regression Verification

**Files:**
- Test: `tests/test_custom_component.py`
- Test: `tests/test_render.py`

- [ ] Run: `pytest tests/test_custom_component.py tests/test_render.py -v`
- [ ] Run: `pytest -q`
- [ ] Run: `git diff --check`
- [ ] Inspect the diff to verify it is limited to the Custom Dataset Ranking comparison behavior.
