# Ranking Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render optional bilingual Custom Dataset Ranking descriptions, with Dataset-controlled initial visibility and a `D` runtime toggle.

**Architecture:** Keep descriptions specific to Custom historical Ranking at the protocol and projection boundaries. Extend the shared historical Ranking presentation with optional secondary rows, then let standalone and Dashboard hosts hold an ephemeral visibility override and route `D` only when an active Ranking actually has descriptions.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing terminal rendering and Custom protocol layers.

**Spec:** `docs/superpowers/specs/2026-10-09-ranking-descriptions-design.md`

## Global Constraints

- Support `ccuv.custom/v1` and `ccuv.custom/v2` without changing protocol identifiers.
- Only Custom historical Ranking accepts or renders descriptions; native Ranking and other Custom historical chart kinds retain current output.
- Descriptions are `LocalizedText`, plain text only, two rendered rows maximum, and never inherited by local `Other`.
- `minimal` density suppresses descriptions. `D` is a non-persistent, non-querying runtime override.

---

### Task 1: Protocol And Projection

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/custom_protocol.py`
- Modify: `src/ccusage_viz/processing/custom_historical.py`
- Test: `tests/test_custom_protocol.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- Produces a ranking-only capability default and projected localized description consumed by rendering.
- Parser rejects descriptions for non-Ranking requests and invalid ranking defaults.

- [ ] Add failing parser tests for V1/V2 Ranking `descriptions_default`, localized entry descriptions, and forbidden non-Ranking descriptions.
- [ ] Run `pytest tests/test_custom_protocol.py -v` and verify the new cases fail.
- [ ] Extend immutable capability and projected Ranking models; parse and serialize the new fields; validate response descriptions against the requested chart kind.
- [ ] Propagate accepted primary Ranking descriptions through projection, excluding `Other` and comparison-only data.
- [ ] Run `pytest tests/test_custom_protocol.py tests/test_custom_component.py -v` and verify the cases pass.
- [ ] Commit protocol and projection changes with `feat: support custom ranking descriptions`.

### Task 2: Ranking Presentation

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Test: `tests/test_render.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- `RankingPresentationEntry` accepts an optional display description.
- `render_historical_ranking` receives an explicit descriptions-visible flag.

- [ ] Add failing renderer tests for muted indented secondary rows, two-row wrapping/truncation, and minimal-density suppression.
- [ ] Run the focused renderer tests and verify failure.
- [ ] Render ANSI-aware muted description rows after their primary Ranking row while preserving existing description-free output.
- [ ] Pass Custom Ranking projected descriptions and visibility defaults to the shared renderer without changing native call sites.
- [ ] Run focused renderer and Custom Ranking tests and verify success.
- [ ] Commit presentation changes with `feat: render ranking descriptions`.

### Task 3: Runtime Visibility Controls

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/standalone_help.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_tui_dashboard.py`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Custom historical pane/run stores `description_visibility_override: bool | None`.
- `D` toggles only a visible-description-capable Custom Ranking and never submits a query or persists in Dashboard state.

- [ ] Add failing TUI tests for availability, per-pane override isolation, minimal-density temporary suppression, and no scheduler/query mutation on `D`.
- [ ] Route `D` in standalone Custom Ranking and focused Dashboard Custom Ranking; add contextual controls/help labels only when supported.
- [ ] Thread effective visibility to the Custom Ranking renderer while retaining the Probe default when no runtime override exists.
- [ ] Run focused TUI tests and verify success.
- [ ] Commit interaction changes with `feat: toggle ranking descriptions`.

### Task 4: Documentation And Regression Validation

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`
- Test: relevant protocol, rendering, and TUI test modules

**Interfaces:**
- Dataset authors see the exact Ranking capability and response fields in English and Simplified Chinese guides.

- [ ] Add bilingual protocol examples and constraints for `descriptions_default` and Ranking-only localized `description`.
- [ ] Run `git diff --check`, focused test modules, then the project test suite.
- [ ] Review output for regression in native Ranking and description-free Custom Ranking rendering.
- [ ] Commit docs and final verification with `docs: document ranking descriptions`.
