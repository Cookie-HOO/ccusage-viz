# Ranking Project Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe per-project `https` links to Custom Dataset Ranking rows and copied project content.

**Architecture:** Model the optional URL on `CustomSeries` and `CustomProjectedSeries`, validate it only for Ranking protocol responses, then render an OSC 8 `↗` after the copy marker. The existing copy-row map remains tied only to `⊞` or its transient `✓` state, while the copy payload appends the projected URL.

**Tech Stack:** Python 3.12, pytest, existing Custom protocol/parser, Historical Ranking presentation, OSC 8 terminal links.

**Spec:** `docs/superpowers/specs/2026-10-10-ranking-project-links-design.md`

## Global Constraints

- `link` is a Ranking-only optional series field.
- Only absolute `https://` URLs with a host are accepted.
- The row format is `Project ⊞ ↗`; no project link means no `↗`.
- Project links are excluded from local `Other` and comparison-only data.
- Project copying appends the project URL after label and description text.

---

### Task 1: Protocol And Projection

**Files:**
- Modify: `src/ccusage_viz/custom_models.py`
- Modify: `src/ccusage_viz/custom_protocol.py`
- Modify: `src/ccusage_viz/processing/custom_historical.py`
- Test: `tests/test_custom_protocol.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- `CustomSeries.link: str | None` and `CustomProjectedSeries.link: str | None` hold a validated current Ranking URL.
- `_parse_series(..., descriptions_allowed=True)` accepts `link` only for Ranking and rejects invalid URL values.

- [ ] Add parser cases for a valid Ranking `link`, a non-`https` link, and a non-Ranking link field.
- [ ] Run the focused parser cases and verify they fail before implementation.
- [ ] Validate URLs structurally with `urllib.parse.urlparse`, preserving only `https` values with a non-empty netloc.
- [ ] Carry the current response link through Ranking projection and omit it from locally generated `Other` entries and comparison metadata.
- [ ] Run `pytest tests/test_custom_protocol.py tests/test_custom_component.py -v`.

### Task 2: Rendering And Copying

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_render.py`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- `RankingPresentationEntry.project_link: str | None` causes a clickable `↗` after `copy_marker`.
- `_custom_ranking_copyable_entries(...)` provides the current project link for clipboard construction.

- [ ] Add renderer tests for OSC 8 `↗`, link-free rows, and width-safe marker placement.
- [ ] Pass each concrete projected link into `RankingPresentationEntry`; preserve copy marker placement before the link icon.
- [ ] Extend the existing copied entry record and copy payload to include the optional project URL as its final line.
- [ ] Keep `capture_custom_ranking_copy_rows` anchored to the copy marker, so clicking `↗` does not invoke copying.
- [ ] Run focused renderer and TUI Custom tests.

### Task 3: Documentation And Validation

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`

- [ ] Document `link` with its Ranking-only `https` validation, icon behavior, and copied payload semantics in both languages.
- [ ] Run `pytest tests/test_custom_protocol.py tests/test_custom_component.py tests/test_tui_custom.py tests/test_render.py -v`.
- [ ] Run `ruff check` on touched Python files and `git diff --check`.
