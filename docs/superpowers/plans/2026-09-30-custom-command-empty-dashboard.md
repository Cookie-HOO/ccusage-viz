# Custom Command and Empty Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add command-backed custom Timeline, Stack, Calendar, and Ranking charts; an editable empty Dashboard; and dataset-level custom Dashboard summaries without changing ccusage chart behavior.

> **Behavior amendment — 2026-10-03:** An empty pane double-click enters the normal
> pane-adjustment context rather than opening the type chooser. `r` is the
> explicit replacement entry point; `N` and `n` remain insertion entry points.
> The original checklist below is superseded only where it describes
> chooser-on-double-click behavior or tests it directly.

**Architecture:** Keep the token-specific ccusage provider, `UsageRecord` processing, and historical component intact. Add a static `custom-command` provider that produces typed, Decimal-native custom protocol payloads consumed by a sibling custom historical component and projection path. Model `empty` as a real pane config/runtime pane, then route explicit replacement and insertion through one shared pane chooser and custom-source form.

**Tech Stack:** Python 3.12, `asyncio` subprocesses, `Decimal`, argparse, Rich terminal rendering, pytest, existing QueryRuntime/QueryCoordinator lifecycle.

**Spec:** `docs/superpowers/specs/2026-09-30-custom-command-dashboard-design.md`

## Global Constraints

- Protocol version is exactly `ccuv.custom/v1`.
- Run every external command from `shlex.split()` argv with `shell=False`; send one UTF-8 JSON request through stdin, close stdin, accept one UTF-8 JSON response through stdout, and use stderr only as bounded diagnostics.
- All custom measurement values are decimal strings parsed as `Decimal`; reject JSON numeric values, `NaN`, `Infinity`, empty strings, and scientific notation.
- Custom v1 accepts additive measurements only; command computes date filtering, business filtering, grouping, and date-bucket aggregation; ccuv computes ordering, Top N, Other, cumulative display, and rendering.
- Every successful response provides complete capabilities and separately localized `en` and `zh-CN` text for all visible labels.
- Do not add a completed-result cache, interval/range union, request batching, dynamic plugin discovery, source files, HTTP sources, custom monitors, or cross-dataset arithmetic.
- Preserve QueryCoordinator's exact in-flight coalescing model; custom physical identity excludes chart kind, style, theme, density, legend, Top N, Other, and pane position.
- `l` remains the chart Legend key. `L` opens command Logs and animation overlay history.
- `dashboard --empty` fills the selected/default grid with actual `empty` panes and must not initialize default ccusage panes or header work.
- Preserve ccusage CLI, charts, token summaries, dashboard presets, ordinary pane deletion/reflow, and clock-preset first-pane behavior.

---

## File Structure

### New modules

- `src/ccusage_viz/custom_protocol.py` — strict JSON wire schema, request construction, response validation, localized text and Decimal parsing, canonical request descriptors, protocol failures.
- `src/ccusage_viz/custom_models.py` — immutable Decimal-valued normalized custom data, capabilities, summary values, diagnostics, and projection-ready models.
- `src/ccusage_viz/providers/custom_command.py` — static provider compile/execute/normalize/assemble adapter for one command invocation.
- `src/ccusage_viz/custom_component.py` — custom chart lifecycle state, candidate source edits, accepted snapshots, query submission, and bounded run history.
- `src/ccusage_viz/processing/custom_historical.py` — local Top N/Other/order/cumulative projection for additive custom series.
- `tests/test_custom_protocol.py` — schema, identity, localized text, Decimal, and error response validation.
- `tests/test_custom_provider.py` — subprocess contract, timeout/cancellation/diagnostics, registry, and in-flight sharing.
- `tests/test_custom_component.py` — accepted/candidate state and projection semantics.
- `tests/test_custom_dashboard.py` — empty pane, chooser/form, dashboard summary deduplication, and custom dashboard lifecycle.

### Principal modified modules

- `src/ccusage_viz/options.py` — custom source/config/pane and empty-pane declarative types.
- `src/ccusage_viz/cli.py` — `custom` subcommands, `dashboard --empty`, and `--pane empty` / custom fragments.
- `src/ccusage_viz/acquisition.py`, `src/ccusage_viz/query/models.py`, `src/ccusage_viz/query/provider.py`, `src/ccusage_viz/bootstrap.py` — typed custom query intent and static provider registration.
- `src/ccusage_viz/configuration.py`, `src/ccusage_viz/command_copy.py` — host conversion and lossless custom/empty command serialization.
- `src/ccusage_viz/tui.py` — empty/custom runtime panes, shared pane chooser, form, logs, custom summary manager, scheduler integration, rendering, focus, history, and lifecycle.
- `src/ccusage_viz/render/*` — narrow Decimal/unit custom-display adapters only; token rendering remains unchanged.
- `src/ccusage_viz/animate.py`, `src/ccusage_viz/locales/en.py`, `src/ccusage_viz/locales/zh.py` — `L` remap and all English/Chinese UI copy.

## Task 1: Establish declarative custom and empty-pane configuration

**Files:**
- Modify: `src/ccusage_viz/options.py`
- Modify: `src/ccusage_viz/configuration.py`
- Test: `tests/test_options.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces `CustomCommandSource`, `CustomChartConfig`, `CustomChartPaneConfig`, and `EmptyPaneConfig` for later CLI, provider, component, and TUI tasks.
- `CustomCommandSource` stores `dataset_id: str` and canonical `command_argv: tuple[str, ...]`.
- `CustomChartConfig` carries a historical `kind`, source, declared custom filters, group-by, granularity, period/range, and existing local presentation fields.
- `EmptyPaneConfig` is a provider-free `PaneConfig` variant.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_custom_source_requires_slug_dataset_and_nonempty_argv() -> None:
    assert CustomCommandSource("wechat-reading", ("reader", "ccuv")).dataset_id == "wechat-reading"
    with pytest.raises(ValueError, match="dataset"):
        CustomCommandSource("", ("reader",))
    with pytest.raises(ValueError, match="command"):
        CustomCommandSource("wechat-reading", ())


def test_pane_config_union_accepts_empty_and_custom() -> None:
    empty = EmptyPaneConfig()
    custom = CustomChartPaneConfig(chart=make_custom_timeline())
    assert pane_kind(empty) == "empty"
    assert pane_kind(custom) == "custom"
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run pytest tests/test_options.py -k 'custom or empty' -v`

Expected: FAIL because the custom and empty configuration classes do not exist.

- [ ] **Step 3: Add immutable configuration types and validation**

Implement the new frozen dataclasses alongside the existing chart/pane configuration types. Keep command argv tokenized in config; parse raw command text only in CLI/TUI form adapters. Add `EmptyPaneConfig` to the closed `PaneConfig` union, and custom historical configurations to the chart/pane conversion unions without changing built-in configuration behavior.

```python
@dataclass(frozen=True)
class CustomCommandSource:
    dataset_id: str
    command_argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("custom dataset_id must not be empty")
        if not self.command_argv:
            raise ValueError("custom command argv must not be empty")
```

- [ ] **Step 4: Add default and conversion behavior tests**

Test that a custom Timeline uses the existing Timeline default period and presentation defaults, that `EmptyPaneConfig` has no source/provider fields, and that `standalone_from_chart_pane()` preserves custom source and chart configuration.

- [ ] **Step 5: Run focused configuration tests**

Run: `uv run pytest tests/test_options.py tests/test_cli.py -k 'custom or empty' -v`

Expected: PASS.

- [ ] **Step 6: Commit the configuration foundation**

```bash
git add src/ccusage_viz/options.py src/ccusage_viz/configuration.py tests/test_options.py tests/test_cli.py
git commit -m "feat: add custom and empty pane configs"
```

## Task 2: Implement the strict custom-command protocol model

**Files:**
- Create: `src/ccusage_viz/custom_protocol.py`
- Create: `src/ccusage_viz/custom_models.py`
- Test: `tests/test_custom_protocol.py`

**Interfaces:**
- Produces `CustomPaneRequest`, `CustomDashboardSummaryRequest`, `CustomPaneResponse`, `CustomDashboardSummaryResponse`, `CustomProtocolError`, and `canonical_custom_request_key()`.
- Consumers receive exact `Decimal` custom series values, localized text, complete capabilities, summaries, and bounded protocol errors.
- `parse_custom_response(raw: bytes, request: CustomRequest) -> CustomResponse` validates echoed protocol, request ID, dataset ID, request kind, response status, localizations, capabilities, dates, and decimals.

- [ ] **Step 1: Write failing protocol validation tests**

```python
def test_pane_response_rejects_json_number_measurements() -> None:
    response = valid_pane_response(point_value=1.25)
    with pytest.raises(CustomProtocolError, match="decimal string"):
        parse_custom_response(json.dumps(response).encode(), pane_request())


def test_pane_response_accepts_exact_decimal_strings() -> None:
    response = valid_pane_response(point_value="1.25")
    result = parse_custom_response(json.dumps(response).encode(), pane_request())
    assert result.data.series[0].points[0].value == Decimal("1.25")


def test_visible_text_requires_both_locales() -> None:
    response = valid_pane_response()
    del response["dataset"]["title"]["zh-CN"]
    with pytest.raises(CustomProtocolError, match="zh-CN"):
        parse_custom_response(json.dumps(response).encode(), pane_request())
```

- [ ] **Step 2: Run protocol tests and confirm failure**

Run: `uv run pytest tests/test_custom_protocol.py -v`

Expected: FAIL because the module and parser do not exist.

- [ ] **Step 3: Define wire models and validation**

Implement constants and dataclasses for both request kinds. Serialize requests with compact deterministic JSON. Parse strings into `Decimal`, rejecting numeric JSON tokens and exponent notation. Require all visible labels to be `{ "en": str, "zh-CN": str }`. Require every successful pane response to include dataset metadata, capabilities, data, and summary; require successful dashboard-summary responses to include capabilities and metrics.

```python
PROTOCOL_VERSION = "ccuv.custom/v1"

@dataclass(frozen=True)
class LocalizedText:
    en: str
    zh_cn: str

@dataclass(frozen=True)
class CustomPoint:
    date: date
    value: Decimal
```

- [ ] **Step 4: Implement canonical physical identity tests and code**

Write tests showing equivalent Timeline/Stack/Ranking neutral queries share a key, while changes to source argv, dataset ID, normalized filter selections, group-by, granularity, date range, summary period, or as-of date do not. Assert chart kind, theme, style, density, Legend, Top N, Other, and slot position never enter the key.

- [ ] **Step 5: Add success, error, empty-data, and comparison-state tests**

Cover `ok` empty series, every stable protocol error code, `ready` with a base value, `pending`/`unavailable` without one, mismatched IDs, malformed JSON, unsupported versions, invalid date values, and duplicate/unsorted filter canonicalization.

- [ ] **Step 6: Run the protocol suite**

Run: `uv run pytest tests/test_custom_protocol.py -v`

Expected: PASS.

- [ ] **Step 7: Commit protocol types**

```bash
git add src/ccusage_viz/custom_protocol.py src/ccusage_viz/custom_models.py tests/test_custom_protocol.py
git commit -m "feat: define custom command protocol"
```

## Task 3: Add the static custom-command provider and exact coalescing

**Files:**
- Create: `src/ccusage_viz/providers/custom_command.py`
- Modify: `src/ccusage_viz/query/models.py`
- Modify: `src/ccusage_viz/query/provider.py`
- Modify: `src/ccusage_viz/acquisition.py`
- Modify: `src/ccusage_viz/bootstrap.py`
- Modify: `src/ccusage_viz/query/runtime.py` (only if type plumbing requires it)
- Test: `tests/test_custom_provider.py`
- Test: `tests/test_query_coordinator.py`
- Test: `tests/test_query_models.py`

**Interfaces:**
- Produces `CUSTOM_COMMAND_DEFINITION` with a static provider ID of `custom-command`.
- Produces `custom_historical_query_intent(config, *, owner_id, generation, trigger)` and a dashboard-summary intent constructor.
- The provider compiles canonical custom requests to one `PhysicalQuery` and returns typed custom protocol payloads.

- [ ] **Step 1: Write failing subprocess-contract tests**

```python
def test_provider_writes_one_json_request_without_shell(fake_command) -> None:
    result = run_custom_provider(fake_command, pane_request())
    assert fake_command.argv == ("collector", "ccuv")
    assert fake_command.shell is False
    assert fake_command.stdin_documents == [pane_request_json()]
    assert result.payload.dataset_id == "wechat-reading"


def test_stderr_is_diagnostic_not_protocol_output(fake_command) -> None:
    fake_command.stdout = b""
    fake_command.stderr = valid_pane_response_json()
    with pytest.raises(CustomCommandExecutionError, match="stdout"):
        run_custom_provider(fake_command, pane_request())
```

- [ ] **Step 2: Run provider tests and confirm failure**

Run: `uv run pytest tests/test_custom_provider.py -v`

Expected: FAIL because the provider is missing.

- [ ] **Step 3: Implement compile and subprocess execution**

Use the project’s existing bounded process/cancellation patterns. Start the configured argv with no shell; write one request document to stdin then close it; collect bounded stdout/stderr under timeout; terminate process trees on cancellation/timeout; reject nonzero exits unless stdout is a valid protocol error response. Pass stdout only to `parse_custom_response()` and record truncated stderr in diagnostics.

```python
async def execute(query: PhysicalQuery, cancellation: CancellationToken) -> ProviderResult:
    request = query.arguments["request"]
    process = await asyncio.create_subprocess_exec(
        *request.command_argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    process.stdin.write(request.to_json_bytes())
    await process.stdin.drain()
    process.stdin.close()
    # await bounded completion, then parse stdout exactly once
```

- [ ] **Step 4: Register the provider and create intents**

Register one definition in `build_provider_registry()`. Build `ProviderRef("custom-command", dataset_id)` intents whose physical arguments carry the canonical request model, not presentation-only fields. Ensure custom routes never call ccusage dependency checks.

- [ ] **Step 5: Add exact in-flight coalescing tests**

Use a blocking fake command and two `QueryRuntime` submissions. Assert equivalent requests start one process and both subscribers receive the result. Assert a changed date range, filter, group-by, granularity, source argv, or summary as-of starts a second process. Assert a second request after completion starts a new process.

- [ ] **Step 6: Run provider and coordinator suites**

Run: `uv run pytest tests/test_custom_provider.py tests/test_query_coordinator.py tests/test_query_models.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the provider layer**

```bash
git add src/ccusage_viz/providers/custom_command.py src/ccusage_viz/query/models.py src/ccusage_viz/query/provider.py src/ccusage_viz/query/runtime.py src/ccusage_viz/acquisition.py src/ccusage_viz/bootstrap.py tests/test_custom_provider.py tests/test_query_coordinator.py tests/test_query_models.py
git commit -m "feat: add custom command provider"
```

## Task 4: Project custom data into existing historical chart semantics

**Files:**
- Create: `src/ccusage_viz/processing/custom_historical.py`
- Create: `src/ccusage_viz/custom_component.py`
- Modify: `src/ccusage_viz/render/summary.py`
- Modify: `src/ccusage_viz/render/timeline.py`
- Modify: `src/ccusage_viz/render/stack.py`
- Modify: `src/ccusage_viz/render/calendar.py`
- Modify: `src/ccusage_viz/render/ranking.py`
- Test: `tests/test_custom_component.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces `process_custom_historical(response, config) -> CustomChartProjection`.
- Produces `CustomHistoricalComponent`, whose `submit()`, `apply_result()`, `adjust()`, and source-edit candidate behavior match the stale-result/preserve-on-error guarantees of `HistoricalChartComponent`.
- Custom chart render adapters accept Decimal/unit models without changing any token render model API.

- [ ] **Step 1: Write failing local-projection tests**

```python
def test_top_n_and_other_are_local_decimal_operations() -> None:
    projection = process_custom_historical(series_response([("a", "10"), ("b", "5"), ("c", "2")]), top_n=2, other=True)
    assert projection.series_labels == ["a", "b", "Other"]
    assert projection.series[-1].points[0].value == Decimal("2")


def test_calendar_rejects_grouped_or_non_daily_results() -> None:
    with pytest.raises(CustomProjectionError, match="calendar"):
        process_custom_historical(grouped_weekly_response(), calendar_config())
```

- [ ] **Step 2: Run projection tests and confirm failure**

Run: `uv run pytest tests/test_custom_component.py -k 'top_n or calendar' -v`

Expected: FAIL because custom projection does not exist.

- [ ] **Step 3: Implement Decimal projection rules**

Apply complete-candidate ordering by requested-range sum, local Top N, bucket-by-bucket Other aggregation, and cumulative display transformation with `Decimal`. Require a single `total` series and daily buckets for Calendar. Keep ungrouped Stack and Ranking protocol-valid. Preserve existing style restriction checks (such as grouped Timeline area incompatibility) through existing style compatibility mechanisms.

- [ ] **Step 4: Implement custom component accepted/candidate lifecycle**

Mirror existing component generation checks and scheduler-facing APIs. Keep `accepted_config`, `accepted_response`, and capabilities until a new source edit has returned a validated success. Do not submit a provider request for style, density, legend, Top N, or Other changes; do resubmit for period, filters, group-by, granularity, and source changes.

- [ ] **Step 5: Add generic custom summary rendering**

Render exact Decimal values with protocol unit placement/precision. Compute comparison direction/ratio in ccuv from current/base values, including unchanged, `from_zero`, pending, and unavailable states. Keep existing token summary formatting untouched and regression-tested.

- [ ] **Step 6: Add renderer and lifecycle regression tests**

Test Timeline, Stack, Calendar, and Ranking projections; exact decimals; local redraw calls; source edit failure preserving the old chart; fixed range summary comparisons unavailable; relative day summary behavior; and existing built-in rendering snapshots.

- [ ] **Step 7: Run component/render suites**

Run: `uv run pytest tests/test_custom_component.py tests/test_render.py tests/test_historical_component.py tests/test_summaries.py -v`

Expected: PASS.

- [ ] **Step 8: Commit chart integration**

```bash
git add src/ccusage_viz/processing/custom_historical.py src/ccusage_viz/custom_component.py src/ccusage_viz/render tests/test_custom_component.py tests/test_render.py
git commit -m "feat: render custom historical charts"
```

## Task 5: Add custom CLI, fragments, empty startup, and round-trip copy

**Files:**
- Modify: `src/ccusage_viz/cli.py`
- Modify: `src/ccusage_viz/configuration.py`
- Modify: `src/ccusage_viz/command_copy.py`
- Modify: `src/ccusage_viz/dashboard.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_terminal.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Supports `ccuv custom {timeline,stack,calendar,ranking} --dataset ID --command TEXT`.
- Supports `--pane 'empty'` and `--pane 'custom <kind> ...'`.
- `dashboard --empty` returns a layout-size list of `EmptyPaneConfig` unless explicit ordered `--pane` fragments fill positions.
- `format_full_dashboard_command()` emits explicit `--pane 'empty'` positions.

- [ ] **Step 1: Write failing parser and serialization tests**

```python
def test_custom_timeline_cli_parses_tokenized_command() -> None:
    options = parse_args(["custom", "timeline", "--dataset", "wechat-reading", "--command", "reader ccuv --account main"])
    assert options.source.command_argv == ("reader", "ccuv", "--account", "main")


def test_dashboard_copy_retains_intermediate_empty_panes() -> None:
    command = format_full_dashboard_command(dashboard_with([empty(), custom(), empty()]))
    assert command.count("--pane 'empty'") == 2
```

- [ ] **Step 2: Run parser tests and confirm failure**

Run: `uv run pytest tests/test_cli.py tests/test_terminal.py -k 'custom or empty' -v`

Expected: FAIL because commands/fragments are unsupported.

- [ ] **Step 3: Implement CLI and fragment parsing**

Add one `custom` top-level branch with subordinate historical kinds. Require `--dataset` and `--command`; tokenize commands with `shlex.split` and report invalid quoting as argparse validation errors. Extend pane-fragment parsing to accept exactly `empty` and `custom <kind> ...`; reject host-only and incompatible built-in/data-source options inside custom fragments.

- [ ] **Step 4: Implement `dashboard --empty` topology construction**

Preserve the selected/default layout and create actual empty configs for its slot count. Do not construct default ccusage panes or default header acquisition. Permit explicit ordered pane fragments to replace/append positions; retain clock preset first pane behavior exactly as it is today.

- [ ] **Step 5: Implement canonical command-copy behavior**

Serialize custom source argv with `shlex.join`; serialize each explicit empty pane as `--pane 'empty'`; keep order, grid, layout weights, host configuration, and ordinary pane serialization stable. Add parser-round-trip tests for empty/custom mixed topology.

- [ ] **Step 6: Run CLI suites**

Run: `uv run pytest tests/test_cli.py tests/test_terminal.py tests/test_tui.py -k 'custom or empty or command_copy' -v`

Expected: PASS.

- [ ] **Step 7: Commit CLI and serialization support**

```bash
git add src/ccusage_viz/cli.py src/ccusage_viz/configuration.py src/ccusage_viz/command_copy.py src/ccusage_viz/dashboard.py tests/test_cli.py tests/test_terminal.py tests/test_tui.py
git commit -m "feat: add custom dashboard commands"
```

## Task 6: Implement empty and custom Dashboard panes with the shared chooser

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/dashboard_history.py`
- Modify: `src/ccusage_viz/terminal_ui.py`
- Modify: `src/ccusage_viz/tui_input.py` (only if a reusable form primitive is needed)
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_dashboard.py`
- Test: `tests/test_tui.py`
- Test: `tests/test_dashboard_layout.py`

**Interfaces:**
- Adds `TuiEmptyPane` and `TuiCustomPane` to the runtime pane union.
- Adds one chooser workflow for explicit Replace, Insert before, and Insert after; double-click only enters pane adjustment.
- The chooser yields `Empty`, existing built-in types, or `Custom`, then custom historical kind, then a Dataset ID/Command form.

- [ ] **Step 1: Write failing empty-pane lifecycle tests**

```python
def test_empty_pane_has_two_instruction_lines_and_never_submits_query() -> None:
    pane = make_empty_tui_pane()
    assert pane.render_lines(locale="en") == [
        "Empty pane",
        "Double-click to select, then press r to choose a type",
    ]
    pane.refresh()
    assert pane.query_count == 0


def test_double_click_empty_enters_pane_adjustment() -> None:
    tui = dashboard_with_empty_pane()
    tui.handle_double_click(slot=0)
    assert tui.adjustment_mode == "pane"
    assert tui.overlay is None
    tui.handle_key("r")
    assert tui.overlay.kind == "pane_type_chooser"
```

- [ ] **Step 2: Run empty-pane tests and confirm failure**

Run: `uv run pytest tests/test_custom_dashboard.py -k 'empty or chooser' -v`

Expected: FAIL because empty runtime panes and chooser flow are absent.

- [ ] **Step 3: Add runtime empty/custom pane variants**

Make empty panes normal layout/focus/mouse/history participants with no provider, scheduler, summary, or refresh work. Render exactly the two localized lines. Add custom panes backed by `CustomHistoricalComponent`, with generation-safe refresh and shutdown behavior alongside existing chart/animation panes.

- [ ] **Step 4: Refactor pane chooser into one transactional flow**

Use one chooser order:

```text
Empty
Timeline
Stack
Calendar
Ranking
Monitor
Animate
Custom
```

Selecting Custom opens the second chooser for Timeline, Stack, Calendar, Ranking, then a form with Dataset ID and Command. Reuse existing Tab focus/edit/Enter/Escape interaction conventions. Do not mutate replace/insert topology until a custom initial query validates. On Escape/failure preserve the prior pane; when opening from an empty pane, keep it empty.

- [ ] **Step 5: Wire every creation entry point**

Route explicit Replace, Insert Before, and Insert After through the shared flow. Empty-pane double-click enters pane adjustment without opening a chooser. Allow insertion of `Empty`; preserve existing `x` behavior so deleting any pane, including empty, removes it and compact/reflows remaining panes.

- [ ] **Step 6: Add history, focus, mouse, and restoration tests**

Test empty panes are focusable via Tab, mouse-selectable, serializable, restored by dashboard history, replaceable, insertable, deletable, and leave no query operation. Test failed source form validation leaves topology unchanged; successful validation commits exactly one replacement/insertion.

- [ ] **Step 7: Run Dashboard interaction suites**

Run: `uv run pytest tests/test_custom_dashboard.py tests/test_tui.py tests/test_dashboard_layout.py -v`

Expected: PASS.

- [ ] **Step 8: Commit Dashboard pane UX**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/dashboard_history.py src/ccusage_viz/terminal_ui.py src/ccusage_viz/tui_input.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_custom_dashboard.py tests/test_tui.py tests/test_dashboard_layout.py
git commit -m "feat: add editable empty dashboard panes"
```

## Task 7: Add custom Source/Logs controls and remap animation history to `L`

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/animate.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_custom_dashboard.py`
- Test: `tests/test_animation.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Custom advanced adjustment exposes exactly Source and Logs as custom-specific controls.
- Source opens the existing-style Dataset ID/Command editor and atomically accepts only a validated source.
- `L` opens bounded custom diagnostics and animation overlay history; `l` remains chart Legend.

- [ ] **Step 1: Write failing key/action tests**

```python
def test_chart_lowercase_l_keeps_legend_behavior() -> None:
    assert adjust_chart(chart, "l").legend != chart.legend


def test_animation_history_requires_uppercase_l() -> None:
    tui = dashboard_with_animation()
    tui.handle_key("l")
    assert tui.overlay is None
    tui.handle_key("L")
    assert tui.overlay.kind == "overlay_history"


def test_custom_logs_requires_uppercase_l() -> None:
    tui = dashboard_with_custom_pane(run_diagnostics="bad response")
    tui.handle_key("L")
    assert "bad response" in tui.overlay.text
```

- [ ] **Step 2: Run key tests and confirm failure**

Run: `uv run pytest tests/test_animation.py tests/test_custom_dashboard.py tests/test_tui.py -k 'legend or logs or history' -v`

Expected: FAIL because animation still binds lowercase `l` and custom controls do not exist.

- [ ] **Step 3: Implement bounded run diagnostics and Source action**

Store timestamp, duration, command outcome category, exit status, and truncated stderr for each accepted/failed custom physical run. Expose a Source editor only in custom advanced adjustment; validate a source against the current custom query shape before atomically swapping accepted config/capabilities/data. Expose Logs as read-only existing-overlay-style diagnostics; never display raw protocol payload as logs.

- [ ] **Step 4: Remap animation overlay history**

Change the animation advanced control mapping from `l` to `L` in both `animate.py` and Dashboard key dispatch. Update both locales and help/control tables. Do not alter chart lower-case legend handling.

- [ ] **Step 5: Run diagnostics/key suites**

Run: `uv run pytest tests/test_animation.py tests/test_custom_dashboard.py tests/test_tui.py -k 'legend or logs or history or source' -v`

Expected: PASS.

- [ ] **Step 6: Commit source/log interaction**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/animate.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_animation.py tests/test_custom_dashboard.py tests/test_tui.py
git commit -m "feat: add custom source logs controls"
```

## Task 8: Add dataset-level Dashboard custom summaries

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Modify: `src/ccusage_viz/acquisition.py`
- Modify: `src/ccusage_viz/custom_component.py`
- Modify: `src/ccusage_viz/render/summary.py`
- Test: `tests/test_custom_dashboard.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Produces a Dashboard-scoped custom-summary manager keyed by dataset ID.
- Submits exactly one `dashboard_summary` request for each distinct active custom dataset per refresh cycle.
- Keeps custom summary state separate from token `DashboardHeader` and never adds its Decimal values to token totals.

- [ ] **Step 1: Write failing deduplication tests**

```python
def test_dashboard_requests_one_summary_per_dataset_per_refresh() -> None:
    tui, fake_command = dashboard_with_two_custom_panes_same_dataset()
    tui.refresh_all()
    assert fake_command.count_requests(kind="dashboard_summary", dataset="wechat-reading") == 1


def test_dashboard_keeps_datasets_and_token_header_independent() -> None:
    tui = dashboard_with_token_and_two_custom_datasets()
    tui.refresh_all()
    assert tui.token_header.total == expected_token_total
    assert set(tui.custom_summaries) == {"wechat-reading", "builds"}
```

- [ ] **Step 2: Run summary tests and confirm failure**

Run: `uv run pytest tests/test_custom_dashboard.py -k 'summary or dataset' -v`

Expected: FAIL because the Dashboard has no custom-summary manager.

- [ ] **Step 3: Implement per-dataset summary lifecycle**

Group active custom panes by dataset/source and reject conflicting command configurations for the same dataset. Create one query intent for each unique dataset with request kind `dashboard_summary`, Dashboard header period, and current date. Preserve accepted summaries on failures and render unit-aware, independent metrics beside—not inside—the token header total.

- [ ] **Step 4: Add empty/custom-only Dashboard tests**

Assert `dashboard --empty` with no built-in pane does not acquire default ccusage header work. Assert a custom-only Dashboard obtains only declared custom summary requests. Assert two custom datasets produce two display groups and never arithmetic aggregation.

- [ ] **Step 5: Run Dashboard summary suites**

Run: `uv run pytest tests/test_custom_dashboard.py tests/test_tui.py -k 'summary or empty' -v`

Expected: PASS.

- [ ] **Step 6: Commit custom Dashboard summaries**

```bash
git add src/ccusage_viz/tui.py src/ccusage_viz/acquisition.py src/ccusage_viz/custom_component.py src/ccusage_viz/render/summary.py tests/test_custom_dashboard.py tests/test_tui.py
git commit -m "feat: add custom dashboard summaries"
```

## Task 9: Document the protocol and run the full regression suite

**Files:**
- Create: `docs/custom-command-protocol.md`
- Create: `docs/custom-command-protocol.zh-CN.md`
- Modify: `docs/usage.md`
- Modify: `docs/usage.zh-CN.md`
- Modify: `docs/architecture.md`
- Modify: `docs/architecture.zh-CN.md`
- Modify: `docs/source-plugin-guide.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: all relevant existing and new test modules

**Interfaces:**
- Documents the final, implemented protocol—not hypothetical extensions.
- Gives English and Chinese users matching command examples, `--empty` semantics, Source/Logs controls, and `l`/`L` mappings.

- [ ] **Step 1: Write the protocol guide from executable fixtures**

Document the exact pane and dashboard-summary request JSON, successful and error response JSON, both-language labels, Decimal constraints, additive-only boundary, capabilities, filters, summary comparison base values, timeout/error behavior, and exact in-flight coalescing. Derive every JSON block from a passing protocol/provider fixture before publishing it.

- [ ] **Step 2: Update user documentation and architecture**

Add standalone and Dashboard examples, use `--pane 'empty'` in round-trip examples, explain `dashboard --empty`, type chooser behavior, custom Source and `L` Logs controls, and animation history’s `L` remap. Explain that custom command data is a static provider and is not a plugin registration or an overlap-merging cache.

- [ ] **Step 3: Run format, focused, and full tests**

Run:

```bash
uv run pytest tests/test_custom_protocol.py tests/test_custom_provider.py tests/test_custom_component.py tests/test_custom_dashboard.py -v
uv run pytest -v
```

Expected: all PASS.

- [ ] **Step 4: Run the CLI smoke tests with a fixture command**

Run a fixture command that reads stdin and emits one valid response, then verify:

```bash
uv run ccuv custom timeline --dataset fixture --command 'python tests/fixtures/custom_command.py'
uv run ccuv dashboard --empty --grid 2x2 --pane 'empty' --pane 'custom timeline --dataset fixture --command "python tests/fixtures/custom_command.py"'
```

Expected: custom standalone starts, Dashboard starts with preserved empty pane, and no ccusage dependency acquisition is attempted for the empty/custom-only host.

- [ ] **Step 5: Commit final documentation and regression coverage**

```bash
git add docs README.md README.zh-CN.md tests
git commit -m "docs: document custom command dashboards"
```
