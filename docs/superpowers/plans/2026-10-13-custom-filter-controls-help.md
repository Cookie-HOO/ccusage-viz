# Custom Filter Single-Line Controls and Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Dataset Custom filter controls to one width-safe row, reserve `h` for an in-editor help page, and use only arrows for horizontal filter switching while preserving `j`/`k` option movement.

**Architecture:** `custom_filter_draft.py` will own one pure formatter for a three-section footer and ephemeral help visibility in the editor loop. Localized strings provide semantic left/middle/right sections and help rows; every host continues receiving the unchanged `paint(body, controls)` interface with an already bounded one-line footer.

**Tech Stack:** Python 3.12+, dataclasses, terminal display-width helpers, localized dictionaries, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-13-custom-filter-controls-help-design.md`

## Global Constraints

- Change Dataset/Custom filtering only; do not modify native `filter_draft.py` or Dashboard global help.
- The footer always occupies exactly one physical terminal row and never exceeds the supplied display width.
- Preserve both footer ends and replace omitted middle actions with one ellipsis.
- Left/Right arrows switch filter dimensions; plain `h`/`l` do not.
- Up/Down arrows and `j`/`k` move through options.
- Search editing, toggle, clear, columns, Apply, Cancel, mouse, paste, tab wrapping, and repaint behavior remain unchanged.
- Filter help is ephemeral and must not modify or reset any draft state.

---

## File Structure

- Modify `src/ccusage_viz/custom_filter_draft.py`: format width-bounded footer sections, route updated keys, and render/handle ephemeral help.
- Modify `src/ccusage_viz/locales/en.py`: add concise English footer sections, help rows, and back control.
- Modify `src/ccusage_viz/locales/zh.py`: add equivalent Chinese strings.
- Modify `tests/test_custom_filter_draft.py`: cover width guarantees, key routing, search precedence, help lifecycle, ignored help events, and state preservation.
- Modify `tests/test_i18n.py` only if its locale-key parity fixture requires explicit updates.

### Task 1: Width-safe one-line filter controls

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_filter_draft.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `clip_width()`, `display_width()`, localized left/middle/right control sections, and editor `width`.
- Produces: `_custom_filter_controls(translator: Translator, width: int, *, help_visible: bool = False) -> str`, always one line with display width `<= width`.

- [ ] **Step 1: Add failing footer formatting tests**

Add direct tests for wide English output and narrow English/Chinese output. Assert the narrow line begins with its localized `h Help` section, ends with localized `Enter Apply · Esc Cancel`, contains exactly one `…`, contains no newline, and satisfies `display_width(result) <= width`.

```python
@pytest.mark.parametrize("language", ("en", "zh"))
def test_custom_filter_controls_preserve_ends_without_wrapping(language: str) -> None:
    controls = _custom_filter_controls(load_translator(language), 58)
    assert controls.count("…") == 1
    assert "\n" not in controls
    assert display_width(controls) <= 58
```

Use widths large enough to preserve both required semantic ends; add one very narrow fallback assertion that checks only no newline and bounded width.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_custom_filter_draft.py -k 'controls_preserve or controls_full' -v`

Expected: FAIL because `_custom_filter_controls` and section locale keys do not exist.

- [ ] **Step 3: Add localized semantic control sections**

Add matching keys in both locales:

```python
"status.custom_filter_controls_left": "h Help · ←/→ switch filter",
"status.custom_filter_controls_middle": "↑/↓ or j/k select · / search · Space toggle · c clear current · C columns",
"status.custom_filter_controls_right": "Enter apply · Esc cancel",
"status.custom_filter_help_back": "h/Esc back",
```

Provide idiomatic Chinese equivalents while retaining the same shortcut tokens. Remove use of the old monolithic `status.custom_filter_controls`; delete it if no callers remain.

- [ ] **Step 4: Implement the one-line formatter and route it through paint**

Construct the full line as `left · middle · right`. If it fits, return it unchanged. If not, reserve the complete left, ` · … · ` marker, and complete right, omitting the middle. If those ends still exceed width, use display-width-safe middle truncation as the final narrow-terminal fallback. Never use Python string slicing for terminal width.

Change `run_custom_filter_editor()` to pass `_custom_filter_controls(translator, width)` instead of the monolithic locale text.

- [ ] **Step 5: Run footer and locale tests**

Run: `uv run pytest tests/test_custom_filter_draft.py -k controls -v && uv run pytest tests/test_i18n.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the standalone footer change**

```bash
git add src/ccusage_viz/custom_filter_draft.py src/ccusage_viz/locales/en.py \
  src/ccusage_viz/locales/zh.py tests/test_custom_filter_draft.py tests/test_i18n.py
git commit -m "fix: bound custom filter controls"
```

### Task 2: Filter key simplification and in-editor help

**Files:**
- Modify: `src/ccusage_viz/custom_filter_draft.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_filter_draft.py`

**Interfaces:**
- Consumes: Task 1 `_custom_filter_controls(...)`, immutable `CustomFilterDraft`, current renderer, and `run_custom_filter_editor()` event loop.
- Produces: localized `_render_custom_filter_help(translator: Translator, width: int, height: int) -> str` and ephemeral `help_visible: bool` local editor state.

- [ ] **Step 1: Write failing horizontal-navigation tests**

Drive the editor with Right-arrow then Space and assert the second filter changes. Drive a separate editor with plain `l`, Space, Enter and assert the first filter changes, proving `l` no longer switches dimensions. Retain existing `j`/`k` and arrow vertical tests.

```python
def test_custom_filter_editor_switches_tabs_only_with_horizontal_arrows() -> None:
    # Right arrow selects Source; plain l remains on Category.
```

- [ ] **Step 2: Write failing help and search-precedence tests**

Capture painted frames while sending `h`, an ignored ordinary key/mouse event, then `h` to return and Enter to apply. Assert:

- help body includes the localized complete shortcut rows;
- help footer is `_custom_filter_controls(..., help_visible=True)` and remains one row/within width;
- ignored help events do not change draft values or focus;
- returning restores the same active filter, option, query, columns, viewport, and unsubmitted selection;
- sending `/`, `h`, Enter while search editing paints `Search: h` and never opens help.

Add an Escape-help-return case followed by a second Escape to confirm the first closes help and the second retains existing editor cancellation semantics.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `uv run pytest tests/test_custom_filter_draft.py -k 'horizontal_arrows or filter_help or search_h' -v`

Expected: FAIL because `h/l` still switch tabs and no filter-help state/renderer exists.

- [ ] **Step 4: Implement localized filter help rendering**

Add matching English/Chinese help title and action-row keys covering:

- `←/→` filter switching;
- `↑/↓ or j/k` selection;
- `/`, printable input, Backspace, Enter, and Escape search behavior;
- Space toggle, `c` clear current, `C` columns;
- Enter Apply and Escape Cancel;
- `h/Esc` return.

Implement `_render_custom_filter_help()` as clipped localized rows, joined with newlines and limited to `height` rows. It must not inspect or mutate the draft.

- [ ] **Step 5: Implement ephemeral help routing and simplify keys**

Initialize `help_visible = False` beside `draft`. At the top of each loop, paint either help or the normal draft with the corresponding width-bounded footer. Preserve Ctrl-C handling. While help is visible, only `h` and Escape close it; ignore mouse, paste, and all other keys. Because search editing dispatch remains before normal `h`, printable `h` continues to append to the query. Outside search/help, map only Left/Right arrows to `move_filter`; remove plain `h`, plain `l`, and Tab from horizontal switching unless Tab is explicitly retained by existing requirements (the approved design does not retain it).

- [ ] **Step 6: Run all filter and locale tests**

Run: `uv run pytest tests/test_custom_filter_draft.py tests/test_i18n.py -q`

Expected: PASS.

- [ ] **Step 7: Run Custom host regressions**

Run: `uv run pytest tests/test_tui_custom.py tests/test_custom_monitor.py -q`

Expected: PASS; host callback interfaces are unchanged.

- [ ] **Step 8: Commit the help/key behavior**

```bash
git add src/ccusage_viz/custom_filter_draft.py src/ccusage_viz/locales/en.py \
  src/ccusage_viz/locales/zh.py tests/test_custom_filter_draft.py tests/test_i18n.py
git commit -m "feat: add custom filter help"
```

## Self-Review

- **Spec coverage:** Task 1 guarantees a one-row width-bounded footer with preserved semantic ends in both locales. Task 2 reserves `h`, removes `h/l` and Tab dimension switching, retains arrows and `j/k`, implements isolated help, preserves search precedence and draft state, and keeps host APIs unchanged.
- **Placeholder scan:** Every behavior has an explicit test shape, implementation target, command, and expected result; no deferred requirements remain.
- **Type consistency:** `_custom_filter_controls()` is produced in Task 1 and consumed by both normal/help painting in Task 2; `_render_custom_filter_help()` is pure and receives only translator and geometry.
