# Ranking Description Emphasis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render safe `**bold**` and `*italic*` Markdown in Custom Dataset Ranking descriptions.

**Architecture:** Extend the existing Ranking description presentation parser with a small emphasis-token layer applied only to accepted visible text and supported link labels. Keep wrapping, searching, copying, and URL validation based on plain text. Update tests and the two bilingual Dataset-facing document pairs to describe the exact supported syntax.

**Tech Stack:** Python 3.12, pytest, terminal ANSI SGR formatting, existing Ranking renderer.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-description-emphasis-design.md`

## Global Constraints

- Only `**bold**` and `*italic*` are supported; underscore variants are not.
- Valid emphasis may occur inside existing `[label](https://URL)` link labels.
- Invalid, nested, empty, and unsupported Markdown stays visible safe text.
- Dataset-supplied terminal controls remain stripped before parsing.
- The change applies only to historical Custom Ranking descriptions.

---

### Task 1: Safe Emphasis Presentation

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Test: `tests/test_render.py`

**Interfaces:**
- `_render_highlighted_description(value: str, query: str, context: RenderContext) -> str` renders accepted emphasis styles while retaining OSC 8 link wrappers.
- `_description_visible_text(value: str) -> str` returns the plain visible label text used for wrapping.

- [ ] Add renderer assertions for `**bold**`, `*italic*`, and a linked italic label, checking visible plain text, SGR styles, OSC 8 wrappers, and display width.
- [ ] Run `pytest tests/test_render.py -k description -v` and verify the new assertions fail before the implementation.
- [ ] Add a constrained star-delimiter parser that accepts only non-empty, non-nested matching markers and produces bold or italic spans.
- [ ] Render accepted spans through existing terminal styling while applying search highlighting only to matching textual spans; retain link underline/dim affordance and OSC 8 wrapper around the full label.
- [ ] Ensure malformed, nested, and underscore syntax remains literal visible text.
- [ ] Run `pytest tests/test_render.py -k description -v` and verify the renderer cases pass.

### Task 2: Documentation And Regression Validation

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`
- Test: `tests/test_render.py`

**Interfaces:**
- Dataset-facing documentation states the complete allowed description markup contract.

- [ ] Replace link-only wording with the allowed `**bold**`, `*italic*`, and link markup forms, explicitly excluding underscores and all other Markdown.
- [ ] Run `pytest tests/test_render.py -k description -v`.
- [ ] Run `git diff --check` and inspect the touched-file diff to confirm unrelated pending changes were not altered.
