# CLI Subcommand Error Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve invalid-subcommand diagnostics by listing commands supported at the failing level and, for a strong unique spelling match, suggesting the intended command.

**Architecture:** Keep parsing, default-command injection, namespace construction, launch conversion, routing, and execution unchanged. Enrich only `UsageError` instances produced by already-failing subcommand parses: parser-level metadata handles `chart` and `dataset`, while `main()` uses the untouched raw argv only to relabel the existing failed default-route parse as a top-level command typo.

**Tech Stack:** Python 3.11+, `argparse`, `difflib`, existing `UsageError`/`Translator` localization pipeline, pytest, uv, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-10-17-cli-subcommand-error-guidance-design.md`

## Global Constraints

- This is a diagnostic-only change: every argv sequence that currently parses successfully must produce the same namespace, launch configuration, route, side effects, and exit behavior.
- Do not change `_inject_default_command()`, `_to_options()`, `_route()`, `application.run()`, or any command handler.
- Never execute a suggested command and never silently correct argv.
- Only invalid subcommands receive command lists; invalid options, invalid option values, missing values, semantic validation errors, and help output remain unchanged.
- Command order is stable and follows the public parser declarations: top level `chart, dashboard, animate, dataset, text`; chart `timeline, calendar, stack, ranking, monitor`; Dataset `list, add-local`.
- English and Chinese labels are localized; literal command names are unchanged.
- Do not modify or commit the user's existing `README.md` and `README.zh-CN.md` changes.

---

## File Map

- `src/ccusage_viz/cli.py` — owns command declarations, argparse construction, failed-parse diagnostic enrichment, and `main()` stderr behavior.
- `src/ccusage_viz/locales/en.py` — English multiline invalid-subcommand diagnostics.
- `src/ccusage_viz/locales/zh.py` — Chinese multiline invalid-subcommand diagnostics.
- `tests/test_cli.py` — parser-level, `main()`-level, localization, and successful-routing regression coverage.

No new production module is warranted: the behavior is CLI-parser-specific and uses the command tuples already owned by `cli.py`.

---

### Task 1: Add structured nested-subcommand diagnostics

**Files:**
- Modify: `src/ccusage_viz/cli.py:79-135,376-460`
- Modify: `src/ccusage_viz/locales/en.py:217`
- Modify: `src/ccusage_viz/locales/zh.py:217`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_TUI_COMMANDS: tuple[str, ...]`, `_DATASET_COMMANDS: tuple[str, ...]`, `UsageError`, and argparse's invalid-choice callback.
- Produces: `LocalizedParser.set_subcommand_choices(choices: tuple[str, ...]) -> None`; `_invalid_subcommand_error(detail: str, rejected: str, choices: tuple[str, ...]) -> UsageError`.
- Preserves: `LocalizedParser.error(message: str) -> Never` still raises exit-code-2 `UsageError`; non-subcommand parser failures still use `error.arguments` with the original `detail`.

- [ ] **Step 1: Write failing parser-level tests**

Add focused tests to `tests/test_cli.py` that inspect the structured error and formatted English/Chinese text:

```python
from ccusage_viz.diagnostics import format_error


def test_invalid_chart_kind_lists_only_chart_kinds_and_suggests_match() -> None:
    tr = load_translator("en")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timline"])

    assert caught.value.key == "error.invalid_subcommand_suggestion"
    text = format_error(caught.value, tr)
    assert "argument KIND: invalid choice: 'timline'" in text
    assert "Supported commands: timeline, calendar, stack, ranking, monitor" in text
    assert "Did you mean 'timeline'?" in text
    assert "dashboard" not in text


def test_invalid_dataset_operation_lists_only_dataset_operations() -> None:
    tr = load_translator("en")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["dataset", "unknown-operation"])

    text = format_error(caught.value, tr)
    assert caught.value.key == "error.invalid_subcommand"
    assert "Supported commands: list, add-local" in text
    assert "Did you mean" not in text
    assert "timeline" not in text


def test_invalid_chart_kind_guidance_is_localized_in_chinese() -> None:
    tr = load_translator("zh")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timline"])

    text = format_error(caught.value, tr)
    assert "支持的命令：timeline, calendar, stack, ranking, monitor" in text
    assert "你是不是想输入 'timeline'？" in text


def test_invalid_option_value_does_not_gain_subcommand_guidance() -> None:
    tr = load_translator("en")
    parser = build_parser(tr)

    with pytest.raises(UsageError) as caught:
        parser.parse_args(["chart", "timeline", "--density", "standard"])

    assert caught.value.key == "error.arguments"
    assert "Supported commands" not in format_error(caught.value, tr)
```

If the repository's established Chinese phrasing differs after reviewing nearby locale entries, keep the assertion and locale message consistent while preserving the exact meaning.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
uv run pytest \
  tests/test_cli.py::test_invalid_chart_kind_lists_only_chart_kinds_and_suggests_match \
  tests/test_cli.py::test_invalid_dataset_operation_lists_only_dataset_operations \
  tests/test_cli.py::test_invalid_chart_kind_guidance_is_localized_in_chinese \
  tests/test_cli.py::test_invalid_option_value_does_not_gain_subcommand_guidance -q
```

Expected: the first three tests fail because errors still use `error.arguments`; the invalid-option regression already passes.

- [ ] **Step 3: Add localized diagnostic templates**

Add adjacent to `error.arguments` in both locale catalogs:

```python
# en.py
"error.invalid_subcommand": "Invalid arguments: {detail}\nSupported commands: {commands}",
"error.invalid_subcommand_suggestion": (
    "Invalid arguments: {detail}\nSupported commands: {commands}\nDid you mean '{suggestion}'?"
),

# zh.py
"error.invalid_subcommand": "参数无效：{detail}\n支持的命令：{commands}",
"error.invalid_subcommand_suggestion": (
    "参数无效：{detail}\n支持的命令：{commands}\n你是不是想输入 '{suggestion}'？"
),
```

Do not modify `error.arguments`; ordinary diagnostics depend on it.

- [ ] **Step 4: Implement the minimal parser metadata and suggestion helper**

In `src/ccusage_viz/cli.py`, import `get_close_matches` from `difflib`, add the Dataset tuple beside the existing command tuples, and implement:

```python
_DATASET_COMMANDS = ("list", "add-local")


def _invalid_subcommand_error(
    detail: str,
    rejected: str,
    choices: tuple[str, ...],
) -> UsageError:
    matches = get_close_matches(rejected, choices, n=2, cutoff=0.7)
    values: dict[str, object] = {
        "detail": detail,
        "commands": ", ".join(choices),
    }
    if len(matches) == 1:
        values["suggestion"] = matches[0]
        return UsageError("error.invalid_subcommand_suggestion", **values)
    return UsageError("error.invalid_subcommand", **values)
```

Extend `LocalizedParser` with parser-local subcommand choices and a narrowly bounded invalid-choice extractor:

```python
class LocalizedParser(argparse.ArgumentParser):
    _subcommand_choices: tuple[str, ...] = ()

    def set_subcommand_choices(self, choices: tuple[str, ...]) -> None:
        self._subcommand_choices = choices

    def error(self, message: str) -> Never:
        rejected = _rejected_subcommand(message, self._subcommand_choices)
        if rejected is not None:
            raise _invalid_subcommand_error(message, rejected, self._subcommand_choices)
        raise UsageError("error.arguments", detail=message)
```

Implement `_rejected_subcommand()` with a full-match regular expression constrained by the configured metavar and current choices, not a general parser for arbitrary argparse prose. It must return `None` for `--density` invalid-choice text and malformed/unexpected messages. Use `ast.literal_eval()` for argparse's quoted rejected token rather than stripping quotes manually, and accept only a resulting `str`.

After creating parser groups in `build_parser()`, configure only the parsers that own nested subcommands:

```python
chart.set_subcommand_choices(_TUI_COMMANDS)
dataset.set_subcommand_choices(_DATASET_COMMANDS)
```

Create Dataset subparsers from `_DATASET_COMMANDS` values (or assert the explicit declarations equal that tuple) so the displayed list cannot drift from parser behavior. Do not configure leaf chart parsers, since option-value errors on those parsers must remain generic.

- [ ] **Step 5: Run focused tests and the existing CLI suite**

Run:

```bash
uv run pytest \
  tests/test_cli.py::test_invalid_chart_kind_lists_only_chart_kinds_and_suggests_match \
  tests/test_cli.py::test_invalid_dataset_operation_lists_only_dataset_operations \
  tests/test_cli.py::test_invalid_chart_kind_guidance_is_localized_in_chinese \
  tests/test_cli.py::test_invalid_option_value_does_not_gain_subcommand_guidance -q
uv run pytest tests/test_cli.py -q
```

Expected: all tests pass. Existing assertions for `error.arguments` on option and semantic failures remain unchanged.

- [ ] **Step 6: Commit Task 1 without unrelated README changes**

```bash
git add src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
git commit -m "fix: clarify nested subcommand errors"
```

Before committing, verify `git diff --cached --name-only` does not include either README.

---

### Task 2: Enrich failed top-level typos without changing routing

**Files:**
- Modify: `src/ccusage_viz/cli.py:526-540,1252-1305`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_invalid_subcommand_error(detail, rejected, _COMMANDS)`, raw `argv`, the unchanged result of `_inject_default_command(raw_args)`, and the `UsageError` already raised by `parser.parse_args(args)`.
- Produces: `_top_level_typo(raw_args: list[str], error: UsageError) -> UsageError`, returning either the exact input error object or a replacement diagnostic error.
- Preserves: no change to `_inject_default_command()`; `main()` calls `parser.parse_args(args)` with exactly the same `args` as before.

- [ ] **Step 1: Write failing screenshot-case and no-behavior-change tests**

Add these tests to `tests/test_cli.py`:

```python
def test_main_top_level_typo_lists_commands_and_suggests_dashboard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["dashbaord", "--lang", "en"]) == 2

    error = capsys.readouterr().err
    assert "unrecognized arguments: dashbaord" in error
    assert "Supported commands: chart, dashboard, animate, dataset, text" in error
    assert "Did you mean 'dashboard'?" in error


def test_main_top_level_typo_honors_leading_language_option(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--lang", "zh", "dashbaord"]) == 2

    error = capsys.readouterr().err
    assert "支持的命令：chart, dashboard, animate, dataset, text" in error
    assert "你是不是想输入 'dashboard'？" in error


def test_distant_top_level_failure_lists_commands_without_suggestion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["nonsense", "--lang", "en"]) == 2

    error = capsys.readouterr().err
    assert "Supported commands: chart, dashboard, animate, dataset, text" in error
    assert "Did you mean" not in error


def test_option_led_default_chart_route_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(
        "ccusage_viz.cli.run",
        lambda launch, _tr: captured.append(launch) or 0,
    )

    assert main(["--demo", "small", "--lang", "en"]) == 0
    assert len(captured) == 1
    assert isinstance(captured[0], StandaloneLaunch)
```

Also add a direct regression table proving `_inject_default_command()` remains byte-for-byte behaviorally unchanged for representative public forms:

```python
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--period", "14d"], ["chart", "timeline", "--period", "14d"]),
        (["chart", "ranking"], ["chart", "ranking"]),
        (["dashboard"], ["dashboard"]),
        (["dataset", "list"], ["dataset", "list"]),
        (["dashbaord"], ["chart", "timeline", "dashbaord"]),
    ],
)
def test_subcommand_guidance_does_not_change_default_injection(
    argv: list[str], expected: list[str]
) -> None:
    assert _inject_default_command(argv) == expected
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```bash
uv run pytest \
  tests/test_cli.py::test_main_top_level_typo_lists_commands_and_suggests_dashboard \
  tests/test_cli.py::test_main_top_level_typo_honors_leading_language_option \
  tests/test_cli.py::test_distant_top_level_failure_lists_commands_without_suggestion \
  tests/test_cli.py::test_option_led_default_chart_route_is_unchanged \
  tests/test_cli.py::test_subcommand_guidance_does_not_change_default_injection -q
```

Expected: diagnostic tests fail because the current injected default route reports only `unrecognized arguments`; routing and injection regression tests pass before implementation.

- [ ] **Step 3: Implement post-failure top-level enrichment**

Do not add a pre-parse early return. Add a helper that is called only after `parser.parse_args(args)` has raised `UsageError`:

```python
def _top_level_typo(raw_args: list[str], error: UsageError) -> UsageError:
    if error.key != "error.arguments":
        return error
    remaining = list(raw_args)
    while len(remaining) >= 2 and remaining[0] == "--lang":
        remaining = remaining[2:]
    if not remaining:
        return error
    rejected = remaining[0]
    if rejected.startswith("-") or rejected in _COMMANDS or rejected in _TUI_COMMANDS:
        return error
    detail = error.values.get("detail")
    if not isinstance(detail, str) or f"unrecognized arguments: {rejected}" not in detail:
        return error
    return _invalid_subcommand_error(detail, rejected, _COMMANDS)
```

Keep `args = _inject_default_command(raw_args)` and parser invocation unchanged. Wrap only the parse call so a failed parse can be enriched and re-raised into the existing outer `except VizError` formatter:

```python
try:
    namespace = parser.parse_args(args)
except UsageError as error:
    raise _top_level_typo(raw_args, error) from error
```

The helper must return the original object for uncertain cases. In particular, it must not classify option-led invocations, valid top-level commands, bare compatibility chart kinds, or any failure whose original detail does not name the same rejected raw token as an unrecognized argument.

- [ ] **Step 4: Run focused and full CLI tests**

Run:

```bash
uv run pytest \
  tests/test_cli.py::test_main_top_level_typo_lists_commands_and_suggests_dashboard \
  tests/test_cli.py::test_main_top_level_typo_honors_leading_language_option \
  tests/test_cli.py::test_distant_top_level_failure_lists_commands_without_suggestion \
  tests/test_cli.py::test_option_led_default_chart_route_is_unchanged \
  tests/test_cli.py::test_subcommand_guidance_does_not_change_default_injection -q
uv run pytest tests/test_cli.py tests/test_application.py -q
```

Expected: all pass; successful default route reaches the monkeypatched runtime once, and invalid commands still exit 2 without executing runtime code.

- [ ] **Step 5: Manually verify exact CLI output**

Run:

```bash
uv run ccuv dashbaord --lang en 2>&1; test ${PIPESTATUS[0]} -eq 2
uv run ccuv chart timline --lang en 2>&1; test ${PIPESTATUS[0]} -eq 2
uv run ccuv dataset unknown-operation --lang zh 2>&1; test ${PIPESTATUS[0]} -eq 2
uv run ccuv chart timeline --density invalid --lang en 2>&1; test ${PIPESTATUS[0]} -eq 2
```

Expected:

- the first output lists top-level commands and suggests `dashboard`;
- the second lists only chart kinds and suggests `timeline`;
- the third lists only `list, add-local` in Chinese and has no weak suggestion;
- the fourth remains the ordinary one-line invalid-choice diagnostic with no supported-command line.

- [ ] **Step 6: Commit Task 2 without unrelated README changes**

```bash
git add src/ccusage_viz/cli.py tests/test_cli.py
git commit -m "fix: clarify top-level command typos"
```

Before committing, verify `git diff --cached --name-only` does not include either README.

---

### Task 3: Run final regression and static checks

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: evidence that diagnostics changed without altering successful command implementation.

- [ ] **Step 1: Run the complete test suite**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run formatting, lint, and type checks**

```bash
uv run ruff format --check src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
uv run ruff check src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
uv run ty check
```

Expected: all commands pass. Do not add broad suppressions. If `ty check` exposes a pre-existing unrelated baseline, record the exact diagnostics and confirm no changed file introduces a new one.

- [ ] **Step 3: Verify scope and working tree**

```bash
git diff --check
git status --short
git log -4 --oneline
```

Expected: no whitespace errors; feature commits contain only CLI, locale, and test changes. The pre-existing uncommitted `README.md` and `README.zh-CN.md` changes remain present and untouched.

- [ ] **Step 4: Commit only if checks required a targeted fix**

If and only if a check required a feature-scoped correction:

```bash
git add src/ccusage_viz/cli.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_cli.py
git commit -m "test: complete subcommand guidance coverage"
```

Do not create an empty commit and do not stage README files.
