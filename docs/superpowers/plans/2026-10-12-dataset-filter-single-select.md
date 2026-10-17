# Dataset Filter Single-Select Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Dataset-declared single-select runtime filters while making Custom filter tabs show accepted per-dimension selection counts and preserving one explicit multi-filter apply action.

**Architecture:** Extend the existing `CustomFilter` protocol model with a second mode, then keep the existing immutable `CustomFilters` wire shape. The draft editor receives both accepted filters and local draft filters: tab `n/m` counts derive only from the accepted input, while its current-detail count derives from the draft. Rendering uses existing palette/theme styling, with no hard-coded ANSI colors.

**Tech Stack:** Python 3.12+, dataclasses, pytest, existing Custom V2 protocol parsing, Custom filter draft editor, terminal palette renderer.

**Spec:** `docs/superpowers/specs/2026-10-12-dataset-filter-single-select-design.md`

## Global Constraints

- Apply only to Dataset/Custom-command filters in `custom_filter_draft.py`; do not change native `filter_draft.py` behavior.
- Omitted Filter mode means `multi_select`; query wire values remain option-ID arrays.
- `single_select` allows zero or one selected option; Dataset remains authoritative for required values and all semantic validation.
- Space edits one local draft, Enter applies every dimension in one query, and Esc cancels the whole draft.
- Tab `n/m` reflects accepted input filters and de-duplicated visible options only; it must not react to unsubmitted draft edits.
- Use existing palette/theme tokens; no hard-coded ANSI colors. No-color and ASCII modes remain readable.

---

## File Structure

- `src/ccusage_viz/custom_models.py`: expand `CustomFilter.mode` type.
- `src/ccusage_viz/custom_protocol.py`: parse/validate `single_select` in runtime filters and serialize it where applicable.
- `src/ccusage_viz/custom_filter_draft.py`: single-select draft mutation, accepted tab counts, and palette-aware chrome rendering.
- `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py`: any count/tab labels required by the render contract.
- `tests/test_custom_protocol.py`: protocol default, parse, rejection, and serialization cases.
- `tests/test_custom_filter_draft.py`: draft mode behavior, accepted-vs-draft counts, visual hierarchy, and regression coverage.
- `docs/custom-command-protocol.md`, `docs/custom-command-protocol.zh-CN.md`: runtime Filter mode contract and author guidance.
- `docs/dataset-developer-guide.md`, `docs/dataset-developer-guide.zh-CN.md`: author guidance to prefer single-select for exclusive modes/ranges and multi-select for combinable discrete values.

### Task 1: Extend the runtime Filter protocol model

**Files:**
- Modify: `src/ccusage_viz/custom_models.py:CustomFilter`
- Modify: `src/ccusage_viz/custom_protocol.py:_parse_filter`, wire serialization helpers
- Modify: `tests/test_custom_protocol.py`

**Interfaces:**
- Produces: `CustomFilter.mode: Literal["multi_select", "single_select"]`, defaulting to `"multi_select"`.
- Produces: parser acceptance of `single_select` and rejection of other values.

- [ ] **Step 1: Write failing protocol tests**

```python
def test_v2_runtime_filter_defaults_to_multi_select_and_accepts_single_select() -> None:
    parsed = parse_runtime_filter({"id": "seed_book", "label": text("Based on book", "基于图书"), "options": []})
    assert parsed.mode == "multi_select"

    parsed = parse_runtime_filter({"id": "seed_book", "label": text("Based on book", "基于图书"), "mode": "single_select", "options": []})
    assert parsed.mode == "single_select"


def test_runtime_filter_rejects_unknown_selection_mode() -> None:
    with pytest.raises(CustomProtocolError, match="filter mode"):
        parse_runtime_filter({"id": "seed_book", "label": text("Based on book", "基于图书"), "mode": "range", "options": []})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_protocol.py -k 'filter.*mode or single_select' -v`

Expected: FAIL because `single_select` is not a declared model/parser mode.

- [ ] **Step 3: Implement model/parser support**

Update the `CustomFilter.mode` Literal. In runtime filter parsing, use the existing default `"multi_select"`, accept exactly `"multi_select"` and `"single_select"`, and report `CustomProtocolError` for any other value. Preserve mode in any existing runtime filter wire conversion.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_custom_protocol.py -k 'filter.*mode or single_select' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ccusage_viz/custom_models.py src/ccusage_viz/custom_protocol.py tests/test_custom_protocol.py
git commit -m "feat: support single-select dataset filters"
```

### Task 2: Implement single-select mutations and accepted tab counts

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Modify: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Produces: `CustomFilterDraft.toggle(filter: CustomFilter, option_id: str) -> CustomFilterDraft`.
- Produces: `filter_tab_counts(accepted: CustomFilters, choices: tuple[CustomFilter, ...]) -> tuple[tuple[int, int], ...]`.
- `toggle` uses the Filter's declared mode; `filter_tab_counts` counts selected IDs visible in each de-duplicated option list.

- [ ] **Step 1: Write failing draft behavior tests**

```python
def test_single_select_space_replaces_then_clears_the_draft_value() -> None:
    choice = filter_choice("seed_book", mode="single_select", options=("a", "b"))
    draft = CustomFilterDraft((("seed_book", ("a",)),))

    assert draft.toggle(choice, "b").filters == (("seed_book", ("b",)),)
    assert draft.toggle(choice, "b").filters == ()


def test_multi_select_preserves_existing_toggle_behavior() -> None:
    choice = filter_choice("language", mode="multi_select", options=("go", "python"))
    draft = CustomFilterDraft((("language", ("go",)),))

    assert draft.toggle(choice, "python").filters == (("language", ("go", "python")),)


def test_tab_counts_describe_accepted_filters_not_draft_filters() -> None:
    choice = filter_choice("language", options=("go", "python", "rust"))
    accepted = (("language", ("go",)),)
    draft = CustomFilterDraft(accepted).toggle(choice, "python")

    assert filter_tab_counts(accepted, (choice,)) == ((1, 3),)
    assert draft.selected("language") == ("go", "python")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_filter_draft.py -k 'single_select or tab_counts or multi_select_preserves' -v`

Expected: FAIL because toggle takes an ID rather than Filter metadata and no tab-count helper exists.

- [ ] **Step 3: Implement focused immutable helpers**

Change each editor call site from `draft.toggle(current.id, option.id)` to `draft.toggle(current, option.id)`. For `single_select`, replace existing values with `(option_id,)` when selecting an unselected option; remove the filter entry when toggling the selected option. Keep sorted immutable `CustomFilters` output and current multi-select behavior.

Implement `filter_tab_counts` from accepted input. For each choice, calculate `m` from `_display_options(choice)`, and `n` by intersecting accepted selected IDs with visible option IDs. Do not count unknown selected IDs.

- [ ] **Step 4: Run focused draft tests**

Run: `uv run pytest tests/test_custom_filter_draft.py -k 'single_select or tab_counts or multi_select_preserves' -v`

Expected: PASS.

- [ ] **Step 5: Run the complete draft module tests**

Run: `uv run pytest tests/test_custom_filter_draft.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/custom_filter_draft.py tests/test_custom_filter_draft.py
git commit -m "feat: apply single-select dataset filter drafts"
```

### Task 3: Render accepted `n/m` tabs with existing theme hierarchy

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py:_render_custom_filter_draft`, editor paint boundary as needed
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Modify: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: `filter_tab_counts(accepted, choices)` from Task 2.
- Produces: a renderer argument/state holding immutable accepted filters, separate from mutable draft filters.
- Produces: tab text of `[Label n/m]` and palette-styled title/tab/count spans while retaining plain-text no-color output.

- [ ] **Step 1: Write failing rendering tests**

```python
def test_tab_rows_render_accepted_counts_without_using_unsubmitted_draft() -> None:
    rendered = render_editor(
        accepted=(("language", ("go",)),),
        draft=(("language", ("go", "python")),),
        choices=(filter_choice("language", options=("go", "python")),),
        color=False,
    )

    assert "[Language 1/2]" in rendered
    assert "Selected 2 / 2" in rendered


def test_color_rendering_distinguishes_current_tab_and_effective_nonzero_count() -> None:
    rendered = render_editor(accepted=(("language", ("go",)),), choices=two_choices(), color=True)

    assert primary_tab_ansi() in rendered
    assert secondary_count_ansi() in rendered
    assert muted_zero_count_ansi() in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_filter_draft.py -k 'tab_rows_render or color_rendering_distinguishes' -v`

Expected: FAIL because tabs contain labels only and rendering does not receive accepted filter state/palette styling.

- [ ] **Step 3: Thread immutable accepted filters through the editor**

Capture `accepted_filters = filters` at `run_custom_filter_editor` entry and never modify it. Pass it to `_render_custom_filter_draft`. Render every tab as `Label n/m`, bracket only the active one, and retain existing `clip_width` behavior. Continue rendering row two from the mutable draft so Space gives immediate active-dimension feedback.

Use the same existing theme/palette rendering helpers that color Custom editor titles, muted chrome, and emphasized text. Apply primary emphasis to the active tab/brackets and immediate draft selected count, secondary emphasis to a nonzero accepted tab count, and muted styling to inactive labels and zero counts. Keep ANSI-free output under no-color.

- [ ] **Step 4: Run rendering and regression tests**

Run: `uv run pytest tests/test_custom_filter_draft.py -v`

Expected: PASS.

- [ ] **Step 5: Run Custom TUI filter integration tests**

Run: `uv run pytest tests/test_tui_custom.py -k filter -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ccusage_viz/custom_filter_draft.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_custom_filter_draft.py
git commit -m "feat: show effective dataset filter counts"
```

### Task 4: Document filter-mode choices for Dataset authors

**Files:**
- Modify: `docs/custom-command-protocol.md`
- Modify: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/dataset-developer-guide.md`
- Modify: `docs/dataset-developer-guide.zh-CN.md`

**Interfaces:**
- Documents the implementation from Tasks 1–3; no new executable interface.

- [ ] **Step 1: Document mode and wire compatibility**

Add `single_select` beside existing `multi_select` runtime filter documentation. State that an omitted mode defaults to multi-select and filter requests retain the array-of-option-ID wire shape.

- [ ] **Step 2: Add authoring guidance in both languages**

State exactly: prefer `single_select` for mutually exclusive modes and understandable ranges such as `Within 7 days`, `Within 30 days`, and `Any time`; choosing several ranges is ambiguous and difficult to present. Use `multi_select` only when users genuinely combine discrete dimension values such as languages, categories, tags, authors, or shelf labels.

- [ ] **Step 3: Verify documentation and links**

Run: `git diff --check && rg -n 'single_select|7 days|7 天' docs/custom-command-protocol* docs/dataset-developer-guide*`

Expected: both language variants describe mode compatibility and authoring guidance.

- [ ] **Step 4: Commit**

```bash
git add docs/custom-command-protocol.md docs/custom-command-protocol.zh-CN.md docs/dataset-developer-guide.md docs/dataset-developer-guide.zh-CN.md
git commit -m "docs: guide dataset filter selection modes"
```

### Task 5: Final verification

**Files:**
- Test only unless a discovered regression requires a focused fix.

- [ ] **Step 1: Run all Custom filter and protocol tests**

Run: `uv run pytest tests/test_custom_filter_draft.py tests/test_custom_protocol.py tests/test_tui_custom.py -q`

Expected: PASS.

- [ ] **Step 2: Run configured lint and type checks**

Run: `uv run ruff check src tests && uv run ty check src`

Expected: PASS. If `ty` is not configured, run its available project-equivalent check and report the exact command.

- [ ] **Step 3: Inspect final state**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and no unrelated modified files.
