# Ranking Local Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pane-local, instant, request-free search for native and Custom Dataset historical Rankings, visible row counts by density, and correct Dataset Ranking default periods.

**Architecture:** Put literal case-insensitive matching and ANSI-safe highlighted text in the shared historical Ranking presentation module so native and Custom Dataset historical Rankings behave identically. Store query/editing state on each Dashboard query-backed pane and thread its query through the two historical rendering paths; the event loop owns editing without refresh. Preserve the existing probe-default application boundary, correcting its period capability projection so a Dataset Ranking's declared default wins only at creation.

**Tech Stack:** Python 3.13, pytest, terminal ANSI/display-width formatting utilities, existing Dashboard TUI input decoder.

**Spec:** `docs/superpowers/specs/2026-10-09-ranking-local-search-design.md`

## Global Constraints

- Search applies only to focused interactive Dashboard historical Ranking panes; monitors and non-Ranking charts remain unchanged.
- Search is case-insensitive literal contiguous substring matching via `casefold()` for labels and descriptions; it does not use a provider request, regex, fuzzy match, or persistence.
- `/` edits search; Enter retains query/filter; Escape clears both query and filter.
- A non-empty query keeps a localized `Search: <query>` row directly beneath the title, including after editing ends and at `minimal` density.
- `+/-` retain the query and filter newly available local Ranking data; no new matching item is valid.
- Original source ordering and rank numbers survive filtering.
- `minimal` hides visible-row count; `compact` shows count and hides descriptions; `normal` shows count/current normal content; `detailed` shows count and defaults Dataset descriptions expanded.
- The count represents actual filtered rendered entries, not configured Top or Dataset capacity.
- A newly created Dataset Ranking uses its supported declared default period; later explicit user period changes remain authoritative.

---

## File Structure

- Modify: `src/ccusage_viz/render/ranking_presentation.py` — pure matching/highlighting helpers and shared historical Ranking search/count rendering.
- Modify: `src/ccusage_viz/render/ranking.py` — pass native historical Ranking query into the shared renderer.
- Modify: `src/ccusage_viz/render/custom.py` — pass Custom Dataset Ranking query into the shared renderer.
- Modify: `src/ccusage_viz/historical_render.py` — accept and carry a Dashboard Ranking query to native rendering.
- Modify: `src/ccusage_viz/tui.py` — pane-local state, `/` editor, input handling, rendering query plumbing, default density choice, and Dataset default-period projection.
- Modify: `src/ccusage_viz/configuration.py` — retain V2 historical capability periods when adapting it to the probe-default interface.
- Modify: `src/ccusage_viz/locales/en.py` and `src/ccusage_viz/locales/zh.py` — localized search, visible-count, and no-match text.
- Modify: `tests/test_render.py` — pure shared historical renderer tests.
- Modify: `tests/test_tui_dashboard.py` — Dashboard input, no-refresh, per-pane state, and native render plumbing tests.
- Modify: `tests/test_custom_component.py` and `tests/test_tui_custom.py` — Custom Dataset Ranking filtering/rendering behavior.
- Modify: `tests/test_options.py` — V2 Dataset Ranking defaults-period regression coverage.

### Task 1: Shared historical Ranking search presentation

**Files:**
- Modify: `src/ccusage_viz/render/ranking_presentation.py`
- Modify: `src/ccusage_viz/locales/en.py`
- Modify: `src/ccusage_viz/locales/zh.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `filter_ranking_entries(entries: Sequence[RankingPresentationEntry], query: str) -> tuple[RankingPresentationEntry, ...]`.
- Produces: `highlight_ranking_match(value: str, query: str, *, context: RenderContext) -> str`.
- Extends: `render_historical_ranking(..., descriptions_visible: bool = False, search_query: str = "") -> str`.

- [ ] **Step 1: Add failing rendering tests for literal matching, row count, highlight, and no results**

Add tests that call the shared renderer directly. Cover label-only and description-only case-folded matches, retain original rank two for a second source entry, and validate compact count + no-result copy:

```python
def test_historical_ranking_search_filters_casefolded_label_and_keeps_source_rank() -> None:
    context = RenderContext(80, 20, load_translator("en"), color=False, style="dot", density="normal")
    output = render_historical_ranking(
        (
            RankingPresentationEntry("a", "Alpha", 12),
            RankingPresentationEntry("b", "claude worker", 8),
        ),
        heading="Ranking",
        value_formatter=str,
        context=context,
        search_query="CLAUDE",
    )
    assert "Search: CLAUDE" in output
    assert "Showing 1 item" in output
    assert " 2" in output
    assert "Alpha" not in output


def test_historical_ranking_search_matches_description_and_has_localized_empty_state() -> None:
    context = RenderContext(80, 20, load_translator("en"), color=False, style="dot", density="normal")
    entries = (RankingPresentationEntry("a", "API", 12, description="Claude release checks"),)
    output = render_historical_ranking(
        entries, heading="Ranking", value_formatter=str, context=context,
        descriptions_visible=True, search_query="claude",
    )
    assert "API" in output
    assert "Claude" in output
    empty = render_historical_ranking(
        entries, heading="Ranking", value_formatter=str, context=context, search_query="missing",
    )
    assert 'No ranking entries match "missing".' in empty
```

Also add a color-enabled assertion that `highlight_ranking_match("Claude claude", "CLAUDE", context=...)` has two highlight ANSI spans, and parameterize density expectations: `minimal` has no `Showing`; `compact`, `normal`, and `detailed` do.

- [ ] **Step 2: Run the focused tests to confirm failure**

Run: `pytest tests/test_render.py -k 'ranking_search or ranking_visible_count' -v`

Expected: FAIL because the renderer has no `search_query` parameter or search presentation helpers.

- [ ] **Step 3: Implement pure casefold matching and ANSI-safe highlighting**

In `ranking_presentation.py`, add a helper that finds non-overlapping `query.casefold()` occurrences while retaining original string indices. Return the original string unchanged for an empty query. Build highlighted output by joining untouched slices and `styled_text(matched, scheme.highlight, context, bold=True)` slices. Add `filter_ranking_entries()` that retains an entry if the query occurs in `entry.label.casefold()` or non-`None` `entry.description.casefold()`.

Do not match `display`, numeric values, keys, or generated `Other` labels. Never call `casefold()` on a `None` description.

- [ ] **Step 4: Update shared renderer layout and density behavior**

At the beginning of `render_historical_ranking()`, preserve `source_entries`, derive `entries = filter_ranking_entries(source_entries, search_query)`, and build chrome in this order:

```python
lines = [line for line in (summary, center_text(heading, context.width)) if line]
if search_query:
    lines.append(context.translator.text("label.ranking_search", query=search_query))
if context.density != "minimal":
    lines.append(context.translator.text("label.ranking_visible_items", count=len(entries)))
if search_query and not entries:
    lines.append(context.translator.text("message.ranking_search_empty", query=search_query))
    return "\n".join(lines)
```

Use a singular/plural localization formatter rather than hand-building English plurals. Preserve original source ranks by enumerate over `source_entries` before filtering (for example, construct `(rank, entry)` pairs then retain matching pairs); do not enumerate filtered entries from one. Use `highlight_ranking_match()` to render labels when a query is active. For description rows, highlight before wrapping only if the project already has ANSI-aware wrapping; otherwise add an ANSI-aware wrapping helper beside the matcher that uses visible widths and does not split a styled span. Keep nonmatching description text muted/dim and matching text highlighted.

Require description visibility to be `descriptions_visible and context.density == "detailed"` for default expansion supplied by callers; the renderer must not independently hide an explicit description merely because density is `normal`. This retains the caller's state authority while later TUI logic selects the default.

- [ ] **Step 5: Add localization strings**

Add exact message keys in both locale dictionaries, using count-aware translator formatting consistent with existing locale conventions:

```python
# en.py
"label.ranking_search": "Search: {query}",
"label.ranking_visible_items": "Showing {count} item(s)",
"message.ranking_search_empty": "No ranking entries match \"{query}\".",

# zh.py
"label.ranking_search": "搜索：{query}",
"label.ranking_visible_items": "显示 {count} 项",
"message.ranking_search_empty": "没有与“{query}”匹配的排名项。",
```

If Translator has plural support, use it for the English item string and assert `1 item` / `2 items`; otherwise intentionally use the neutral `Showing {count} item(s)` text above and test that exact contract.

- [ ] **Step 6: Run renderer tests and lint**

Run:

```bash
pytest tests/test_render.py -k 'ranking' -v
ruff check src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_render.py
```

Expected: PASS with no Ruff diagnostics.

- [ ] **Step 7: Commit the shared renderer feature**

```bash
git add src/ccusage_viz/render/ranking_presentation.py src/ccusage_viz/locales/en.py src/ccusage_viz/locales/zh.py tests/test_render.py
git commit -m "feat: add local ranking search presentation"
```

### Task 2: Thread local query through native and Custom Dataset historical Ranking paths

**Files:**
- Modify: `src/ccusage_viz/render/ranking.py`
- Modify: `src/ccusage_viz/render/custom.py`
- Modify: `src/ccusage_viz/historical_render.py`
- Test: `tests/test_render.py`
- Test: `tests/test_custom_component.py`

**Interfaces:**
- Extends: `render_ranking(model: RankingModel, context: RenderContext, *, search_query: str = "") -> str` for historical models only.
- Extends: `render_custom_ranking(..., descriptions_visible: bool = False, search_query: str = "") -> str`.
- Extends: `render_custom_projection(..., descriptions_visible: bool = False, search_query: str = "") -> str`.
- Extends: `render_historical_component(..., ranking_search_query: str = "") -> RenderedChart`.

- [ ] **Step 1: Add failing native and Custom Dataset delegation tests**

In `tests/test_render.py`, construct a historical `RankingModel` with labels `Alpha` and `Claude`; pass `search_query="claude"` to `render_ranking()` and assert the output has only the source rank of Claude and a search line. In `tests/test_custom_component.py`, create a projection with label `API` and description `Claude release checks`, call `render_custom_projection(..., descriptions_visible=True, search_query="CLAUDE")`, and assert it includes that row and search chrome. Add an empty Custom projection search assertion using an existing nonempty projection and `search_query="absent"`.

- [ ] **Step 2: Run tests to confirm failure**

Run:

```bash
pytest tests/test_render.py -k native_ranking_search -v
pytest tests/test_custom_component.py -k custom_ranking_search -v
```

Expected: FAIL due to unsupported keyword arguments.

- [ ] **Step 3: Add optional keyword-only query plumbing without changing monitor behavior**

Update `render_ranking()` with `search_query: str = ""`. Pass it only to `render_historical_ranking()` in the `not model.is_observed` branch. Do not change observed monitor rendering.

Update `render_custom_ranking()` and `render_custom_projection()` signatures and their ranking branch to thread `search_query` to the shared renderer. Preserve empty-projection handling: it continues to use existing no-data rendering because no Ranking rows exist to search.

Update `render_historical_component()` with `ranking_search_query: str = ""`; after its context construction, call the definition renderer as follows while retaining non-Ranking behavior:

```python
if isinstance(chart, RankingConfig):
    rendered = component.definition.renderer(model, context, search_query=ranking_search_query)
else:
    rendered = component.definition.renderer(model, context)
```

Confirm chart registry renderer type annotations permit this keyword. If they do not, expose a narrow `render_historical_ranking_component()` adapter at this layer rather than weakening all renderer callable types.

- [ ] **Step 4: Run focused integration tests**

Run:

```bash
pytest tests/test_render.py -k 'ranking and search' -v
pytest tests/test_custom_component.py -k 'ranking and search' -v
```

Expected: PASS.

- [ ] **Step 5: Commit query plumbing**

```bash
git add src/ccusage_viz/render/ranking.py src/ccusage_viz/render/custom.py src/ccusage_viz/historical_render.py tests/test_render.py tests/test_custom_component.py
git commit -m "feat: share ranking search across renderers"
```

### Task 3: Dashboard pane-local search editor and render integration

**Files:**
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_tui_dashboard.py`

**Interfaces:**
- Produces: `RankingSearchState(query: str = "", editing: bool = False)`.
- Extends: `TuiChartPane` and `TuiCustomPane` with `ranking_search: RankingSearchState`.
- Consumes: `_pane_render(..., dashboard: DashboardLaunch | None = None, ...) -> PaneRender` and passes `pane.ranking_search.query` exclusively for eligible historical Ranking panes.

- [ ] **Step 1: Add deterministic Dashboard interaction tests**

Use the existing Dashboard test pattern that monkeypatches `tui_input_mode`, `read_event`/input event source, render painter, and `refresh`/query handles. Add event sequences for a focused native Ranking pane:

```python
(KeyEvent("/"), KeyEvent("c"), KeyEvent("l"), KeyEvent("\r"), KeyEvent("+"), KeyEvent("\x1b"))
```

Assert after typing and Enter that `pane.ranking_search.query == "cl"` and `editing is False`; after `+`, the query remains `"cl"`; after Escape, query is empty. Instrument the refresh submission function and assert the `/`, letters, backspace, Enter, and Escape transitions add no refresh calls. Use a separate Custom Dataset Ranking pane test to assert query state is independent from the native pane's state.

Add a `_pane_render()` test with a prepared native historical component and `pane.ranking_search.query = "claude"` that verifies search chrome is present; add the equivalent prepared Custom pane test.

- [ ] **Step 2: Run focused Dashboard tests to confirm failure**

Run: `pytest tests/test_tui_dashboard.py -k 'ranking_search' -v`

Expected: FAIL because panes have no search state and `/` is not a Ranking editor action.

- [ ] **Step 3: Add pane-local state and eligibility helpers**

Near pane dataclasses, add:

```python
@dataclass(slots=True)
class RankingSearchState:
    query: str = ""
    editing: bool = False
```

Add `ranking_search: RankingSearchState = field(default_factory=RankingSearchState)` to `TuiChartPane` and `TuiCustomPane` only. Add a helper that returns true only when `pane.body_view == "chart"` and its active/candidate configuration is a historical `ranking`; explicitly return false for `TuiAnimationPane`, `TuiEmptyPane`, native `MonitorComponent`, and `CustomMonitorComponent`.

Do not add search state to `DashboardState`, preset materialization, configuration objects, or mutation snapshots.

- [ ] **Step 4: Thread query into Dashboard render calls**

In every Dashboard `_pane_render()` path that invokes `render_historical_component()`, pass:

```python
ranking_search_query=(
    pane.ranking_search.query
    if isinstance(active.chart, RankingConfig) and pane.body_view == "chart"
    else ""
)
```

Pass `search_query=pane.ranking_search.query` to `_render_custom_projection()` and extend its signature to pass onward to `render_custom_projection()`. Use an empty query for pending/error/text views. Ensure recovery rendering uses the same native query expression so a transient error does not flash unfiltered accepted Ranking data.

- [ ] **Step 5: Add editor handling before normal adjustment shortcuts**

In the main Dashboard loop, after modal/editor ownership checks and before generic `key`/adjustment dispatch, handle a pane whose `ranking_search.editing` is true. Accept `PasteEvent` and `KeyEvent`; Escape resets `RankingSearchState()`; Enter/newline sets `editing=False` without clearing query; backspace removes one final Unicode codepoint; printable characters append; all other keys are inert. Paint and `continue` after each handled event.

When no Ranking search editor owns input, recognize `/` for the focused eligible Ranking pane before pane adjustment mode handling:

```python
if key == "/" and focused is not None and _ranking_search_eligible(panes[focused]):
    panes[focused].ranking_search.editing = True
    paint()
    continue
```

Escape outside edit mode must retain its existing adjustment/modal meaning. A search query remains active even though editing is false; only Escape while editing clears it. Do not call `record_mutation()`, `configure()`, or `refresh()` in this code.

- [ ] **Step 6: Run Dashboard tests and the TUI input suite**

Run:

```bash
pytest tests/test_tui_dashboard.py -k 'ranking_search or pane_render' -v
pytest tests/test_tui_input.py tests/test_tui_dashboard.py -v
ruff check src/ccusage_viz/tui.py tests/test_tui_dashboard.py
```

Expected: PASS with no Ruff diagnostics.

- [ ] **Step 7: Commit Dashboard interaction**

```bash
git add src/ccusage_viz/tui.py tests/test_tui_dashboard.py
git commit -m "feat: add dashboard ranking search input"
```

### Task 4: Make Ranking density behavior distinct and set Dashboard Ranking default to normal

**Files:**
- Modify: `src/ccusage_viz/configuration.py`
- Modify: `src/ccusage_viz/tui.py`
- Test: `tests/test_options.py`
- Test: `tests/test_tui_custom.py`

**Interfaces:**
- Consumes: `_default_dashboard_chart_presentation(kind: str) -> ChartPresentation`.
- Extends: `_custom_descriptions_visible(component, override) -> bool` to use `detailed` as the default expansion condition.

- [ ] **Step 1: Write failing density/default tests**

In `tests/test_options.py`, assert `default_pane("ranking", dashboard=dashboard).chart.presentation.density == "normal"` and the same for `default_custom_pane("ranking", ...)`. In `tests/test_tui_custom.py`, create a Custom Ranking with a description and assert `_custom_descriptions_visible(component, None)` is false at `compact` and `normal`, true at `detailed`, and false at `minimal`. Retain an explicit override test proving `override=True` makes descriptions visible at `normal` and `override=False` hides them at `detailed`.

- [ ] **Step 2: Run tests to confirm failure**

Run:

```bash
pytest tests/test_options.py -k ranking_default_density -v
pytest tests/test_tui_custom.py -k custom_descriptions_visible -v
```

Expected: FAIL because dashboard defaults are compact and current description default relies on Dataset capability instead of density.

- [ ] **Step 3: Implement Ranking-specific Dashboard defaults and description resolution**

In `_default_dashboard_chart_presentation()`, set `density="normal"` when `kind == "ranking"`; retain the current compact default for other kinds.

In `_custom_descriptions_visible()`, preserve all availability checks, then resolve `override is None` as `config.presentation.density == "detailed"`. When override is explicit, preserve it except for `minimal`, which remains false by the existing early return. Do not use `capability.descriptions_default` for Dashboard default visibility; capability remains data metadata, not a Dashboard density override.

- [ ] **Step 4: Run density tests and related renderer tests**

Run:

```bash
pytest tests/test_options.py -k 'default or ranking' -v
pytest tests/test_tui_custom.py -k 'descriptions or ranking' -v
pytest tests/test_render.py -k historical_ranking -v
```

Expected: PASS.

- [ ] **Step 5: Commit density behavior**

```bash
git add src/ccusage_viz/configuration.py src/ccusage_viz/tui.py tests/test_options.py tests/test_tui_custom.py
git commit -m "feat: differentiate ranking density levels"
```

### Task 5: Preserve V2 Ranking periods while applying Dataset defaults

**Files:**
- Modify: `src/ccusage_viz/configuration.py`
- Test: `tests/test_options.py`

**Interfaces:**
- Extends: `v2_metric_probe_descriptor(descriptor: V2ProbeDescriptor, metric_id: str | None) -> CustomProbeDescriptor` so projected `CustomChartCapability.periods` contains the original `V2HistoricalChartCapability.periods`.
- Consumes: `apply_custom_probe_defaults(config, descriptor, timezone="UTC") -> CustomChartConfig`.

- [ ] **Step 1: Add a failing V2 default-period regression test**

Build a minimal V2 descriptor in `tests/test_options.py` whose selected metric has Ranking capability periods `("7d", "30d")` and defaults declaring `period="7d"`. Start with a newly created Ranking `CustomChartConfig` whose `initial_explicit` has no period/since/until. Then assert:

```python
projected = v2_metric_probe_descriptor(v2_descriptor, "metric")
resolved = apply_custom_probe_defaults(initial, projected, timezone="UTC")
assert resolved.date_range.period == "7d"
assert "7d" in projected.capabilities.charts["ranking"].periods
```

Create a second `initial` with `initial_explicit=frozenset({"period"})` and a `30d` range, then assert defaults leave it at `30d`.

- [ ] **Step 2: Run the regression test to confirm failure**

Run: `pytest tests/test_options.py -k v2_ranking_default_period -v`

Expected: FAIL because `v2_metric_probe_descriptor()` currently constructs `CustomChartCapability(..., (), ...)` and discards supported periods.

- [ ] **Step 3: Preserve historical periods in the V2-to-V1 compatibility adapter**

Change only the projected `CustomChartCapability` construction in `v2_metric_probe_descriptor()`:

```python
CustomChartCapability(
    capability.granularities,
    capability.group_by,
    capability.periods,
    capability.max_items,
    capability.descriptions_default,
)
```

Do not change `apply_custom_probe_defaults()` precedence: its existing `initial_explicit` check already guarantees later `p/P` changes are retained. Confirm the Dataset pane creation/probe path invokes that function before its first data submission; if a test shows it does not, add the narrow invocation at the accepted probe boundary rather than changing period during redraws.

- [ ] **Step 4: Run options and Dataset creation tests**

Run:

```bash
pytest tests/test_options.py -k 'v2 or custom_probe_defaults or default_custom_pane' -v
pytest tests/test_tui_dashboard.py -k 'dataset and ranking' -v
ruff check src/ccusage_viz/configuration.py tests/test_options.py
```

Expected: PASS with no Ruff diagnostics.

- [ ] **Step 5: Commit Dataset period support**

```bash
git add src/ccusage_viz/configuration.py tests/test_options.py
git commit -m "fix: apply dataset ranking default periods"
```

## Final Verification

- [ ] Run the complete suite: `pytest -v`.
- [ ] Run `ruff check src tests`.
- [ ] Run `git diff --check`.
- [ ] Manually run a Dashboard with one native Ranking and one Custom Dataset Ranking: verify `/` filters immediately without a loading/refresh indication; Enter preserves the query/search line; Escape clears it; `+/-` preserves it; `minimal` hides the count; and a Dataset declared `7d` Ranking opens at 7d rather than 14d.
