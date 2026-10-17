# CLI Preset Error Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give invalid Dashboard and Text presets the same localized supported-item list and unique close-match suggestion style as invalid subcommands.

**Architecture:** Generalize the existing diagnostic helper with a command/preset kind while retaining the same matching rules and original error detail. Text attaches static positional-choice metadata to its parser; Dashboard reuses one successful user-preset store load to resolve exact user presets and build merged built-in/user candidates only for the existing unknown-preset failure.

**Tech Stack:** Python 3.11+, argparse, difflib, existing UsageError/Translator pipeline, DashboardPresetStore, pytest, uv, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-10-17-cli-preset-error-guidance-design.md`

## Global Constraints

- Diagnostic-only: successful namespace, preset selection, launch, route, side effects, and exit behavior remain unchanged.
- Do not add argparse choices to Dashboard presets because user presets are dynamic.
- Do not automatically substitute or execute suggestions.
- Built-in candidates retain `DASHBOARD_PRESETS` insertion order; user candidates retain store order and follow built-ins; duplicates appear once.
- Corrupt/unreadable storage keeps existing storage error behavior; valid built-ins remain usable despite corrupt user storage.
- Text option errors remain ordinary argument errors.
- Do not touch or stage existing README or unrelated documentation changes.

---

### Task 1: Generalize guidance and align Text preset errors

**Files:**
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Add `_TEXT_PRESETS = ("time-state",)` and use it as both parser choices and diagnostic metadata.
- Generalize `_invalid_subcommand_error(detail, rejected, choices)` into `_invalid_choice_error(detail, rejected, choices, *, kind: Literal["command", "preset"]) -> UsageError`, or an equivalent typed enum design.
- Extend `LocalizedParser.set_subcommand_choices` into item metadata that includes exact metavar and diagnostic kind; existing chart/dataset behavior and messages must remain byte-for-byte equivalent.

- [ ] **Step 1: Add failing tests**

Add tests asserting:

```python
def test_invalid_text_preset_lists_presets_and_suggests_match() -> None:
    tr = load_translator("en")
    with pytest.raises(UsageError) as caught:
        build_parser(tr).parse_args(["text", "time-stte"])
    text = format_error(caught.value, tr)
    assert "Supported presets: time-state" in text
    assert "Did you mean 'time-state'?" in text


def test_invalid_text_preset_guidance_is_localized_in_chinese() -> None:
    tr = load_translator("zh")
    with pytest.raises(UsageError) as caught:
        build_parser(tr).parse_args(["text", "time-stte"])
    text = format_error(caught.value, tr)
    assert "支持的预设：time-state" in text
    assert "你是不是想输入 'time-state'？" in text


def test_invalid_text_option_value_has_no_preset_guidance() -> None:
    tr = load_translator("en")
    with pytest.raises(UsageError) as caught:
        build_parser(tr).parse_args(["text", "time-state", "--lang", "bad"])
    assert caught.value.key == "error.arguments"
    assert "Supported presets" not in format_error(caught.value, tr)
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/test_cli.py -k 'invalid_text_preset or invalid_text_option' -q
```

Expected: preset guidance tests fail; unrelated option regression passes.

- [ ] **Step 3: Implement preset-kind localization and parser metadata**

Add locale keys parallel to command keys:

```python
# English
"error.invalid_preset": "Invalid arguments: {detail}\nSupported presets: {choices}",
"error.invalid_preset_suggestion": (
    "Invalid arguments: {detail}\nSupported presets: {choices}\nDid you mean '{suggestion}'?"
),

# Chinese
"error.invalid_preset": "参数无效：{detail}\n支持的预设：{choices}",
"error.invalid_preset_suggestion": (
    "参数无效：{detail}\n支持的预设：{choices}\n你是不是想输入 '{suggestion}'？"
),
```

Generalize the helper without changing cutoff `0.7`, `n=2`, or unique-match behavior. Preserve existing command message keys/placeholder names or update all callers and tests consistently. Configure only the `text` parser's `preset` positional as preset-kind metadata and use `_TEXT_PRESETS` for its choices.

- [ ] **Step 4: Run CLI tests and static checks**

```bash
uv run pytest tests/test_cli.py -q
uv run ruff format --check src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
uv run ruff check src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
```

Expected: all pass; existing command guidance output is unchanged.

- [ ] **Step 5: Commit only feature files**

```bash
git add src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
git commit -m "fix: align text preset errors"
```

---

### Task 2: Add dynamic Dashboard preset guidance

**Files:**
- Modify: `src/ccusage_viz/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Add `_dashboard_preset_choices(user_names: tuple[str, ...]) -> tuple[str, ...]` returning stable deduplicated `(*DASHBOARD_PRESETS, *user_names)`.
- Reuse `_invalid_choice_error(..., kind="preset")` from Task 1.
- Within `_to_options`, load/list user records once for a non-null named preset, resolve the matching record from that tuple, and use the same tuple only if the final built-in lookup also fails.

- [ ] **Step 1: Add failing Dashboard tests**

Cover exact behavior with tests that monkeypatch `dashboard_preset_state_root` to isolated `tmp_path`:

```python
def test_unknown_dashboard_preset_lists_builtins_and_suggests_match(tmp_path, monkeypatch):
    monkeypatch.setattr("ccusage_viz.cli.dashboard_preset_state_root", lambda: tmp_path)
    with pytest.raises(UsageError) as caught:
        _to_options(build_parser(load_translator("en")).parse_args(["dashboard", "wid-clock"]))
    text = format_error(caught.value, load_translator("en"))
    assert "Supported presets: " + ", ".join(DASHBOARD_PRESETS) in text
    assert "Did you mean 'wide-clock'?" in text
```

Also add tests that:

- save `my-dashbord`, reject `my-dashboard`, and assert the saved name appears after built-ins and is suggested;
- save a record with a built-in name and assert that name occurs once in the supported-list line;
- reject a distant value and assert no suggestion;
- preserve the existing corrupt-store error key/detail;
- successfully load one existing built-in and one saved user preset unchanged;
- monkeypatch `run` to fail and call `main(["dashboard", "wid-clock", ...])`, proving runtime is not reached.

- [ ] **Step 2: Run focused tests and verify failures**

```bash
uv run pytest tests/test_cli.py -k 'dashboard_preset and (unknown or guidance or suggestion or duplicate or corrupt)' -q
```

Expected: new guidance assertions fail while existing successful/corrupt behavior passes.

- [ ] **Step 3: Implement stable candidates without changing successful behavior**

Implement stable de-duplication without sorting:

```python
def _dashboard_preset_choices(user_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*DASHBOARD_PRESETS, *user_names)))
```

For non-null `preset_name`, instantiate one store and call `list()` once. Find an exact user record from the returned tuple rather than calling `get()` and then reading again for diagnostics. Preserve exception branches:

- corrupt store + non-built-in → current `user dashboard preset storage is unavailable` error;
- corrupt store + built-in → continue with no user records;
- other store errors → current storage-unavailable error.

If no exact user record is materialized, continue through the existing built-in flow. Replace only the final `unknown dashboard preset` raise with `_invalid_choice_error` using merged choices and kind `preset`. Keep its detail exactly `unknown dashboard preset: {preset_name}`.

- [ ] **Step 4: Run focused, CLI, and application tests**

```bash
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_application.py tests/test_dashboard_presets.py tests/test_dashboard_preset_store.py -q
```

Expected: all pass; successful preset launches remain equal to previous expectations.

- [ ] **Step 5: Manually verify output**

```bash
uv run ccuv text time-stte --lang en 2>&1
uv run ccuv dashboard wid-clock --lang en 2>&1
uv run ccuv text time-state --lang invalid 2>&1
```

Expected: first two show `Supported presets` and suggestions with exit 2; third remains an ordinary one-line option error.

- [ ] **Step 6: Commit only feature files**

```bash
git add src/ccusage_viz/cli.py tests/test_cli.py
git commit -m "fix: suggest dashboard presets"
```

---

### Task 3: Final verification

**Files:** Verify only.

- [ ] **Step 1: Run all tests**

```bash
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 2: Run static checks**

```bash
uv run ruff format --check src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
uv run ruff check src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
uv run ty check
```

Expected: Ruff passes; ty introduces no diagnostics beyond the recorded 1519-diagnostic baseline.

- [ ] **Step 3: Verify scope**

```bash
git diff --check
git status --short
git log -6 --oneline
```

Expected: unrelated README/docs modifications remain unstaged and untouched; feature commits contain only CLI, locale, and test files.
